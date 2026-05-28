"""L0 raw conversation store (SQLite)."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from nanobot.agent.layered_memory.sanitize import L0CaptureRow
from nanobot.utils.helpers import ensure_dir

_DB_NAME = "memory.sqlite"
_META_PLUGIN_START = "plugin_start_ts"


@dataclass(frozen=True)
class L0Checkpoint:
    session_key: str
    message_count: int
    enabled_at: float


class L0Store:
    """Append-only L0 message store at ``{workspace}/.nanobot/memory.sqlite``."""

    def __init__(self, workspace: Path) -> None:
        self._workspace = workspace
        self._db_path = ensure_dir(workspace / ".nanobot") / _DB_NAME
        self._conn: sqlite3.Connection | None = None

    @property
    def db_path(self) -> Path:
        return self._db_path

    def append_messages(
        self,
        session_key: str,
        turn_id: str | None,
        rows: list[L0CaptureRow],
    ) -> int:
        """Insert sanitized rows; returns number of rows written."""
        if not rows:
            return 0
        conn = self._connect()
        now = time.time()
        self._ensure_session_checkpoint(conn, session_key, now)
        tid = turn_id or ""
        inserted = 0
        for row in rows:
            ts_ms = row.timestamp_ms or int(now * 1000)
            conn.execute(
                """
                INSERT INTO l0_messages (
                    session_key, turn_id, role, name, tool_call_id,
                    content, timestamp_ms, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_key,
                    tid,
                    row.role,
                    row.name,
                    row.tool_call_id,
                    row.content,
                    ts_ms,
                    now,
                ),
            )
            inserted += 1
        conn.execute(
            """
            UPDATE l0_capture_checkpoint
            SET message_count = message_count + ?, updated_at = ?
            WHERE session_key = ?
            """,
            (inserted, now, session_key),
        )
        conn.commit()
        logger.debug(
            "layered_memory l0_capture session={} turn_id={} rows={}",
            session_key,
            tid or "-",
            inserted,
        )
        return inserted

    def count_messages(self, session_key: str | None = None) -> int:
        conn = self._connect()
        if session_key is None:
            row = conn.execute("SELECT COUNT(*) AS n FROM l0_messages").fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM l0_messages WHERE session_key = ?",
                (session_key,),
            ).fetchone()
        return int(row["n"]) if row is not None else 0

    def get_checkpoint(self, session_key: str) -> L0Checkpoint | None:
        row = self._connect().execute(
            """
            SELECT session_key, message_count, enabled_at
            FROM l0_capture_checkpoint WHERE session_key = ?
            """,
            (session_key,),
        ).fetchone()
        if row is None:
            return None
        return L0Checkpoint(
            session_key=str(row["session_key"]),
            message_count=int(row["message_count"]),
            enabled_at=float(row["enabled_at"]),
        )

    def prune_older_than_days(self, days: int) -> int:
        if days <= 0:
            return 0
        cutoff = time.time() - days * 86400
        conn = self._connect()
        cur = conn.execute(
            "DELETE FROM l0_messages WHERE recorded_at < ?",
            (cutoff,),
        )
        conn.commit()
        deleted = cur.rowcount
        if deleted:
            logger.info("layered_memory l0_prune deleted={} older_than_days={}", deleted, days)
        return deleted

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._init_schema(self._conn)
        return self._conn

    def _ensure_session_checkpoint(
        self,
        conn: sqlite3.Connection,
        session_key: str,
        now: float,
    ) -> None:
        row = conn.execute(
            "SELECT 1 FROM l0_capture_checkpoint WHERE session_key = ?",
            (session_key,),
        ).fetchone()
        if row is not None:
            return
        conn.execute(
            """
            INSERT INTO l0_capture_checkpoint (session_key, message_count, enabled_at, updated_at)
            VALUES (?, 0, ?, ?)
            """,
            (session_key, now, now),
        )
        meta = conn.execute(
            "SELECT value FROM l0_meta WHERE key = ?",
            (_META_PLUGIN_START,),
        ).fetchone()
        if meta is None:
            conn.execute(
                "INSERT INTO l0_meta (key, value) VALUES (?, ?)",
                (_META_PLUGIN_START, str(now)),
            )

    @staticmethod
    def _init_schema(conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS l0_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_key TEXT NOT NULL,
                turn_id TEXT NOT NULL DEFAULT '',
                role TEXT NOT NULL,
                name TEXT,
                tool_call_id TEXT,
                content TEXT NOT NULL,
                timestamp_ms INTEGER NOT NULL,
                recorded_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_l0_messages_session_ts
                ON l0_messages(session_key, timestamp_ms);
            CREATE INDEX IF NOT EXISTS idx_l0_messages_session_turn
                ON l0_messages(session_key, turn_id);

            CREATE TABLE IF NOT EXISTS l0_capture_checkpoint (
                session_key TEXT PRIMARY KEY,
                message_count INTEGER NOT NULL DEFAULT 0,
                enabled_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS l0_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
