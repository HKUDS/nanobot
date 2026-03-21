"""Tests for MemoryRetriever — extracted retrieval read path."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

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
    """When mem0 is enabled, retrieve calls _retrieve_core."""

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
