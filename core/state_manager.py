"""
state_manager.py - 状态持久化与死信队列管理

职责:
    1. 使用 SQLite 实现状态持久化（冷却期管理）
    2. 实现"先写状态，后发消息"的防漏报设计
    3. 实现死信队列 (DLQ) 用于暂存和重试发送失败的报警消息

设计原则:
    - 原子性：冷却期写入必须是原子操作，防止并发竞争
    - 可靠性：消息发送失败后自动进入死信队列，由后台任务重试
    - 可恢复性：系统重启后能从 SQLite 恢复状态
"""

import sqlite3
import json
import time
import threading
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from contextlib import contextmanager
import os

# 获取当前文件所在目录，用于构建数据库路径
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
DB_PATH = os.path.join(PROJECT_ROOT, "yuffie_state.db")


class StateManager:
    """
    状态管理器 - 管理冷却期和死信队列
    
    核心功能:
        1. check_cooldown(key) -> bool: 检查指定 key 是否处于冷却期
        2. set_cooldown(key, duration_minutes) -> bool: 设置冷却期（先写状态）
        3. push_dlq(message) -> bool: 将失败消息压入死信队列
        4. pop_dlq(limit) -> List[Dict]: 从死信队列取出待重试消息
        5. remove_from_dlq(message_id) -> bool: 从死信队列移除已发送成功的消息
    """
    
    def __init__(self, db_path: str = DB_PATH):
        """
        初始化状态管理器
        
        Args:
            db_path: SQLite 数据库文件路径
        """
        self.db_path = db_path
        self._local = threading.local()  # 线程本地存储，避免并发冲突
        self._init_db()
    
    @contextmanager
    def _get_connection(self):
        """
        获取数据库连接的上下文管理器
        
        确保每个线程使用独立的连接，避免 SQLite 的线程安全问题
        自动处理事务提交和回滚
        """
        conn = None
        try:
            # 检查是否已有当前线程的连接
            if not hasattr(self._local, 'conn') or self._local.conn is None:
                self._local.conn = sqlite3.connect(
                    self.db_path,
                    timeout=30.0,  # 锁等待超时时间
                    isolation_level=None  # 自动提交模式，手动控制事务
                )
                self._local.conn.execute("PRAGMA journal_mode=WAL")  # WAL 模式提升并发性能
                self._local.conn.execute("PRAGMA busy_timeout=30000")  # 忙等待 30 秒
            
            conn = self._local.conn
            yield conn
        except sqlite3.Error as e:
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            raise e
        finally:
            # 注意：不关闭连接，保持线程池复用
            pass
    
    def _init_db(self):
        """
        初始化数据库表结构
        
        创建两张表:
            1. cooldown_states: 存储冷却期状态
            2. dead_letter_queue: 死信队列，存储发送失败的消息
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # 创建冷却期状态表
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS cooldown_states (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        state_key TEXT UNIQUE NOT NULL,      -- 状态键（如 alert_type）
                        cooldown_until REAL NOT NULL,         -- 冷却期结束时间戳（Unix 时间）
                        created_at REAL DEFAULT (strftime('%s', 'now')),
                        updated_at REAL DEFAULT (strftime('%s', 'now'))
                    )
                """)
                
                # 创建死信队列表
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS dead_letter_queue (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        message_content TEXT NOT NULL,        -- 消息内容（JSON 字符串）
                        message_type TEXT NOT NULL,           -- 消息类型（如 alert, system）
                        retry_count INTEGER DEFAULT 0,        -- 重试次数
                        max_retries INTEGER DEFAULT 3,        -- 最大重试次数
                        created_at REAL DEFAULT (strftime('%s', 'now')),
                        next_retry_at REAL DEFAULT (strftime('%s', 'now')),
                        last_error TEXT,                      -- 最后一次错误信息
                        is_processed INTEGER DEFAULT 0        -- 是否已处理（0: 未处理，1: 已处理）
                    )
                """)
                
                # 创建索引加速查询
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_cooldown_key 
                    ON cooldown_states(state_key)
                """)
                
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_dlq_retry 
                    ON dead_letter_queue(next_retry_at, is_processed)
                """)
                
                conn.commit()
                
        except sqlite3.Error as e:
            print(f"[StateManager] 数据库初始化失败：{e}")
            raise
    
    def check_cooldown(self, state_key: str) -> bool:
        """
        检查指定状态键是否处于冷却期
        
        Args:
            state_key: 状态键（如 "price_alert", "system_alert"）
        
        Returns:
            bool: True 表示处于冷却期（不能发送），False 表示可以发送
        
        异常处理:
            - 数据库异常时返回 False（允许发送，避免漏报）
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                current_time = time.time()
                
                cursor.execute("""
                    SELECT cooldown_until FROM cooldown_states
                    WHERE state_key = ?
                """, (state_key,))
                
                row = cursor.fetchone()
                
                if row is None:
                    # 没有记录，说明不在冷却期
                    return False
                
                cooldown_until = row[0]
                
                if current_time >= cooldown_until:
                    # 冷却期已过，可以删除记录或更新
                    cursor.execute("""
                        DELETE FROM cooldown_states WHERE state_key = ?
                    """, (state_key,))
                    conn.commit()
                    return False
                else:
                    # 仍在冷却期
                    remaining_seconds = cooldown_until - current_time
                    print(f"[StateManager] 状态 '{state_key}' 处于冷却期，剩余 {remaining_seconds:.0f} 秒")
                    return True
                    
        except sqlite3.Error as e:
            print(f"[StateManager] 检查冷却期失败：{e}，默认允许发送")
            return False
        except Exception as e:
            print(f"[StateManager] 未知错误（检查冷却期）：{e}，默认允许发送")
            return False
    
    def set_cooldown(self, state_key: str, duration_minutes: int) -> bool:
        """
        设置冷却期（先写状态，后发消息）
        
        这是防漏报设计的核心：在发送消息之前，先将冷却期写入数据库。
        即使消息发送失败，冷却期状态也已经持久化，不会导致重复报警。
        
        Args:
            state_key: 状态键
            duration_minutes: 冷却时长（分钟），从 config.yaml 读取
        
        Returns:
            bool: True 表示设置成功，False 表示失败
        
        注意:
            - 使用 INSERT OR REPLACE 确保原子性
            - 即使消息发送失败，冷却期也已经记录
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                current_time = time.time()
                cooldown_until = current_time + (duration_minutes * 60)
                
                # 使用 INSERT OR REPLACE 实现原子更新
                cursor.execute("""
                    INSERT OR REPLACE INTO cooldown_states 
                    (state_key, cooldown_until, updated_at)
                    VALUES (?, ?, ?)
                """, (state_key, cooldown_until, current_time))
                
                conn.commit()
                
                print(f"[StateManager] 已设置状态 '{state_key}' 的冷却期，持续 {duration_minutes} 分钟")
                return True
                
        except sqlite3.Error as e:
            print(f"[StateManager] 设置冷却期失败：{e}")
            return False
        except Exception as e:
            print(f"[StateManager] 未知错误（设置冷却期）：{e}")
            return False
    
    def clear_cooldown(self, state_key: str) -> bool:
        """
        手动清除指定状态键的冷却期
        
        Args:
            state_key: 状态键
        
        Returns:
            bool: 清除是否成功
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    DELETE FROM cooldown_states WHERE state_key = ?
                """, (state_key,))
                conn.commit()
                
                print(f"[StateManager] 已清除状态 '{state_key}' 的冷却期")
                return True
                
        except sqlite3.Error as e:
            print(f"[StateManager] 清除冷却期失败：{e}")
            return False
    
    def push_dlq(
        self, 
        message_content: str, 
        message_type: str = "alert",
        max_retries: int = 3
    ) -> bool:
        """
        将发送失败的消息压入死信队列 (DLQ)
        
        当消息发送失败时（如网络超时、API 限流），调用此方法将消息暂存，
        由后台任务定期重试发送。
        
        Args:
            message_content: 消息内容（可以是 JSON 字符串或纯文本）
            message_type: 消息类型（alert/system/report 等）
            max_retries: 最大重试次数
        
        Returns:
            bool: 入队是否成功
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                current_time = time.time()
                
                # 立即重试可能再次失败，设置 1 分钟后首次重试
                next_retry_at = current_time + 60
                
                cursor.execute("""
                    INSERT INTO dead_letter_queue 
                    (message_content, message_type, max_retries, next_retry_at)
                    VALUES (?, ?, ?, ?)
                """, (message_content, message_type, max_retries, next_retry_at))
                
                conn.commit()
                
                message_id = cursor.lastrowid
                print(f"[StateManager] 消息已压入死信队列，ID={message_id}, 类型={message_type}")
                return True
                
        except sqlite3.Error as e:
            print(f"[StateManager] 压入死信队列失败：{e}")
            return False
        except Exception as e:
            print(f"[StateManager] 未知错误（压入 DLQ）：{e}")
            return False
    
    def pop_dlq(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        从死信队列取出待重试的消息
        
        只返回当前时间已到重试时间且未处理完成的消息。
        
        Args:
            limit: 每次最多取出的消息数量
        
        Returns:
            List[Dict]: 待重试消息列表，每条消息包含:
                - id: 消息 ID
                - content: 消息内容
                - type: 消息类型
                - retry_count: 当前重试次数
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                current_time = time.time()
                
                # 查询已到重试时间且未处理完成的消息
                cursor.execute("""
                    SELECT id, message_content, message_type, retry_count, max_retries
                    FROM dead_letter_queue
                    WHERE next_retry_at <= ? AND is_processed = 0
                    ORDER BY created_at ASC
                    LIMIT ?
                """, (current_time, limit))
                
                rows = cursor.fetchall()
                
                messages = []
                for row in rows:
                    messages.append({
                        "id": row[0],
                        "content": row[1],
                        "type": row[2],
                        "retry_count": row[3],
                        "max_retries": row[4]
                    })
                
                if messages:
                    print(f"[StateManager] 从死信队列取出 {len(messages)} 条待重试消息")
                
                return messages
                
        except sqlite3.Error as e:
            print(f"[StateManager] 从死信队列取出消息失败：{e}")
            return []
        except Exception as e:
            print(f"[StateManager] 未知错误（弹出 DLQ）：{e}")
            return []
    
    def update_dlq_retry(
        self, 
        message_id: int, 
        increment_retry: bool = True,
        error_message: Optional[str] = None
    ) -> bool:
        """
        更新死信队列消息的重试状态
        
        Args:
            message_id: 消息 ID
            increment_retry: 是否增加重试次数
            error_message: 错误信息（如果重试失败）
        
        Returns:
            bool: 更新是否成功
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                current_time = time.time()
                
                if increment_retry:
                    # 增加重试次数，设置下次重试时间（指数退避）
                    cursor.execute("""
                        UPDATE dead_letter_queue
                        SET retry_count = retry_count + 1,
                            next_retry_at = ? + (60 * POW(2, retry_count)),
                            last_error = ?
                        WHERE id = ?
                    """, (current_time, error_message, message_id))
                else:
                    # 重试成功，标记为已处理
                    cursor.execute("""
                        UPDATE dead_letter_queue
                        SET is_processed = 1,
                            last_error = NULL
                        WHERE id = ?
                    """, (message_id,))
                
                conn.commit()
                return True
                
        except sqlite3.Error as e:
            print(f"[StateManager] 更新 DLQ 重试状态失败：{e}")
            return False
        except Exception as e:
            print(f"[StateManager] 未知错误（更新 DLQ）：{e}")
            return False
    
    def remove_from_dlq(self, message_id: int) -> bool:
        """
        从死信队列移除消息（发送成功后调用）
        
        Args:
            message_id: 消息 ID
        
        Returns:
            bool: 移除是否成功
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    DELETE FROM dead_letter_queue WHERE id = ?
                """, (message_id,))
                conn.commit()
                
                print(f"[StateManager] 已从死信队列移除消息 ID={message_id}")
                return True
                
        except sqlite3.Error as e:
            print(f"[StateManager] 从死信队列移除消息失败：{e}")
            return False
        except Exception as e:
            print(f"[StateManager] 未知错误（移除 DLQ）：{e}")
            return False
    
    def get_dlq_stats(self) -> Dict[str, Any]:
        """
        获取死信队列统计信息
        
        Returns:
            Dict: 包含 pending_count, total_retries, oldest_message 等统计
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # 统计待处理消息数量
                cursor.execute("""
                    SELECT COUNT(*) FROM dead_letter_queue WHERE is_processed = 0
                """)
                pending_count = cursor.fetchone()[0]
                
                # 统计总重试次数
                cursor.execute("""
                    SELECT COALESCE(SUM(retry_count), 0) FROM dead_letter_queue WHERE is_processed = 0
                """)
                total_retries = cursor.fetchone()[0]
                
                # 获取最早的消息时间
                cursor.execute("""
                    SELECT MIN(created_at) FROM dead_letter_queue WHERE is_processed = 0
                """)
                oldest_timestamp = cursor.fetchone()[0]
                oldest_message = datetime.fromtimestamp(oldest_timestamp).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ) if oldest_timestamp else None
                
                return {
                    "pending_count": pending_count,
                    "total_retries": int(total_retries),
                    "oldest_message": oldest_message
                }
                
        except sqlite3.Error as e:
            print(f"[StateManager] 获取 DLQ 统计失败：{e}")
            return {"pending_count": 0, "total_retries": 0, "oldest_message": None}
        except Exception as e:
            print(f"[StateManager] 未知错误（获取 DLQ 统计）：{e}")
            return {"pending_count": 0, "total_retries": 0, "oldest_message": None}
    
    def cleanup_processed(self, older_than_days: int = 7) -> int:
        """
        清理已处理的消息（定期维护用）
        
        Args:
            older_than_days: 清理多少天前的已处理消息
        
        Returns:
            int: 清理的消息数量
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cutoff_time = time.time() - (older_than_days * 24 * 60 * 60)
                
                cursor.execute("""
                    DELETE FROM dead_letter_queue 
                    WHERE is_processed = 1 AND created_at < ?
                """, (cutoff_time,))
                
                deleted_count = cursor.rowcount
                conn.commit()
                
                if deleted_count > 0:
                    print(f"[StateManager] 已清理 {deleted_count} 条已处理的历史消息")
                
                return deleted_count
                
        except sqlite3.Error as e:
            print(f"[StateManager] 清理已处理消息失败：{e}")
            return 0
        except Exception as e:
            print(f"[StateManager] 未知错误（清理 DLQ）：{e}")
            return 0
    
    def close(self):
        """
        关闭数据库连接
        
        在程序退出时调用，释放资源
        """
        try:
            if hasattr(self._local, 'conn') and self._local.conn is not None:
                self._local.conn.close()
                self._local.conn = None
                print("[StateManager] 数据库连接已关闭")
        except Exception as e:
            print(f"[StateManager] 关闭连接时出错：{e}")


# ==================== 使用示例 ====================
if __name__ == "__main__":
    # 测试代码
    state_mgr = StateManager()
    
    # 测试冷却期
    print("=== 测试冷却期 ===")
    print(f"检查冷却期 (should be False): {state_mgr.check_cooldown('test_alert')}")
    print(f"设置冷却期 1 分钟：{state_mgr.set_cooldown('test_alert', 1)}")
    print(f"检查冷却期 (should be True): {state_mgr.check_cooldown('test_alert')}")
    
    # 测试死信队列
    print("\n=== 测试死信队列 ===")
    print(f"压入 DLQ: {state_mgr.push_dlq('{\"price\": 2000}', 'alert')}")
    print(f"压入 DLQ: {state_mgr.push_dlq('{\"price\": 1999}', 'alert')}")
    print(f"DLQ 统计：{state_mgr.get_dlq_stats()}")
    print(f"弹出 DLQ: {state_mgr.pop_dlq(5)}")
    
    # 清理
    state_mgr.close()
