"""Memory retrieval read path — unified vector + FTS5 + RRF pipeline.

``MemoryRetriever`` owns the complete retrieval pipeline extracted from
``MemoryStore``.  It queries the unified DB (vector KNN + FTS5), fuses via
Reciprocal Rank Fusion, applies intent-based routing, profile-aware score
adjustments, graph expansion, and cross-encoder re-ranking.

Pipeline architecture (pipes and filters)::

    Source (vector + FTS5 + RRF) → Graph Augment → Filter → Score → Rerank → Truncate
"""

from __future__ import annotations

import copy
import re
import time
from typing import TYPE_CHECKING, Any, Callable

from nanobot.observability.tracing import bind_trace

from ..helpers import (
    _contains_any,
    _extract_query_keywords,
    _norm_text,
)
from .retrieval_planner import RetrievalPlan, RetrievalPlanner

if TYPE_CHECKING:
    from ..graph.graph import KnowledgeGraph
    from ..persistence.profile_io import ProfileStore as ProfileManager
    from ..ranking.reranker import Reranker
    from ..write.extractor import MemoryExtractor
    from .embedder import Embedder
    from .unified_db import UnifiedMemoryDB


# ---------------------------------------------------------------------------
# Module-private helpers
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


def _contains_norm_phrase(text: str, phrase_norm: str) -> bool:
    if not phrase_norm:
        return False
    text_norm = _norm_text(text)
    if not text_norm:
        return False
    return phrase_norm in text_norm


