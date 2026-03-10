"""Memory search tool with SQLite FTS5 full-text search."""

from __future__ import annotations

import sqlite3
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.agent.tools.base import Tool


class MemoryIndex:
    """SQLite FTS5 index for HISTORY.md entries."""

    def __init__(self, memory_dir: Path):
        self.db_path = memory_dir / "memory.db"
        self.history_file = memory_dir / "HISTORY.md"
        self._conn: sqlite3.Connection | None = None
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            # Ensure parent directory exists
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.execute("PRAGMA journal_mode=WAL")
        return self._conn

    def _init_db(self) -> None:
        """Create tables and FTS5 virtual table if not exists."""
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                content TEXT,
                source TEXT DEFAULT 'history'
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(
                content,
                content='entries',
                content_rowid='id',
                tokenize='unicode61'
            );
            CREATE TRIGGER IF NOT EXISTS entries_ai AFTER INSERT ON entries BEGIN
                INSERT INTO entries_fts(rowid, content) VALUES (new.id, new.content);
            END;
            CREATE TRIGGER IF NOT EXISTS entries_ad AFTER DELETE ON entries BEGIN
                INSERT INTO entries_fts(entries_fts, rowid, content)
                    VALUES('delete', old.id, old.content);
            END;
        """)
        conn.commit()
        # Auto-import existing HISTORY.md on first use
        count = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        if count == 0:
            self._import_history()

    def _import_history(self) -> None:
        """Import existing HISTORY.md entries into SQLite."""
        if not self.history_file.exists():
            return
        text = self.history_file.read_text(encoding="utf-8")
        entries = self._parse_history(text)
        if not entries:
            return
        conn = self._get_conn()
        conn.executemany(
            "INSERT INTO entries (timestamp, content) VALUES (?, ?)",
            entries,
        )
        conn.commit()
        logger.info("Memory index: imported {} entries from HISTORY.md", len(entries))

    @staticmethod
    def _parse_history(text: str) -> list[tuple[str, str]]:
        """Parse HISTORY.md into (timestamp, content) tuples."""
        entries = []
        # Split by double newline (each entry is a paragraph)
        blocks = [b.strip() for b in text.split("\n\n") if b.strip()]
        ts_pattern = re.compile(r"\[(\d{4}-\d{2}-\d{2}[\sT]\d{2}:\d{2})")
        for block in blocks:
            match = ts_pattern.search(block)
            ts = match.group(1).replace("T", " ") if match else ""
            entries.append((ts, block))
        return entries

    def index_entry(self, content: str, timestamp: str | None = None) -> None:
        """Add a single entry to the index."""
        if not content or not content.strip():
            return
        if not timestamp:
            ts_match = re.search(r"\[(\d{4}-\d{2}-\d{2}[\sT]\d{2}:\d{2})", content)
            timestamp = ts_match.group(1).replace("T", " ") if ts_match else ""
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO entries (timestamp, content) VALUES (?, ?)",
            (timestamp, content.strip()),
        )
        conn.commit()

    def search(
        self,
        query: str,
        time_range: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Search entries using FTS5 with optional time filtering."""
        conn = self._get_conn()

        # Build time filter
        time_filter = ""
        params: list[Any] = []

        if time_range:
            cutoff = self._time_cutoff(time_range)
            if cutoff:
                time_filter = "AND e.timestamp >= ?"
                params.append(cutoff)

        # Escape FTS5 special characters and build query
        fts_query = self._build_fts_query(query)
        if not fts_query:
            return []

        sql = f"""
            SELECT e.timestamp, e.content, rank
            FROM entries_fts f
            JOIN entries e ON f.rowid = e.id
            WHERE entries_fts MATCH ?
            {time_filter}
            ORDER BY rank
            LIMIT ?
        """
        params = [fts_query] + params + [limit]

        try:
            rows = conn.execute(sql, params).fetchall()
            return [
                {"timestamp": r[0], "content": r[1], "score": round(-r[2], 4)}
                for r in rows
            ]
        except sqlite3.OperationalError as e:
            logger.warning("FTS5 search failed: {}", e)
            # Fallback to LIKE search
            return self._fallback_search(query, time_range, limit)

    def _fallback_search(
        self, query: str, time_range: str | None, limit: int
    ) -> list[dict[str, Any]]:
        """Fallback to LIKE search when FTS5 query fails."""
        conn = self._get_conn()
        params: list[Any] = [f"%{query}%"]
        time_filter = ""
        if time_range:
            cutoff = self._time_cutoff(time_range)
            if cutoff:
                time_filter = "AND timestamp >= ?"
                params.append(cutoff)
        sql = f"""
            SELECT timestamp, content FROM entries
            WHERE content LIKE ? {time_filter}
            ORDER BY id DESC LIMIT ?
        """
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        return [{"timestamp": r[0], "content": r[1], "score": 0} for r in rows]

    @staticmethod
    def _build_fts_query(query: str) -> str:
        """Build a safe FTS5 query from user input."""
        # Remove FTS5 special operators to prevent syntax errors
        cleaned = re.sub(r'["\'\(\)\*\+\-\^~]', " ", query)
        tokens = [t for t in cleaned.split() if len(t) > 0]
        if not tokens:
            return ""
        # Use implicit AND: each token must appear
        return " ".join(f'"{t}"' for t in tokens)

    @staticmethod
    def _time_cutoff(time_range: str) -> str | None:
        """Convert time range string to cutoff timestamp."""
        now = datetime.now()
        deltas = {
            "day": timedelta(days=1),
            "week": timedelta(weeks=1),
            "month": timedelta(days=30),
            "quarter": timedelta(days=90),
            "year": timedelta(days=365),
        }
        delta = deltas.get(time_range)
        if not delta:
            return None
        return (now - delta).strftime("%Y-%m-%d %H:%M")

    def reindex(self) -> int:
        """Rebuild the entire index from HISTORY.md."""
        conn = self._get_conn()
        conn.execute("DELETE FROM entries")
        conn.execute("INSERT INTO entries_fts(entries_fts) VALUES('delete-all')")
        conn.commit()
        self._import_history()
        count = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        logger.info("Memory index rebuilt: {} entries", count)
        return count

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None


class MemorySearchTool(Tool):
    """Search agent memory (HISTORY.md) using full-text search."""

    name = "memory_search"
    description = (
        "Search past conversation history and events using full-text search. "
        "Returns relevant entries ranked by relevance. Use this instead of "
        "grep to find information from past sessions."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query (keywords or phrases).",
            },
            "time_range": {
                "type": "string",
                "enum": ["day", "week", "month", "quarter", "year"],
                "description": "Optional: limit results to a time range.",
            },
            "limit": {
                "type": "integer",
                "description": "Max results to return (default 10).",
            },
        },
        "required": ["query"],
    }

    def __init__(self, index: MemoryIndex):
        self._index = index

    async def execute(self, **kwargs: Any) -> str:
        query = kwargs.get("query", "")
        time_range = kwargs.get("time_range")
        limit = kwargs.get("limit", 10)

        if not query.strip():
            return "Error: query cannot be empty."

        results = self._index.search(query, time_range=time_range, limit=limit)

        if not results:
            return f"No results found for '{query}'."

        lines = [f"Found {len(results)} result(s) for '{query}':\n"]
        for i, r in enumerate(results, 1):
            ts = f"[{r['timestamp']}] " if r["timestamp"] else ""
            lines.append(f"{i}. {ts}{r['content']}")
        return "\n\n".join(lines)
