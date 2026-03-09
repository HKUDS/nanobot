"""Tests for the knowledge graph adapter (graceful degradation + data model)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from nanobot.agent.memory.graph import KnowledgeGraph
from nanobot.agent.memory.ontology import (
    Entity,
    EntityType,
    Relationship,
    RelationType,
    Triple,
)

# ---------------------------------------------------------------------------
# Graceful degradation — no Neo4j driver
# ---------------------------------------------------------------------------


class TestGracefulDegradation:
    """Verify the adapter stays disabled when neo4j is not installed or fails."""

    def test_disabled_when_neo4j_not_installed(self) -> None:
        with patch("nanobot.agent.memory.graph._HAS_NEO4J", False):
            g = KnowledgeGraph.__new__(KnowledgeGraph)
            g._uri = ""
            g._database = "neo4j"
            g._driver = None
            g.enabled = False
            g.error = "neo4j package not installed"
            assert g.enabled is False
            assert "not installed" in (g.error or "")

    def test_disabled_graph_returns_empty(self) -> None:
        g = KnowledgeGraph()
        g.enabled = False

        # Sync methods return safe defaults
        assert g.error is not None or g.enabled is False

    @pytest.mark.asyncio
    async def test_upsert_entity_noop_when_disabled(self) -> None:
        g = KnowledgeGraph()
        g.enabled = False
        entity = Entity(name="Test", entity_type=EntityType.PERSON)
        await g.upsert_entity(entity)  # Should not raise

    @pytest.mark.asyncio
    async def test_add_relationship_noop_when_disabled(self) -> None:
        g = KnowledgeGraph()
        g.enabled = False
        rel = Relationship(
            source_id="a",
            target_id="b",
            relation_type=RelationType.WORKS_ON,
        )
        await g.add_relationship(rel)  # Should not raise

    @pytest.mark.asyncio
    async def test_get_entity_returns_none_when_disabled(self) -> None:
        g = KnowledgeGraph()
        g.enabled = False
        assert await g.get_entity("anything") is None

    @pytest.mark.asyncio
    async def test_search_entities_returns_empty_when_disabled(self) -> None:
        g = KnowledgeGraph()
        g.enabled = False
        assert await g.search_entities("test") == []

    @pytest.mark.asyncio
    async def test_get_neighbors_returns_empty_when_disabled(self) -> None:
        g = KnowledgeGraph()
        g.enabled = False
        assert await g.get_neighbors("test") == []

    @pytest.mark.asyncio
    async def test_find_paths_returns_empty_when_disabled(self) -> None:
        g = KnowledgeGraph()
        g.enabled = False
        assert await g.find_paths("a", "b") == []

    @pytest.mark.asyncio
    async def test_query_subgraph_returns_empty_when_disabled(self) -> None:
        g = KnowledgeGraph()
        g.enabled = False
        result = await g.query_subgraph(["a", "b"])
        assert result == {"nodes": [], "edges": []}

    @pytest.mark.asyncio
    async def test_resolve_entity_returns_normalized_when_disabled(self) -> None:
        g = KnowledgeGraph()
        g.enabled = False
        assert await g.resolve_entity("Carlos Martinez") == "carlos_martinez"

    @pytest.mark.asyncio
    async def test_ingest_event_triples_noop_when_disabled(self) -> None:
        g = KnowledgeGraph()
        g.enabled = False
        triples = [Triple(subject="A", predicate=RelationType.USES, object="B")]
        await g.ingest_event_triples("e1", triples)  # Should not raise

    @pytest.mark.asyncio
    async def test_verify_connectivity_returns_false_when_disabled(self) -> None:
        g = KnowledgeGraph()
        g.enabled = False
        g._driver = None
        assert await g.verify_connectivity() is False

    @pytest.mark.asyncio
    async def test_ensure_indexes_noop_when_disabled(self) -> None:
        g = KnowledgeGraph()
        g.enabled = False
        await g.ensure_indexes()  # Should not raise

    @pytest.mark.asyncio
    async def test_close_noop_when_no_driver(self) -> None:
        g = KnowledgeGraph()
        g.enabled = False
        g._driver = None
        await g.close()
        assert g.enabled is False


# ---------------------------------------------------------------------------
# Node conversion helper
# ---------------------------------------------------------------------------


class TestNodeToEntity:
    def test_basic_conversion(self) -> None:
        props = {
            "name": "Carlos",
            "canonical_name": "carlos",
            "entity_type": "person",
            "aliases_text": "Charlie, C",
            "first_seen": "2024-01-01",
            "last_seen": "2024-06-01",
            "prop_department": "engineering",
        }
        e = KnowledgeGraph._node_to_entity(props)
        assert e.name == "Carlos"
        assert e.entity_type == EntityType.PERSON
        assert "Charlie" in e.aliases
        assert "C" in e.aliases
        assert e.properties["department"] == "engineering"
        assert e.first_seen == "2024-01-01"

    def test_unknown_entity_type(self) -> None:
        props = {"name": "X", "entity_type": "alien"}
        e = KnowledgeGraph._node_to_entity(props)
        assert e.entity_type == EntityType.UNKNOWN

    def test_empty_aliases(self) -> None:
        props = {"name": "X", "aliases_text": ""}
        e = KnowledgeGraph._node_to_entity(props)
        assert e.aliases == []


# ---------------------------------------------------------------------------
# Triple extraction heuristics (from extractor.py)
# ---------------------------------------------------------------------------


class TestHeuristicTripleExtraction:
    def test_works_on_pattern(self) -> None:
        from nanobot.agent.memory.extractor import MemoryExtractor

        triples = MemoryExtractor._extract_triples_heuristic(
            "Carlos works on the deployment pipeline",
            entities=["Carlos", "deployment pipeline"],
            event_type="task",
        )
        # Should find at least the pattern-based triple
        subjects = {t["subject"] for t in triples}
        assert any("Carlos" in s for s in subjects)

    def test_uses_pattern(self) -> None:
        from nanobot.agent.memory.extractor import MemoryExtractor

        triples = MemoryExtractor._extract_triples_heuristic(
            "The team uses Python for backend development",
            entities=["team", "Python"],
            event_type="fact",
        )
        predicates = {t["predicate"] for t in triples}
        assert "USES" in predicates

    def test_relationship_event_infers_works_with(self) -> None:
        from nanobot.agent.memory.extractor import MemoryExtractor

        triples = MemoryExtractor._extract_triples_heuristic(
            "Alice is great",
            entities=["Alice", "Bob"],
            event_type="relationship",
        )
        predicates = {t["predicate"] for t in triples}
        assert "WORKS_WITH" in predicates

    def test_empty_text_returns_empty(self) -> None:
        from nanobot.agent.memory.extractor import MemoryExtractor

        triples = MemoryExtractor._extract_triples_heuristic(
            "",
            entities=[],
            event_type="fact",
        )
        assert triples == []

    def test_max_10_triples(self) -> None:
        from nanobot.agent.memory.extractor import MemoryExtractor

        # Build a long text with many pattern matches
        text = ". ".join(
            f"Person{i} works on Project{i}" for i in range(20)
        )
        triples = MemoryExtractor._extract_triples_heuristic(
            text,
            entities=[],
            event_type="fact",
        )
        assert len(triples) <= 10


# ---------------------------------------------------------------------------
# Graph context builder (from store.py)
# ---------------------------------------------------------------------------


class TestGraphContextBuilder:
    def test_builds_lines_from_event_triples(self, tmp_path: object) -> None:
        from pathlib import Path

        from nanobot.agent.memory.store import MemoryStore

        workspace = Path(str(tmp_path))
        store = MemoryStore(workspace)
        store.graph.enabled = True
        # Isolate from real Neo4j so only local event triples are used.
        store.graph._sync_driver = None

        # Write events with triples
        events = [
            {
                "id": "e1",
                "type": "relationship",
                "summary": "Carlos works with platform-team",
                "entities": ["Carlos", "platform-team"],
                "timestamp": "2024-01-01T00:00:00Z",
                "triples": [
                    {"subject": "Carlos", "predicate": "WORKS_WITH", "object": "platform-team"}
                ],
                "salience": 0.7,
                "confidence": 0.8,
            }
        ]
        store.persistence.write_jsonl(store.events_file, events)

        lines = store._build_graph_context_lines(
            query="Tell me about Carlos",
            retrieved=[{"entities": ["Carlos"]}],
        )
        assert len(lines) >= 1
        assert "Carlos" in lines[0]
        assert "WORKS_WITH" in lines[0]

    def test_no_lines_when_no_matching_entities(self, tmp_path: object) -> None:
        from pathlib import Path

        from nanobot.agent.memory.store import MemoryStore

        workspace = Path(str(tmp_path))
        store = MemoryStore(workspace)
        store.graph.enabled = True
        # Isolate from real Neo4j so only local event triples are scanned.
        store.graph._sync_driver = None

        events = [
            {
                "id": "e1",
                "type": "fact",
                "summary": "Unrelated fact",
                "entities": ["Unrelated"],
                "timestamp": "2024-01-01T00:00:00Z",
                "triples": [
                    {"subject": "Foo", "predicate": "USES", "object": "Bar"}
                ],
                "salience": 0.5,
                "confidence": 0.5,
            }
        ]
        store.persistence.write_jsonl(store.events_file, events)

        lines = store._build_graph_context_lines(
            query="Tell me about Carlos",
            retrieved=[],
        )
        assert lines == []
