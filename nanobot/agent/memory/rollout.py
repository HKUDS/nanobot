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
            "memory_shadow_mode": False,
            "memory_shadow_sample_rate": 0.2,
            "memory_vector_health_enabled": True,
            "memory_auto_reindex_on_empty_vector": True,
            "memory_history_fallback_enabled": False,
            "memory_fallback_allowed_sources": ["profile", "events", "mem0_get_all"],
            "memory_fallback_max_summary_chars": 280,
            "rollout_gates": {
                "min_recall_at_k": 0.55,
                "min_precision_at_k": 0.25,
                "max_avg_memory_context_tokens": 1400.0,
                "max_history_fallback_ratio": 0.05,
            },
            "reranker_mode": "enabled",
            "reranker_alpha": 0.5,
            "reranker_model": "onnx:ms-marco-MiniLM-L-6-v2",
            "mem0_user_id": "nanobot",
            "mem0_add_debug": False,
            "mem0_verify_write": True,
            "mem0_force_infer_true": False,
            "consolidation_single_tool": True,
        }
        rollout = dict(defaults)

        mode = str(rollout.get("memory_rollout_mode", "enabled")).strip().lower()
        rollout["memory_rollout_mode"] = mode if mode in self.ROLLOUT_MODES else "enabled"

        for key in (
            "memory_type_separation_enabled",
            "memory_router_enabled",
            "memory_reflection_enabled",
            "memory_shadow_mode",
            "memory_vector_health_enabled",
            "memory_auto_reindex_on_empty_vector",
            "memory_history_fallback_enabled",
        ):
            rollout[key] = bool(rollout.get(key, defaults[key]))

        allowed_sources = rollout.get(
            "memory_fallback_allowed_sources", defaults["memory_fallback_allowed_sources"]
        )
        if not isinstance(allowed_sources, list):
            allowed_sources = defaults["memory_fallback_allowed_sources"]
        rollout["memory_fallback_allowed_sources"] = [
            str(item).strip().lower() for item in allowed_sources if str(item).strip()
        ] or list(defaults["memory_fallback_allowed_sources"])

        try:
            max_summary_chars = int(
                rollout.get(
                    "memory_fallback_max_summary_chars",
                    defaults["memory_fallback_max_summary_chars"],
                )
            )
        except (TypeError, ValueError):
            max_summary_chars = int(defaults["memory_fallback_max_summary_chars"])
        rollout["memory_fallback_max_summary_chars"] = max(80, min(max_summary_chars, 4000))

        try:
            sample_rate = float(rollout.get("memory_shadow_sample_rate", 0.2))
        except (TypeError, ValueError):
            sample_rate = 0.2
        rollout["memory_shadow_sample_rate"] = min(max(sample_rate, 0.0), 1.0)

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
            "memory_shadow_mode",
            "memory_vector_health_enabled",
            "memory_auto_reindex_on_empty_vector",
            "memory_history_fallback_enabled",
        ):
            if key in overrides:
                self.rollout[key] = bool(overrides[key])
        if "memory_fallback_allowed_sources" in overrides and isinstance(
            overrides.get("memory_fallback_allowed_sources"), list
        ):
            parsed = [
                str(item).strip().lower()
                for item in overrides.get("memory_fallback_allowed_sources", [])
                if str(item).strip()
            ]
            if parsed:
                self.rollout["memory_fallback_allowed_sources"] = parsed
        if "memory_fallback_max_summary_chars" in overrides:
            try:
                self.rollout["memory_fallback_max_summary_chars"] = max(
                    80,
                    min(int(overrides["memory_fallback_max_summary_chars"]), 4000),
                )
            except (TypeError, ValueError):
                pass  # keep default on bad input
        if "memory_shadow_sample_rate" in overrides:
            try:
                rate = float(overrides["memory_shadow_sample_rate"])
                self.rollout["memory_shadow_sample_rate"] = min(max(rate, 0.0), 1.0)
            except (TypeError, ValueError):
                pass  # keep default on bad input
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
        # mem0 overrides
        if "mem0_user_id" in overrides:
            self.rollout["mem0_user_id"] = str(overrides["mem0_user_id"]).strip() or "nanobot"
        for bk in (
            "mem0_add_debug",
            "mem0_verify_write",
            "mem0_force_infer_true",
            "mem0_raw_turn_ingestion",
            "consolidation_single_tool",
        ):
            if bk in overrides:
                self.rollout[bk] = bool(overrides[bk])

    # ── query ───────────────────────────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        """Return a snapshot copy of the current rollout dict."""
        return dict(self.rollout)
