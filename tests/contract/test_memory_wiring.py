"""Wiring contract tests: memory subsystem construction and state propagation."""

from __future__ import annotations

from pathlib import Path

from nanobot.config.memory import MemoryConfig
from nanobot.memory.store import MemoryStore


def test_strategies_ddl_importable():
    """STRATEGIES_DDL is a public constant in unified_db, used by test fixtures."""
    from nanobot.memory.unified_db import STRATEGIES_DDL

    assert "CREATE TABLE" in STRATEGIES_DDL
    assert "strategies" in STRATEGIES_DDL


def test_unified_db_connection_property(tmp_path):
    """UnifiedMemoryDB exposes a shared connection for subsystem components."""
    import sqlite3

    store = _make_store(tmp_path)
    conn = store.db.connection
    assert isinstance(conn, sqlite3.Connection)
    # Verify strategies table exists in the shared database
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='strategies'")
    assert cursor.fetchone() is not None


def _make_store(tmp_path: Path) -> MemoryStore:
    return MemoryStore(
        tmp_path,
        embedding_provider="hash",
        memory_config=MemoryConfig(graph_enabled=False),
    )


def test_conflict_resolve_gap_follows_memory_config(tmp_path):
    """ConflictManager reads the current MemoryConfig value, not a stale copy."""
    store = _make_store(tmp_path)

    # Default gap is 0.25
    assert store.conflict_mgr._resolve_gap_fn() == 0.25

    # Replace the memory config with a new gap value.
    store._memory_config = MemoryConfig(graph_enabled=False, conflict_auto_resolve_gap=0.5)

    # ConflictManager must see the new value — no stale copy.
    assert store.conflict_mgr._resolve_gap_fn() == 0.5


def test_profile_mgr_has_conflict_mgr_at_construction(tmp_path):
    """ProfileStore._conflict_mgr_fn resolves immediately after MemoryStore construction."""
    store = _make_store(tmp_path)
    assert store.profile_mgr._conflict_mgr_fn is not None
    assert store.profile_mgr._conflict_mgr_fn() is not None


def test_profile_mgr_corrector_fn_resolves(tmp_path):
    """ProfileStore._corrector_fn resolves to a CorrectionOrchestrator after construction."""
    store = _make_store(tmp_path)
    assert store.profile_mgr._corrector_fn is not None
    corrector = store.profile_mgr._corrector_fn()
    assert corrector is not None


def test_rollout_override_atomic_consistency(tmp_path):
    """After updating memory_config, the scorer sees the updated values."""
    store = _make_store(tmp_path)

    # Replace the memory config with one that has reranker disabled
    store._memory_config = MemoryConfig(reranker={"mode": "disabled"})

    # Scorer's memory_config_fn should reflect the update (lambda reads live attribute)
    scorer_config = store._scorer._memory_config_fn()
    assert scorer_config.reranker.mode == "disabled"


def test_maintenance_reindex_runs_without_error(tmp_path):
    """MemoryMaintenance.reindex runs without AttributeError (all deps wired)."""
    store = _make_store(tmp_path)
    store.ingester.append_events(
        [
            {
                "type": "fact",
                "summary": "Test fact for reindex.",
                "timestamp": "2026-03-01T10:00:00+00:00",
                "source": "test",
            }
        ]
    )
    try:
        store.maintenance.reindex_from_structured_memory(
            read_profile_fn=store.profile_mgr.read_profile,
            read_events_fn=store.ingester.read_events,
            ingester=store.ingester,
            profile_keys=store.PROFILE_KEYS,
        )
    except Exception as e:
        # reindex may fail for other reasons in test context, but must NOT
        # fail with AttributeError from missing wiring
        assert not isinstance(e, AttributeError), f"Wiring error: {e}"
