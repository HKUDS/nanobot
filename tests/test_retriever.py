"""Tests for MemoryRetriever — extracted retrieval read path."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from nanobot.agent.memory.retriever import MemoryRetriever


def _make_retriever(
    *,
    mem0_enabled: bool = False,
    rollout: dict[str, Any] | None = None,
    events: list[dict[str, Any]] | None = None,
    graph_enabled: bool = False,
) -> MemoryRetriever:
    """Build a MemoryRetriever with mocked dependencies."""
    mem0 = MagicMock()
    mem0.enabled = mem0_enabled
    mem0.mode = "local"

    graph = MagicMock()
    graph.enabled = graph_enabled
    graph.get_related_entity_names_sync = MagicMock(return_value=set())
    graph.get_triples_for_entities_sync = MagicMock(return_value=[])

    planner = MagicMock()
    plan = MagicMock()
    plan.intent = "general"
    plan.policy = {
        "candidate_multiplier": 3,
        "half_life_days": 60.0,
        "fallback_topics": [],
        "fallback_types": [],
        "type_boost": {},
    }
    plan.include_superseded = False
    plan.routing_hints = {
        "focus_task_decision": False,
        "focus_planning": False,
        "focus_architecture": False,
        "requires_open": False,
        "requires_resolved": False,
    }
    planner.plan = MagicMock(return_value=plan)

    reranker = MagicMock()
    reranker.rerank = MagicMock(side_effect=lambda q, items: items)

    profile_mgr = MagicMock()
    profile_mgr.read_profile = MagicMock(return_value={})
    profile_mgr._meta_section = MagicMock(return_value={})

    extractor = MagicMock()
    extractor._extract_entities = MagicMock(return_value=[])

    return MemoryRetriever(
        mem0=mem0,
        graph=graph,
        planner=planner,
        reranker=reranker,
        profile_mgr=profile_mgr,
        rollout=rollout or {},
        read_events_fn=lambda **kw: events or [],
        extractor=extractor,
    )


def _make_plan(
    *,
    intent: str = "general",
    policy: dict[str, Any] | None = None,
    routing_hints: dict[str, Any] | None = None,
    include_superseded: bool = False,
) -> MagicMock:
    """Build a mock RetrievalPlan."""
    plan = MagicMock()
    plan.intent = intent
    plan.policy = policy or {
        "candidate_multiplier": 3,
        "half_life_days": 60.0,
        "fallback_topics": [],
        "fallback_types": [],
        "type_boost": {},
    }
    plan.include_superseded = include_superseded
    plan.routing_hints = routing_hints or {
        "focus_task_decision": False,
        "focus_planning": False,
        "focus_architecture": False,
        "requires_open": False,
        "requires_resolved": False,
    }
    return plan


class TestRetrieveMem0Disabled:
    """When mem0 is disabled, retrieve uses BM25 local path."""

    def test_returns_local_results(self) -> None:
        events = [
            {
                "id": "e1",
                "type": "fact",
                "summary": "Python is great",
                "timestamp": "2025-01-01T00:00:00Z",
                "entities": [],
                "status": "active",
            }
        ]
        retriever = _make_retriever(events=events)
        with patch(
            "nanobot.agent.memory.retriever._local_retrieve",
            return_value=[
                {
                    "id": "e1",
                    "type": "fact",
                    "summary": "Python is great",
                    "timestamp": "2025-01-01T00:00:00Z",
                    "retrieval_reason": {"score": 0.5},
                    "entities": [],
                }
            ],
        ):
            results = retriever.retrieve("Python", top_k=3)
        assert len(results) == 1
        assert results[0]["id"] == "e1"
        assert "score" in results[0]


class TestRetrieveMem0Enabled:
    """When mem0 is enabled, retrieve calls _run_mem0_pipeline."""

    def test_calls_mem0_search(self) -> None:
        retriever = _make_retriever(mem0_enabled=True)
        retriever._mem0.search = MagicMock(
            return_value=(
                [
                    {
                        "id": "m1",
                        "type": "fact",
                        "summary": "Test memory",
                        "timestamp": "2025-01-01T00:00:00Z",
                        "score": 0.8,
                        "stability": "high",
                        "entities": [],
                    }
                ],
                {
                    "source_vector": 1,
                    "source_get_all": 0,
                    "source_history": 0,
                    "rejected_blob_like": 0,
                },
            )
        )
        results = retriever.retrieve("test", top_k=3)
        assert len(results) == 1
        assert results[0]["id"] == "m1"
        retriever._mem0.search.assert_called_once()


class TestRetrieveEmptyResults:
    """Empty mem0 results return empty list."""

    def test_empty_mem0(self) -> None:
        retriever = _make_retriever(mem0_enabled=True)
        retriever._mem0.search = MagicMock(
            return_value=(
                [],
                {
                    "source_vector": 0,
                    "source_get_all": 0,
                    "source_history": 0,
                    "rejected_blob_like": 0,
                },
            )
        )
        results = retriever.retrieve("anything", top_k=3)
        assert results == []


class TestRetrieveWithGraphAugmentation:
    """Graph-enabled retrieval expands query with related entities."""

    def test_graph_terms_expand_query(self) -> None:
        retriever = _make_retriever(graph_enabled=True)
        retriever._graph.get_related_entity_names_sync = MagicMock(
            return_value={"python", "fastapi"}
        )
        with patch(
            "nanobot.agent.memory.retriever._local_retrieve",
            return_value=[],
        ) as mock_local:
            retriever.retrieve("web framework", top_k=3)
        # The augmented query should have been passed to _local_retrieve
        call_args = mock_local.call_args
        query_arg = call_args[0][1]
        assert "python" in query_arg or "fastapi" in query_arg


class TestBuildGraphContextLines:
    """_build_graph_context_lines formats triples correctly."""

    def test_formats_graph_lines(self) -> None:
        retriever = _make_retriever()
        retriever._extractor._extract_entities = MagicMock(return_value=["Alice"])
        retriever._read_events_fn = lambda **kw: [
            {
                "entities": ["Alice", "Bob"],
                "triples": [
                    {"subject": "Alice", "predicate": "knows", "object": "Bob"},
                ],
            }
        ]
        with patch("nanobot.agent.memory.ontology.classify_entity_type") as mock_classify:
            mock_type = MagicMock()
            mock_type.value = "unknown"
            mock_classify.return_value = mock_type
            lines = retriever._build_graph_context_lines("Who is Alice?", [], max_tokens=100)
        assert len(lines) >= 1
        assert "Alice" in lines[0]
        assert "knows" in lines[0]
        assert "Bob" in lines[0]


class TestExtractQueryEntities:
    """_extract_query_entities matches tokens against entity index."""

    def test_extracts_unigrams(self) -> None:
        retriever = _make_retriever()
        entity_index = {"alice", "bob", "python"}
        matched = retriever._extract_query_entities("who is alice", entity_index)
        assert "alice" in matched
        assert "bob" not in matched

    def test_extracts_bigrams(self) -> None:
        retriever = _make_retriever()
        entity_index = {"github actions", "python"}
        matched = retriever._extract_query_entities("setup github actions pipeline", entity_index)
        assert "github actions" in matched


class TestRetrieveAppliesTypeBoost:
    """Type boosts from policy affect final scores."""

    def test_type_boost_increases_score(self) -> None:
        retriever = _make_retriever()
        plan = retriever._planner.plan.return_value
        plan.policy["type_boost"] = {"semantic": 0.1}

        with patch(
            "nanobot.agent.memory.retriever._local_retrieve",
            return_value=[
                {
                    "id": "e1",
                    "type": "fact",
                    "summary": "A semantic fact",
                    "memory_type": "semantic",
                    "timestamp": "2025-01-01T00:00:00Z",
                    "retrieval_reason": {"score": 0.5},
                    "entities": [],
                    "stability": "medium",
                    "metadata": {"memory_type": "semantic"},
                },
                {
                    "id": "e2",
                    "type": "task",
                    "summary": "An episodic task",
                    "memory_type": "episodic",
                    "timestamp": "2025-01-01T00:00:00Z",
                    "retrieval_reason": {"score": 0.5},
                    "entities": [],
                    "stability": "medium",
                    "metadata": {"memory_type": "episodic"},
                },
            ],
        ):
            results = retriever.retrieve("test", top_k=10)

        # The semantic item should get the 0.1 boost, making its score higher
        scores = {r["id"]: r["score"] for r in results}
        assert scores["e1"] > scores["e2"]


# ======================================================================
# Pipeline stage unit tests
# ======================================================================


class TestAugmentQueryWithGraph:
    """_augment_query_with_graph expands query with entity names."""

    def test_expands_with_entity_names(self) -> None:
        retriever = _make_retriever(graph_enabled=True)
        retriever._graph.get_related_entity_names_sync = MagicMock(
            return_value={"python", "fastapi", "web"}
        )
        augmented, extra = retriever._augment_query_with_graph("web framework")
        # "web" is already a keyword, so extra should contain python and fastapi
        assert "python" in augmented or "fastapi" in augmented
        assert len(extra) > 0

    def test_no_graph_returns_original(self) -> None:
        retriever = _make_retriever(graph_enabled=False)
        # graph is not None but disabled
        retriever._graph.enabled = False
        augmented, extra = retriever._augment_query_with_graph("hello world")
        assert augmented == "hello world"
        assert extra == set()

    def test_no_graph_object_returns_original(self) -> None:
        retriever = _make_retriever()
        retriever._graph = None
        augmented, extra = retriever._augment_query_with_graph("test query")
        assert augmented == "test query"
        assert extra == set()


class TestFilterItemsByIntent:
    """_filter_items filters items based on routing hints and intent."""

    def test_focus_task_decision_filters_non_tasks(self) -> None:
        retriever = _make_retriever()
        plan = _make_plan(
            routing_hints={
                "focus_task_decision": True,
                "focus_planning": False,
                "focus_architecture": False,
                "requires_open": False,
                "requires_resolved": False,
            }
        )
        items = [
            {"id": "t1", "type": "task", "summary": "Build feature", "topic": "task_progress"},
            {"id": "f1", "type": "fact", "summary": "Python is great", "topic": "language"},
        ]
        filtered, counts = retriever._filter_items(items, plan)
        assert len(filtered) == 1
        assert filtered[0]["id"] == "t1"

    def test_constraints_lookup_filters_non_semantic(self) -> None:
        retriever = _make_retriever()
        plan = _make_plan(intent="constraints_lookup")
        items = [
            {
                "id": "c1",
                "type": "constraint",
                "summary": "Must not use eval",
                "topic": "constraint",
                "metadata": {"memory_type": "semantic"},
            },
            {
                "id": "e1",
                "type": "task",
                "summary": "Deployed the app",
                "topic": "task_progress",
                "metadata": {"memory_type": "episodic"},
            },
        ]
        filtered, _ = retriever._filter_items(items, plan)
        assert len(filtered) == 1
        assert filtered[0]["id"] == "c1"

    def test_reflection_filtered_when_disabled(self) -> None:
        retriever = _make_retriever()
        plan = _make_plan()
        items = [
            {
                "id": "r1",
                "type": "reflection",
                "summary": "I noticed a pattern",
                "topic": "meta",
                "metadata": {"memory_type": "reflection"},
            },
        ]
        filtered, counts = retriever._filter_items(items, plan, reflection_enabled=False)
        assert len(filtered) == 0
        assert counts["reflection_filtered_non_reflection_intent"] == 1

    def test_general_intent_passes_all(self) -> None:
        retriever = _make_retriever()
        plan = _make_plan()
        items = [
            {"id": "f1", "type": "fact", "summary": "Fact one", "topic": "general"},
            {"id": "f2", "type": "fact", "summary": "Fact two", "topic": "general"},
        ]
        filtered, _ = retriever._filter_items(items, plan)
        assert len(filtered) == 2


class TestScoreItemsRecencyBoost:
    """_score_items applies recency boost to recent items."""

    def test_recent_items_score_higher(self) -> None:
        retriever = _make_retriever()
        plan = _make_plan(
            policy={
                "candidate_multiplier": 3,
                "half_life_days": 30.0,
                "fallback_topics": [],
                "fallback_types": [],
                "type_boost": {},
            }
        )
        profile_data = {
            "profile": {},
            "resolved_keep_new_old": {k: set() for k in MemoryRetriever.PROFILE_KEYS},
            "resolved_keep_new_new": {k: set() for k in MemoryRetriever.PROFILE_KEYS},
        }
        items = [
            {
                "id": "old",
                "type": "fact",
                "summary": "Old fact",
                "memory_type": "semantic",
                "timestamp": "2020-01-01T00:00:00Z",
                "score": 0.5,
                "stability": "medium",
                "entities": [],
            },
            {
                "id": "new",
                "type": "fact",
                "summary": "New fact",
                "memory_type": "semantic",
                "timestamp": "2026-03-21T00:00:00Z",
                "score": 0.5,
                "stability": "medium",
                "entities": [],
            },
        ]
        scored = retriever._score_items(
            items,
            plan,
            profile_data,
            set(),
            use_recency=True,
            router_enabled=True,
            type_separation_enabled=True,
        )
        scores = {s["id"]: s["score"] for s in scored}
        assert scores["new"] > scores["old"]


class TestScoreItemsTypeBoost:
    """_score_items applies type boost from policy."""

    def test_semantic_boosted_over_episodic(self) -> None:
        retriever = _make_retriever()
        plan = _make_plan(
            policy={
                "candidate_multiplier": 3,
                "half_life_days": 60.0,
                "fallback_topics": [],
                "fallback_types": [],
                "type_boost": {"semantic": 0.15, "episodic": 0.0},
            }
        )
        profile_data = {
            "profile": {},
            "resolved_keep_new_old": {k: set() for k in MemoryRetriever.PROFILE_KEYS},
            "resolved_keep_new_new": {k: set() for k in MemoryRetriever.PROFILE_KEYS},
        }
        items = [
            {
                "id": "sem",
                "type": "fact",
                "summary": "Semantic item",
                "memory_type": "semantic",
                "timestamp": "2025-01-01T00:00:00Z",
                "score": 0.5,
                "stability": "medium",
                "entities": [],
            },
            {
                "id": "epi",
                "type": "task",
                "summary": "Episodic item",
                "memory_type": "episodic",
                "timestamp": "2025-01-01T00:00:00Z",
                "score": 0.5,
                "stability": "medium",
                "entities": [],
            },
        ]
        scored = retriever._score_items(
            items,
            plan,
            profile_data,
            set(),
            use_recency=False,
            router_enabled=True,
            type_separation_enabled=True,
        )
        scores = {s["id"]: s["score"] for s in scored}
        assert scores["sem"] > scores["epi"]


class TestScoreItemsUnified:
    """_score_items applies the same formula for BM25 and mem0 candidates."""

    def test_same_adjustments_different_bases(self) -> None:
        retriever = _make_retriever()
        plan = _make_plan(
            policy={
                "candidate_multiplier": 3,
                "half_life_days": 60.0,
                "fallback_topics": [],
                "fallback_types": [],
                "type_boost": {"semantic": 0.1},
            }
        )
        profile_data = {
            "profile": {},
            "resolved_keep_new_old": {k: set() for k in MemoryRetriever.PROFILE_KEYS},
            "resolved_keep_new_new": {k: set() for k in MemoryRetriever.PROFILE_KEYS},
        }
        # BM25 candidate: base from retrieval_reason
        bm25_item = {
            "id": "bm25",
            "type": "fact",
            "summary": "BM25 result",
            "memory_type": "semantic",
            "timestamp": "2025-01-01T00:00:00Z",
            "stability": "high",
            "entities": [],
            "retrieval_reason": {"score": 0.6},
        }
        # mem0 candidate: base from score field
        mem0_item = {
            "id": "mem0",
            "type": "fact",
            "summary": "mem0 result",
            "memory_type": "semantic",
            "timestamp": "2025-01-01T00:00:00Z",
            "score": 0.7,
            "stability": "high",
            "entities": [],
        }
        bm25_scored = retriever._score_items(
            [bm25_item],
            plan,
            profile_data,
            set(),
            use_recency=False,
            router_enabled=True,
            type_separation_enabled=True,
        )
        mem0_scored = retriever._score_items(
            [mem0_item],
            plan,
            profile_data,
            set(),
            use_recency=True,
            router_enabled=True,
            type_separation_enabled=True,
        )
        # Both should have type_boost=0.1 and stability_boost=0.03
        bm25_reason = bm25_scored[0]["retrieval_reason"]
        mem0_reason = mem0_scored[0]["retrieval_reason"]
        assert bm25_reason["type_boost"] == pytest.approx(0.1)
        assert mem0_reason["type_boost"] == pytest.approx(0.1)
        assert bm25_reason["stability_boost"] == pytest.approx(0.03)
        assert mem0_reason["stability_boost"] == pytest.approx(0.03)


class TestRerankItemsEnabled:
    """_rerank_items calls cross-encoder when enabled."""

    def test_reranker_called(self) -> None:
        retriever = _make_retriever(rollout={"reranker_mode": "enabled"})
        items = [
            {"id": "a", "score": 0.5, "summary": "Item A"},
            {"id": "b", "score": 0.3, "summary": "Item B"},
        ]
        reranked = retriever._rerank_items("test query", items)
        retriever._reranker.rerank.assert_called_once_with("test query", items)
        assert len(reranked) == 2


class TestRerankItemsDisabled:
    """_rerank_items passes through when disabled."""

    def test_passthrough(self) -> None:
        retriever = _make_retriever(rollout={"reranker_mode": "disabled"})
        items = [
            {"id": "a", "score": 0.5, "summary": "Item A"},
        ]
        result = retriever._rerank_items("test query", items)
        retriever._reranker.rerank.assert_not_called()
        assert result is items
