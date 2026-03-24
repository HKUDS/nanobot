"""Feature flag management for the memory subsystem.

``RolloutConfig`` centralises the default feature-flag dict that was previously
built inline inside ``MemoryStore.__init__``.  It validates modes, coerces types,
and merges user-supplied overrides.

Extracted from ``store.py`` as part of the store-decomposition effort.
"""

from __future__ import annotations

from typing import Any, ClassVar


class RolloutConfig:
    """Feature flag management for the memory subsystem."""

    ROLLOUT_MODES: ClassVar[set[str]] = {"enabled", "shadow", "disabled"}

    def __init__(self, overrides: dict[str, Any] | None = None) -> None:
        self.rollout = self._load_defaults()
        if isinstance(overrides, dict):
            self.apply_overrides(overrides)

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
        """Merge *overrides* into the current rollout dict, with validation."""
        if not overrides:
            return
        mode = (
            str(
                overrides.get(
                    "memory_rollout_mode",
                    self.rollout.get("memory_rollout_mode", "enabled"),
                )
            )
            .strip()
            .lower()
        )
        if mode in self.ROLLOUT_MODES:
            self.rollout["memory_rollout_mode"] = mode
        for key in (
            "memory_type_separation_enabled",
            "memory_router_enabled",
            "memory_reflection_enabled",
            "memory_vector_health_enabled",
            "memory_auto_reindex_on_empty_vector",
        ):
            if key in overrides:
                self.rollout[key] = bool(overrides[key])
        if isinstance(overrides.get("rollout_gates"), dict):
            gates = self.rollout.get("rollout_gates")
            if not isinstance(gates, dict):
                gates = {}
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
            self.rollout["rollout_gates"] = gates
        # Reranker overrides
        if "reranker_mode" in overrides:
            rm = str(overrides["reranker_mode"]).strip().lower()
            if rm in ("enabled", "shadow", "disabled"):
                self.rollout["reranker_mode"] = rm
        if "reranker_alpha" in overrides:
            try:
                self.rollout["reranker_alpha"] = min(
                    max(float(overrides["reranker_alpha"]), 0.0), 1.0
                )
            except (TypeError, ValueError):
                pass  # keep default on bad input
        if "reranker_model" in overrides:
            self.rollout["reranker_model"] = str(overrides["reranker_model"]).strip()

    # ── query ───────────────────────────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        """Return a snapshot copy of the current rollout dict."""
        return dict(self.rollout)
