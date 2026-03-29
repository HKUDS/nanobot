from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone

import pytest

from nanobot.memory.strategy import Strategy, StrategyAccess


def _sample_strategy(**overrides: object) -> Strategy:
    """Create a Strategy with sensible defaults, overridable by keyword."""
    now = datetime.now(timezone.utc)
    defaults: dict = dict(
        id=str(uuid.uuid4()),
        domain="filesystem",
        task_type="file_read",
        strategy="Use read_file with explicit encoding param",
        context="When reading non-UTF8 files",
        source="guardrail_recovery",
        confidence=0.7,
        created_at=now,
        last_used=now,
        use_count=0,
        success_count=0,
    )
    defaults.update(overrides)
    return Strategy(**defaults)


def _create_schema(conn: sqlite3.Connection) -> None:
    """Create the strategies table (normally owned by UnifiedMemoryDB)."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS strategies (
            id            TEXT PRIMARY KEY,
            domain        TEXT NOT NULL,
            task_type     TEXT NOT NULL,
            strategy      TEXT NOT NULL,
            context       TEXT NOT NULL,
            source        TEXT NOT NULL DEFAULT 'guardrail_recovery',
            confidence    REAL NOT NULL DEFAULT 0.5,
            created_at    TEXT NOT NULL,
            last_used     TEXT NOT NULL,
            use_count     INTEGER NOT NULL DEFAULT 0,
            success_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_strategies_domain ON strategies(domain);
        CREATE INDEX IF NOT EXISTS idx_strategies_task_type ON strategies(task_type);
    """)


@pytest.fixture()
def store() -> StrategyAccess:
    conn = sqlite3.connect(":memory:")
    _create_schema(conn)
    return StrategyAccess(conn)


class TestStrategyAccess:
    def test_save_and_retrieve(self, store: StrategyAccess) -> None:
        s = _sample_strategy(domain="shell")
        store.save(s)
        results = store.retrieve(domain="shell")
        assert len(results) == 1
        assert results[0].id == s.id
        assert results[0].domain == "shell"
        assert results[0].strategy == s.strategy

    def test_retrieve_empty(self, store: StrategyAccess) -> None:
        results = store.retrieve()
        assert results == []

    def test_retrieve_by_domain(self, store: StrategyAccess) -> None:
        store.save(_sample_strategy(domain="filesystem"))
        store.save(_sample_strategy(domain="network"))
        fs_results = store.retrieve(domain="filesystem")
        net_results = store.retrieve(domain="network")
        assert len(fs_results) == 1
        assert len(net_results) == 1
        assert fs_results[0].domain == "filesystem"
        assert net_results[0].domain == "network"

    def test_update_confidence(self, store: StrategyAccess) -> None:
        s = _sample_strategy(confidence=0.5)
        store.save(s)
        store.update_confidence(s.id, 0.9)
        results = store.retrieve()
        assert len(results) == 1
        assert results[0].confidence == pytest.approx(0.9)

    def test_record_usage_success(self, store: StrategyAccess) -> None:
        s = _sample_strategy(use_count=0, success_count=0)
        store.save(s)
        store.record_usage(s.id, success=True)
        results = store.retrieve()
        assert results[0].use_count == 1
        assert results[0].success_count == 1

    def test_record_usage_failure(self, store: StrategyAccess) -> None:
        s = _sample_strategy(use_count=0, success_count=0)
        store.save(s)
        store.record_usage(s.id, success=False)
        results = store.retrieve()
        assert results[0].use_count == 1
        assert results[0].success_count == 0

    def test_prune_low_confidence(self, store: StrategyAccess) -> None:
        store.save(_sample_strategy(confidence=0.05, domain="low"))
        store.save(_sample_strategy(confidence=0.8, domain="high"))
        pruned = store.prune(min_confidence=0.1)
        assert pruned == 1
        results = store.retrieve()
        assert len(results) == 1
        assert results[0].domain == "high"

    def test_retrieve_with_limit(self, store: StrategyAccess) -> None:
        for i in range(10):
            store.save(_sample_strategy(confidence=i * 0.1))
        results = store.retrieve(limit=3)
        assert len(results) == 3

    def test_retrieve_min_confidence(self, store: StrategyAccess) -> None:
        store.save(_sample_strategy(confidence=0.2, domain="low"))
        store.save(_sample_strategy(confidence=0.8, domain="high"))
        results = store.retrieve(min_confidence=0.5)
        assert len(results) == 1
        assert results[0].domain == "high"

    def test_shared_connection_no_close(self, store: StrategyAccess) -> None:
        """StrategyAccess must not close the shared connection."""
        s = _sample_strategy()
        store.save(s)
        # Connection should still be usable after operations
        results = store.retrieve()
        assert len(results) == 1
