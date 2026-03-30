"""Procedural memory: learned tool-use strategies.

Strategies are extracted from successful guardrail recoveries and user
corrections. They persist across sessions in the ``strategies`` table
(owned by ``MemoryDatabase``) and are injected into the system prompt
to prevent repeating past failures.

``StrategyAccess`` operates on a shared SQLite connection provided by
``MemoryDatabase`` — it never opens or closes connections itself.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(slots=True)
class Strategy:
    """A learned tool-use pattern."""

    id: str
    domain: str
    task_type: str
    strategy: str
    context: str
    source: str
    confidence: float
    created_at: datetime
    last_used: datetime
    use_count: int
    success_count: int


class StrategyAccess:
    """CRUD operations for the strategies table.

    Receives a shared SQLite connection from ``MemoryDatabase``.
    The table schema is owned by ``MemoryDatabase._init_schema()`` —
    this class only reads and writes rows.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def save(self, strategy: Strategy) -> None:
        """Insert or replace a strategy record."""
        with self._conn:
            self._conn.execute(
                """INSERT OR REPLACE INTO strategies
                (id, domain, task_type, strategy, context, source, confidence,
                 created_at, last_used, use_count, success_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    strategy.id,
                    strategy.domain,
                    strategy.task_type,
                    strategy.strategy,
                    strategy.context,
                    strategy.source,
                    strategy.confidence,
                    strategy.created_at.isoformat(),
                    strategy.last_used.isoformat(),
                    strategy.use_count,
                    strategy.success_count,
                ),
            )

    def retrieve(
        self,
        domain: str | None = None,
        task_type: str | None = None,
        limit: int = 10,
        min_confidence: float = 0.0,
    ) -> list[Strategy]:
        """Retrieve strategies filtered by domain, task_type, and confidence."""
        query = "SELECT * FROM strategies WHERE confidence >= ?"
        params: list = [min_confidence]
        if domain:
            query += " AND domain = ?"
            params.append(domain)
        if task_type:
            query += " AND task_type = ?"
            params.append(task_type)
        query += " ORDER BY confidence DESC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_strategy(r) for r in rows]

    def update_confidence(self, strategy_id: str, confidence: float) -> None:
        """Set the confidence score for a strategy."""
        with self._conn:
            self._conn.execute(
                "UPDATE strategies SET confidence = ? WHERE id = ?",
                (confidence, strategy_id),
            )

    def record_usage(self, strategy_id: str, *, success: bool) -> None:
        """Increment use_count (and success_count if successful)."""
        now = datetime.now(timezone.utc).isoformat()
        with self._conn:
            if success:
                self._conn.execute(
                    "UPDATE strategies SET use_count = use_count + 1, "
                    "success_count = success_count + 1, last_used = ? WHERE id = ?",
                    (now, strategy_id),
                )
            else:
                self._conn.execute(
                    "UPDATE strategies SET use_count = use_count + 1, last_used = ? WHERE id = ?",
                    (now, strategy_id),
                )

    def prune(self, min_confidence: float = 0.1) -> int:
        """Delete strategies below the confidence threshold. Returns count deleted."""
        with self._conn:
            cursor = self._conn.execute(
                "DELETE FROM strategies WHERE confidence < ?",
                (min_confidence,),
            )
            return cursor.rowcount

    @staticmethod
    def _row_to_strategy(row: tuple) -> Strategy:
        return Strategy(
            id=row[0],
            domain=row[1],
            task_type=row[2],
            strategy=row[3],
            context=row[4],
            source=row[5],
            confidence=row[6],
            created_at=datetime.fromisoformat(row[7]),
            last_used=datetime.fromisoformat(row[8]),
            use_count=row[9],
            success_count=row[10],
        )
