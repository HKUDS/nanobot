"""Memory retrieval read path — unified vector + FTS5 + RRF pipeline.

``MemoryRetriever`` orchestrates the retrieval pipeline by delegating to
``RetrievalScorer`` (filter/score/rerank) and ``GraphAugmenter``
(entity collection and graph context).

Pipeline architecture (pipes and filters)::

    Source (vector + FTS5 + RRF) → Graph Augment → Filter → Score → Rerank → Truncate
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

from nanobot.observability.tracing import bind_trace

from .graph_augmentation import GraphAugmenter
from .retrieval_planner import RetrievalPlanner
from .scoring import RetrievalScorer

if TYPE_CHECKING:
    from ..embedder import Embedder
    from ..unified_db import UnifiedMemoryDB


class MemoryRetriever:
    """Orchestrates the full memory retrieval read path.

    Delegates scoring to ``RetrievalScorer`` and graph augmentation to
    ``GraphAugmenter``.  Owns only fusion, metadata enrichment, and
    top-level orchestration.
    """

    def __init__(
        self,
        *,
        scorer: RetrievalScorer,
        graph_aug: GraphAugmenter,
        planner: RetrievalPlanner,
        db: UnifiedMemoryDB | None = None,
        embedder: Embedder | None = None,
    ) -> None:
        self._scorer = scorer
        self._graph_aug = graph_aug
        self._planner = planner
        self._db = db
        self._embedder = embedder

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def retrieve(
        self,
        query: str,
        *,
        top_k: int = 6,
        recency_half_life_days: float | None = None,
        embedding_provider: str | None = None,
    ) -> list[dict[str, Any]]:
        self._graph_aug.reset_cache()
        t0 = time.monotonic()

        # Unified path: vector + FTS5 + RRF when db and embedder are injected
        if self._db is not None and self._embedder is not None:
            return await self._retrieve_unified(
                query,
                top_k=top_k,
                recency_half_life_days=recency_half_life_days,
                t0=t0,
            )

        return []

    # ------------------------------------------------------------------
    # Unified path (vector + FTS5 + RRF)
    # ------------------------------------------------------------------

    async def _retrieve_unified(
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
        assert self._db is not None  # noqa: S101 — guarded by caller
        assert self._embedder is not None  # noqa: S101

        plan = self._planner.plan(query)
        policy = plan.policy
        candidate_k = max(1, min(top_k * int(policy.get("candidate_multiplier", 3)), 60))

        # 1. Embed query
        query_vec = await self._embedder.embed(query)

        # 2. Dual source — DB methods are synchronous; run concurrently via to_thread
        vec_results, fts_results = await asyncio.gather(
            asyncio.to_thread(self._db.search_vector, query_vec, candidate_k),
            asyncio.to_thread(self._db.search_fts, query, candidate_k),
        )

        # 3. Fuse via RRF
        candidates = self._fuse_results(vec_results, fts_results, vector_weight=0.7)

        if not candidates:
            candidates = await asyncio.to_thread(self._db.read_events, limit=candidate_k)
            if not candidates:
                bind_trace().debug(
                    "Memory retrieve source=unified results=0 duration_ms={:.0f}",
                    (time.monotonic() - t0) * 1000,
                )
                return []

        # 4. Enrich metadata
        self._enrich_item_metadata(candidates)

        # 5. Filter
        filtered, _filter_counts = self._scorer.filter_items(candidates, plan)

        # 6. Score
        profile_data = self._scorer.load_profile_scoring_data()
        graph_entities = self._graph_aug.collect_graph_entity_names(
            query, self._graph_aug._read_events_fn()
        )
        scored = self._scorer.score_items(
            filtered,
            plan,
            profile_data,
            graph_entities,
            use_recency=True,
            router_enabled=True,
            type_separation_enabled=True,
        )

        # 7. Rerank
        scored = self._scorer.rerank_items(query, scored)

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
    # Pipeline stage: metadata enrichment
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
