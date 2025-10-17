#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import time
import signal
import logging
from logging.handlers import RotatingFileHandler
import schedule
from datetime import datetime
from typing import Dict, List

# 导入自定义模块
from config import ConfigManager
from bili_api_v2 import BiliApiV2
from dingtalk_sender import DingtalkSender
from database import DynamicDatabase

class BiliDynamicBotV2:
    """B站动态监控机器人主程序 V2
    
    基于最新API文档实现，包含完善的错误处理和重试机制
    """
    
    def __init__(self, config_file: str = "config_v2.json"):
        """初始化机器人"""
        self.config_file = config_file
        self.config_manager = ConfigManager(config_file)
        self.is_running = False
        self.logger = None
        self.bili_api = None
        self.dingtalk_sender = None
        self.database = None
        self.consecutive_failures = {}  # 记录连续失败次数
        
        # 初始化组件
        self._init_logging()
        self._init_components()
        
        # 设置信号处理
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _init_logging(self):
        """初始化日志系统"""
        log_config = self.config_manager.get_config('logging', {})
        log_level = log_config.get('level', 'INFO')
        log_file = log_config.get('file', 'bili_monitor.log')
        max_size_mb = log_config.get('max_size_mb', 10)
        backup_count = log_config.get('backup_count', 5)
        
        # 配置根日志记录器
        root_logger = logging.getLogger()
        root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
        
        # 清除现有的处理器
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
        
        # 文件处理器（带滚动）
        file_handler = RotatingFileHandler(
            log_file, 
            maxBytes=max_size_mb * 1024 * 1024,
            backupCount=backup_count,
            encoding='utf-8'
        )
        file_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        file_handler.setFormatter(file_formatter)
        
        # 控制台处理器
        console_handler = logging.StreamHandler(sys.stdout)
        console_formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s'
        )
        console_handler.setFormatter(console_formatter)
        
        # 添加处理器
        root_logger.addHandler(file_handler)
        root_logger.addHandler(console_handler)
        
        self.logger = logging.getLogger(__name__)
        self.logger.info("日志系统初始化完成")
    
    def _init_components(self):
        """初始化各个组件"""
        try:
            # 验证配置
            config_errors = self.config_manager.validate_config()
            if config_errors:
                self.logger.error("配置验证失败:")
                for error in config_errors:
                    self.logger.error(f"  - {error}")
                self.logger.error("请修复配置文件后重新运行")
                sys.exit(1)
            
            # 初始化B站API
            self.bili_api = BiliApiV2(self.config_manager)
            
            # 初始化钉钉发送器
            dingtalk_config = self.config_manager.get_dingtalk_config()
            self.dingtalk_sender = DingtalkSender(
                webhook_url=dingtalk_config['webhook_url'],
                secret=dingtalk_config.get('secret', '')
            )
            
            # 初始化数据库
            db_config = self.config_manager.get_config('database', {})
            db_file = db_config.get('file', 'sent_dynamics.db')
            self.database = DynamicDatabase(db_file)
            
            self.logger.info("所有组件初始化完成")
            
        except Exception as e:
            self.logger.error(f"初始化组件时发生错误: {e}")
            sys.exit(1)
    
    def check_and_send_updates(self):
        """检查并发送UP主更新"""
        try:
            enabled_ups = self.config_manager.get_enabled_up_list()
            if not enabled_ups:
                self.logger.warning("没有启用的UP主，跳过检查")
                return
            
            self.logger.info(f"开始检查 {len(enabled_ups)} 个UP主的更新")
            
            for up in enabled_ups:
                try:
                    self._check_single_up(up)
                    
                    # 重置失败计数
                    uid = up.get('uid')
                    if uid in self.consecutive_failures:
                        del self.consecutive_failures[uid]
                        
                except Exception as e:
                    uid = up.get('uid', 'unknown')
                    name = up.get('name', f'UP主{uid}')
                    
                    # 增加失败计数
                    self.consecutive_failures[uid] = self.consecutive_failures.get(uid, 0) + 1
                    failure_count = self.consecutive_failures[uid]
                    
                    self.logger.error(f"检查 {name} 时发生错误 (连续第{failure_count}次): {e}")
                    
                    # 如果连续失败次数过多，暂时跳过
                    if failure_count >= 5:
                        self.logger.warning(f"{name} 连续失败{failure_count}次，暂时跳过")
                        continue
                
                # 请求间隔
                time.sleep(2)
                
        except Exception as e:
            self.logger.error(f"检查更新时发生未知错误: {e}")
    
    def quick_check_updates(self):
        """快速检测更新（超高效：先检测全局新动态，再获取具体动态）
        
        使用优化策略：
        1. 先调用 /feed/all/update 检测是否有新动态
        2. 如果有新动态，再获取全部动态并筛选监控的UP主
        3. 大大减少API请求频率，避免 -799 错误
        """
        try:
            self.logger.debug("🚀 开始全局新动态检测（超高效模式）")
            
            # 第一步：检测全局是否有新动态
            update_count = self.bili_api.check_global_dynamic_updates()
            
            if update_count == -1:
                self.logger.debug("全局动态检测失败，跳过本次检查")
                return
            elif update_count == 0:
                self.logger.debug("✅ 全局无新动态，跳过详细检查")
                return
            
            self.logger.info(f"🎯 检测到 {update_count} 条新动态，开始详细分析")
            
            # 第二步：获取全部最新动态
            all_dynamics = self.bili_api.get_all_dynamics_with_baseline(limit=50)
            
            if not all_dynamics:
                self.logger.debug("获取全部动态失败")
                return
            
            # 第三步：筛选监控的UP主动态
            enabled_ups = self.config_manager.get_enabled_up_list()
            monitored_uids = {up.get('uid') for up in enabled_ups if up.get('enabled') and 'dynamic' in up.get('monitor_types', [])}
            
            found_updates = False
            for dynamic in all_dynamics:
                author_mid = dynamic.get('author_mid')
                if author_mid in monitored_uids:
                    # 找到监控UP主的新动态
                    dynamic_id = dynamic.get('id')
                    
                    # 检查是否已发送
                    if not self.database.is_dynamic_sent(dynamic_id):
                        found_updates = True
                        author_name = dynamic.get('author_name', f'UP主{author_mid}')
                        
                        self.logger.info(f"🎯 发现 {author_name} 的新动态: {dynamic_id}")
                        
                        # 发送通知
                        if self._send_dynamic_notification(dynamic, "dynamic"):
                            if self.database.record_sent_dynamic(dynamic):
                                self.logger.info(f"✅ {author_name} 新动态推送成功: {dynamic_id}")
                            else:
                                self.logger.error(f"发送成功但记录失败: {dynamic_id}")
                        else:
                            self.logger.error(f"发送 {author_name} 的动态失败: {dynamic_id}")
            
            if found_updates:
                self.logger.info("🎉 快速检测完成，已推送新动态")
            else:
                self.logger.debug("✅ 快速检测完成，监控UP主无新动态")
                
        except Exception as e:
            self.logger.error(f"快速检测时发生未知错误: {e}")
    
    def _check_single_up(self, up: Dict):
        """检查单个UP主的更新
        
        Args:
            up: UP主配置
        """
        uid = up.get('uid')
        name = up.get('name', f'UP主{uid}')
        monitor_types = up.get('monitor_types', ['dynamic', 'video'])
        
        if not uid:
            self.logger.warning(f"UP主 {name} 缺少UID配置")
            return
        
        # 检查动态更新
        if 'dynamic' in monitor_types:
            self._check_dynamic_updates(uid, name)
        
        # 检查视频更新
        if 'video' in monitor_types:
            self._check_video_updates(uid, name)
    
    def _check_dynamic_updates(self, uid: str, name: str):
        """检查动态更新（优化版：先轻量检测，有更新再完整获取）
        
        Args:
            uid: UP主ID
            name: UP主昵称
        """
        try:
            # 第一步：轻量级检测是否有新动态
            update_count = self.bili_api.check_dynamic_updates(uid)
            
            if update_count == -1:
                self.logger.debug(f"{name} 动态检测失败")
                return
            elif update_count == 0:
                self.logger.debug(f"{name} 无新动态")
                return
            
            # 第二步：有新动态时才执行完整获取
            self.logger.debug(f"{name} 检测到新动态，开始完整获取")
            latest_dynamic = self.bili_api.get_latest_dynamic(uid)
            
            if not latest_dynamic:
                self.logger.debug(f"未获取到 {name} 的最新动态详情")
                return
            
            dynamic_id = latest_dynamic.get('id')
            if not dynamic_id:
                self.logger.warning(f"{name} 的动态缺少ID")
                return
            
            # 第三步：检查数据库去重
            if self.database.is_dynamic_sent(dynamic_id):
                self.logger.debug(f"{name} 的动态 {dynamic_id} 已发送过，跳过")
                return
            
            # 第四步：发送新动态
            if self._send_dynamic_notification(latest_dynamic, "dynamic"):
                # 记录已发送
                if self.database.record_sent_dynamic(latest_dynamic):
                    self.logger.info(f"✅ {name} 新动态推送成功: {dynamic_id}")
                else:
                    self.logger.error(f"发送成功但记录失败: {dynamic_id}")
            else:
                self.logger.error(f"发送 {name} 的动态失败: {dynamic_id}")
                
        except Exception as e:
            self.logger.error(f"检查 {name} 动态更新时发生错误: {e}")
    
    def _check_video_updates(self, uid: str, name: str):
        """检查视频更新
        
        Args:
            uid: UP主ID
            name: UP主昵称
        """
        try:
            latest_video = self.bili_api.get_latest_video(uid)
            
            if not latest_video:
                self.logger.debug(f"未获取到 {name} 的视频")
                return
            
            # 构造视频动态ID（使用bvid）
            bvid = latest_video.get('bvid')
            if not bvid:
                self.logger.warning(f"{name} 的视频缺少BVID")
                return
            
            video_dynamic_id = f"video_{bvid}"
            
            # 检查是否已发送过
            if self.database.is_dynamic_sent(video_dynamic_id):
                self.logger.debug(f"{name} 的视频 {bvid} 已发送过，跳过")
                return
            
            # 构造视频动态数据
            video_dynamic = self._convert_video_to_dynamic(latest_video)
            
            # 发送新视频通知
            if self._send_dynamic_notification(video_dynamic, "video"):
                # 记录已发送
                if self.database.record_sent_dynamic(video_dynamic):
                    self.logger.info(f"成功发送并记录 {name} 的新视频: {bvid}")
                else:
                    self.logger.error(f"发送成功但记录失败: {bvid}")
            else:
                self.logger.error(f"发送 {name} 的视频失败: {bvid}")
                
        except Exception as e:
            self.logger.error(f"检查 {name} 视频更新时发生错误: {e}")
    
    def _convert_video_to_dynamic(self, video: Dict) -> Dict:
        """将视频数据转换为动态格式
        
        Args:
            video: 视频数据
            
        Returns:
            动态格式数据
        """
        bvid = video.get('bvid', '')
        title = video.get('title', '')
        description = video.get('description', '')
        created = video.get('created', 0)
        
        # 构建视频URL
        video_url = f"https://www.bilibili.com/video/{bvid}" if bvid else ""
        
        # 构建内容
        content = f"【视频】{title}"
        if description:
            # 截取描述长度
            max_length = self.config_manager.get_config('bilibili.monitor_settings.content_max_length', 200)
            if len(description) > max_length:
                description = description[:max_length] + "..."
            content += f"\n{description}"
        
        return {
            'id': f"video_{bvid}",
            'author_name': video.get('author', ''),
            'author_mid': str(video.get('mid', '')),
            'content': content,
            'pub_time': datetime.fromtimestamp(created) if created else datetime.now(),
            'pub_timestamp': created,
            'type': 'video',
            'url': video_url
        }
    
    def _send_dynamic_notification(self, dynamic_data: Dict, notification_type: str) -> bool:
        """发送动态通知
        
        Args:
            dynamic_data: 动态数据
            notification_type: 通知类型 ('dynamic' 或 'video')
            
        Returns:
            是否发送成功
        """
        try:
            # 使用集成的图文消息发送方法
            return self.dingtalk_sender.send_bili_dynamic_message(dynamic_data)
            
        except Exception as e:
            self.logger.error(f"发送通知消息失败: {e}")
            return False
    
    def cleanup_old_data(self):
        """清理旧数据"""
        try:
            cleanup_days = self.config_manager.get_config('database.cleanup_days', 30)
            deleted_count = self.database.cleanup_old_records(days_to_keep=cleanup_days)
            if deleted_count > 0:
                self.logger.info(f"清理了 {deleted_count} 条旧记录")
        except Exception as e:
            self.logger.error(f"清理旧数据时发生错误: {e}")
    
    def show_statistics(self):
        """显示统计信息"""
        try:
            stats = self.database.get_statistics()
            self.logger.info("=== 统计信息 ===")
            self.logger.info(f"总发送动态数: {stats.get('total_dynamics', 0)}")
            self.logger.info(f"今日发送数: {stats.get('today_count', 0)}")
            self.logger.info(f"监控UP主数: {stats.get('up_count', 0)}")
            self.logger.info(f"最新记录时间: {stats.get('latest_time', '无')}")
            
            # 显示失败统计
            if self.consecutive_failures:
                self.logger.info("=== 失败统计 ===")
                for uid, count in self.consecutive_failures.items():
                    self.logger.info(f"UP主 {uid}: 连续失败 {count} 次")
                    
            self.logger.info("================")
        except Exception as e:
            self.logger.error(f"获取统计信息时发生错误: {e}")
    
    def test_connection(self):
        """测试连接"""
        self.logger.info("开始测试组件连接...")
        
        # 测试钉钉连接
        if self.dingtalk_sender.test_connection():
            self.logger.info("✅ 钉钉机器人连接测试成功")
        else:
            self.logger.error("❌ 钉钉机器人连接测试失败")
        
        # 测试B站API
        enabled_ups = self.config_manager.get_enabled_up_list()
        if enabled_ups:
            test_up = enabled_ups[0]
            uid = test_up.get('uid')
            name = test_up.get('name', f'UP主{uid}')
            
            self.logger.info(f"测试获取 {name} 的信息...")
            
            user_info = self.bili_api.get_user_info(uid)
            if user_info:
                self.logger.info(f"✅ B站API测试成功，获取到用户信息: {user_info.get('name')}")
            else:
                self.logger.error("❌ B站API测试失败")
        else:
            self.logger.warning("⚠️  没有配置UP主，跳过B站API测试")
    
    def run_once(self):
        """手动运行一次检查（使用优化策略）"""
        self.logger.info("开始手动检查更新...")
        
        # 使用优化后的快速检测
        self.quick_check_updates()
        self.logger.info("手动检查完成")
    
    def start_monitoring(self):
        """启动监控"""
        try:
            self.logger.info("B站动态监控机器人 V2 启动中...")
            
            # 显示配置信息
            enabled_ups = self.config_manager.get_enabled_up_list()
            check_interval = self.config_manager.get_check_interval()
            global_check_interval = self.config_manager.get_global_update_check_interval()
            
            self.logger.info(f"监控的UP主数量: {len(enabled_ups)}")
            for up in enabled_ups:
                monitor_types = up.get('monitor_types', ['dynamic', 'video'])
                self.logger.info(f"  - {up.get('name')} (UID: {up.get('uid')}, 监控: {', '.join(monitor_types)})")
            
            self.logger.info(f"🚀 超高效监控模式已启用:")
            self.logger.info(f"  🎯 全局检测间隔: {global_check_interval} 分钟 (超高效)")
            self.logger.info(f"  🔄 完整检查间隔: {check_interval} 分钟 (兜底机制)")
            
            # 测试连接
            self.test_connection()
            
            # 显示统计信息
            self.show_statistics()
            
            # 设置定时任务（三级监控策略）
            schedule.every(global_check_interval).minutes.do(self.quick_check_updates)  # 全局检测（超高效）
            schedule.every(check_interval).minutes.do(self.check_and_send_updates)  # 完整检查（兜底）
            schedule.every().day.at("02:00").do(self.cleanup_old_data)
            schedule.every().hour.do(self.show_statistics)
            
            # 首次运行（使用优化策略）
            self.logger.info("执行首次更新检查（超高效模式）...")
            self.quick_check_updates()
            
            # 开始监控循环
            self.is_running = True
            self.logger.info("监控开始运行，按 Ctrl+C 停止")
            
            while self.is_running:
                schedule.run_pending()
                time.sleep(10)
                
        except KeyboardInterrupt:
            self.logger.info("收到中断信号，正在停止...")
        except Exception as e:
            self.logger.error(f"监控运行时发生错误: {e}")
        finally:
            self.stop_monitoring()
    
    def stop_monitoring(self):
        """停止监控"""
        self.is_running = False
        schedule.clear()
        self.logger.info("监控已停止")
    
    def _signal_handler(self, signum, frame):
        """信号处理器"""
        self.logger.info(f"收到信号 {signum}，正在优雅停止...")
        self.stop_monitoring()
    

def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='B站动态监控机器人 V2')
    parser.add_argument('command', nargs='?', default='start',
                        choices=['start', 'test', 'once', 'stats'],
                        help='执行的命令')
    parser.add_argument('--config', '-c', default='config_v2.json',
                        help='配置文件路径')
    
    args = parser.parse_args()
    
    try:
        # 创建机器人实例
        bot = BiliDynamicBotV2(args.config)
        
        if args.command == 'test':
            bot.test_connection()
        elif args.command == 'once':
            bot.run_once()
        elif args.command == 'stats':
            bot.show_statistics()
        elif args.command == 'start':
            bot.start_monitoring()
        else:
            parser.print_help()
            
    except Exception as e:
        print(f"程序运行时发生错误: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
