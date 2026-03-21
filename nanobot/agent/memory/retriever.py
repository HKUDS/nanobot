"""Memory retrieval read path — queries mem0/BM25, scores, filters, re-ranks.

``MemoryRetriever`` owns the complete retrieval pipeline extracted from
``MemoryStore``.  It reads from mem0 vector search (or local BM25 fallback),
applies intent-based routing, profile-aware score adjustments, graph expansion,
and cross-encoder re-ranking.
"""

from __future__ import annotations

import copy
import re
import time
from typing import TYPE_CHECKING, Any, Callable

from nanobot.agent.tracing import bind_trace

from .helpers import (
    _contains_any,
    _extract_query_keywords,
    _norm_text,
)
from .retrieval import _local_retrieve, _topic_fallback_retrieve
from .retrieval_planner import RetrievalPlanner

if TYPE_CHECKING:
    from .extractor import MemoryExtractor
    from .graph import KnowledgeGraph
    from .mem0_adapter import _Mem0Adapter
    from .profile import ProfileManager
    from .reranker import Reranker


class MemoryRetriever:
    """Encapsulates the full memory retrieval read path.

    Dependencies are injected at construction so that the retriever
    has no circular dependency on ``MemoryStore``.
    """

    def __init__(
        self,
        *,
        mem0: _Mem0Adapter,
        graph: KnowledgeGraph | None,
        planner: RetrievalPlanner,
        reranker: Reranker,
        profile_mgr: ProfileManager,
        rollout: dict[str, Any],  # live rollout dict reference
        read_events_fn: Callable[..., list[dict[str, Any]]],
        extractor: MemoryExtractor | None = None,
    ) -> None:
        self._mem0 = mem0
        self._graph = graph
        self._planner = planner
        self._reranker = reranker
        self._profile_mgr = profile_mgr
        self._rollout = rollout
        self._read_events_fn = read_events_fn
        self._extractor = extractor

    # -- Constants re-used from MemoryStore -----------------------------------

    PROFILE_KEYS = (
        "preferences",
        "stable_facts",
        "active_projects",
        "relationships",
        "constraints",
    )
    ROLLOUT_MODES = {"enabled", "disabled", "shadow"}
    PROFILE_STATUS_STALE = "stale"
    PROFILE_STATUS_CONFLICTED = "conflicted"

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def retrieve(
        self,
        query: str,
        *,
        top_k: int = 6,
        recency_half_life_days: float | None = None,
        embedding_provider: str | None = None,
    ) -> list[dict[str, Any]]:
        t0 = time.monotonic()
        # Local BM25 retrieval with intent routing when mem0 is unavailable.
        if not self._mem0.enabled:
            events = self._read_events_fn()
            plan = self._planner.plan(query)
            policy = plan.policy
            candidate_k = max(1, min(top_k * int(policy.get("candidate_multiplier", 3)), 60))
            half_life = recency_half_life_days or float(policy.get("half_life_days", 60.0))

            wants_superseded = plan.include_superseded

            # Graph query augmentation: expand search terms with related entities.
            augmented_query = query
            if self._graph is not None and self._graph.enabled:
                query_keywords = _extract_query_keywords(query)
                if query_keywords:
                    graph_related = self._graph.get_related_entity_names_sync(
                        query_keywords,
                        depth=2,
                    )
                    # Append related entity names to the query for BM25 matching.
                    extra_terms = graph_related - query_keywords
                    if extra_terms:
                        augmented_query = (
                            query
                            + " "
                            + " ".join(t.replace("-", " ").replace("_", " ") for t in extra_terms)
                        )

            candidates = _local_retrieve(
                events,
                augmented_query,
                top_k=candidate_k,
                recency_half_life_days=half_life,
                include_superseded=wants_superseded,
            )

            # Topic-based fallback: fill remaining slots when BM25 yields few matches.
            bm25_ids = {str(c.get("id", "")) for c in candidates}
            fallback_topics = list(policy.get("fallback_topics", []))
            fallback_types = list(policy.get("fallback_types", []))
            remaining = max(0, candidate_k - len(candidates))
            if remaining > 0 and (fallback_topics or fallback_types):
                fallback = _topic_fallback_retrieve(
                    events,
                    target_topics=fallback_topics,
                    target_memory_types=fallback_types,
                    exclude_ids=bm25_ids,
                    top_k=remaining,
                    base_score=0.25,
                    include_superseded=wants_superseded,
                )
                candidates.extend(fallback)

            # Apply intent-based type boosts and metadata enrichment.
            graph_boost = 0.15 if self._graph is not None and self._graph.enabled else 0.0
            query_entities = (
                {e.lower() for e in self._extractor._extract_entities(query)}
                if self._extractor is not None
                else set()
            )
            graph_entity_names: set[str] = set()
            if graph_boost > 0 and query_entities:
                # Collect entity names related to query entities from event triples.
                for evt in events:
                    for triple in evt.get("triples") or []:
                        subj = str(triple.get("subject", "")).lower()
                        obj = str(triple.get("object", "")).lower()
                        if subj in query_entities:
                            graph_entity_names.add(obj)
                        elif obj in query_entities:
                            graph_entity_names.add(subj)
                # Augment with graph neighbors when available.
                if self._graph is not None:
                    graph_related = self._graph.get_related_entity_names_sync(
                        query_entities,
                        depth=2,
                    )
                    graph_entity_names |= graph_related

            for item in candidates:
                memory_type = RetrievalPlanner.memory_type_for_item(item)
                item["memory_type"] = memory_type
                # Promote metadata fields to top level for downstream consumers.
                meta = item.get("metadata", {})
                if not item.get("topic"):
                    item["topic"] = str(meta.get("topic", "")).strip()
                if not item.get("stability"):
                    item["stability"] = str(meta.get("stability", "medium")).strip()
                base_score = float(item.get("retrieval_reason", {}).get("score", 0.0))
                type_boost = float(policy.get("type_boost", {}).get(memory_type, 0.0))
                stability = str(item.get("stability", "medium")).lower()
                stability_boost = {"high": 0.03, "medium": 0.01, "low": -0.02}.get(stability, 0.0)
                # Graph expansion boost: boost events that mention entities
                # related to query entities via the knowledge graph.
                g_boost = 0.0
                if graph_entity_names:
                    item_entities = {
                        e.lower() for e in (item.get("entities") or []) if isinstance(e, str)
                    }
                    if item_entities & graph_entity_names:
                        g_boost = graph_boost
                item["score"] = base_score + type_boost + stability_boost + g_boost
            candidates.sort(key=lambda x: x.get("score", 0.0), reverse=True)
            results = candidates[:top_k]
            bind_trace().debug(
                "Memory retrieve source=bm25 results={} duration_ms={:.0f}",
                len(results),
                (time.monotonic() - t0) * 1000,
            )
            return results

        mode = str(self._rollout.get("memory_rollout_mode", "enabled")).strip().lower()
        if mode not in self.ROLLOUT_MODES:
            mode = "enabled"
        type_separation_enabled = bool(self._rollout.get("memory_type_separation_enabled", True))
        router_enabled = bool(self._rollout.get("memory_router_enabled", True))
        reflection_enabled = bool(self._rollout.get("memory_reflection_enabled", True))
        if mode == "disabled":
            type_separation_enabled = False
            router_enabled = False
            reflection_enabled = False
        if mode == "shadow":
            router_enabled = False

        final, stats = self._retrieve_core(
            query=query,
            top_k=top_k,
            router_enabled=router_enabled,
            type_separation_enabled=type_separation_enabled,
            reflection_enabled=reflection_enabled,
        )

        shadow_enabled = bool(self._rollout.get("memory_shadow_mode", False))
        shadow_rate = float(self._rollout.get("memory_shadow_sample_rate", 0.2) or 0.0)
        if shadow_enabled and shadow_rate > 0 and mode != "disabled":
            shadow_should_run = shadow_rate >= 1.0 or (hash(f"{query}|{top_k}") % 1000) < int(
                shadow_rate * 1000
            )
            if shadow_should_run:
                shadow_router_enabled = not router_enabled
                shadow_final, _ = self._retrieve_core(
                    query=query,
                    top_k=top_k,
                    router_enabled=shadow_router_enabled,
                    type_separation_enabled=type_separation_enabled,
                    reflection_enabled=reflection_enabled,
                )
                primary_ids = {
                    str(item.get("id", "")) for item in final if str(item.get("id", "")).strip()
                }
                shadow_ids = {
                    str(item.get("id", ""))
                    for item in shadow_final
                    if str(item.get("id", "")).strip()
                }
                if primary_ids or shadow_ids:
                    overlap = len(primary_ids & shadow_ids) / max(len(primary_ids | shadow_ids), 1)
                    bind_trace().debug(
                        "Shadow retrieve overlap={:.2f} primary={} shadow={}",
                        overlap,
                        len(primary_ids),
                        len(shadow_ids),
                    )
        bind_trace().debug(
            "Memory retrieve source=mem0 results={} intent={} duration_ms={:.0f}",
            len(final),
            stats["intent"],
            (time.monotonic() - t0) * 1000,
        )
        return final

    # ------------------------------------------------------------------
    # Core mem0 retrieval pipeline
    # ------------------------------------------------------------------

    def _retrieve_core(
        self,
        *,
        query: str,
        top_k: int,
        router_enabled: bool,
        type_separation_enabled: bool,
        reflection_enabled: bool,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        from .helpers import _utc_now_iso

        planner = RetrievalPlanner(
            router_enabled=router_enabled,
            type_separation_enabled=type_separation_enabled,
        )
        plan = planner.plan(query)
        intent = plan.intent
        policy = plan.policy
        candidate_multiplier = (
            max(int(policy.get("candidate_multiplier", 3)), 1) if router_enabled else 1
        )
        candidate_k = max(1, min(max(top_k, top_k * candidate_multiplier), 60))
        allowed_sources = {
            str(item).strip().lower()
            for item in self._rollout.get("memory_fallback_allowed_sources", [])
            if str(item).strip()
        }
        max_summary_chars = int(self._rollout.get("memory_fallback_max_summary_chars", 280) or 280)

        # Compute graph-expanded terms (used for supplementary BM25 pass below).
        graph_extra_terms: set[str] = set()
        if self._graph is not None and self._graph.enabled:
            query_keywords = _extract_query_keywords(query)
            if query_keywords:
                graph_related = self._graph.get_related_entity_names_sync(
                    query_keywords,
                    depth=2,
                )
                graph_extra_terms = graph_related - query_keywords

        search_result = self._mem0.search(
            query,
            top_k=candidate_k,
            allow_get_all_fallback=True,
            allow_history_fallback=bool(
                self._rollout.get("memory_history_fallback_enabled", False)
            ),
            allowed_sources=allowed_sources,
            max_summary_chars=max_summary_chars,
            reject_blob_like=True,
            return_stats=True,
        )
        if isinstance(search_result, tuple) and len(search_result) == 2:
            retrieved, source_stats = search_result
        else:
            retrieved = search_result if isinstance(search_result, list) else []
            source_stats = {
                "source_vector": 0,
                "source_get_all": 0,
                "source_history": 0,
                "rejected_blob_like": 0,
            }
        if intent == "rollout_status":
            retrieved.append(
                {
                    "id": "rollout_status_snapshot",
                    "timestamp": _utc_now_iso(),
                    "type": "fact",
                    "summary": (
                        "Memory rollout status: "
                        f"mode={self._rollout.get('memory_rollout_mode')}, "
                        f"router={self._rollout.get('memory_router_enabled')}, "
                        f"shadow={self._rollout.get('memory_shadow_mode')}, "
                        f"reflection={self._rollout.get('memory_reflection_enabled')}, "
                        f"type_separation={self._rollout.get('memory_type_separation_enabled')}."
                    ),
                    "entities": [],
                    "score": 0.95,
                    "memory_type": "semantic",
                    "topic": "rollout",
                    "stability": "high",
                    "source": "config",
                    "confidence": 1.0,
                    "evidence_refs": [],
                    "retrieval_reason": {
                        "provider": "nanobot",
                        "backend": "synthetic_rollout",
                        "semantic": 0.95,
                        "recency": 0.0,
                    },
                    "provenance": {
                        "canonical_id": "rollout_status_snapshot",
                        "source_span": None,
                    },
                }
            )

        # Supplementary BM25 pass: pull in events matching graph-related entities
        # that mem0 vector search may have missed.
        if graph_extra_terms and retrieved is not None:
            retrieved_ids = {str(r.get("id", "")) for r in retrieved}
            graph_query = (
                query
                + " "
                + " ".join(t.replace("-", " ").replace("_", " ") for t in graph_extra_terms)
            )
            events = self._read_events_fn()
            bm25_supplement = _local_retrieve(
                events,
                graph_query,
                top_k=candidate_k,
                recency_half_life_days=float(policy.get("half_life_days", 60.0)),
                include_superseded=False,
            )
            for item in bm25_supplement:
                eid = str(item.get("id", ""))
                if eid and eid not in retrieved_ids:
                    # Mark source as graph-augmented BM25
                    reason = item.get("retrieval_reason", {})
                    if not isinstance(reason, dict):
                        reason = {}
                    reason["provider"] = "bm25_graph"
                    item["retrieval_reason"] = reason
                    retrieved.append(item)
                    retrieved_ids.add(eid)

        if not retrieved:
            return [], {
                "intent": intent,
                "retrieved_count": 0,
                "counts": {
                    "retrieval_returned": 0,
                    "retrieval_source_vector_count": int(source_stats.get("source_vector", 0)),
                    "retrieval_source_get_all_count": int(source_stats.get("source_get_all", 0)),
                    "retrieval_source_history_count": int(source_stats.get("source_history", 0)),
                    "retrieval_rejected_blob_count": int(source_stats.get("rejected_blob_like", 0)),
                },
            }

        profile = self._profile_mgr.read_profile()
        conflicts = (
            profile.get("conflicts", []) if isinstance(profile.get("conflicts"), list) else []
        )

        field_by_event_type = {
            "preference": "preferences",
            "fact": "stable_facts",
            "relationship": "relationships",
            "constraint": "constraints",
            "task": "active_projects",
            "decision": "active_projects",
        }
        resolved_keep_new_old: dict[str, set[str]] = {key: set() for key in self.PROFILE_KEYS}
        resolved_keep_new_new: dict[str, set[str]] = {key: set() for key in self.PROFILE_KEYS}
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

        def _contains_norm_phrase(text: str, phrase_norm: str) -> bool:
            if not phrase_norm:
                return False
            text_norm = _norm_text(text)
            if not text_norm:
                return False
            return phrase_norm in text_norm

        adjusted: list[dict[str, Any]] = []
        reflection_filtered_non_reflection_intent = 0
        reflection_filtered_no_evidence = 0
        routing_hints = plan.routing_hints
        for item in retrieved:
            event_type = str(item.get("type", "fact"))
            memory_type = RetrievalPlanner.memory_type_for_item(item)
            item["memory_type"] = memory_type

            topic = str(item.get("topic", "")).strip().lower()
            summary = str(item.get("summary", ""))
            event_status = str(item.get("status", "")).strip().lower()
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
                    summary,
                    (
                        "architecture",
                        "design decision",
                        "memory architecture",
                    ),
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
                # debug_history needs the full timeline (failures + resolutions).
                requires_resolved=(
                    bool(routing_hints["requires_resolved"]) and intent != "debug_history"
                ),
            ):
                continue
            if intent == "constraints_lookup":
                if memory_type != "semantic":
                    continue
                if "constraint" not in topic and not _contains_any(
                    summary,
                    ("must", "cannot", "constraint", "should not"),
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
                    (
                        "conflict",
                        "needs_user",
                        "resolved",
                        "keep_new",
                        "decision",
                    ),
                ):
                    continue
            if intent == "rollout_status":
                if not _contains_any(
                    summary,
                    (
                        "rollout",
                        "router",
                        "shadow",
                        "reflection",
                        "type_separation",
                    ),
                ):
                    continue

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

            field = field_by_event_type.get(event_type)  # type: ignore[assignment]
            summary = str(item.get("summary", ""))
            score = float(item.get("score", 0.0))
            adjustment = 0.0
            adjustment_reasons: list[str] = []
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
                        if status == self.PROFILE_STATUS_STALE and not pinned:
                            adjustment -= 0.08
                            adjustment_reasons.append("stale_profile_penalty")
                            break
                        if status == self.PROFILE_STATUS_CONFLICTED:
                            adjustment -= 0.05
                            adjustment_reasons.append("conflicted_profile_penalty")
                            break
            if memory_type == "semantic":
                if (
                    event_status == "superseded"
                    or str(item.get("superseded_by_event_id", "")).strip()
                ):
                    adjustment -= 0.2
                    adjustment_reasons.append("semantic_superseded_penalty")

            reason = item.get("retrieval_reason")
            if not isinstance(reason, dict):
                reason = {}
                item["retrieval_reason"] = reason
            if adjustment_reasons:
                reason["profile_adjustment"] = round(adjustment, 4)
                reason["profile_adjustment_reasons"] = adjustment_reasons

            recency = RetrievalPlanner.recency_signal(
                str(item.get("timestamp", "")),
                half_life_days=float(policy.get("half_life_days", 60.0)),
            )
            type_boost = (
                float(policy.get("type_boost", {}).get(memory_type, 0.0))
                if type_separation_enabled
                else 0.0
            )
            stability = str(item.get("stability", "medium")).strip().lower()
            stability_boost = {"high": 0.03, "medium": 0.01, "low": -0.02}.get(stability, 0.0)
            reflection_penalty = -0.06 if memory_type == "reflection" else 0.0
            if not router_enabled:
                recency = 0.0
                stability_boost = 0.0
                reflection_penalty = 0.0
                type_boost = 0.0
            elif reflection_penalty:
                adjustment_reasons.append("reflection_default_penalty")
            intent_bonus = type_boost + (0.08 * recency) + stability_boost + reflection_penalty
            item["score"] = score + adjustment + intent_bonus
            reason["recency"] = round(recency, 4)
            reason["intent"] = intent
            reason["type_boost"] = round(type_boost, 4)
            reason["stability_boost"] = round(stability_boost, 4)
            if reflection_penalty:
                reason["reflection_penalty"] = round(reflection_penalty, 4)
            adjusted.append(item)

        # ------------------------------------------------------------------
        # Cross-encoder re-ranking (Step 7)
        # ------------------------------------------------------------------
        reranker_mode = str(self._rollout.get("reranker_mode", "disabled")).strip().lower()
        if reranker_mode in ("enabled", "shadow") and adjusted:
            if reranker_mode == "enabled":
                adjusted = self._reranker.rerank(query, adjusted)
            else:
                # Shadow: compute re-ranked order but keep heuristic order.
                shadow_items = copy.deepcopy(adjusted)
                shadow_items = self._reranker.rerank(query, shadow_items)
                heuristic_ids = [str(it.get("id", "")) for it in adjusted]
                reranked_ids = [str(it.get("id", "")) for it in shadow_items]
                # Rank delta computed for observability logging; result intentionally unused.
                self._reranker.compute_rank_delta(heuristic_ids, reranked_ids)

        adjusted.sort(key=lambda item: item.get("score", 0.0), reverse=True)
        final = adjusted[: max(1, top_k)]
        counts = {
            "retrieval_returned": len(final),
            "retrieval_filtered_out": max(len(retrieved) - len(final), 0),
            "retrieval_source_vector_count": int(source_stats.get("source_vector", 0)),
            "retrieval_source_get_all_count": int(source_stats.get("source_get_all", 0)),
            "retrieval_source_history_count": int(source_stats.get("source_history", 0)),
            "retrieval_rejected_blob_count": int(source_stats.get("rejected_blob_like", 0)),
            "reflection_filtered_non_reflection_intent": reflection_filtered_non_reflection_intent,
            "reflection_filtered_no_evidence": reflection_filtered_no_evidence,
            "retrieval_returned_semantic": 0,
            "retrieval_returned_episodic": 0,
            "retrieval_returned_reflection": 0,
            "retrieval_returned_unknown": 0,
        }
        for item in final:
            memory_type = str(item.get("memory_type", "")).strip().lower()
            if memory_type == "semantic":
                counts["retrieval_returned_semantic"] += 1
            elif memory_type == "episodic":
                counts["retrieval_returned_episodic"] += 1
            elif memory_type == "reflection":
                counts["retrieval_returned_reflection"] += 1
            else:
                counts["retrieval_returned_unknown"] += 1
        return final, {
            "intent": intent,
            "retrieved_count": len(retrieved),
            "counts": counts,
        }

    # ------------------------------------------------------------------
    # Query entity extraction via entity-index lookup
    # ------------------------------------------------------------------

    def _build_entity_index(self, events: list[dict[str, Any]]) -> set[str]:
        """Collect all unique entity strings from events into a lowercase set."""
        index: set[str] = set()
        for evt in events:
            for e in evt.get("entities") or []:
                if isinstance(e, str) and e.strip():
                    index.add(e.strip().lower())
        return index

    def _extract_query_entities(
        self,
        query: str,
        entity_index: set[str],
    ) -> set[str]:
        """Extract entities from a query by matching tokens against known entities.

        Complements the capitalization-based ``_extract_entities`` by handling
        lowercase queries like "who are alice and bob".  Matches unigrams and
        bigrams against the entity index built from events.
        """
        words = re.findall(r"[a-z0-9][\w-]*", query.lower())
        matched: set[str] = set()
        for w in words:
            if w in entity_index:
                matched.add(w)
        # Also check bigrams (e.g. "github actions", "knowledge graph")
        for i in range(len(words) - 1):
            bigram = f"{words[i]} {words[i + 1]}"
            if bigram in entity_index:
                matched.add(bigram)
        return matched

    def _build_graph_context_lines(
        self,
        query: str,
        retrieved: list[dict[str, Any]],
        max_tokens: int = 100,
    ) -> list[str]:
        """Build entity relationship summary lines from graph and local event triples.

        Queries the knowledge graph first (when available), then falls back to
        scanning triples stored in local events.
        """
        query_entities: set[str] = set()
        if self._extractor is not None:
            query_entities = {e.lower() for e in self._extractor._extract_entities(query)}

        # Also extract entities via index lookup (handles lowercase queries).
        events = self._read_events_fn(limit=200)
        entity_index = self._build_entity_index(events)
        query_entities |= self._extract_query_entities(query, entity_index)

        for item in retrieved:
            for e in item.get("entities") or []:
                if isinstance(e, str) and e.strip():
                    query_entities.add(e.strip().lower())

        if not query_entities:
            return []

        # Collect relevant triples — graph first, then local event fallback.
        rel_triples: list[tuple[str, str, str]] = []

        if self._graph is not None and self._graph.enabled:
            rel_triples.extend(self._graph.get_triples_for_entities_sync(query_entities))

        # Supplement with local event triples (may add context the graph lacks).
        for evt in events:
            for triple in evt.get("triples") or []:
                subj = str(triple.get("subject", "")).strip()
                pred = str(triple.get("predicate", "")).strip()
                obj = str(triple.get("object", "")).strip()
                if not subj or not pred or not obj:
                    continue
                if subj.lower() in query_entities or obj.lower() in query_entities:
                    rel_triples.append((subj, pred, obj))

        if not rel_triples:
            return []

        # Deduplicate and format as compact lines, respecting token budget.
        # Annotate entities with ontology types to help the LLM disambiguate.
        from .ontology import classify_entity_type

        seen: set[tuple[str, str, str]] = set()
        graph_lines: list[str] = []
        total_chars = 0
        max_chars = max_tokens * 4

        for subj, pred, obj in rel_triples:
            key = (subj.lower(), pred, obj.lower())
            if key in seen:
                continue
            seen.add(key)
            s_type = classify_entity_type(subj).value
            o_type = classify_entity_type(obj).value
            s_label = f"{subj} [{s_type}]" if s_type != "unknown" else subj
            o_label = f"{obj} [{o_type}]" if o_type != "unknown" else obj
            line = f"- {s_label} \u2192 {pred} \u2192 {o_label}"
            if total_chars + len(line) > max_chars:
                break
            graph_lines.append(line)
            total_chars += len(line)

        return graph_lines
