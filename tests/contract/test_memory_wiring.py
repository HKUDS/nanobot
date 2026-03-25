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
