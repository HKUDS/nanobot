"""Procedural memory: learned tool-use strategies.

Strategies are extracted from successful guardrail recoveries and user
corrections. They persist across sessions in a SQLite table and are
injected into the system prompt to prevent repeating past failures.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


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


class StrategyStore:
    """CRUD operations for the strategies table in SQLite."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        conn = sqlite3.connect(self._db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS strategies (
                id TEXT PRIMARY KEY,
                domain TEXT NOT NULL,
                task_type TEXT NOT NULL,
                strategy TEXT NOT NULL,
                context TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'guardrail_recovery',
                confidence REAL NOT NULL DEFAULT 0.5,
                created_at TEXT NOT NULL,
                last_used TEXT NOT NULL,
                use_count INTEGER NOT NULL DEFAULT 0,
                success_count INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_strategies_domain ON strategies(domain)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_strategies_task_type ON strategies(task_type)")
        conn.commit()
        conn.close()

    def save(self, strategy: Strategy) -> None:
        """Insert or replace a strategy record."""
        conn = sqlite3.connect(self._db_path)
        conn.execute(
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
        conn.commit()
        conn.close()

    def retrieve(
        self,
        domain: str | None = None,
        task_type: str | None = None,
        limit: int = 10,
        min_confidence: float = 0.0,
    ) -> list[Strategy]:
        """Retrieve strategies filtered by domain, task_type, and confidence."""
        conn = sqlite3.connect(self._db_path)
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
        rows = conn.execute(query, params).fetchall()
        conn.close()
        return [self._row_to_strategy(r) for r in rows]

    def update_confidence(self, strategy_id: str, confidence: float) -> None:
        """Set the confidence score for a strategy."""
        conn = sqlite3.connect(self._db_path)
        conn.execute(
            "UPDATE strategies SET confidence = ? WHERE id = ?",
            (confidence, strategy_id),
        )
        conn.commit()
        conn.close()

    def record_usage(self, strategy_id: str, *, success: bool) -> None:
        """Increment use_count (and success_count if successful)."""
        conn = sqlite3.connect(self._db_path)
        now = datetime.now(timezone.utc).isoformat()
        if success:
            conn.execute(
                "UPDATE strategies SET use_count = use_count + 1, "
                "success_count = success_count + 1, last_used = ? WHERE id = ?",
                (now, strategy_id),
            )
        else:
            conn.execute(
                "UPDATE strategies SET use_count = use_count + 1, last_used = ? WHERE id = ?",
                (now, strategy_id),
            )
        conn.commit()
        conn.close()

    def prune(self, min_confidence: float = 0.1) -> int:
        """Delete strategies below the confidence threshold. Returns count deleted."""
        conn = sqlite3.connect(self._db_path)
        cursor = conn.execute(
            "DELETE FROM strategies WHERE confidence < ?",
            (min_confidence,),
        )
        pruned = cursor.rowcount
        conn.commit()
        conn.close()
        return pruned

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
