"""Unified SQLite storage for the memory subsystem.

Replaces events.jsonl + profile.json + mem0/Qdrant + HISTORY.md + MEMORY.md
with a single SQLite database (memory.db). Uses FTS5 for keyword search
and sqlite-vec for vector search.

All public methods are synchronous. Callers that need async compatibility
wrap calls with asyncio.to_thread().
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

import sqlite_vec

from .helpers import _utc_now_iso

__all__ = ["UnifiedMemoryDB"]

# FTS5 content-sync triggers — keep events_fts in sync with events table.
_FTS_TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS events_ai AFTER INSERT ON events BEGIN
    INSERT INTO events_fts(rowid, summary) VALUES (new.rowid, new.summary);
END;
CREATE TRIGGER IF NOT EXISTS events_ad AFTER DELETE ON events BEGIN
    INSERT INTO events_fts(events_fts, rowid, summary)
        VALUES('delete', old.rowid, old.summary);
END;
CREATE TRIGGER IF NOT EXISTS events_au AFTER UPDATE ON events BEGIN
    INSERT INTO events_fts(events_fts, rowid, summary)
        VALUES('delete', old.rowid, old.summary);
    INSERT INTO events_fts(rowid, summary) VALUES (new.rowid, new.summary);
END;
"""


class UnifiedMemoryDB:
    """Single-file SQLite database for all memory storage.

    Parameters
    ----------
    db_path : Path
        Path to the SQLite database file. Created if it does not exist.
    dims : int
        Embedding vector dimensions (1536 for OpenAI, 384 for ONNX test).
    """

    def __init__(self, db_path: Path, *, dims: int) -> None:
        self._db_path = Path(db_path)
        self._dims = int(dims)  # coerce + raise ValueError if not castable
        if self._dims <= 0:
            raise ValueError(f"dims must be positive, got {self._dims}")
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        try:
            self._conn.enable_load_extension(True)
            sqlite_vec.load(self._conn)
            self._conn.enable_load_extension(False)
        except Exception:  # crash-barrier: sqlite-vec extension load failure
            self._conn.close()
            raise RuntimeError(
                "Failed to load sqlite-vec extension. Install with: pip install sqlite-vec"
            ) from None
        self._init_schema()

    def _init_schema(self) -> None:
        """Create tables, virtual tables, and triggers if they don't exist."""
        self._conn.executescript(f"""
            CREATE TABLE IF NOT EXISTS events (
                id          TEXT PRIMARY KEY,
                type        TEXT NOT NULL,
                summary     TEXT NOT NULL,
                timestamp   TEXT NOT NULL,
                source      TEXT,
                status      TEXT DEFAULT 'active',
                metadata    TEXT,
                created_at  TEXT NOT NULL
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
                summary,
                content=events,
                content_rowid=rowid
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS events_vec USING vec0(
                id        INTEGER PRIMARY KEY,
                embedding float[{self._dims}] distance_metric=cosine
            );

            CREATE TABLE IF NOT EXISTS profile (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS history (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                entry      TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS snapshots (
                key        TEXT PRIMARY KEY,
                content    TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            {_FTS_TRIGGERS}
        """)

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def insert_event(
        self,
        event: dict[str, Any],
        embedding: list[float] | None = None,
    ) -> None:
        """Insert an event with optional vector embedding (single transaction)."""
        with self._conn:
            # Clean up any existing vector entry before replace (rowid changes
            # on INSERT OR REPLACE)
            old_row = self._conn.execute(
                "SELECT rowid FROM events WHERE id = ?", (event["id"],)
            ).fetchone()
            if old_row is not None:
                self._conn.execute("DELETE FROM events_vec WHERE id = ?", (old_row[0],))
            self._conn.execute(
                """INSERT OR REPLACE INTO events
                   (id, type, summary, timestamp, source, status, metadata, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event["id"],
                    event["type"],
                    event["summary"],
                    event["timestamp"],
                    event.get("source"),
                    event.get("status", "active"),
                    event.get("metadata"),
                    event.get("created_at", event.get("timestamp", _utc_now_iso())),
                ),
            )
            if embedding is not None:
                rowid = self._conn.execute(
                    "SELECT rowid FROM events WHERE id = ?", (event["id"],)
                ).fetchone()[0]
                self._conn.execute(
                    "INSERT OR REPLACE INTO events_vec (id, embedding) VALUES (?, ?)",
                    (rowid, sqlite_vec.serialize_float32(embedding)),
                )

    def read_events(
        self,
        *,
        limit: int = 100,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """Read events ordered by timestamp descending."""
        if status:
            rows = self._conn.execute(
                "SELECT * FROM events WHERE status = ? ORDER BY timestamp DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM events ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search_vector(
        self,
        query_embedding: list[float],
        k: int = 10,
    ) -> list[dict[str, Any]]:
        """KNN vector search via sqlite-vec. Returns events with distance."""
        rows = self._conn.execute(
            """SELECT e.*, v.distance
               FROM events_vec v
               JOIN events e ON e.rowid = v.id
               WHERE v.embedding MATCH ?
               AND k = ?
               ORDER BY v.distance""",
            (sqlite_vec.serialize_float32(query_embedding), k),
        ).fetchall()
        return [dict(row) for row in rows]

    def search_fts(self, query_text: str, k: int = 10) -> list[dict[str, Any]]:
        """FTS5 keyword search over event summaries.

        Uses term-level matching (implicit AND) rather than phrase matching
        so that "coffee preference" matches documents containing both terms
        anywhere, not just the exact phrase.
        """
        # Quote each term individually to escape FTS5 operators.
        # Use OR logic so that any matching term returns results.
        terms = re.findall(r"\w+", query_text)
        if not terms:
            return []
        safe_query = " OR ".join(f'"{t}"' for t in terms)
        try:
            rows = self._conn.execute(
                """SELECT e.*, rank
                   FROM events_fts fts
                   JOIN events e ON e.rowid = fts.rowid
                   WHERE events_fts MATCH ?
                   ORDER BY rank
                   LIMIT ?""",
                (safe_query, k),
            ).fetchall()
        except sqlite3.OperationalError:
            # Malformed FTS query — return empty
            return []
        return [dict(row) for row in rows]

    def search_by_metadata(
        self,
        *,
        topic: str | None = None,
        memory_type: str | None = None,
        k: int = 10,
    ) -> list[dict[str, Any]]:
        """Fallback search by event type and/or metadata topic."""
        conditions: list[str] = []
        params: list[Any] = []
        if memory_type:
            conditions.append("type = ?")
            params.append(memory_type)
        if topic:
            conditions.append("json_extract(metadata, '$.topic') = ?")
            params.append(topic)
        if not conditions:
            return []
        where = " AND ".join(conditions)
        params.append(k)
        rows = self._conn.execute(
            f"SELECT * FROM events WHERE {where} ORDER BY timestamp DESC LIMIT ?",
            params,
        ).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Profile
    # ------------------------------------------------------------------

    def read_profile(self, key: str) -> dict[str, Any] | None:
        """Read a profile section by key. Returns None if not found."""
        row = self._conn.execute("SELECT value FROM profile WHERE key = ?", (key,)).fetchone()
        if row is None:
            return None
        result: dict[str, Any] = json.loads(row[0])
        return result

    def write_profile(self, key: str, value: dict[str, Any]) -> None:
        """Write a profile section (upsert)."""
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO profile (key, value) VALUES (?, ?)",
                (key, json.dumps(value, default=str)),
            )

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    def append_history(self, entry: str) -> None:
        """Append a history entry with current timestamp."""
        with self._conn:
            self._conn.execute(
                "INSERT INTO history (entry, created_at) VALUES (?, ?)",
                (entry, _utc_now_iso()),
            )

    def read_history(self, *, limit: int = 50) -> list[dict[str, Any]]:
        """Read history entries ordered by creation time ascending."""
        rows = self._conn.execute(
            "SELECT * FROM history ORDER BY created_at ASC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------

    def read_snapshot(self, key: str) -> str:
        """Read a snapshot by key. Returns empty string if not found."""
        row = self._conn.execute("SELECT content FROM snapshots WHERE key = ?", (key,)).fetchone()
        if row is None:
            return ""
        content: str = row[0]
        return content

    def write_snapshot(self, key: str, content: str) -> None:
        """Write a snapshot (upsert)."""
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO snapshots (key, content, updated_at) VALUES (?, ?, ?)",
                (key, content, _utc_now_iso()),
            )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def __enter__(self) -> UnifiedMemoryDB:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
