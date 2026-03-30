"""MemoryDatabase -- SQLite connection, schema init, and simple CRUD.

Owns the SQLite connection (WAL mode, sqlite-vec extension), schema
initialization for all tables, and profile/history/snapshot CRUD.
Event and graph operations will be delegated to focused repository
classes (EventStore, GraphStore) in subsequent tasks.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any

import sqlite_vec  # type: ignore[import-untyped]

from .._text import _utc_now_iso

if TYPE_CHECKING:
    from .event_store import EventStore
    from .graph_store import GraphStore
from ..constants import STRATEGIES_DDL

__all__ = ["MemoryDatabase"]

# FTS5 content-sync triggers -- keep events_fts in sync with events table.
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


class MemoryDatabase:
    """Single-file SQLite database for all memory storage.

    Parameters
    ----------
    db_path : Path
        Path to the SQLite database file.  Created if it does not exist.
    dims : int
        Embedding vector dimensions (1536 for OpenAI, 384 for ONNX test).
    """

    def __init__(self, db_path: Path, *, dims: int) -> None:
        self._db_path = Path(db_path)
        self._dims = int(dims)
        if self._dims <= 0:
            raise ValueError(f"dims must be positive, got {self._dims}")
        # check_same_thread=False: safe because WAL mode allows concurrent
        # readers, and asyncio.to_thread() only dispatches read-only methods.
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
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

        # Lazy references set by Tasks 2-3 (EventStore, GraphStore).
        self._event_store: EventStore | None = None
        self._graph_store: GraphStore | None = None

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

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

            CREATE TABLE IF NOT EXISTS entities (
                name       TEXT PRIMARY KEY,
                type       TEXT DEFAULT 'unknown',
                aliases    TEXT DEFAULT '',
                properties TEXT DEFAULT '{{}}',
                first_seen TEXT DEFAULT '',
                last_seen  TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS edges (
                source     TEXT NOT NULL,
                target     TEXT NOT NULL,
                relation   TEXT NOT NULL,
                confidence REAL DEFAULT 0.7,
                event_id   TEXT DEFAULT '',
                timestamp  TEXT DEFAULT '',
                PRIMARY KEY (source, relation, target)
            );

            {STRATEGIES_DDL}

            {_FTS_TRIGGERS}
        """)

    # ------------------------------------------------------------------
    # Connection access
    # ------------------------------------------------------------------

    @property
    def connection(self) -> sqlite3.Connection:
        """The shared SQLite connection (WAL mode, check_same_thread=False).

        Exposed for subsystem components (e.g. EventStore, GraphStore) that
        operate on the same database but manage their own table logic.
        """
        return self._conn

    @property
    def event_store(self) -> EventStore:
        """Focused repository for event CRUD and search operations."""
        if self._event_store is None:
            from .event_store import EventStore

            self._event_store = EventStore(self._conn)
        return self._event_store

    @property
    def graph_store(self) -> GraphStore:
        """Focused repository for entity/edge CRUD and graph traversal."""
        if self._graph_store is None:
            from .graph_store import GraphStore

            self._graph_store = GraphStore(self._conn)
        return self._graph_store

    # ------------------------------------------------------------------
    # Profile CRUD
    # ------------------------------------------------------------------

    def read_profile(self, key: str) -> dict[str, Any] | None:
        """Read a profile section by key.  Returns None if not found."""
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
    # History CRUD
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
    # Snapshot CRUD
    # ------------------------------------------------------------------

    def read_snapshot(self, key: str) -> str:
        """Read a snapshot by key.  Returns empty string if not found."""
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

    def __enter__(self) -> MemoryDatabase:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
