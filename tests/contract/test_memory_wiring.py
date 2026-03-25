"""Wiring contract tests: memory subsystem construction and state propagation."""

from __future__ import annotations

from pathlib import Path

from nanobot.memory.rollout import RolloutConfig
from nanobot.memory.store import MemoryStore


def test_rollout_override_does_not_mutate_snapshot():
    """After apply_overrides, a previously captured dict is unchanged."""
    config = RolloutConfig()
    # Grab a direct reference to the rollout dict (simulates another component
    # holding a reference to the same dict object).
    old_ref = config.rollout
    old_mode = old_ref.get("reranker_mode")

    config.apply_overrides({"reranker_mode": "disabled"})

    # The old reference must be untouched (atomic replacement, not in-place mutation)
    assert old_ref.get("reranker_mode") == old_mode
    # The current rollout reflects the override
    assert config.rollout.get("reranker_mode") == "disabled"


def _make_store(tmp_path: Path) -> MemoryStore:
    return MemoryStore(
        tmp_path,
        embedding_provider="hash",
        rollout_overrides={"graph_enabled": False},
    )


def test_conflict_resolve_gap_follows_rollout(tmp_path):
    """ConflictManager reads the current rollout value, not a stale copy."""
    store = _make_store(tmp_path)

    # Default gap is 0.25
    assert store.conflict_mgr._resolve_gap_fn() == 0.25

    # Simulate a rollout override by updating the rollout dict directly.
    # (apply_overrides has an allowlist of known keys; conflict_auto_resolve_gap
    # is a pass-through key read via dict.get, not an explicit override target.)
    store._rollout_config.rollout["conflict_auto_resolve_gap"] = 0.5

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
    """After overrides, ingester and retriever see the same rollout values."""
    store = _make_store(tmp_path)

    store._rollout_config.apply_overrides({"reranker_mode": "disabled"})

    # Both subsystems' rollout_fn should return the same dict
    ingester_rollout = store.ingester._rollout_fn()
    scorer_rollout = store._scorer._rollout_fn()

    assert ingester_rollout is scorer_rollout
    assert ingester_rollout.get("reranker_mode") == "disabled"


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
