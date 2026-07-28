"""
基于SQLite的会话存储模块
支持并发安全，替代JSONL文件存储
"""
import sqlite3
import json
import os
from datetime import datetime
from typing import List, Dict, Any, Optional


class SessionStore:
    """SQLite会话存储"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        """初始化数据库表"""
        os.makedirs(os.path.dirname(self.db_path) if os.path.dirname(self.db_path) else '.', exist_ok=True)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 会话表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # 消息表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                user_input TEXT NOT NULL,
                assistant_response TEXT NOT NULL,
                sources TEXT,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            )
        """)
        
        # 索引
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_session_id 
            ON messages(session_id)
        """)
        
        conn.commit()
        conn.close()
    
    def save_conversation(
        self, 
        session_id: str, 
        user_input: str, 
        assistant_response: str, 
        sources: List[Dict] = None
    ):
        """保存一轮对话"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # 确保会话存在
            cursor.execute(
                "INSERT OR IGNORE INTO sessions (session_id) VALUES (?)",
                (session_id,)
            )
            
            # 插入消息
            sources_json = json.dumps(sources or [], ensure_ascii=False)
            cursor.execute(
                """
                INSERT INTO messages (session_id, user_input, assistant_response, sources)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, user_input, assistant_response, sources_json)
            )
            
            conn.commit()
        finally:
            conn.close()
    
    def load_conversation(self, session_id: str, max_rounds: int = 5) -> List[Dict]:
        """加载最近N轮对话历史"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                """
                SELECT timestamp, user_input, assistant_response, sources
                FROM messages
                WHERE session_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (session_id, max_rounds)
            )
            
            rows = cursor.fetchall()
            
            # 转换为字典列表，按时间正序排列
            history = []
            for row in reversed(rows):
                history.append({
                    "timestamp": row[0],
                    "user": row[1],
                    "assistant": row[2],
                    "sources": json.loads(row[3]) if row[3] else []
                })
            
            return history
        finally:
            conn.close()
    
    def truncate_history(self, session_id: str, max_rounds: int = 100):
        """只保留最近N轮对话，防止数据无限膨胀"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # 获取当前消息数
            cursor.execute(
                "SELECT COUNT(*) FROM messages WHERE session_id = ?",
                (session_id,)
            )
            count = cursor.fetchone()[0]
            
            if count > max_rounds:
                # 删除旧消息
                cursor.execute(
                    """
                    DELETE FROM messages
                    WHERE session_id = ? AND id NOT IN (
                        SELECT id FROM messages
                        WHERE session_id = ?
                        ORDER BY timestamp DESC
                        LIMIT ?
                    )
                    """,
                    (session_id, session_id, max_rounds)
                )
                conn.commit()
        finally:
            conn.close()
    
    def delete_session(self, session_id: str):
        """删除整个会话"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            cursor.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
            conn.commit()
        finally:
            conn.close()
    
    def list_sessions(self, limit: int = 100) -> List[Dict]:
        """列出所有会话"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                """
                SELECT s.session_id, s.created_at, COUNT(m.id) as message_count
                FROM sessions s
                LEFT JOIN messages m ON s.session_id = m.session_id
                GROUP BY s.session_id
                ORDER BY s.created_at DESC
                LIMIT ?
                """,
                (limit,)
            )
            
            sessions = []
            for row in cursor.fetchall():
                sessions.append({
                    "session_id": row[0],
                    "created_at": row[1],
                    "message_count": row[2]
                })
            
            return sessions
        finally:
            conn.close()