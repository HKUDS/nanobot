"""L1 atomic memory store (SQLite + FTS5)."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from loguru import logger

from nanobot.utils.helpers import ensure_dir

from nanobot.agent.layered_memory.l1_dedup import content_hash

_DB_NAME = "memory.sqlite"

L1MemoryType = Literal["preference", "fact", "event", "rule"]
_VALID_TYPES = frozenset({"preference", "fact", "event", "rule"})


@dataclass(frozen=True)
class L1Memory:
    atom_id: str
    session_key: str
    memory_type: L1MemoryType
    content: str
    source_l0_ids: tuple[int, ...]
    source_turn_ids: tuple[str, ...]
    content_hash: str
    created_at: float


class L1Store:
    """L1 atoms at ``{workspace}/.nanobot/memory.sqlite`` (shared with L0)."""

    def __init__(self, workspace: Path) -> None:
        self._workspace = workspace
        self._db_path = ensure_dir(workspace / ".nanobot") / _DB_NAME
        self._conn: sqlite3.Connection | None = None

    @property
    def db_path(self) -> Path:
        return self._db_path

    def insert(
        self,
        *,
        session_key: str,
        memory_type: L1MemoryType,
        content: str,
        source_l0_ids: tuple[int, ...],
        source_turn_ids: tuple[str, ...],
    ) -> str | None:
        """Insert one atom; returns ``atom_id`` or ``None`` if ``content_hash`` already exists."""
        normalized = content.strip()
        if not normalized:
            return None
        if memory_type not in _VALID_TYPES:
            memory_type = "fact"
        digest = content_hash(normalized)
        if self.has_content_hash(digest):
            return None
        conn = self._connect()
        atom_id = f"l1_{uuid.uuid4().hex[:12]}"
        now = time.time()
        try:
            conn.execute(
                """
                INSERT INTO l1_memories (
                    atom_id, session_key, memory_type, content,
                    source_l0_ids, source_turn_ids, content_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    atom_id,
                    session_key,
                    memory_type,
                    normalized,
                    json.dumps(list(source_l0_ids)),
                    json.dumps(list(source_turn_ids)),
                    digest,
                    now,
                ),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            return None
        logger.debug(
            "layered_memory l1_insert session={} atom_id={} type={}",
            session_key,
            atom_id,
            memory_type,
        )
        return atom_id

    def has_content_hash(self, digest: str) -> bool:
        row = self._connect().execute(
            "SELECT 1 FROM l1_memories WHERE content_hash = ? LIMIT 1",
            (digest,),
        ).fetchone()
        return row is not None

    def count_session(self, session_key: str) -> int:
        row = self._connect().execute(
            "SELECT COUNT(*) AS n FROM l1_memories WHERE session_key = ?",
            (session_key,),
        ).fetchone()
        return int(row["n"]) if row is not None else 0

    def search(
        self,
        query: str,
        *,
        session_key: str | None = None,
        limit: int = 5,
    ) -> list[L1Memory]:
        """FTS5 search ordered by BM25 relevance."""
        text = query.strip()
        if not text:
            return []
        fts_query = _fts_escape(text)
        conn = self._connect()
        if session_key is None:
            rows = conn.execute(
                """
                SELECT m.*
                FROM l1_memories_fts fts
                JOIN l1_memories m ON m.rowid = fts.rowid
                WHERE l1_memories_fts MATCH ?
                ORDER BY bm25(l1_memories_fts)
                LIMIT ?
                """,
                (fts_query, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT m.*
                FROM l1_memories_fts fts
                JOIN l1_memories m ON m.rowid = fts.rowid
                WHERE l1_memories_fts MATCH ? AND m.session_key = ?
                ORDER BY bm25(l1_memories_fts)
                LIMIT ?
                """,
                (fts_query, session_key, limit),
            ).fetchall()
        return [_row_to_memory(row) for row in rows]

    def list_session(self, session_key: str) -> list[L1Memory]:
        rows = self._connect().execute(
            """
            SELECT * FROM l1_memories
            WHERE session_key = ?
            ORDER BY created_at ASC, rowid ASC
            """,
            (session_key,),
        ).fetchall()
        return [_row_to_memory(row) for row in rows]

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

    @staticmethod
    def _init_schema(conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS l1_memories (
                rowid INTEGER PRIMARY KEY AUTOINCREMENT,
                atom_id TEXT NOT NULL UNIQUE,
                session_key TEXT NOT NULL,
                memory_type TEXT NOT NULL,
                content TEXT NOT NULL,
                source_l0_ids TEXT NOT NULL DEFAULT '[]',
                source_turn_ids TEXT NOT NULL DEFAULT '[]',
                content_hash TEXT NOT NULL UNIQUE,
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_l1_memories_session
                ON l1_memories(session_key, created_at);

            CREATE VIRTUAL TABLE IF NOT EXISTS l1_memories_fts USING fts5(
                content,
                memory_type,
                content='l1_memories',
                content_rowid='rowid',
                tokenize='unicode61'
            );

            CREATE TRIGGER IF NOT EXISTS l1_memories_ai AFTER INSERT ON l1_memories BEGIN
                INSERT INTO l1_memories_fts(rowid, content, memory_type)
                VALUES (new.rowid, new.content, new.memory_type);
            END;
            CREATE TRIGGER IF NOT EXISTS l1_memories_ad AFTER DELETE ON l1_memories BEGIN
                INSERT INTO l1_memories_fts(l1_memories_fts, rowid, content, memory_type)
                VALUES('delete', old.rowid, old.content, old.memory_type);
            END;
            CREATE TRIGGER IF NOT EXISTS l1_memories_au AFTER UPDATE ON l1_memories BEGIN
                INSERT INTO l1_memories_fts(l1_memories_fts, rowid, content, memory_type)
                VALUES('delete', old.rowid, old.content, old.memory_type);
                INSERT INTO l1_memories_fts(rowid, content, memory_type)
                VALUES (new.rowid, new.content, new.memory_type);
            END;
            """
        )


def _row_to_memory(row: sqlite3.Row) -> L1Memory:
    l0_raw = row["source_l0_ids"]
    turn_raw = row["source_turn_ids"]
    try:
        l0_ids = tuple(int(x) for x in json.loads(l0_raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        l0_ids = ()
    try:
        turn_ids = tuple(str(x) for x in json.loads(turn_raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        turn_ids = ()
    memory_type = str(row["memory_type"])
    if memory_type not in _VALID_TYPES:
        memory_type = "fact"
    return L1Memory(
        atom_id=str(row["atom_id"]),
        session_key=str(row["session_key"]),
        memory_type=memory_type,  # type: ignore[arg-type]
        content=str(row["content"]),
        source_l0_ids=l0_ids,
        source_turn_ids=turn_ids,
        content_hash=str(row["content_hash"]),
        created_at=float(row["created_at"]),
    )


def _fts_escape(text: str) -> str:
    """Quote tokens for FTS5 MATCH (best-effort)."""
    tokens = [t for t in text.split() if t]
    if not tokens:
        return '""'
    return " OR ".join(f'"{t.replace(chr(34), "")}"' for t in tokens[:12])
