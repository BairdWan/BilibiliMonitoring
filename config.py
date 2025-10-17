#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import logging
from typing import Dict, List, Any

class ConfigManager:
    """配置管理类"""
    
    def __init__(self, config_file: str = "config.json"):
        """初始化配置管理器
        
        Args:
            config_file: 配置文件路径
        """
        self.config_file = config_file
        self.config = {}
        self.logger = logging.getLogger(__name__)
        self.load_config()
    
    def load_config(self) -> Dict:
        """加载配置文件
        
        Returns:
            配置字典
        """
        try:
            if not os.path.exists(self.config_file):
                self.logger.error(f"配置文件不存在: {self.config_file}")
                return {}
            
            with open(self.config_file, 'r', encoding='utf-8') as f:
                self.config = json.load(f)
            
            self.logger.info("配置文件加载成功")
            return self.config
            
        except json.JSONDecodeError as e:
            self.logger.error(f"配置文件格式错误: {e}")
        except Exception as e:
            self.logger.error(f"加载配置文件时发生错误: {e}")
        
        return {}
    
    def save_config(self) -> bool:
        """保存配置文件
        
        Returns:
            是否保存成功
        """
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=4)
            
            self.logger.info("配置文件保存成功")
            return True
            
        except Exception as e:
            self.logger.error(f"保存配置文件时发生错误: {e}")
            return False
    
    def get_config(self, key_path: str = None, default: Any = None) -> Any:
        """获取配置值
        
        Args:
            key_path: 配置键路径，用.分隔，如 'dingtalk.webhook_url'
            default: 默认值
            
        Returns:
            配置值
        """
        if not key_path:
            return self.config
        
        keys = key_path.split('.')
        current = self.config
        
        try:
            for key in keys:
                current = current[key]
            return current
        except (KeyError, TypeError):
            return default
    
    def set_config(self, key_path: str, value: Any) -> bool:
        """设置配置值
        
        Args:
            key_path: 配置键路径，用.分隔
            value: 配置值
            
        Returns:
            是否设置成功
        """
        try:
            keys = key_path.split('.')
            current = self.config
            
            # 导航到最后一级的父级
            for key in keys[:-1]:
                if key not in current:
                    current[key] = {}
                current = current[key]
            
            # 设置值
            current[keys[-1]] = value
            return True
            
        except Exception as e:
            self.logger.error(f"设置配置值时发生错误: {e}")
            return False
    
    def get_up_list(self) -> List[Dict]:
        """获取UP主列表
        
        Returns:
            UP主列表
        """
        return self.get_config('bilibili.up_list', [])
    
    def get_enabled_up_list(self) -> List[Dict]:
        """获取启用的UP主列表
        
        Returns:
            启用的UP主列表
        """
        up_list = self.get_up_list()
        return [up for up in up_list if up.get('enabled', True)]
    
    def get_dingtalk_config(self) -> Dict:
        """获取钉钉配置
        
        Returns:
            钉钉配置字典
        """
        return self.get_config('dingtalk', {})
    
    def get_check_interval(self) -> int:
        """获取检查间隔（分钟）
        
        Returns:
            检查间隔分钟数
        """
        return self.get_config('bilibili.check_interval_minutes', 5)
    
    def get_global_update_check_interval(self) -> int:
        """获取全局更新检测间隔（分钟）
        
        Returns:
            全局更新检测间隔分钟数
        """
        return self.get_config('bilibili.global_update_check_interval_minutes', 1)
    
    def validate_config(self) -> List[str]:
        """验证配置文件
        
        Returns:
            错误信息列表
        """
        errors = []
        
        # 检查钉钉配置
        dingtalk_config = self.get_dingtalk_config()
        if not dingtalk_config.get('webhook_url'):
            errors.append("缺少钉钉机器人webhook_url配置")
        elif 'YOUR_ACCESS_TOKEN' in dingtalk_config.get('webhook_url', ''):
            errors.append("请配置真实的钉钉机器人access_token")
        
        # 检查UP主列表
        up_list = self.get_up_list()
        if not up_list:
            errors.append("UP主列表为空，请添加要监控的UP主")
        else:
            for i, up in enumerate(up_list):
                if not up.get('uid'):
                    errors.append(f"UP主 {i+1} 缺少uid配置")
                if not up.get('name'):
                    errors.append(f"UP主 {i+1} 缺少name配置")
        
        # 检查检查间隔
        check_interval = self.get_check_interval()
        if check_interval < 1:
            errors.append("检查间隔不能小于1分钟")
        elif check_interval > 60:
            errors.append("检查间隔不建议超过60分钟")
        
        return errors
