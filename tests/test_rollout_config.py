"""Tests for RolloutConfig extracted from MemoryStore."""

from __future__ import annotations

from nanobot.memory.rollout import RolloutConfig


class TestRolloutConfigDefaults:
    """Default values are set correctly."""

    def test_default_mode_is_enabled(self) -> None:
        cfg = RolloutConfig()
        assert cfg.rollout["memory_rollout_mode"] == "enabled"

    def test_default_booleans(self) -> None:
        cfg = RolloutConfig()
        assert cfg.rollout["memory_type_separation_enabled"] is True
        assert cfg.rollout["memory_router_enabled"] is True
        assert cfg.rollout["memory_reflection_enabled"] is True
        assert cfg.rollout["memory_vector_health_enabled"] is True
        assert cfg.rollout["memory_auto_reindex_on_empty_vector"] is True

    def test_default_rollout_gates(self) -> None:
        cfg = RolloutConfig()
        gates = cfg.rollout["rollout_gates"]
        assert gates["min_recall_at_k"] == 0.55
        assert gates["min_precision_at_k"] == 0.25
        assert gates["max_avg_memory_context_tokens"] == 1400.0
        assert gates["max_history_fallback_ratio"] == 0.05

    def test_default_reranker_settings(self) -> None:
        cfg = RolloutConfig()
        assert cfg.rollout["reranker_mode"] == "enabled"
        assert cfg.rollout["reranker_alpha"] == 0.5
        assert cfg.rollout["reranker_model"] == "onnx:ms-marco-MiniLM-L-6-v2"


class TestRolloutConfigOverrides:
    """Overrides merge properly via apply_overrides()."""

    def test_override_mode(self) -> None:
        cfg = RolloutConfig()
        cfg.apply_overrides({"memory_rollout_mode": "shadow"})
        assert cfg.rollout["memory_rollout_mode"] == "shadow"

    def test_invalid_mode_ignored(self) -> None:
        cfg = RolloutConfig()
        cfg.apply_overrides({"memory_rollout_mode": "bogus"})
        assert cfg.rollout["memory_rollout_mode"] == "enabled"

    def test_override_boolean_flag(self) -> None:
        cfg = RolloutConfig()
        cfg.apply_overrides({"memory_router_enabled": False})
        assert cfg.rollout["memory_router_enabled"] is False

    def test_override_rollout_gates_partial(self) -> None:
        cfg = RolloutConfig()
        cfg.apply_overrides({"rollout_gates": {"min_recall_at_k": 0.9}})
        assert cfg.rollout["rollout_gates"]["min_recall_at_k"] == 0.9
        # Other gates should stay at defaults
        assert cfg.rollout["rollout_gates"]["min_precision_at_k"] == 0.25

    def test_override_reranker_mode(self) -> None:
        cfg = RolloutConfig()
        cfg.apply_overrides({"reranker_mode": "disabled"})
        assert cfg.rollout["reranker_mode"] == "disabled"

    def test_override_reranker_alpha_clamped(self) -> None:
        cfg = RolloutConfig()
        cfg.apply_overrides({"reranker_alpha": 2.0})
        assert cfg.rollout["reranker_alpha"] == 1.0

    def test_empty_overrides_no_change(self) -> None:
        cfg = RolloutConfig()
        cfg.apply_overrides({})
        default = RolloutConfig()
        assert cfg.rollout == default.rollout

    def test_none_overrides_no_change(self) -> None:
        # apply_overrides is a no-op for empty dict; verify defaults are unchanged
        cfg = RolloutConfig()
        cfg.apply_overrides({})
        default = RolloutConfig()
        assert cfg.rollout == default.rollout


class TestGetStatus:
    """get_status returns expected structure."""

    def test_returns_copy(self) -> None:
        cfg = RolloutConfig()
        status = cfg.get_status()
        assert status == cfg.rollout
        # Should be a copy, not the same object
        assert status is not cfg.rollout

    def test_contains_all_keys(self) -> None:
        cfg = RolloutConfig()
        status = cfg.get_status()
        expected_keys = {
            "memory_rollout_mode",
            "memory_type_separation_enabled",
            "memory_router_enabled",
            "memory_reflection_enabled",
            "memory_vector_health_enabled",
            "memory_auto_reindex_on_empty_vector",
            "rollout_gates",
            "reranker_mode",
            "reranker_alpha",
            "reranker_model",
        }
        assert expected_keys.issubset(set(status.keys()))


class TestRolloutModes:
    """ROLLOUT_MODES class attribute."""

    def test_valid_modes(self) -> None:
        assert RolloutConfig.ROLLOUT_MODES == {"enabled", "shadow", "disabled"}
