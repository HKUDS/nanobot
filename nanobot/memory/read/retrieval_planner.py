"""Retrieval planning: intent classification, per-intent policy, and routing hints.

Extracted from ``MemoryStore`` (LAN-207) to isolate ~250 lines of retrieval
policy logic into a focused, stateless module.

The ``RetrievalPlanner`` classifies a natural-language query into an *intent*,
selects tuning knobs (candidate multiplier, recency half-life, type boosts) for
that intent, and computes status/type routing hints that downstream filtering
uses to narrow candidates.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ..event import (
    is_resolved_task_or_decision,
)
from ..event import (
    memory_type_for_item as _memory_type_for_item,
)

# ── Data structures ───────────────────────────────────────────────────


@dataclass(slots=True)
class RetrievalPlan:
    """Output of ``RetrievalPlanner.plan()``."""

    intent: str
    policy: dict[str, Any]
    routing_hints: dict[str, Any]
    include_superseded: bool = False


# ── Planner ────────────────────────────────────────────────────────────


class RetrievalPlanner:
    """Stateless retrieval planner: intent → policy → routing hints.

    Parameters
    ----------
    router_enabled:
        When *False*, ``plan()`` always returns the ``fact_lookup`` intent
        regardless of the query content (shadow / disabled rollout modes).
    type_separation_enabled:
        Stored for callers that need to know whether type boosts should be
        applied; the planner itself always populates ``type_boost`` in the
        policy dict.
    """

    def __init__(
        self,
        *,
        router_enabled: bool = True,
        type_separation_enabled: bool = True,
    ) -> None:
        self.router_enabled = router_enabled
        self.type_separation_enabled = type_separation_enabled

    # ── Public API ─────────────────────────────────────────────────────

    def plan(self, query: str) -> RetrievalPlan:
        """Classify *query* and return a full retrieval plan."""
        intent = self.infer_retrieval_intent(query) if self.router_enabled else "fact_lookup"
        policy = self.retrieval_policy(intent)
        hints = self.query_routing_hints(query)

        q_lower = str(query or "").lower()
        wants_superseded = any(
            m in q_lower for m in ("supersede", "stale", "older fact", "replaced")
        )

        return RetrievalPlan(
            intent=intent,
            policy=policy,
            routing_hints=hints,
            include_superseded=wants_superseded,
        )

    # ── Intent classification ──────────────────────────────────────────

    @staticmethod
    def infer_retrieval_intent(query: str) -> str:
        """Classify *query* into a retrieval intent string."""
        text = str(query or "").strip().lower()
        if not text:
            return "fact_lookup"

        debug_markers = (
            "what happened",
            "last time",
            "failed",
            "failure",
            "error",
            "incident",
            "debug",
            "timeline",
            "yesterday",
            "what did we try",
            "correction",
            "corrected",
            "post-mortem",
            "postmortem",
            "root cause",
            "outage",
        )
        reflection_markers = (
            "reflect",
            "reflection",
            "lesson",
            "learned",
            "retrospective",
            "insight",
            "insights",
        )
        planning_markers = (
            "plan",
            "next step",
            "roadmap",
            "todo",
            "should we",
            "what should",
            "task",
            "tasks",
            "decision",
            "decisions",
            "in progress",
            "still open",
            "resolved",
            "completed",
            "closed",
            "project",
            "projects",
            "active",
        )
        architecture_markers = (
            "architecture",
            "architectural",
            "design decision",
            "memory architecture",
        )
        constraints_markers = ("constraint", "must", "cannot", "before running commands")
        conflict_markers = ("conflict", "needs_user", "unresolved decision")
        rollout_markers = ("rollout", "router", "shadow mode", "memory behavior enabled")

        if any(marker in text for marker in reflection_markers):
            return "reflection"
        if any(marker in text for marker in rollout_markers):
            return "rollout_status"
        if any(marker in text for marker in conflict_markers):
            return "conflict_review"
        if any(marker in text for marker in constraints_markers):
            return "constraints_lookup"
        if any(marker in text for marker in debug_markers):
            return "debug_history"
        if any(marker in text for marker in architecture_markers):
            return "planning"
        if any(marker in text for marker in planning_markers):
            return "planning"
        return "fact_lookup"

    # ── Per-intent policy configuration ────────────────────────────────

    @staticmethod
    def retrieval_policy(intent: str) -> dict[str, Any]:
        """Return tuning knobs for *intent*."""
        policy = {
            "fact_lookup": {
                "candidate_multiplier": 3,
                "half_life_days": 120.0,
                "type_boost": {"semantic": 0.18, "episodic": -0.05, "reflection": -0.12},
                "fallback_topics": [
                    "knowledge",
                    "user_preference",
                    "relationship",
                    "profile_update",
                ],
                "fallback_types": ["semantic"],
            },
            "debug_history": {
                "candidate_multiplier": 4,
                "half_life_days": 21.0,
                "type_boost": {"semantic": -0.04, "episodic": 0.22, "reflection": -0.1},
                "fallback_topics": ["infra", "user_correction"],
                "fallback_types": ["episodic"],
            },
            "planning": {
                "candidate_multiplier": 3,
                "half_life_days": 45.0,
                "type_boost": {"semantic": 0.1, "episodic": 0.08, "reflection": -0.06},
                "fallback_topics": ["task_progress", "decision_log", "project"],
                "fallback_types": ["episodic"],
            },
            "reflection": {
                "candidate_multiplier": 3,
                "half_life_days": 60.0,
                "type_boost": {"semantic": 0.03, "episodic": -0.03, "reflection": 0.2},
                "fallback_topics": ["reflection"],
                "fallback_types": ["reflection"],
            },
            "constraints_lookup": {
                "candidate_multiplier": 4,
                "half_life_days": 180.0,
                "type_boost": {"semantic": 0.24, "episodic": -0.1, "reflection": -0.14},
                "fallback_topics": ["constraint"],
                "fallback_types": ["semantic"],
            },
            "conflict_review": {
                "candidate_multiplier": 4,
                "half_life_days": 90.0,
                "type_boost": {"semantic": 0.05, "episodic": 0.15, "reflection": -0.08},
                "fallback_topics": ["decision_log"],
                "fallback_types": ["episodic"],
            },
            "rollout_status": {
                "candidate_multiplier": 2,
                "half_life_days": 365.0,
                "type_boost": {"semantic": 0.3, "episodic": -0.16, "reflection": -0.2},
                "fallback_topics": ["rollout"],
                "fallback_types": ["semantic"],
            },
        }
        return policy.get(intent, policy["fact_lookup"])

    # ── Routing hints ──────────────────────────────────────────────────

    @staticmethod
    def query_routing_hints(query: str) -> dict[str, Any]:
        """Return status/type routing hints from *query* surface markers."""
        text = str(query or "").strip().lower()
        open_markers = (
            "still open",
            "open task",
            "open tasks",
            "pending",
            "in progress",
            "unresolved",
            "needs user",
        )
        resolved_markers = ("resolved", "completed", "closed", "finished", "done")
        planning_markers = ("plan", "next step", "roadmap", "todo", "planning")
        architecture_markers = (
            "architecture",
            "architectural",
            "design decision",
            "memory architecture",
        )
        task_decision_markers = ("task", "tasks", "decision", "decisions")

        requires_open = any(marker in text for marker in open_markers)
        requires_resolved = any(marker in text for marker in resolved_markers)
        if requires_open and requires_resolved:
            requires_open = False
            requires_resolved = False

        focus_architecture = any(marker in text for marker in architecture_markers)
        focus_planning = focus_architecture or any(marker in text for marker in planning_markers)
        focus_task_decision = (
            requires_open
            or requires_resolved
            or any(marker in text for marker in task_decision_markers)
        )

        return {
            "requires_open": requires_open,
            "requires_resolved": requires_resolved,
            "focus_planning": focus_planning,
            "focus_architecture": focus_architecture,
            "focus_task_decision": focus_task_decision,
        }

    # ── Status matching ────────────────────────────────────────────────

    @staticmethod
    def status_matches_query_hint(
        *,
        status: str,
        summary: str,
        requires_open: bool,
        requires_resolved: bool,
    ) -> bool:
        """Check whether an item's *status* satisfies routing-hint constraints."""
        status_norm = str(status or "").strip().lower()
        summary_text = str(summary or "")
        open_statuses = {"open", "in_progress", "pending", "active", "needs_user"}
        resolved_statuses = {"resolved", "completed", "closed", "done", "superseded"}
        summary_is_resolved = is_resolved_task_or_decision(summary_text)

        if requires_open:
            if status_norm in resolved_statuses:
                return False
            if status_norm in open_statuses:
                return True
            return not summary_is_resolved
        if requires_resolved:
            if status_norm in resolved_statuses:
                return True
            if status_norm in open_statuses:
                return False
            return summary_is_resolved
        return True

    # ── Memory type classification ─────────────────────────────────────

    @staticmethod
    def memory_type_for_item(item: dict[str, Any] | Any) -> str:
        """Classify the memory type of *item* (dict or RetrievedMemory)."""
        return _memory_type_for_item(item)

    # ── Recency signal ─────────────────────────────────────────────────

    @staticmethod
    def recency_signal(timestamp: str, *, half_life_days: float) -> float:
        """Compute exponential-decay recency score for *timestamp*."""
        ts = _to_datetime(timestamp)
        if ts is None:
            return 0.0
        now = datetime.now(timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age_days = max((now - ts).total_seconds() / 86400.0, 0.0)
        if half_life_days <= 0:
            return 0.0
        decay = math.exp(-math.log(2) * age_days / half_life_days)
        return max(min(decay, 1.0), 0.0)


# ── Module-level helpers ───────────────────────────────────────────────


def _to_datetime(value: str | None) -> datetime | None:
    """Best-effort ISO-8601 parse — returns *None* on failure."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
