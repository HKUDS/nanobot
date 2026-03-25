"""Retrieval scoring — filter, score, and rerank pipeline stages.

``RetrievalScorer`` owns the scoring-related stages of the retrieval pipeline:
filtering by intent/routing hints, profile-aware score adjustments, stability
and type boosts, and cross-encoder re-ranking delegation.
"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any, Callable

from .._text import _contains_any, _norm_text
from .retrieval_planner import RetrievalPlan, RetrievalPlanner

if TYPE_CHECKING:
    from ..persistence.profile_io import ProfileStore as ProfileManager
    from ..ranking.reranker import Reranker


# ---------------------------------------------------------------------------
# Module-private helpers and constants
# ---------------------------------------------------------------------------

_FIELD_BY_EVENT_TYPE: dict[str, str] = {
    "preference": "preferences",
    "fact": "stable_facts",
    "relationship": "relationships",
    "constraint": "constraints",
    "task": "active_projects",
    "decision": "active_projects",
}

_STABILITY_BOOST: dict[str, float] = {
    "high": 0.03,
    "medium": 0.01,
    "low": -0.02,
}

PROFILE_KEYS = (
    "preferences",
    "stable_facts",
    "active_projects",
    "relationships",
    "constraints",
)

PROFILE_STATUS_STALE = "stale"
PROFILE_STATUS_CONFLICTED = "conflicted"


def _contains_norm_phrase(text: str, phrase_norm: str) -> bool:
    if not phrase_norm:
        return False
    text_norm = _norm_text(text)
    if not text_norm:
        return False
    return phrase_norm in text_norm


# ---------------------------------------------------------------------------
# RetrievalScorer
# ---------------------------------------------------------------------------


class RetrievalScorer:
    """Owns filter → score → rerank stages of the retrieval pipeline."""

    def __init__(
        self,
        *,
        profile_mgr: ProfileManager,
        reranker: Reranker,
        rollout_fn: Callable[[], dict[str, Any]],
    ) -> None:
        self._profile_mgr = profile_mgr
        self._reranker = reranker
        self._rollout_fn = rollout_fn

    # ------------------------------------------------------------------
    # Pipeline stage: load profile scoring data
    # ------------------------------------------------------------------

    def load_profile_scoring_data(self) -> dict[str, Any]:
        """Read profile and extract resolved-conflict scoring data.

        Returns a dict with keys:
        - ``profile``: the full profile dict
        - ``resolved_keep_new_old``: {field: set(norm_phrase)} for old values
        - ``resolved_keep_new_new``: {field: set(norm_phrase)} for new values
        """
        profile = self._profile_mgr.read_profile()
        conflicts = (
            profile.get("conflicts", []) if isinstance(profile.get("conflicts"), list) else []
        )

        resolved_keep_new_old: dict[str, set[str]] = {key: set() for key in PROFILE_KEYS}
        resolved_keep_new_new: dict[str, set[str]] = {key: set() for key in PROFILE_KEYS}
        for conflict in conflicts:
            if not isinstance(conflict, dict):
                continue
            if str(conflict.get("status", "")).lower() != "resolved":
                continue
            if str(conflict.get("resolution", "")).lower() != "keep_new":
                continue
            field = str(conflict.get("field", ""))
            if field not in resolved_keep_new_old:
                continue
            old_value = str(conflict.get("old", "")).strip()
            new_value = str(conflict.get("new", "")).strip()
            if old_value:
                resolved_keep_new_old[field].add(_norm_text(old_value))
            if new_value:
                resolved_keep_new_new[field].add(_norm_text(new_value))

        return {
            "profile": profile,
            "resolved_keep_new_old": resolved_keep_new_old,
            "resolved_keep_new_new": resolved_keep_new_new,
        }

    # ------------------------------------------------------------------
    # Pipeline stage: intent-based filtering
    # ------------------------------------------------------------------

    def filter_items(
        self,
        items: list[dict[str, Any]],
        plan: RetrievalPlan,
        *,
        reflection_enabled: bool = True,
        type_separation_enabled: bool = True,
    ) -> tuple[list[dict[str, Any]], dict[str, int]]:
        """Filter items by intent routing hints and reflection rules.

        Returns (filtered_items, filter_counts).
        """
        intent = plan.intent
        routing_hints = plan.routing_hints
        filtered: list[dict[str, Any]] = []
        reflection_filtered_non_reflection_intent = 0
        reflection_filtered_no_evidence = 0

        for item in items:
            event_type = str(item.get("type", "fact"))
            memory_type = RetrievalPlanner.memory_type_for_item(item)
            item["memory_type"] = memory_type

            topic = str(item.get("topic", "")).strip().lower()
            summary = str(item.get("summary", ""))
            event_status = str(item.get("status", "")).strip().lower()

            # -- Routing-hint filters -----------------------------------------
            task_or_decision_like = event_type in {
                "task",
                "decision",
                "relationship",
            } or topic in {
                "task_progress",
                "project",
                "planning",
                "relationship",
            }
            planning_like = task_or_decision_like or _contains_any(
                summary, ("plan", "next step", "roadmap", "milestone")
            )
            architecture_like = (
                "architecture" in topic
                or _contains_any(
                    summary, ("architecture", "design decision", "memory architecture")
                )
                or event_type == "decision"
            )

            if (
                routing_hints["focus_task_decision"]
                and not task_or_decision_like
                and intent != "debug_history"
            ):
                continue
            if routing_hints["focus_planning"] and not planning_like:
                continue
            if routing_hints["focus_architecture"] and not architecture_like:
                continue
            if not RetrievalPlanner.status_matches_query_hint(
                status=event_status,
                summary=summary,
                requires_open=bool(routing_hints["requires_open"]),
                requires_resolved=(
                    bool(routing_hints["requires_resolved"]) and intent != "debug_history"
                ),
            ):
                continue

            # -- Intent-specific filters --------------------------------------
            if intent == "constraints_lookup":
                if memory_type != "semantic":
                    continue
                if "constraint" not in topic and not _contains_any(
                    summary, ("must", "cannot", "constraint", "should not")
                ):
                    continue
            if intent == "debug_history":
                if memory_type != "episodic" and topic not in {
                    "infra",
                    "task_progress",
                    "incident",
                }:
                    continue
            if intent == "conflict_review":
                if not _contains_any(
                    summary,
                    ("conflict", "needs_user", "resolved", "keep_new", "decision"),
                ):
                    continue
            if intent == "rollout_status":
                if not _contains_any(
                    summary,
                    ("rollout", "router", "shadow", "reflection", "type_separation"),
                ):
                    continue

            # -- Reflection filters -------------------------------------------
            if reflection_enabled:
                if (
                    memory_type == "reflection"
                    and type_separation_enabled
                    and intent != "reflection"
                ):
                    reflection_filtered_non_reflection_intent += 1
                    continue
                evidence_refs = item.get("evidence_refs")
                if memory_type == "reflection" and not (
                    isinstance(evidence_refs, list) and len(evidence_refs) > 0
                ):
                    reflection_filtered_no_evidence += 1
                    continue
            elif memory_type == "reflection":
                reflection_filtered_non_reflection_intent += 1
                continue

            filtered.append(item)

        filter_counts = {
            "reflection_filtered_non_reflection_intent": reflection_filtered_non_reflection_intent,
            "reflection_filtered_no_evidence": reflection_filtered_no_evidence,
        }
        return filtered, filter_counts

    # ------------------------------------------------------------------
    # Pipeline stage: unified scoring
    # ------------------------------------------------------------------

    def score_items(
        self,
        items: list[dict[str, Any]],
        plan: RetrievalPlan,
        profile_data: dict[str, Any],
        graph_entities: set[str],
        *,
        use_recency: bool,
        router_enabled: bool,
        type_separation_enabled: bool,
    ) -> list[dict[str, Any]]:
        """Apply the shared scoring formula to items from any source."""
        policy = plan.policy
        intent = plan.intent
        profile = profile_data["profile"]
        resolved_keep_new_old = profile_data["resolved_keep_new_old"]
        resolved_keep_new_new = profile_data["resolved_keep_new_new"]

        graph_boost_value = 0.15 if graph_entities else 0.0

        scored: list[dict[str, Any]] = []
        for item in items:
            memory_type = str(item.get("memory_type", ""))
            if not memory_type:
                memory_type = RetrievalPlanner.memory_type_for_item(item)
                item["memory_type"] = memory_type

            event_type = str(item.get("type", "fact"))
            event_status = str(item.get("status", "")).strip().lower()
            summary = str(item.get("summary", ""))

            # -- Base score (preserved from source) ---------------------------
            if use_recency:
                base_score = float(item.get("score", 0.0))
            else:
                base_score = float(
                    item.get("retrieval_reason", {}).get("score", 0.0)
                    if isinstance(item.get("retrieval_reason"), dict)
                    else 0.0
                )

            # -- Profile adjustments ------------------------------------------
            adjustment = 0.0
            adjustment_reasons: list[str] = []
            field = _FIELD_BY_EVENT_TYPE.get(event_type) if use_recency else None
            if field:
                for old_norm in resolved_keep_new_old.get(field, set()):
                    if _contains_norm_phrase(summary, old_norm):
                        adjustment -= 0.18
                        adjustment_reasons.append("resolved_keep_new_old_penalty")
                        break
                for new_norm in resolved_keep_new_new.get(field, set()):
                    if _contains_norm_phrase(summary, new_norm):
                        adjustment += 0.12
                        adjustment_reasons.append("resolved_keep_new_new_boost")
                        break
                section_meta = self._profile_mgr._meta_section(profile, field)
                if isinstance(section_meta, dict):
                    for norm_key, meta in section_meta.items():
                        if not isinstance(meta, dict):
                            continue
                        if not _contains_norm_phrase(summary, str(norm_key)):
                            continue
                        status = str(meta.get("status", "")).lower()
                        pinned = bool(meta.get("pinned"))
                        if status == PROFILE_STATUS_STALE and not pinned:
                            adjustment -= 0.08
                            adjustment_reasons.append("stale_profile_penalty")
                            break
                        if status == PROFILE_STATUS_CONFLICTED:
                            adjustment -= 0.05
                            adjustment_reasons.append("conflicted_profile_penalty")
                            break

            # Superseded semantic penalty
            if use_recency and memory_type == "semantic":
                if (
                    event_status == "superseded"
                    or str(item.get("superseded_by_event_id", "")).strip()
                ):
                    adjustment -= 0.2
                    adjustment_reasons.append("semantic_superseded_penalty")

            # -- Record profile adjustment in retrieval_reason ----------------
            reason = item.get("retrieval_reason")
            if not isinstance(reason, dict):
                reason = {}
                item["retrieval_reason"] = reason
            if adjustment_reasons:
                reason["profile_adjustment"] = round(adjustment, 4)
                reason["profile_adjustment_reasons"] = adjustment_reasons

            # -- Type / recency / stability / reflection boosts ---------------
            type_boost = (
                float(policy.get("type_boost", {}).get(memory_type, 0.0))
                if type_separation_enabled
                else 0.0
            )
            stability = str(item.get("stability", "medium")).strip().lower()
            stability_boost = _STABILITY_BOOST.get(stability, 0.0)
            reflection_penalty = -0.06 if (use_recency and memory_type == "reflection") else 0.0

            if use_recency:
                recency = RetrievalPlanner.recency_signal(
                    str(item.get("timestamp", "")),
                    half_life_days=float(policy.get("half_life_days", 60.0)),
                )
            else:
                recency = 0.0

            if not router_enabled:
                recency = 0.0
                stability_boost = 0.0
                reflection_penalty = 0.0
                type_boost = 0.0
            elif reflection_penalty:
                adjustment_reasons.append("reflection_default_penalty")

            # -- Graph entity boost -------------------------------------------
            g_boost = 0.0
            if graph_entities:
                item_entities = {
                    e.lower() for e in (item.get("entities") or []) if isinstance(e, str)
                }
                if item_entities & graph_entities:
                    g_boost = graph_boost_value

            intent_bonus = type_boost + (0.08 * recency) + stability_boost + reflection_penalty
            item["score"] = base_score + adjustment + intent_bonus + g_boost

            # Record scoring metadata
            reason["recency"] = round(recency, 4)
            reason["intent"] = intent
            reason["type_boost"] = round(type_boost, 4)
            reason["stability_boost"] = round(stability_boost, 4)
            if reflection_penalty:
                reason["reflection_penalty"] = round(reflection_penalty, 4)

            scored.append(item)

        return scored

    # ------------------------------------------------------------------
    # Pipeline stage: cross-encoder reranking
    # ------------------------------------------------------------------

    def rerank_items(
        self,
        query: str,
        items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Apply cross-encoder reranking (enabled/shadow/disabled)."""
        reranker_mode = str(self._rollout_fn().get("reranker_mode", "disabled")).strip().lower()
        if reranker_mode not in ("enabled", "shadow") or not items:
            return items

        if reranker_mode == "enabled":
            return self._reranker.rerank(query, items)

        # Shadow: compute re-ranked order but keep heuristic order.
        shadow_items = copy.deepcopy(items)
        shadow_items = self._reranker.rerank(query, shadow_items)
        heuristic_ids = [str(it.get("id", "")) for it in items]
        reranked_ids = [str(it.get("id", "")) for it in shadow_items]
        # Rank delta computed for observability logging; result intentionally unused.
        self._reranker.compute_rank_delta(heuristic_ids, reranked_ids)
        return items
