"""
subscriber_manager.py - 订阅用户管理

职责:
    1. 管理订阅用户列表（SQLite 存储）
    2. 用户订阅/取消订阅
    3. 获取所有订阅用户用于推送
"""

import os
import sqlite3
from datetime import datetime
from typing import List, Dict, Optional
from contextlib import contextmanager

# 获取项目根目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
DB_PATH = os.path.join(PROJECT_ROOT, "yuffie_subscribers.db")


class SubscriberManager:
    """
    订阅用户管理器
    
    核心功能:
        1. 添加/删除订阅用户
        2. 获取所有订阅用户
        3. 检查用户是否订阅
    """
    
    def __init__(self, db_path: str = DB_PATH):
        """
        初始化订阅管理器
        
        Args:
            db_path: SQLite 数据库路径
        """
        self.db_path = db_path
        self._init_db()
    
    @contextmanager
    def _get_connection(self):
        """获取数据库连接的上下文管理器"""
        conn = None
        try:
            conn = sqlite3.connect(self.db_path, timeout=30.0)
            conn.execute("PRAGMA journal_mode=WAL")
            yield conn
        except Exception as e:
            if conn:
                conn.rollback()
            raise e
        finally:
            if conn:
                conn.close()
    
    def _init_db(self):
        """初始化数据库表结构"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # 创建订阅用户表
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS subscribers (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id TEXT UNIQUE NOT NULL,      -- 用户 ID
                        user_name TEXT,                     -- 用户名
                        subscribed_at REAL DEFAULT (strftime('%s', 'now')),
                        is_active INTEGER DEFAULT 1,        -- 是否激活
                        last_alert_at REAL,                 -- 最后报警时间
                        alert_count INTEGER DEFAULT 0       -- 收到报警次数
                    )
                """)
                
                # 创建索引
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_user_id 
                    ON subscribers(user_id)
                """)
                
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_active 
                    ON subscribers(is_active)
                """)
                
                conn.commit()
                
        except Exception as e:
            print(f"[SubscriberManager] 数据库初始化失败：{e}")
            raise
    
    def subscribe(self, user_id: str, user_name: str = "") -> bool:
        """
        用户订阅
        
        Args:
            user_id: 用户 ID
            user_name: 用户名
        
        Returns:
            bool: 是否成功
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # 检查是否已存在
                cursor.execute("""
                    SELECT is_active FROM subscribers WHERE user_id = ?
                """, (user_id,))
                
                row = cursor.fetchone()
                
                if row:
                    # 已存在，激活订阅
                    if row[0] == 0:
                        cursor.execute("""
                            UPDATE subscribers 
                            SET is_active = 1, subscribed_at = strftime('%s', 'now')
                            WHERE user_id = ?
                        """, (user_id,))
                        conn.commit()
                        print(f"[SubscriberManager] 用户 {user_name} 已重新订阅")
                    else:
                        print(f"[SubscriberManager] 用户 {user_name} 已是订阅用户")
                    return True
                else:
                    # 新用户
                    cursor.execute("""
                        INSERT INTO subscribers (user_id, user_name)
                        VALUES (?, ?)
                    """, (user_id, user_name))
                    conn.commit()
                    print(f"[SubscriberManager] 用户 {user_name} 订阅成功")
                    return True
                    
        except Exception as e:
            print(f"[SubscriberManager] 订阅失败：{e}")
            return False
    
    def unsubscribe(self, user_id: str) -> bool:
        """
        用户取消订阅
        
        Args:
            user_id: 用户 ID
        
        Returns:
            bool: 是否成功
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    UPDATE subscribers 
                    SET is_active = 0
                    WHERE user_id = ?
                """, (user_id,))
                
                conn.commit()
                print(f"[SubscriberManager] 用户 {user_id} 已取消订阅")
                return True
                
        except Exception as e:
            print(f"[SubscriberManager] 取消订阅失败：{e}")
            return False
    
    def is_subscribed(self, user_id: str) -> bool:
        """
        检查用户是否订阅
        
        Args:
            user_id: 用户 ID
        
        Returns:
            bool: 是否已订阅
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT is_active FROM subscribers WHERE user_id = ?
                """, (user_id,))
                
                row = cursor.fetchone()
                
                if row and row[0] == 1:
                    return True
                return False
                
        except Exception as e:
            print(f"[SubscriberManager] 检查订阅状态失败：{e}")
            return False
    
    def get_all_subscribers(self) -> List[Dict[str, any]]:
        """
        获取所有活跃订阅用户
        
        Returns:
            List[Dict]: 订阅用户列表
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT user_id, user_name, subscribed_at, alert_count, last_alert_at
                    FROM subscribers
                    WHERE is_active = 1
                """)
                
                rows = cursor.fetchall()
                
                subscribers = []
                for row in rows:
                    subscribers.append({
                        "user_id": row[0],
                        "user_name": row[1],
                        "subscribed_at": row[2],
                        "alert_count": row[3],
                        "last_alert_at": row[4]
                    })
                
                return subscribers
                
        except Exception as e:
            print(f"[SubscriberManager] 获取订阅用户失败：{e}")
            return []
    
    def record_alert(self, user_id: str) -> bool:
        """
        记录报警发送
        
        Args:
            user_id: 用户 ID
        
        Returns:
            bool: 是否成功
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    UPDATE subscribers 
                    SET alert_count = alert_count + 1,
                        last_alert_at = strftime('%s', 'now')
                    WHERE user_id = ?
                """, (user_id,))
                
                conn.commit()
                return True
                
        except Exception as e:
            print(f"[SubscriberManager] 记录报警失败：{e}")
            return False
    
    def get_stats(self) -> Dict[str, any]:
        """
        获取订阅统计
        
        Returns:
            Dict: 统计信息
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # 总订阅数
                cursor.execute("SELECT COUNT(*) FROM subscribers WHERE is_active = 1")
                total_active = cursor.fetchone()[0]
                
                # 总用户数
                cursor.execute("SELECT COUNT(*) FROM subscribers")
                total_users = cursor.fetchone()[0]
                
                # 总报警次数
                cursor.execute("SELECT COALESCE(SUM(alert_count), 0) FROM subscribers WHERE is_active = 1")
                total_alerts = cursor.fetchone()[0]
                
                return {
                    "total_active": total_active,
                    "total_users": total_users,
                    "total_alerts": total_alerts
                }
                
        except Exception as e:
            print(f"[SubscriberManager] 获取统计失败：{e}")
            return {
                "total_active": 0,
                "total_users": 0,
                "total_alerts": 0
            }
    
    def close(self):
        """关闭数据库连接"""
        pass  # 使用 contextmanager 自动管理


# ==================== 使用示例 ====================

if __name__ == "__main__":
    # 测试
    mgr = SubscriberManager()
    
    # 订阅
    mgr.subscribe("user123", "测试用户")
    
    # 检查订阅
    print(f"是否订阅：{mgr.is_subscribed('user123')}")
    
    # 获取所有订阅用户
    subscribers = mgr.get_all_subscribers()
    print(f"订阅用户：{subscribers}")
    
    # 统计
    stats = mgr.get_stats()
    print(f"统计：{stats}")
    
    # 取消订阅
    mgr.unsubscribe("user123")
    print(f"取消后是否订阅：{mgr.is_subscribed('user123')}")
