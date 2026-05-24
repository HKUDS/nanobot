"""SQLite persistence for turn execution traces."""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.agent.evolution.models import TurnTrace, TurnTraceOutcome

_INSERT_SQL = """
INSERT INTO turn_traces (
    trace_id, session_key, turn_id, timestamp, query,
    skills_injected_json, tool_calls_json, tool_call_count, iterations,
    stop_reason, outcome, token_usage_json, used_for_evolution, created_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


class TraceStore:
    """L2 SQLite store for turn traces at ``{workspace}/.nanobot/traces.sqlite``."""

    def __init__(self, workspace: Path) -> None:
        self._workspace = workspace.expanduser().resolve()
        self._db_path = self._workspace / ".nanobot" / "traces.sqlite"
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None

    @property
    def db_path(self) -> Path:
        return self._db_path

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def insert(self, trace: TurnTrace) -> None:
        """Persist one turn trace."""
        with self._lock:
            conn = self._connect()
            conn.execute(_INSERT_SQL, trace.to_row_values())
            conn.commit()
            logger.debug(
                "TraceStore insert: trace_id={} session={} tool_calls={} outcome={}",
                trace.trace_id,
                trace.session_key,
                trace.tool_call_count,
                trace.outcome,
            )

    def get(self, trace_id: str) -> TurnTrace | None:
        with self._lock:
            row = self._connect().execute(
                "SELECT * FROM turn_traces WHERE trace_id = ?",
                (trace_id,),
            ).fetchone()
            return None if row is None else TurnTrace.from_row(row)

    def list_by_session(self, session_key: str, *, limit: int = 50) -> list[TurnTrace]:
        with self._lock:
            rows = self._connect().execute(
                """
                SELECT * FROM turn_traces
                WHERE session_key = ?
                ORDER BY created_at DESC, rowid DESC
                LIMIT ?
                """,
                (session_key, limit),
            ).fetchall()
            return [TurnTrace.from_row(row) for row in rows]

    def list_recent(self, *, limit: int = 100) -> list[TurnTrace]:
        with self._lock:
            rows = self._connect().execute(
                """
                SELECT * FROM turn_traces
                ORDER BY created_at DESC, rowid DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [TurnTrace.from_row(row) for row in rows]

    def list_for_gepa(
        self,
        *,
        min_tool_calls: int = 1,
        outcome: TurnTraceOutcome = "success",
        limit: int = 100,
        unused_only: bool = True,
    ) -> list[TurnTrace]:
        """Return traces suitable for offline GEPA runs."""
        clauses = ["tool_call_count >= ?", "outcome = ?"]
        params: list[Any] = [min_tool_calls, outcome]
        if unused_only:
            clauses.append("used_for_evolution = 0")
        where = " AND ".join(clauses)
        sql = f"""
            SELECT * FROM turn_traces
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT ?
        """
        params.append(limit)
        with self._lock:
            rows = self._connect().execute(sql, params).fetchall()
            return [TurnTrace.from_row(row) for row in rows]

    def mark_used_for_evolution(self, trace_ids: list[str]) -> int:
        if not trace_ids:
            return 0
        placeholders = ",".join("?" for _ in trace_ids)
        with self._lock:
            conn = self._connect()
            cursor = conn.execute(
                f"""
                UPDATE turn_traces
                SET used_for_evolution = 1
                WHERE trace_id IN ({placeholders})
                """,
                trace_ids,
            )
            conn.commit()
            return cursor.rowcount

    def prune(self, retention_days: int) -> int:
        """Delete traces older than *retention_days*. Returns rows removed."""
        if retention_days <= 0:
            return 0
        cutoff = time.time() - retention_days * 86_400
        with self._lock:
            conn = self._connect()
            cursor = conn.execute(
                "DELETE FROM turn_traces WHERE created_at < ?",
                (cutoff,),
            )
            conn.commit()
            deleted = cursor.rowcount
            if deleted:
                logger.info(
                    "TraceStore pruned {} trace(s) older than {} day(s)",
                    deleted,
                    retention_days,
                )
            return deleted

    def count(self) -> int:
        with self._lock:
            row = self._connect().execute("SELECT COUNT(*) AS n FROM turn_traces").fetchone()
            return int(row["n"]) if row is not None else 0

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
            CREATE TABLE IF NOT EXISTS turn_traces (
                trace_id TEXT PRIMARY KEY,
                session_key TEXT NOT NULL,
                turn_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                query TEXT NOT NULL,
                skills_injected_json TEXT NOT NULL DEFAULT '[]',
                tool_calls_json TEXT NOT NULL DEFAULT '[]',
                tool_call_count INTEGER NOT NULL,
                iterations INTEGER NOT NULL DEFAULT 0,
                stop_reason TEXT NOT NULL,
                outcome TEXT NOT NULL,
                token_usage_json TEXT NOT NULL DEFAULT '{}',
                used_for_evolution INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_turn_traces_session
                ON turn_traces(session_key, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_turn_traces_created
                ON turn_traces(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_turn_traces_gepa
                ON turn_traces(outcome, used_for_evolution, tool_call_count, created_at DESC);
            """
        )
