"""Feature flag management for the memory subsystem.

``RolloutConfig`` centralises the default feature-flag dict that was previously
built inline inside ``MemoryStore.__init__``.  It validates modes, coerces types,
and merges user-supplied overrides.

Extracted from ``store.py`` as part of the store-decomposition effort.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from nanobot.config.memory import MemoryConfig


class RolloutConfig:
    """Feature flag management for the memory subsystem."""

    ROLLOUT_MODES: ClassVar[set[str]] = {"enabled", "shadow", "disabled"}

    def __init__(
        self,
        overrides: dict[str, Any] | None = None,
        *,
        memory_config: MemoryConfig | None = None,
    ) -> None:
        self.rollout = self._load_defaults()
        if memory_config is not None:
            self.apply_overrides(self._config_to_overrides(memory_config))
        elif isinstance(overrides, dict):
            self.apply_overrides(overrides)

    @staticmethod
    def _config_to_overrides(mc: MemoryConfig) -> dict[str, Any]:
        """Convert a MemoryConfig to the rollout overrides dict format."""
        return {
            "memory_rollout_mode": mc.rollout_mode,
            "memory_type_separation_enabled": mc.type_separation_enabled,
            "memory_router_enabled": mc.router_enabled,
            "memory_reflection_enabled": mc.reflection_enabled,
            "memory_shadow_mode": mc.shadow_mode,
            "memory_shadow_sample_rate": mc.shadow_sample_rate,
            "memory_vector_health_enabled": mc.vector_health_enabled,
            "memory_auto_reindex_on_empty_vector": mc.auto_reindex_on_empty_vector,
            "memory_history_fallback_enabled": mc.history_fallback_enabled,
            "conflict_auto_resolve_gap": mc.conflict_auto_resolve_gap,
            "memory_fallback_allowed_sources": mc.fallback_allowed_sources
            or ["profile", "events", "vector_search"],
            "memory_fallback_max_summary_chars": mc.fallback_max_summary_chars,
            "rollout_gates": {
                "min_recall_at_k": mc.rollout_gate_min_recall_at_k,
                "min_precision_at_k": mc.rollout_gate_min_precision_at_k,
                "max_avg_memory_context_tokens": mc.rollout_gate_max_avg_context_tokens,
                "max_history_fallback_ratio": mc.rollout_gate_max_history_fallback_ratio,
            },
            "reranker_mode": mc.reranker.mode,
            "reranker_alpha": mc.reranker.alpha,
            "reranker_model": mc.reranker.model,
            "vector_user_id": mc.vector.user_id,
            "vector_add_debug": mc.vector.add_debug,
            "vector_verify_write": mc.vector.verify_write,
            "vector_force_infer": mc.vector.force_infer,
        }

    # ── defaults ────────────────────────────────────────────────────────

    def _load_defaults(self) -> dict[str, Any]:
        """Build the default rollout dict with all feature flags."""
        defaults: dict[str, Any] = {
            "memory_rollout_mode": "enabled",
            "memory_type_separation_enabled": True,
            "memory_router_enabled": True,
            "memory_reflection_enabled": True,
            "memory_vector_health_enabled": True,
            "memory_auto_reindex_on_empty_vector": True,
            "rollout_gates": {
                "min_recall_at_k": 0.55,
                "min_precision_at_k": 0.25,
                "max_avg_memory_context_tokens": 1400.0,
                "max_history_fallback_ratio": 0.05,
            },
            "graph_enabled": True,
            "reranker_mode": "enabled",
            "reranker_alpha": 0.5,
            "reranker_model": "onnx:ms-marco-MiniLM-L-6-v2",
        }
        rollout = dict(defaults)

        mode = str(rollout.get("memory_rollout_mode", "enabled")).strip().lower()
        rollout["memory_rollout_mode"] = mode if mode in self.ROLLOUT_MODES else "enabled"

        for key in (
            "memory_type_separation_enabled",
            "memory_router_enabled",
            "memory_reflection_enabled",
            "memory_vector_health_enabled",
            "memory_auto_reindex_on_empty_vector",
        ):
            rollout[key] = bool(rollout.get(key, defaults[key]))

        return rollout

    # ── overrides ───────────────────────────────────────────────────────

    def apply_overrides(self, overrides: dict[str, Any]) -> None:
        """Merge *overrides* into the current rollout dict, with validation.

        Builds a new dict and replaces ``self.rollout`` atomically so that any
        existing references to the previous dict are never partially mutated.
        """
        if not overrides:
            return
        merged = dict(self.rollout)
        mode = (
            str(
                overrides.get(
                    "memory_rollout_mode",
                    merged.get("memory_rollout_mode", "enabled"),
                )
            )
            .strip()
            .lower()
        )
        if mode in self.ROLLOUT_MODES:
            merged["memory_rollout_mode"] = mode
        for key in (
            "memory_type_separation_enabled",
            "memory_router_enabled",
            "memory_reflection_enabled",
            "memory_vector_health_enabled",
            "memory_auto_reindex_on_empty_vector",
        ):
            if key in overrides:
                merged[key] = bool(overrides[key])
        if isinstance(overrides.get("rollout_gates"), dict):
            gates = merged.get("rollout_gates")
            if not isinstance(gates, dict):
                gates = {}
            else:
                gates = dict(gates)  # shallow copy to avoid mutating the old dict's gates
            for key in (
                "min_recall_at_k",
                "min_precision_at_k",
                "max_avg_memory_context_tokens",
                "max_history_fallback_ratio",
            ):
                if key not in overrides["rollout_gates"]:
                    continue
                try:
                    gates[key] = float(overrides["rollout_gates"][key])
                except (TypeError, ValueError):
                    continue
            merged["rollout_gates"] = gates
        # Reranker overrides
        if "reranker_mode" in overrides:
            rm = str(overrides["reranker_mode"]).strip().lower()
            if rm in ("enabled", "shadow", "disabled"):
                merged["reranker_mode"] = rm
        if "reranker_alpha" in overrides:
            try:
                merged["reranker_alpha"] = min(max(float(overrides["reranker_alpha"]), 0.0), 1.0)
            except (TypeError, ValueError):
                pass  # keep default on bad input
        if "reranker_model" in overrides:
            merged["reranker_model"] = str(overrides["reranker_model"]).strip()
        self.rollout = merged

    # ── query ───────────────────────────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        """Return a snapshot copy of the current rollout dict."""
        return dict(self.rollout)
