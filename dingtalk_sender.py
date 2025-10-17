#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import json
import time
import hmac
import hashlib
import base64
import urllib.parse
import logging
from typing import Dict, Optional

class DingtalkSender:
    """钉钉群机器人消息发送类"""
    
    def __init__(self, webhook_url: str, secret: str = None):
        """初始化钉钉发送器
        
        Args:
            webhook_url: 钉钉机器人webhook地址
            secret: 机器人签名密钥（可选）
        """
        self.webhook_url = webhook_url
        self.secret = secret
        self.logger = logging.getLogger(__name__)
    
    def _generate_signature(self, timestamp: str) -> str:
        """生成签名
        
        Args:
            timestamp: 时间戳
            
        Returns:
            签名字符串
        """
        if not self.secret:
            return ""
        
        string_to_sign = f'{timestamp}\n{self.secret}'
        hmac_code = hmac.new(
            self.secret.encode('utf-8'),
            string_to_sign.encode('utf-8'),
            digestmod=hashlib.sha256
        ).digest()
        
        sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
        return sign
    
    def _get_signed_url(self) -> str:
        """获取带签名的URL
        
        Returns:
            带签名的webhook URL
        """
        if not self.secret:
            return self.webhook_url
        
        timestamp = str(round(time.time() * 1000))
        sign = self._generate_signature(timestamp)
        
        return f"{self.webhook_url}&timestamp={timestamp}&sign={sign}"
    
    def send_text_message(self, content: str, at_mobiles: list = None, at_all: bool = False) -> bool:
        """发送文本消息
        
        Args:
            content: 消息内容
            at_mobiles: @的手机号列表
            at_all: 是否@所有人
            
        Returns:
            是否发送成功
        """
        data = {
            "msgtype": "text",
            "text": {
                "content": content
            },
            "at": {
                "atMobiles": at_mobiles or [],
                "isAtAll": at_all
            }
        }
        
        return self._send_message(data)
    
    def send_markdown_message(self, title: str, text: str, at_mobiles: list = None, at_all: bool = False) -> bool:
        """发送Markdown消息
        
        Args:
            title: 消息标题
            text: Markdown格式的消息内容
            at_mobiles: @的手机号列表
            at_all: 是否@所有人
            
        Returns:
            是否发送成功
        """
        data = {
            "msgtype": "markdown",
            "markdown": {
                "title": title,
                "text": text
            },
            "at": {
                "atMobiles": at_mobiles or [],
                "isAtAll": at_all
            }
        }
        
        return self._send_message(data)
    
    def send_link_message(self, title: str, text: str, message_url: str, pic_url: str = "") -> bool:
        """发送链接消息
        
        Args:
            title: 消息标题
            text: 消息文本
            message_url: 点击消息跳转的URL
            pic_url: 图片URL
            
        Returns:
            是否发送成功
        """
        data = {
            "msgtype": "link",
            "link": {
                "text": text,
                "title": title,
                "picUrl": pic_url,
                "messageUrl": message_url
            }
        }
        
        return self._send_message(data)
    
    def send_bili_dynamic_message(self, dynamic_data: Dict) -> bool:
        """发送B站动态消息（集成版，支持图文一体化显示）
        
        Args:
            dynamic_data: 动态数据
            
        Returns:
            是否发送成功
        """
        try:
            author_name = dynamic_data.get('author_name', '未知UP主')
            title = dynamic_data.get('title', '')
            content = dynamic_data.get('content', '')
            images = dynamic_data.get('images', [])
            video_info = dynamic_data.get('video_info')
            article_info = dynamic_data.get('article_info')
            pub_time = dynamic_data.get('pub_time')
            dynamic_url = dynamic_data.get('url', '')
            
            # 格式化时间
            time_str = pub_time.strftime('%Y-%m-%d %H:%M:%S') if pub_time else '未知时间'
            
            # 构建消息标题
            if "转发自:" in content or "转发评论:" in content:
                msg_title = f"🔄 {author_name} 转发了动态"
            elif video_info:
                msg_title = f"📹 {author_name} 发布了新视频"
            elif article_info:
                msg_title = f"📰 {author_name} 发布了新专栏"
            elif images:
                msg_title = f"🖼️ {author_name} 发布了图片动态"
            else:
                msg_title = f"🔔 {author_name} 发布了新动态"
            
            # 优先使用集成的图文显示格式
            return self._send_integrated_message(
                author_name, title, content, images, video_info, article_info,
                time_str, dynamic_url, msg_title
            )
            
        except Exception as e:
            self.logger.error(f"发送B站动态消息失败: {e}")
            return False
    
    def _send_feed_card_message(self, author_name: str, title: str, content: str, 
                               images: list, time_str: str, dynamic_url: str, msg_title: str) -> bool:
        """发送FeedCard格式消息（支持多图显示）
        
        Args:
            author_name: UP主名称
            title: 动态标题
            content: 动态内容
            images: 图片URL列表
            time_str: 时间字符串
            dynamic_url: 动态链接
            msg_title: 消息标题
            
        Returns:
            是否发送成功
        """
        try:
            # 限制内容长度
            if len(content) > 150:
                content = content[:150] + "..."
            
            # 构建描述
            description = f"**时间:** {time_str}\n"
            if title:
                description += f"**标题:** {title}\n"
            if content and content != "【动态】":
                description += f"**内容:** {content}\n"
            
            # 构建链接列表（最多显示9张图片）
            links = []
            for i, img_url in enumerate(images[:9]):
                # 确保图片URL使用HTTPS协议
                https_img_url = self._ensure_https_url(img_url)
                links.append({
                    "title": f"{msg_title}" if i == 0 else f"图片 {i+1}",
                    "messageURL": dynamic_url,
                    "picURL": https_img_url
                })
            
            # 如果只有一张图片，使用link格式更好
            if len(links) == 1:
                # 确保图片URL使用HTTPS协议
                pic_url = self._ensure_https_url(images[0])
                return self.send_link_message(
                    title=msg_title,
                    text=description.replace("**", "").replace("*", ""),
                    message_url=dynamic_url,
                    pic_url=pic_url
                )
            
            # 多图使用feedCard
            data = {
                "msgtype": "feedCard",
                "feedCard": {
                    "links": links
                }
            }
            
            return self._send_message(data)
            
        except Exception as e:
            self.logger.error(f"发送FeedCard消息失败: {e}")
            return False
    
    def _send_enhanced_markdown_message(self, author_name: str, title: str, content: str,
                                      video_info: dict, article_info: dict, time_str: str,
                                      dynamic_url: str, msg_title: str) -> bool:
        """发送增强的Markdown消息
        
        Args:
            author_name: UP主名称
            title: 动态标题
            content: 动态内容
            video_info: 视频信息
            article_info: 专栏信息
            time_str: 时间字符串
            dynamic_url: 动态链接
            msg_title: 消息标题
            
        Returns:
            是否发送成功
        """
        try:
            # 构建Markdown内容
            markdown_parts = [f"## {msg_title}", ""]
            
            # 基本信息
            markdown_parts.extend([
                f"**UP主:** {author_name}",
                f"**发布时间:** {time_str}",
                ""
            ])
            
            # 标题（如果有）
            if title and title != content:
                markdown_parts.extend([
                    f"**标题:** {title}",
                    ""
                ])
            
            # 视频信息
            if video_info:
                video_url = video_info.get('url', dynamic_url)
                markdown_parts.extend([
                    f"**视频标题:** {video_info.get('title', '无标题')}",
                    f"**视频简介:** {video_info.get('desc', '无简介')[:100]}...",
                    f"[🎬 观看视频]({video_url})",
                    ""
                ])
            
            # 专栏信息
            elif article_info:
                markdown_parts.extend([
                    f"**专栏标题:** {article_info.get('title', '无标题')}",
                    f"**专栏简介:** {article_info.get('desc', '无简介')[:100]}...",
                    ""
                ])
            
            # 动态内容
            if content and content != "【动态】":
                # 限制内容长度
                display_content = content
                if len(display_content) > 300:
                    display_content = display_content[:300] + "..."
                
                markdown_parts.extend([
                    "**动态内容:**",
                    display_content,
                    ""
                ])
            
            # 链接
            markdown_parts.append(f"[📱 点击查看完整动态]({dynamic_url})")
            
            markdown_text = "\n".join(markdown_parts)
            
            return self.send_markdown_message(msg_title, markdown_text)
            
        except Exception as e:
            self.logger.error(f"发送增强Markdown消息失败: {e}")
            return False
    
    def _send_integrated_message(self, author_name: str, title: str, content: str, 
                                images: list, video_info: dict, article_info: dict,
                                time_str: str, dynamic_url: str, msg_title: str) -> bool:
        """发送集成的图文消息（Markdown格式，图片嵌入文本中）
        
        Args:
            author_name: UP主名称
            title: 动态标题
            content: 动态内容
            images: 图片URL列表
            video_info: 视频信息
            article_info: 专栏信息
            time_str: 时间字符串
            dynamic_url: 动态链接
            msg_title: 消息标题
            
        Returns:
            是否发送成功
        """
        try:
            # 构建Markdown内容
            markdown_parts = [f"## {msg_title}", ""]
            
            # 基本信息 - 每个字段单独一行，增加空行分隔
            markdown_parts.extend([
                f"**UP主:** {author_name}",
                "",
                f"**发布时间:** {time_str}",
                ""
            ])
            
            # 标题（如果有）
            if title and title != content and title != "【动态】":
                markdown_parts.extend([
                    f"**标题:** {title}",
                    ""
                ])
            
            # 视频信息
            if video_info:
                video_url = video_info.get('url', dynamic_url)
                markdown_parts.extend([
                    f"**视频标题:** {video_info.get('title', '无标题')}",
                    f"**视频简介:** {video_info.get('desc', '无简介')[:200]}...",
                    f"[🎬 观看视频]({video_url})",
                    ""
                ])
            
            # 专栏信息
            elif article_info:
                markdown_parts.extend([
                    f"**专栏标题:** {article_info.get('title', '无标题')}",
                    f"**专栏简介:** {article_info.get('desc', '无简介')[:200]}...",
                    ""
                ])
            
            # 动态内容
            if content and content != "【动态】":
                # 不截断内容，显示完整内容
                display_content = content
                
                markdown_parts.extend([
                    "**动态内容:**",
                    "",
                    display_content,
                    ""
                ])
            
            # 嵌入图片（关键：使用Markdown语法）
            if images:
                markdown_parts.extend([
                    "**动态图片:**",
                    ""
                ])
                for i, img_url in enumerate(images[:6]):  # 最多显示6张图片
                    https_img_url = self._ensure_https_url(img_url)
                    markdown_parts.append(f"![图片{i+1}]({https_img_url})")
                markdown_parts.append("")
            
            # 链接
            markdown_parts.extend([
                "",
                f"[📱 点击查看详情]({dynamic_url})"
            ])
            
            markdown_text = "\n".join(markdown_parts)
            
            return self.send_markdown_message(msg_title, markdown_text)
            
        except Exception as e:
            self.logger.error(f"发送集成消息失败: {e}")
            # 降级到原有的显示方式
            if images and len(images) > 0:
                return self._send_feed_card_message(
                    author_name, title, content, images, time_str, dynamic_url, msg_title
                )
            else:
                return self._send_enhanced_markdown_message(
                    author_name, title, content, video_info, article_info,
                    time_str, dynamic_url, msg_title
                )
    
    def _ensure_https_url(self, url: str) -> str:
        """确保URL使用HTTPS协议
        
        Args:
            url: 原始URL
            
        Returns:
            HTTPS协议的URL
        """
        if url.startswith('http://'):
            return url.replace('http://', 'https://', 1)
        return url
    
    def _send_message(self, data: Dict) -> bool:
        """发送消息到钉钉
        
        Args:
            data: 消息数据
            
        Returns:
            是否发送成功
        """
        try:
            url = self._get_signed_url()
            headers = {'Content-Type': 'application/json'}
            
            response = requests.post(
                url=url,
                headers=headers,
                data=json.dumps(data, ensure_ascii=False).encode('utf-8'),
                timeout=10,
                proxies={"http": None, "https": None}  # 禁用代理
            )
            
            response.raise_for_status()
            result = response.json()
            
            if result.get('errcode') == 0:
                self.logger.info("钉钉消息发送成功")
                return True
            else:
                self.logger.error(f"钉钉消息发送失败: {result.get('errmsg')}")
                return False
                
        except requests.exceptions.RequestException as e:
            self.logger.error(f"发送钉钉消息时网络错误: {e}")
        except Exception as e:
            self.logger.error(f"发送钉钉消息时发生未知错误: {e}")
        
        return False
    
    def test_connection(self) -> bool:
        """测试钉钉机器人连接
        
        Returns:
            是否连接成功
        """
        test_message = "🤖 B站动态监控机器人测试消息"
        return self.send_text_message(test_message)
