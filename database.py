#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

class DynamicDatabase:
    """动态数据库管理类"""
    
    def __init__(self, db_file: str):
        """初始化数据库
        
        Args:
            db_file: 数据库文件路径
        """
        self.db_file = db_file
        self.logger = logging.getLogger(__name__)
        self._init_database()
    
    def _init_database(self):
        """初始化数据库表"""
        try:
            with sqlite3.connect(self.db_file) as conn:
                cursor = conn.cursor()
                
                # 创建已发送动态记录表
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS sent_dynamics (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        dynamic_id TEXT NOT NULL UNIQUE,
                        author_mid TEXT NOT NULL,
                        author_name TEXT NOT NULL,
                        content TEXT,
                        pub_timestamp INTEGER,
                        sent_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(dynamic_id)
                    )
                ''')
                
                # 创建索引提高查询性能
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_dynamic_id 
                    ON sent_dynamics(dynamic_id)
                ''')
                
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_author_mid 
                    ON sent_dynamics(author_mid)
                ''')
                
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_sent_time 
                    ON sent_dynamics(sent_time)
                ''')
                
                conn.commit()
                self.logger.info("数据库初始化成功")
                
        except sqlite3.Error as e:
            self.logger.error(f"数据库初始化失败: {e}")
            raise
    
    def is_dynamic_sent(self, dynamic_id: str) -> bool:
        """检查动态是否已经发送过
        
        Args:
            dynamic_id: 动态ID
            
        Returns:
            是否已发送
        """
        try:
            with sqlite3.connect(self.db_file) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT COUNT(*) FROM sent_dynamics WHERE dynamic_id = ?",
                    (dynamic_id,)
                )
                count = cursor.fetchone()[0]
                return count > 0
                
        except sqlite3.Error as e:
            self.logger.error(f"检查动态是否已发送时数据库错误: {e}")
            return False
    
    def record_sent_dynamic(self, dynamic_data: Dict) -> bool:
        """记录已发送的动态
        
        Args:
            dynamic_data: 动态数据
            
        Returns:
            是否记录成功
        """
        try:
            with sqlite3.connect(self.db_file) as conn:
                cursor = conn.cursor()
                
                cursor.execute('''
                    INSERT OR REPLACE INTO sent_dynamics 
                    (dynamic_id, author_mid, author_name, content, pub_timestamp)
                    VALUES (?, ?, ?, ?, ?)
                ''', (
                    dynamic_data.get('id'),
                    dynamic_data.get('author_mid'),
                    dynamic_data.get('author_name'),
                    dynamic_data.get('content', ''),
                    dynamic_data.get('pub_timestamp', 0)
                ))
                
                conn.commit()
                self.logger.info(f"记录动态成功: {dynamic_data.get('id')}")
                return True
                
        except sqlite3.Error as e:
            self.logger.error(f"记录动态时数据库错误: {e}")
            return False
    
    def get_sent_dynamics(self, author_mid: str = None, limit: int = 100) -> List[Dict]:
        """获取已发送的动态列表
        
        Args:
            author_mid: UP主ID（可选）
            limit: 返回数量限制
            
        Returns:
            动态列表
        """
        try:
            with sqlite3.connect(self.db_file) as conn:
                cursor = conn.cursor()
                
                if author_mid:
                    cursor.execute('''
                        SELECT dynamic_id, author_mid, author_name, content, 
                               pub_timestamp, sent_time
                        FROM sent_dynamics 
                        WHERE author_mid = ?
                        ORDER BY sent_time DESC 
                        LIMIT ?
                    ''', (author_mid, limit))
                else:
                    cursor.execute('''
                        SELECT dynamic_id, author_mid, author_name, content, 
                               pub_timestamp, sent_time
                        FROM sent_dynamics 
                        ORDER BY sent_time DESC 
                        LIMIT ?
                    ''', (limit,))
                
                rows = cursor.fetchall()
                
                dynamics = []
                for row in rows:
                    dynamics.append({
                        'dynamic_id': row[0],
                        'author_mid': row[1],
                        'author_name': row[2],
                        'content': row[3],
                        'pub_timestamp': row[4],
                        'sent_time': row[5]
                    })
                
                return dynamics
                
        except sqlite3.Error as e:
            self.logger.error(f"获取已发送动态时数据库错误: {e}")
            return []
    
    def cleanup_old_records(self, days_to_keep: int = 30) -> int:
        """清理旧的记录
        
        Args:
            days_to_keep: 保留多少天的记录
            
        Returns:
            删除的记录数量
        """
        try:
            cutoff_date = datetime.now() - timedelta(days=days_to_keep)
            
            with sqlite3.connect(self.db_file) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "DELETE FROM sent_dynamics WHERE sent_time < ?",
                    (cutoff_date,)
                )
                deleted_count = cursor.rowcount
                conn.commit()
                
                self.logger.info(f"清理了 {deleted_count} 条旧记录")
                return deleted_count
                
        except sqlite3.Error as e:
            self.logger.error(f"清理旧记录时数据库错误: {e}")
            return 0
    
    def get_statistics(self) -> Dict:
        """获取统计信息
        
        Returns:
            统计数据字典
        """
        try:
            with sqlite3.connect(self.db_file) as conn:
                cursor = conn.cursor()
                
                # 总动态数
                cursor.execute("SELECT COUNT(*) FROM sent_dynamics")
                total_dynamics = cursor.fetchone()[0]
                
                # 今日发送数
                today = datetime.now().date()
                cursor.execute(
                    "SELECT COUNT(*) FROM sent_dynamics WHERE DATE(sent_time) = ?",
                    (today,)
                )
                today_count = cursor.fetchone()[0]
                
                # UP主数量
                cursor.execute("SELECT COUNT(DISTINCT author_mid) FROM sent_dynamics")
                up_count = cursor.fetchone()[0]
                
                # 最新记录时间
                cursor.execute("SELECT MAX(sent_time) FROM sent_dynamics")
                latest_time = cursor.fetchone()[0]
                
                return {
                    'total_dynamics': total_dynamics,
                    'today_count': today_count,
                    'up_count': up_count,
                    'latest_time': latest_time
                }
                
        except sqlite3.Error as e:
            self.logger.error(f"获取统计信息时数据库错误: {e}")
            return {}
    
    def reset_database(self) -> bool:
        """重置数据库（清空所有数据）
        
        Returns:
            是否成功
        """
        try:
            with sqlite3.connect(self.db_file) as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM sent_dynamics")
                conn.commit()
                self.logger.info("数据库已重置")
                return True
                
        except sqlite3.Error as e:
            self.logger.error(f"重置数据库时错误: {e}")
            return False
