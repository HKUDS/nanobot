"""SQLite-based token usage storage.

This module provides a SQLite-based storage for token usage statistics,
which is more reliable than JSON files for concurrent access.
"""

import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.utils.helpers import ensure_dir


class TokenStore:
    """SQLite-based token usage storage."""
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        """Singleton pattern to ensure single database connection."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        """Initialize the token store."""
        if self._initialized:
            return
        
        self.db_path = ensure_dir(Path.home() / ".nanobot") / "token_usage.db"
        self._local = threading.local()
        self._init_db()
        self._initialized = True
    
    def _get_connection(self) -> sqlite3.Connection:
        """Get a thread-local database connection."""
        if not hasattr(self._local, 'connection') or self._local.connection is None:
            self._local.connection = sqlite3.connect(self.db_path)
            self._local.connection.row_factory = sqlite3.Row
        return self._local.connection
    
    def _init_db(self) -> None:
        """Initialize the database schema."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Token usage table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS token_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_key TEXT NOT NULL,
                model TEXT NOT NULL,
                prompt_tokens INTEGER NOT NULL DEFAULT 0,
                completion_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Index for faster queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_token_usage_session 
            ON token_usage(session_key)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_token_usage_model 
            ON token_usage(model)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_token_usage_created 
            ON token_usage(created_at)
        """)
        
        conn.commit()
        logger.debug(f"Token database initialized at {self.db_path}")
    
    def record_usage(
        self,
        session_key: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int
    ) -> None:
        """
        Record token usage for a request.
        
        Args:
            session_key: The session identifier (channel:chat_id).
            model: The model name used.
            prompt_tokens: Number of prompt tokens.
            completion_tokens: Number of completion tokens.
        """
        total_tokens = prompt_tokens + completion_tokens
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO token_usage 
            (session_key, model, prompt_tokens, completion_tokens, total_tokens)
            VALUES (?, ?, ?, ?, ?)
        """, (session_key, model, prompt_tokens, completion_tokens, total_tokens))
        
        conn.commit()
        logger.debug(
            f"Recorded token usage: {session_key} / {model} "
            f"= {prompt_tokens} + {completion_tokens} = {total_tokens}"
        )
    
    def get_summary(self) -> dict[str, Any]:
        """
        Get token usage summary for different time periods.
        
        Returns:
            Dict with usage statistics for today, this week, this month, and all time.
        """
        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=now.weekday())
        month_start = today_start.replace(day=1)
        
        return {
            "today": self._get_usage_by_date_range(today_start, now),
            "this_week": self._get_usage_by_date_range(week_start, now),
            "this_month": self._get_usage_by_date_range(month_start, now),
            "all_time": self._get_usage_by_date_range(),
        }
    
    def _get_usage_by_date_range(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None
    ) -> dict[str, Any]:
        """
        Get aggregated token usage for a date range.
        
        Args:
            start_date: Start date (inclusive), None for no limit.
            end_date: End date (inclusive), None for no limit.
        
        Returns:
            Dict with token usage statistics.
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Build query
        where_clauses = []
        params = []
        
        if start_date:
            where_clauses.append("created_at >= ?")
            params.append(start_date.isoformat())
        if end_date:
            where_clauses.append("created_at <= ?")
            params.append(end_date.isoformat())
        
        where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""
        
        # Get overall stats
        cursor.execute(f"""
            SELECT 
                COUNT(*) as request_count,
                SUM(prompt_tokens) as prompt_tokens,
                SUM(completion_tokens) as completion_tokens,
                SUM(total_tokens) as total_tokens
            FROM token_usage
            {where_sql}
        """, params)
        
        row = cursor.fetchone()
        result = {
            "request_count": row["request_count"] or 0,
            "prompt_tokens": row["prompt_tokens"] or 0,
            "completion_tokens": row["completion_tokens"] or 0,
            "total_tokens": row["total_tokens"] or 0,
            "model_usage": {},
        }
        
        # Get per-model stats
        cursor.execute(f"""
            SELECT 
                model,
                COUNT(*) as request_count,
                SUM(prompt_tokens) as prompt_tokens,
                SUM(completion_tokens) as completion_tokens,
                SUM(total_tokens) as total_tokens
            FROM token_usage
            {where_sql}
            GROUP BY model
        """, params)
        
        for row in cursor.fetchall():
            result["model_usage"][row["model"]] = {
                "request_count": row["request_count"],
                "prompt_tokens": row["prompt_tokens"],
                "completion_tokens": row["completion_tokens"],
                "total_tokens": row["total_tokens"],
            }
        
        return result
    
    def reset(self, model: str | None = None) -> int:
        """
        Reset token usage statistics.
        
        Args:
            model: If provided, only reset usage for this model.
                  If None, reset all token usage.
        
        Returns:
            Number of records deleted.
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        if model:
            cursor.execute(
                "DELETE FROM token_usage WHERE model = ?",
                (model,)
            )
        else:
            cursor.execute("DELETE FROM token_usage")
        
        deleted = cursor.rowcount
        conn.commit()
        
        if model:
            logger.info(f"Reset token usage for model '{model}': {deleted} records deleted")
        else:
            logger.info(f"Reset all token usage: {deleted} records deleted")
        
        return deleted
    
    def close(self) -> None:
        """Close the database connection."""
        if hasattr(self._local, 'connection') and self._local.connection:
            self._local.connection.close()
            self._local.connection = None
