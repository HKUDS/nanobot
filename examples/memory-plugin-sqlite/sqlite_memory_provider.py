"""SQLite-based memory provider for nanobot.

This provider stores memory in SQLite database, offering:
- Persistent storage with ACID guarantees
- Efficient full-text search (with FTS5 extension)
- Structured data storage
- Easy backup and migration

Usage:
    # In your nanobot configuration
    memory:
      provider: "sqlite"
      config:
        db_path: "~/.nanobot/memory.db"
        use_fts5: true  # Enable full-text search (if SQLite supports it)

Or programmatically:
    from sqlite_memory_provider import SQLiteMemoryProvider
    
    provider = SQLiteMemoryProvider({
        "db_path": "/path/to/memory.db",
        "use_fts5": True
    })
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from nanobot.memory.base import BaseMemoryProvider, MemoryEntry
from nanobot.memory.registry import MemoryProviderRegistry


class SQLiteMemoryProvider(BaseMemoryProvider):
    """SQLite-based memory provider.
    
    Schema:
        - long_term: Single row table storing long-term memory content
        - history: Table storing history entries with timestamps
        - history_fts: FTS5 virtual table for full-text search (optional)
    
    Configuration:
        db_path: Path to SQLite database file (default: "~/.nanobot/memory.db")
        use_fts5: Enable FTS5 full-text search (default: True if available)
    """

    def __init__(self, config: dict[str, Any] | None = None):
        """Initialize SQLite memory provider.
        
        Args:
            config: Configuration with keys:
                - db_path: Database file path
                - use_fts5: Enable FTS5 search
        """
        super().__init__(config)
        
        self._db_path = Path(self.config.get("db_path", "~/.nanobot/memory.db")).expanduser()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Check FTS5 availability
        self._use_fts5 = self.config.get("use_fts5", True)
        if self._use_fts5 and not self._has_fts5():
            self._use_fts5 = False
        
        self._init_db()

    def _has_fts5(self) -> bool:
        """Check if SQLite supports FTS5 extension."""
        try:
            conn = sqlite3.connect(":memory:")
            conn.execute("CREATE VIRTUAL TABLE test USING fts5(content)")
            conn.close()
            return True
        except sqlite3.OperationalError:
            return False

    def _init_db(self) -> None:
        """Initialize database schema."""
        with sqlite3.connect(self._db_path) as conn:
            # Long-term memory table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS long_term (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    content TEXT NOT NULL DEFAULT '',
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Insert default row if not exists
            conn.execute("""
                INSERT OR IGNORE INTO long_term (id, content) VALUES (1, '')
            """)
            
            # History table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    metadata TEXT  -- JSON-encoded metadata
                )
            """)
            
            # Create index on timestamp
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_history_timestamp 
                ON history(timestamp)
            """)
            
            # FTS5 virtual table for full-text search
            if self._use_fts5:
                conn.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS history_fts USING fts5(
                        content,
                        content_rowid=rowid,
                        content=history
                    )
                """)
                
                # Triggers to keep FTS index in sync
                conn.execute("""
                    CREATE TRIGGER IF NOT EXISTS history_fts_insert
                    AFTER INSERT ON history
                    BEGIN
                        INSERT INTO history_fts(rowid, content) VALUES (new.id, new.content);
                    END
                """)
                
                conn.execute("""
                    CREATE TRIGGER IF NOT EXISTS history_fts_delete
                    AFTER DELETE ON history
                    BEGIN
                        INSERT INTO history_fts(history_fts, rowid, content) 
                        VALUES ('delete', old.id, old.content);
                    END
                """)

    @property
    def name(self) -> str:
        """Return provider name."""
        return "sqlite"

    def read_long_term(self) -> str:
        """Read long-term memory content.
        
        Returns:
            Long-term memory content or empty string.
        """
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute(
                "SELECT content FROM long_term WHERE id = 1"
            )
            row = cursor.fetchone()
            return row[0] if row else ""

    def write_long_term(self, content: str) -> None:
        """Write long-term memory content.
        
        Args:
            content: Complete long-term memory content.
        """
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO long_term (id, content, updated_at) 
                VALUES (1, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET 
                    content = excluded.content,
                    updated_at = excluded.updated_at
                """,
                (content,)
            )

    def append_history(self, entry: str) -> None:
        """Append entry to history.
        
        Args:
            entry: History entry text (typically with [YYYY-MM-DD HH:MM] prefix).
        """
        # Try to parse timestamp from entry
        timestamp = None
        if entry.startswith("[") and "]" in entry:
            time_str = entry[1:entry.find("]")]
            try:
                timestamp = datetime.strptime(time_str, "%Y-%m-%d %H:%M")
            except ValueError:
                pass

        metadata = {}
        if timestamp:
            metadata["parsed_timestamp"] = timestamp.isoformat()

        with sqlite3.connect(self._db_path) as conn:
            if timestamp:
                conn.execute(
                    """
                    INSERT INTO history (content, timestamp, metadata) 
                    VALUES (?, ?, ?)
                    """,
                    (entry, timestamp, json.dumps(metadata))
                )
            else:
                conn.execute(
                    "INSERT INTO history (content, metadata) VALUES (?, ?)",
                    (entry, json.dumps(metadata))
                )

    def search_history(
        self,
        query: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 100,
    ) -> list[MemoryEntry]:
        """Search history entries.
        
        Uses FTS5 for full-text search if available and query is provided.
        Otherwise uses LIKE-based search.
        
        Args:
            query: Optional text to search for
            start_time: Optional start time filter
            end_time: Optional end time filter
            limit: Maximum entries to return
            
        Returns:
            List of matching entries, newest first.
        """
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            
            # Build query
            if query and self._use_fts5:
                # Use FTS5 for full-text search
                sql = """
                    SELECT h.id, h.content, h.timestamp, h.metadata
                    FROM history h
                    JOIN history_fts fts ON h.id = fts.rowid
                    WHERE history_fts MATCH ?
                """
                params = [query]
                
                if start_time:
                    sql += " AND h.timestamp >= ?"
                    params.append(start_time)
                if end_time:
                    sql += " AND h.timestamp <= ?"
                    params.append(end_time)
                
                sql += " ORDER BY h.timestamp DESC LIMIT ?"
                params.append(limit)
                
            else:
                # Use regular query with LIKE
                sql = "SELECT id, content, timestamp, metadata FROM history WHERE 1=1"
                params = []
                
                if query:
                    sql += " AND content LIKE ?"
                    params.append(f"%{query}%")
                if start_time:
                    sql += " AND timestamp >= ?"
                    params.append(start_time)
                if end_time:
                    sql += " AND timestamp <= ?"
                    params.append(end_time)
                
                sql += " ORDER BY timestamp DESC LIMIT ?"
                params.append(limit)
            
            cursor = conn.execute(sql, params)
            rows = cursor.fetchall()
            
            results = []
            for row in rows:
                metadata = json.loads(row["metadata"]) if row["metadata"] else {}
                results.append(MemoryEntry(
                    content=row["content"],
                    timestamp=datetime.fromisoformat(row["timestamp"]),
                    metadata=metadata,
                    entry_type="history",
                ))
            
            return results

    def get_memory_context(self) -> str:
        """Get formatted memory context.
        
        Returns:
            Long-term memory with header, or empty string.
        """
        long_term = self.read_long_term()
        return f"## Long-term Memory\n{long_term}" if long_term else ""

    def close(self) -> None:
        """Close database connection (no-op for connection-per-operation)."""
        pass

    @property
    def is_available(self) -> bool:
        """Check if database is accessible.
        
        Returns:
            True if database can be written to.
        """
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute("SELECT 1")
            return True
        except Exception:
            return False

    def get_stats(self) -> dict[str, Any]:
        """Get memory statistics.
        
        Returns:
            Dictionary with statistics about stored memory.
        """
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM history")
            history_count = cursor.fetchone()[0]
            
            cursor = conn.execute(
                "SELECT LENGTH(content) FROM long_term WHERE id = 1"
            )
            long_term_size = cursor.fetchone()[0] or 0
            
            return {
                "history_entries": history_count,
                "long_term_size_bytes": long_term_size,
                "database_path": str(self._db_path),
                "fts5_enabled": self._use_fts5,
            }

    def clear(self) -> None:
        """Clear all memory (use with caution)."""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("UPDATE long_term SET content = '', updated_at = CURRENT_TIMESTAMP")
            conn.execute("DELETE FROM history")
            if self._use_fts5:
                conn.execute("DELETE FROM history_fts")


# Register the provider
MemoryProviderRegistry.register("sqlite", SQLiteMemoryProvider)
