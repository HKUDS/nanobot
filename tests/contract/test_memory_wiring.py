"""Wiring contract tests: memory subsystem construction and state propagation."""

from __future__ import annotations

from nanobot.memory.rollout import RolloutConfig


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
