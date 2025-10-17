#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import json
import time
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import ConfigManager

class BiliApiV2:
    """简化版B站API调用器
    
    去除复杂的签名验证和登录管理，直接使用配置文件中的cookie
    """
    
    # API基础地址
    BASE_URL = "https://api.bilibili.com"
    
    # 动态相关接口
    DYNAMIC_SPACE_URL = f"{BASE_URL}/x/polymer/web-dynamic/v1/feed/space"
    DYNAMIC_ALL_URL = f"{BASE_URL}/x/polymer/web-dynamic/v1/feed/all"  # 新的全部动态接口
    DYNAMIC_UPDATE_URL = f"{BASE_URL}/x/polymer/web-dynamic/v1/feed/all/update"  # 检测新动态接口
    USER_SPACE_URL = f"{BASE_URL}/x/space/acc/info"
    USER_VIDEOS_URL = f"{BASE_URL}/x/space/arc/search"
    
    def __init__(self, config_manager: ConfigManager):
        """初始化API调用器"""
        self.logger = logging.getLogger(__name__)
        self.config_manager = config_manager
        
        # 创建会话
        self.session = self._create_session()
        
        # 请求计数和频率控制
        self._request_count = 0
        self._last_request_time = 0
        # 从配置读取最小请求间隔，默认3秒（避免频繁请求）
        api_settings = self.config_manager.get_config('bilibili.api_settings', {})
        self._min_interval = api_settings.get('min_interval', 3.0)
        
        # 动态更新基线管理
        self._update_baseline = None  # 用于检测新动态
        
        # 从配置文件加载cookie
        self._load_cookies_from_config()
    
    def _create_session(self) -> requests.Session:
        """创建配置好的会话对象"""
        session = requests.Session()
        
        # 禁用代理（避免系统代理导致连接问题）
        session.trust_env = False
        
        # 设置重试策略
        retry_strategy = Retry(
            total=3,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS"],
            backoff_factor=1
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        # 设置基础headers
        api_settings = self.config_manager.get_config('bilibili.api_settings', {})
        user_agent = api_settings.get('user_agent', 
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36')
        
        session.headers.update({
            'User-Agent': user_agent,
            'Referer': 'https://www.bilibili.com/',
            'Origin': 'https://www.bilibili.com'
        })
        
        return session
    
    def _load_cookies_from_config(self):
        """从配置文件加载cookie"""
        # 尝试加载cookie字符串格式
        cookie_string = self.config_manager.get_config('bilibili.cookie_string', '')
        
        if cookie_string:
            # 解析cookie字符串
            cookies_dict = self._parse_cookie_string(cookie_string)
            for name, value in cookies_dict.items():
                if value:  # 只添加非空的cookie
                    self.session.cookies.set(name, value, domain='.bilibili.com')
            
            if cookies_dict:
                self.logger.info(f"已从配置文件解析并加载 {len(cookies_dict)} 个Cookie")
        else:
            # 兼容旧的cookies对象格式
            cookies_config = self.config_manager.get_config('bilibili.cookies', {})
            for name, value in cookies_config.items():
                if value:  # 只添加非空的cookie
                    self.session.cookies.set(name, value, domain='.bilibili.com')
            
            if cookies_config:
                self.logger.info(f"已从配置文件加载 {len(cookies_config)} 个Cookie")
    
    def _parse_cookie_string(self, cookie_string: str) -> dict:
        """解析cookie字符串为字典
        
        Args:
            cookie_string: 浏览器cookie字符串，格式如：name1=value1; name2=value2; ...
            
        Returns:
            解析后的cookie字典
        """
        cookies_dict = {}
        
        # 按分号分割cookie对
        for cookie_pair in cookie_string.split(';'):
            cookie_pair = cookie_pair.strip()
            if '=' in cookie_pair:
                # 按等号分割键值对，只分割第一个等号
                name, value = cookie_pair.split('=', 1)
                cookies_dict[name.strip()] = value.strip()
        
        return cookies_dict
    
    def _rate_limit(self):
        """请求频率限制"""
        current_time = time.time()
        time_diff = current_time - self._last_request_time
        
        if time_diff < self._min_interval:
            sleep_time = self._min_interval - time_diff
            self.logger.debug(f"频率限制，等待 {sleep_time:.2f} 秒")
            time.sleep(sleep_time)
        
        self._last_request_time = time.time()
        self._request_count += 1
    
    def _make_request(self, url: str, params: Dict = None) -> Optional[Dict]:
        """发起API请求"""
        try:
            self._rate_limit()
            
            if params is None:
                params = {}
            
            self.logger.debug(f"请求URL: {url}, 参数: {params}")
            
            response = self.session.get(url, params=params, timeout=15)
            response.raise_for_status()
            
            data = response.json()
            
            # 检查响应码
            code = data.get('code', -1)
            if code != 0:
                message = data.get('message', '未知错误')
                self.logger.error(f"API返回错误, code: {code}, message: {message}")
                return None
            
            return data.get('data')
            
        except requests.exceptions.RequestException as e:
            self.logger.error(f"网络请求失败: {e}")
        except json.JSONDecodeError as e:
            self.logger.error(f"JSON解析失败: {e}")
        except Exception as e:
            self.logger.error(f"请求过程中发生未知错误: {e}")
        
        return None
    
    def get_user_info(self, uid: str) -> Optional[Dict]:
        """获取用户基本信息"""
        params = {'mid': uid}
        data = self._make_request(self.USER_SPACE_URL, params)
        
        if data:
            self.logger.info(f"成功获取用户 {uid} 的基本信息")
            return data
        
        return None
    
    def get_user_dynamics(self, uid: str, offset: str = "", limit: int = 20) -> List[Dict]:
        """获取用户动态列表
        
        根据B站API文档使用 /feed/all 接口，支持获取特定UP主的动态
        参考: https://socialsisteryi.github.io/bilibili-API-collect/docs/dynamic/all.html
        """
        params = {
            'host_mid': uid,  # 指定UP主UID
            'offset': offset,
            'platform': 'web',
            'features': 'itemOpusStyle,listOnlyfans,opusBigCover,onlyfansVote,decorationCard,onlyfansAssetsV2,forwardListHidden,ugcDelete'
        }
        
        # 使用新的全部动态接口
        data = self._make_request(self.DYNAMIC_ALL_URL, params)
        
        if not data:
            return []
        
        items = data.get('items', [])
        dynamics = []
        
        for item in items:
            try:
                parsed_dynamic = self._parse_dynamic_item(item)
                if parsed_dynamic:
                    dynamics.append(parsed_dynamic)
            except Exception as e:
                self.logger.error(f"解析动态失败: {e}")
                continue
        
        # 过滤置顶动态
        filtered_dynamics = self._filter_pinned_dynamics(dynamics)
        
        self.logger.info(f"成功获取用户 {uid} 的 {len(filtered_dynamics)} 条动态（已过滤置顶动态）")
        return filtered_dynamics
    
    def get_user_videos(self, uid: str, pn: int = 1, ps: int = 10) -> List[Dict]:
        """获取用户投稿视频列表"""
        params = {
            'mid': uid,
            'pn': pn,
            'ps': ps,
            'order': 'pubdate'  # 按发布时间排序
        }
        
        data = self._make_request(self.USER_VIDEOS_URL, params)
        
        if not data:
            return []
        
        list_data = data.get('list', {})
        vlist = list_data.get('vlist', [])
        
        videos = []
        for video in vlist:
            videos.append({
                'bvid': video.get('bvid'),
                'aid': video.get('aid'),
                'title': video.get('title'),
                'description': video.get('description', ''),
                'pic': video.get('pic', ''),
                'created': video.get('created', 0),
                'length': video.get('length', ''),
                'play': video.get('play', 0),
                'danmaku': video.get('video_review', 0),
                'author': video.get('author', ''),
                'mid': video.get('mid', 0)
            })
        
        self.logger.info(f"成功获取用户 {uid} 的 {len(videos)} 个视频")
        return videos
    
    def get_latest_video(self, uid: str) -> Optional[Dict]:
        """获取用户最新视频"""
        videos = self.get_user_videos(uid, pn=1, ps=1)
        return videos[0] if videos else None
    
    def get_latest_dynamic(self, uid: str) -> Optional[Dict]:
        """获取用户最新动态"""
        dynamics = self.get_user_dynamics(uid, limit=1)
        return dynamics[0] if dynamics else None
    
    def _parse_dynamic_item(self, item: Dict) -> Optional[Dict]:
        """解析动态项目"""
        try:
            # 检查item是否为None
            if not item:
                return None
                
            # 基础信息
            dynamic_id = item.get('id_str', '')
            
            # 作者信息
            modules = item.get('modules', {})
            if not modules:
                return None
            
            author_info = modules.get('module_author', {})
            author_mid = str(author_info.get('mid', '')) if author_info else ''
            author_name = author_info.get('name', '') if author_info else ''
            
            # 从author_info中获取时间戳（新API格式）
            pub_timestamp = author_info.get('pub_ts', 0)
            if not pub_timestamp:
                # 兼容旧API格式
                pub_timestamp = item.get('pub_timestamp', 0)
            
            # 将UTC时间戳转换为北京时间（UTC+8）
            if pub_timestamp:
                utc_time = datetime.fromtimestamp(pub_timestamp, tz=timezone.utc)
                beijing_time = utc_time.astimezone(timezone(timedelta(hours=8)))
                pub_time = beijing_time.replace(tzinfo=None)  # 移除时区信息，保持datetime对象
            else:
                pub_time = None
            
            # 动态内容
            dynamic_info = modules.get('module_dynamic', {})
            content = ''
            images = []
            title = ''  # 添加标题字段
            
            if dynamic_info:
                # 提取文字内容
                desc = dynamic_info.get('desc')
                if desc and isinstance(desc, dict):
                    content = desc.get('text', '')
                
                # 提取图片和内容（支持新旧两种API格式）
                major = dynamic_info.get('major')
                if major and isinstance(major, dict):
                    major_type = major.get('type')
                    
                    if major_type == 'MAJOR_TYPE_DRAW':  # 旧API格式：图片动态
                        draw_info = major.get('draw', {})
                        if draw_info:
                            draw_items = draw_info.get('items', [])
                            for draw_item in draw_items:
                                if draw_item:
                                    img_src = draw_item.get('src', '')
                                    if img_src:
                                        images.append(img_src)
                    
                    elif major_type == 'MAJOR_TYPE_OPUS':  # 新API格式：动态内容
                        opus_info = major.get('opus', {})
                        if opus_info:
                            # 提取动态标题
                            title = opus_info.get('title', '')
                            
                            # 提取文字内容（如果desc为空的话）
                            if not content:
                                summary = opus_info.get('summary', {})
                                if summary:
                                    content = summary.get('text', '')
                            
                            # 提取图片
                            pics = opus_info.get('pics', [])
                            for pic in pics:
                                if pic and 'url' in pic:
                                    images.append(pic['url'])
            
            # 构建动态对象
            dynamic = {
                'id': dynamic_id,
                'author_mid': author_mid,
                'author_name': author_name,
                'title': title,  # 添加动态标题
                'content': content,
                'pub_timestamp': pub_timestamp,
                'pub_time': pub_time,
                'images': images,
                'type': 'dynamic',
                'url': f"https://t.bilibili.com/{dynamic_id}"
            }
            
            return dynamic
                
        except Exception as e:
            self.logger.error(f"解析动态项目时出错: {e}")
        return None
    
    def _filter_pinned_dynamics(self, dynamics: List[Dict]) -> List[Dict]:
        """过滤置顶动态（简化版）"""
        if not dynamics:
            return dynamics
        
        # 简单的时间过滤：跳过发布时间超过30天的动态（可能是置顶）
        current_time = int(time.time())
        filtered = []
        
        for dynamic in dynamics:
            pub_timestamp = dynamic.get('pub_timestamp', 0)
            if pub_timestamp > 0:
                # 如果动态发布时间超过30天，可能是置顶动态
                if current_time - pub_timestamp > 30 * 24 * 3600:
                    self.logger.debug(f"跳过可能的置顶动态: {dynamic.get('id')} (发布时间: {dynamic.get('pub_time')})")
                    continue
            
            filtered.append(dynamic)
        
        return filtered
    
    def check_login_status(self) -> bool:
        """检查登录状态"""
        try:
            nav_url = "https://api.bilibili.com/x/web-interface/nav"
            response = self.session.get(nav_url, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            if data.get('code') == 0:
                user_data = data.get('data', {})
                if user_data.get('isLogin'):
                    username = user_data.get('uname', 'Unknown')
                    uid = user_data.get('mid', 0)
                    self.logger.info(f"已登录用户: {username} (UID: {uid})")
                    return True
            
            self.logger.info("当前未登录")
            return False
            
        except Exception as e:
            self.logger.error(f"检查登录状态失败: {e}")
            return False
    
    def check_global_dynamic_updates(self) -> int:
        """检查全局是否有新动态（高效方式）
        
        使用 /feed/all/update 接口检测是否有新动态，避免频繁获取动态列表
        参考: https://socialsisteryi.github.io/bilibili-API-collect/docs/dynamic/all.html#检测是否有新动态
            
        Returns:
            新动态数量，-1表示检查失败，0表示无更新，>0表示有更新
        """
        try:
            params = {
                'update_baseline': self._update_baseline or '0',
                'web_location': '333.1365'
            }
            
            data = self._make_request(self.DYNAMIC_UPDATE_URL, params)
            
            if data:
                update_num = data.get('update_num', 0)
                self.logger.debug(f"全局新动态检测: {update_num} 条新动态")
                return update_num
            
            return -1
            
        except Exception as e:
            self.logger.error(f"检查全局动态更新失败: {e}")
            return -1
    
    def update_baseline_from_dynamics(self, dynamics: List[Dict]):
        """从获取的动态列表更新基线
        
        Args:
            dynamics: 动态列表
        """
        if dynamics:
            # 使用第一条动态的ID作为新的基线
            first_dynamic = dynamics[0]
            self._update_baseline = first_dynamic.get('id')
            self.logger.debug(f"更新动态基线: {self._update_baseline}")
    
    def get_all_dynamics_with_baseline(self, limit: int = 20) -> List[Dict]:
        """获取全部动态并更新基线
        
        Args:
            limit: 获取数量限制
            
        Returns:
            动态列表
        """
        params = {
            'offset': '',
            'platform': 'web',
            'features': 'itemOpusStyle,listOnlyfans,opusBigCover,onlyfansVote,decorationCard,onlyfansAssetsV2,forwardListHidden,ugcDelete'
        }
        
        data = self._make_request(self.DYNAMIC_ALL_URL, params)
        
        if not data:
            return []
        
        items = data.get('items', [])
        
        # 更新基线
        update_baseline = data.get('update_baseline')
        if update_baseline:
            self._update_baseline = update_baseline
            self.logger.debug(f"从API响应更新基线: {self._update_baseline}")
        
        # 解析动态
        dynamics = []
        for item in items:
            parsed_dynamic = self._parse_dynamic_item(item)
            if parsed_dynamic:
                dynamics.append(parsed_dynamic)
        
        # 过滤置顶动态
        filtered_dynamics = self._filter_pinned_dynamics(dynamics)
        
        if filtered_dynamics:
            self.logger.info(f"成功获取全部动态 {len(filtered_dynamics)} 条（已过滤置顶动态）")
        
        return filtered_dynamics
    
    def check_dynamic_updates(self, uid: str) -> int:
        """检查动态更新（简化版）
        
        Args:
            uid: UP主ID
            
        Returns:
            更新数量，-1表示检查失败，0表示无更新，>0表示有更新
        """
        try:
            # 简化实现：直接获取最新动态
            dynamics = self.get_user_dynamics(uid, limit=1)
            return len(dynamics)
        except Exception as e:
            self.logger.error(f"检查动态更新失败: {e}")
            return -1
