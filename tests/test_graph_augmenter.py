"""Tests for GraphAugmenter — entity collection and graph context lines."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from nanobot.memory.read.graph_augmentation import GraphAugmenter

_EXTRACT_ENTITIES_PATH = "nanobot.memory.read.graph_augmentation.extract_entities"


def _make_augmenter(
    *,
    graph_enabled: bool = True,
    events: list[dict[str, Any]] | None = None,
) -> GraphAugmenter:
    """Build a GraphAugmenter with mocked dependencies."""
    graph = MagicMock()
    graph.enabled = graph_enabled
    graph.get_related_entity_names_sync = MagicMock(return_value=set())
    graph.get_triples_for_entities_sync = MagicMock(return_value=[])

    extractor = MagicMock()
    extractor._extract_entities = MagicMock(return_value=[])

    return GraphAugmenter(
        graph=graph,
        extractor=extractor,
        read_events_fn=lambda **kw: events or [],
    )


class TestCollectGraphEntityNames:
    """collect_graph_entity_names collects related entities from graph and triples."""

    def test_returns_empty_when_graph_disabled(self) -> None:
        aug = _make_augmenter(graph_enabled=False)
        result = aug.collect_graph_entity_names("query", [])
        assert result == set()

    def test_returns_empty_when_no_query_entities(self) -> None:
        aug = _make_augmenter()
        with patch(_EXTRACT_ENTITIES_PATH, return_value=[]):
            result = aug.collect_graph_entity_names("query", [])
        assert result == set()

    def test_collects_from_event_triples(self) -> None:
        aug = _make_augmenter()
        with patch(_EXTRACT_ENTITIES_PATH, return_value=["Alice"]):
            events = [
                {
                    "triples": [
                        {"subject": "Alice", "predicate": "knows", "object": "Bob"},
                    ]
                }
            ]
            result = aug.collect_graph_entity_names("query", events)
        assert "bob" in result

    def test_augments_with_graph_neighbors(self) -> None:
        aug = _make_augmenter()
        aug._graph.get_related_entity_names_sync.return_value = {"python", "fastapi"}
        with patch(_EXTRACT_ENTITIES_PATH, return_value=["Web"]):
            result = aug.collect_graph_entity_names("web framework", [])
        assert "python" in result or "fastapi" in result

    def test_cache_prevents_duplicate_traversal(self) -> None:
        aug = _make_augmenter()
        with patch(_EXTRACT_ENTITIES_PATH, return_value=["Alice"]):
            aug.collect_graph_entity_names("query", [])
            aug.collect_graph_entity_names("query", [])
        assert aug._graph.get_related_entity_names_sync.call_count == 1

    def test_reset_cache_allows_fresh_traversal(self) -> None:
        aug = _make_augmenter()
        with patch(_EXTRACT_ENTITIES_PATH, return_value=["Alice"]):
            aug.collect_graph_entity_names("query", [])
            aug.reset_cache()
            aug.collect_graph_entity_names("query", [])
        assert aug._graph.get_related_entity_names_sync.call_count == 2


class TestBuildEntityIndex:
    """build_entity_index collects entities from events into a set."""

    def test_collects_unique_lowercase(self) -> None:
        aug = _make_augmenter()
        events = [
            {"entities": ["Alice", "Bob"]},
            {"entities": ["alice", "Charlie"]},
        ]
        index = aug.build_entity_index(events)
        assert index == {"alice", "bob", "charlie"}

    def test_empty_events(self) -> None:
        aug = _make_augmenter()
        assert aug.build_entity_index([]) == set()


class TestExtractQueryEntities:
    """extract_query_entities matches tokens against entity index."""

    def test_unigram_match(self) -> None:
        aug = _make_augmenter()
        index = {"alice", "bob", "python"}
        matched = aug.extract_query_entities("who is alice", index)
        assert "alice" in matched
        assert "bob" not in matched

    def test_bigram_match(self) -> None:
        aug = _make_augmenter()
        index = {"github actions", "python"}
        matched = aug.extract_query_entities("setup github actions pipeline", index)
        assert "github actions" in matched


class TestBuildGraphContextLines:
    """build_graph_context_lines formats triples as context lines."""

    def test_formats_lines(self) -> None:
        aug = _make_augmenter()
        aug._read_events_fn = lambda **kw: [
            {
                "entities": ["Alice", "Bob"],
                "triples": [
                    {"subject": "Alice", "predicate": "knows", "object": "Bob"},
                ],
            }
        ]
        with (
            patch(_EXTRACT_ENTITIES_PATH, return_value=["Alice"]),
            patch("nanobot.memory.graph.entity_classifier.classify_entity_type") as mock_cls,
        ):
            mock_type = MagicMock()
            mock_type.value = "unknown"
            mock_cls.return_value = mock_type
            lines = aug.build_graph_context_lines("Who is Alice?", [], max_tokens=100)
        assert len(lines) >= 1
        assert "Alice" in lines[0]
        assert "knows" in lines[0]

    def test_empty_when_no_entities(self) -> None:
        aug = _make_augmenter()
        aug._read_events_fn = lambda **kw: []
        with patch(_EXTRACT_ENTITIES_PATH, return_value=[]):
            lines = aug.build_graph_context_lines("random query", [])
        assert lines == []

    def test_respects_token_budget(self) -> None:
        aug = _make_augmenter()
        # Many triples to test budget truncation
        triples = [
            {"subject": "A", "predicate": f"rel_{i}", "object": f"entity_{i}"} for i in range(50)
        ]
        aug._read_events_fn = lambda **kw: [{"entities": ["A"], "triples": triples}]
        with (
            patch(_EXTRACT_ENTITIES_PATH, return_value=["A"]),
            patch("nanobot.memory.graph.entity_classifier.classify_entity_type") as mock_cls,
        ):
            mock_type = MagicMock()
            mock_type.value = "unknown"
            mock_cls.return_value = mock_type
            lines = aug.build_graph_context_lines("query about A", [], max_tokens=10)
        # With max_tokens=10 (40 chars), should be truncated
        assert len(lines) < 50