class MemoryRetriever:
    """Encapsulates the full memory retrieval read path.

    Dependencies are injected at construction so that the retriever
    has no circular dependency on ``MemoryStore``.
    """

    def __init__(
        self,
        *,
        graph: KnowledgeGraph | None,
        planner: RetrievalPlanner,
        reranker: Reranker,
        profile_mgr: ProfileManager,
        rollout: dict[str, Any],  # live rollout dict reference
        read_events_fn: Callable[..., list[dict[str, Any]]],
        extractor: MemoryExtractor | None = None,
        db: UnifiedMemoryDB | None = None,
        embedder: Embedder | None = None,
    ) -> None:
        self._graph = graph
        self._planner = planner
        self._reranker = reranker
        self._profile_mgr = profile_mgr
        self._rollout = rollout
        self._read_events_fn = read_events_fn
        self._extractor = extractor
        self._db = db
        self._embedder = embedder
        self._graph_cache: dict[frozenset[str], set[str]] = {}

    # -- Constants re-used from MemoryStore -----------------------------------

    PROFILE_KEYS = (
        "preferences",
        "stable_facts",
        "active_projects",
        "relationships",
        "constraints",
    )
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
        self._graph_cache = {}  # reset per-request
        t0 = time.monotonic()

        # Unified path: vector + FTS5 + RRF when db and embedder are injected
        if self._db is not None and self._embedder is not None:
            return self._retrieve_unified(
                query,
                top_k=top_k,
                recency_half_life_days=recency_half_life_days,
                t0=t0,
            )

        return []

    # ------------------------------------------------------------------
    # Unified path (vector + FTS5 + RRF)
    # ------------------------------------------------------------------

    def _retrieve_unified(
        self,
        query: str,
        *,
        top_k: int,
        recency_half_life_days: float | None,
        t0: float,
    ) -> list[dict[str, Any]]:
        """Single fused retrieval: vector + FTS5 + RRF.

        Used when ``UnifiedMemoryDB`` and ``Embedder`` are injected.  Runs
        embedding and dual-source search (vector KNN + FTS5), fuses via
        Reciprocal Rank Fusion, then applies the standard scoring pipeline.
        """
        import asyncio

        assert self._db is not None  # noqa: S101 — guarded by caller
        assert self._embedder is not None  # noqa: S101
        embedder = self._embedder  # local ref for lambda closure (mypy narrowing)

        plan = self._planner.plan(query)
        policy = plan.policy
        candidate_k = max(1, min(top_k * int(policy.get("candidate_multiplier", 3)), 60))

        # 1. Embed query (async → sync bridge)
        # Try asyncio.run() first; if a loop is already active (e.g. inside
        # pytest-asyncio), fall back to a helper thread.
        coro = embedder.embed(query)
        try:
            query_vec = asyncio.run(coro)
        except RuntimeError:
            # asyncio.run() failed because a loop is already running.
            # Close the unawaited coroutine to suppress the
            # "coroutine was never awaited" warning.
            coro.close()
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                query_vec = pool.submit(lambda: asyncio.run(embedder.embed(query))).result()

        # 2. Dual source — DB methods are synchronous
        vec_results = self._db.search_vector(query_vec, candidate_k)
        fts_results = self._db.search_fts(query, candidate_k)

        # 3. Fuse via RRF
        candidates = self._fuse_results(vec_results, fts_results, vector_weight=0.7)

        if not candidates:
            # Fallback: if vector + FTS returned nothing (e.g., events have no
            # embeddings yet, or FTS terms don't match), try recent events.
            candidates = self._db.read_events(limit=candidate_k)
            if not candidates:
                bind_trace().debug(
                    "Memory retrieve source=unified results=0 duration_ms={:.0f}",
                    (time.monotonic() - t0) * 1000,
                )
                return []

        # 4. Enrich metadata
        self._enrich_item_metadata(candidates)

        # 5. Filter
        filtered, _filter_counts = self._filter_items(candidates, plan)

        # 6. Score
        profile_data = self._load_profile_scoring_data()
        graph_entities = self._collect_graph_entity_names(query, self._read_events_fn())
        scored = self._score_items(
            filtered,
            plan,
            profile_data,
            graph_entities,
            use_recency=True,
            router_enabled=True,
            type_separation_enabled=True,
        )

        # 7. Rerank
        scored = self._rerank_items(query, scored)

        # 8. Sort + truncate
        scored.sort(key=lambda x: x.get("score", 0.0), reverse=True)
        results = scored[:top_k]

        bind_trace().debug(
            "Memory retrieve source=unified results={} duration_ms={:.0f}",
            len(results),
            (time.monotonic() - t0) * 1000,
        )
        return results

    @staticmethod
    def _fuse_results(
        vec_results: list[dict[str, Any]],
        fts_results: list[dict[str, Any]],
        vector_weight: float = 0.7,
    ) -> list[dict[str, Any]]:
        """Reciprocal Rank Fusion of vector and FTS5 results."""
        k = 60  # standard RRF constant
        scores: dict[str, float] = {}
        items: dict[str, dict[str, Any]] = {}

        for rank, item in enumerate(vec_results):
            eid = str(item.get("id", ""))
            scores[eid] = scores.get(eid, 0.0) + vector_weight / (k + rank)
            items[eid] = item

        for rank, item in enumerate(fts_results):
            eid = str(item.get("id", ""))
            scores[eid] = scores.get(eid, 0.0) + (1 - vector_weight) / (k + rank)
            if eid not in items:
                items[eid] = item

        # Sort by fused score descending
        ranked = sorted(scores.keys(), key=lambda eid: scores[eid], reverse=True)
        result: list[dict[str, Any]] = []
        for eid in ranked:
            entry = dict(items[eid])
            entry["_rrf_score"] = scores[eid]
            result.append(entry)
        return result

    # ------------------------------------------------------------------
    # Pipeline stage: graph query augmentation
    # ------------------------------------------------------------------

    def _augment_query_with_graph(self, query: str) -> tuple[str, set[str]]:
        """Expand query with graph entity names.

        Returns (augmented_query, extra_terms).
        """
        if self._graph is None or not self._graph.enabled:
            return query, set()

        query_keywords = _extract_query_keywords(query)
        if not query_keywords:
            return query, set()

        graph_related = self._graph.get_related_entity_names_sync(
            query_keywords,
            depth=2,
        )
        extra_terms = graph_related - query_keywords
        if not extra_terms:
            return query, set()

        augmented_query = (
            query + " " + " ".join(t.replace("-", " ").replace("_", " ") for t in extra_terms)
        )
        return augmented_query, extra_terms

    # ------------------------------------------------------------------
    # Pipeline stage: load profile scoring data
    # ------------------------------------------------------------------

    def _load_profile_scoring_data(self) -> dict[str, Any]:
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

        return {
            "profile": profile,
            "resolved_keep_new_old": resolved_keep_new_old,
            "resolved_keep_new_new": resolved_keep_new_new,
        }

    # ------------------------------------------------------------------
    # Pipeline stage: intent-based filtering
    # ------------------------------------------------------------------

    def _filter_items(
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

    def _score_items(
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
        """Apply the shared scoring formula to items from any source.

        Both BM25 and mem0 paths use the same adjustment logic on top of their
        respective base scores.  The base score (BM25 raw or mem0 similarity)
        is preserved — only the adjustments are unified.
        """
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
                # BM25 path: base score comes from retrieval_reason
                base_score = float(
                    item.get("retrieval_reason", {}).get("score", 0.0)
                    if isinstance(item.get("retrieval_reason"), dict)
                    else 0.0
                )

            # -- Profile adjustments (mem0 path only) --------------------------
            # The BM25 path historically applied only lightweight boosts (type,
            # stability, graph).  Profile adjustments, superseded penalties, and
            # reflection penalties are mem0-specific scoring refinements.
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
                        if status == self.PROFILE_STATUS_STALE and not pinned:
                            adjustment -= 0.08
                            adjustment_reasons.append("stale_profile_penalty")
                            break
                        if status == self.PROFILE_STATUS_CONFLICTED:
                            adjustment -= 0.05
                            adjustment_reasons.append("conflicted_profile_penalty")
                            break

            # Superseded semantic penalty (mem0 path only)
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

            # -- Graph entity boost (BM25 path only) --------------------------
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

    def _rerank_items(
        self,
        query: str,
        items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Apply cross-encoder reranking (enabled/shadow/disabled)."""
        reranker_mode = str(self._rollout.get("reranker_mode", "disabled")).strip().lower()
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

    # ------------------------------------------------------------------
    # Pipeline stage: result statistics
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Pipeline stage: metadata enrichment + graph entity collection
    # ------------------------------------------------------------------

    def _enrich_item_metadata(self, items: list[dict[str, Any]]) -> None:
        """Promote metadata fields (topic, stability, memory_type) to top level."""
        import json as _json

        for item in items:
            memory_type = RetrievalPlanner.memory_type_for_item(item)
            item["memory_type"] = memory_type
            meta = item.get("metadata", {})
            if isinstance(meta, str):
                try:
                    meta = _json.loads(meta)
                except (ValueError, TypeError):
                    meta = {}
            if not isinstance(meta, dict):
                meta = {}
            # Unpack extra fields stored by ingester (entities, triples, etc.)
            extras = meta.pop("_extra", None)
            if isinstance(extras, dict):
                for k, v in extras.items():
                    if k not in item:
                        item[k] = v
            if not item.get("topic"):
                item["topic"] = str(meta.get("topic", "")).strip()
            if not item.get("stability"):
                item["stability"] = str(meta.get("stability", "medium")).strip()

    def _collect_graph_entity_names(
        self,
        query: str,
        events: list[dict[str, Any]],
    ) -> set[str]:
        """Collect entity names related to query entities via graph and event triples."""
        if self._graph is None or not self._graph.enabled:
            return set()

        query_entities = (
            {e.lower() for e in self._extractor._extract_entities(query)}
            if self._extractor is not None
            else set()
        )
        if not query_entities:
            return set()

        cache_key = frozenset(query_entities)
        if cache_key in self._graph_cache:
            return self._graph_cache[cache_key]

        graph_entity_names: set[str] = set()
        # Collect from event triples
        for evt in events:
            for triple in evt.get("triples") or []:
                subj = str(triple.get("subject", "")).lower()
                obj = str(triple.get("object", "")).lower()
                if subj in query_entities:
                    graph_entity_names.add(obj)
                elif obj in query_entities:
                    graph_entity_names.add(subj)
        # Augment with graph neighbors
        graph_related = self._graph.get_related_entity_names_sync(
            query_entities,
            depth=2,
        )
        result = graph_entity_names | graph_related
        self._graph_cache[cache_key] = result
        return result

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
        from ..graph.entity_classifier import classify_entity_type

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
