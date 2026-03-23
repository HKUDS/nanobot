"""Tests for the knowledge graph adapter (networkx + JSON persistence)."""

from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.agent.memory.graph import KnowledgeGraph
from nanobot.agent.memory.ontology_types import (
    Entity,
    EntityType,
    Relationship,
    RelationType,
    Triple,
)

# ---------------------------------------------------------------------------
# Graceful degradation — workspace=None (disabled)
# ---------------------------------------------------------------------------


class TestGracefulDegradation:
    """Verify the adapter stays disabled when no workspace is provided."""

    def test_disabled_when_no_workspace(self) -> None:
        g = KnowledgeGraph()
        assert g.enabled is False

    def test_enabled_when_workspace_provided(self, tmp_path: Path) -> None:
        g = KnowledgeGraph(workspace=tmp_path)
        assert g.enabled is True

    async def test_upsert_entity_noop_when_disabled(self) -> None:
        g = KnowledgeGraph()
        entity = Entity(name="Test", entity_type=EntityType.PERSON)
        await g.upsert_entity(entity)  # Should not raise

    async def test_add_relationship_noop_when_disabled(self) -> None:
        g = KnowledgeGraph()
        rel = Relationship(
            source_id="a",
            target_id="b",
            relation_type=RelationType.WORKS_ON,
        )
        await g.add_relationship(rel)  # Should not raise

    async def test_get_entity_returns_none_when_disabled(self) -> None:
        g = KnowledgeGraph()
        assert await g.get_entity("anything") is None

    async def test_search_entities_returns_empty_when_disabled(self) -> None:
        g = KnowledgeGraph()
        assert await g.search_entities("test") == []

    async def test_get_neighbors_returns_empty_when_disabled(self) -> None:
        g = KnowledgeGraph()
        assert await g.get_neighbors("test") == []

    async def test_find_paths_returns_empty_when_disabled(self) -> None:
        g = KnowledgeGraph()
        assert await g.find_paths("a", "b") == []

    async def test_query_subgraph_returns_empty_when_disabled(self) -> None:
        g = KnowledgeGraph()
        result = await g.query_subgraph(["a", "b"])
        assert result == {"nodes": [], "edges": []}

    async def test_resolve_entity_returns_normalized_when_disabled(self) -> None:
        g = KnowledgeGraph()
        assert await g.resolve_entity("Carlos Martinez") == "carlos_martinez"

    async def test_ingest_event_triples_noop_when_disabled(self) -> None:
        g = KnowledgeGraph()
        triples = [Triple(subject="A", predicate=RelationType.USES, object="B")]
        await g.ingest_event_triples("e1", triples)  # Should not raise

    async def test_verify_connectivity_returns_false_when_disabled(self) -> None:
        g = KnowledgeGraph()
        assert await g.verify_connectivity() is False

    async def test_ensure_indexes_noop_when_disabled(self) -> None:
        g = KnowledgeGraph()
        await g.ensure_indexes()  # Should not raise

    async def test_close_noop_when_disabled(self) -> None:
        g = KnowledgeGraph()
        await g.close()
        assert g.enabled is False

    def test_sync_helpers_return_empty_when_disabled(self) -> None:
        g = KnowledgeGraph()
        assert g.get_related_entity_names_sync({"Carlos"}) == set()
        assert g.get_triples_for_entities_sync({"Carlos"}) == []


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
# Networkx graph operations
# ---------------------------------------------------------------------------


class TestNetworkxGraphOperations:
    """Test actual graph operations with networkx backend."""

    @pytest.fixture()
    def graph(self, tmp_path: Path) -> KnowledgeGraph:
        return KnowledgeGraph(workspace=tmp_path)

    async def test_upsert_and_get_entity(self, graph: KnowledgeGraph) -> None:
        entity = Entity(
            name="Carlos",
            entity_type=EntityType.PERSON,
            aliases=["Charlie"],
            first_seen="2024-01-01",
            last_seen="2024-06-01",
        )
        await graph.upsert_entity(entity)
        result = await graph.get_entity("Carlos")
        assert result is not None
        assert result.name == "Carlos"
        assert result.entity_type == EntityType.PERSON
        assert "Charlie" in result.aliases

    async def test_upsert_merges_aliases(self, graph: KnowledgeGraph) -> None:
        e1 = Entity(name="Carlos", entity_type=EntityType.PERSON, aliases=["Charlie"])
        await graph.upsert_entity(e1)
        e2 = Entity(name="Carlos", entity_type=EntityType.PERSON, aliases=["C"])
        await graph.upsert_entity(e2)
        result = await graph.get_entity("Carlos")
        assert result is not None
        assert "Charlie" in result.aliases
        assert "C" in result.aliases

    async def test_upsert_preserves_first_seen(self, graph: KnowledgeGraph) -> None:
        e1 = Entity(
            name="Carlos",
            entity_type=EntityType.PERSON,
            first_seen="2024-01-01",
            last_seen="2024-06-01",
        )
        await graph.upsert_entity(e1)
        e2 = Entity(
            name="Carlos",
            entity_type=EntityType.PERSON,
            first_seen="2024-06-01",
            last_seen="2024-12-01",
        )
        await graph.upsert_entity(e2)
        result = await graph.get_entity("Carlos")
        assert result is not None
        assert result.first_seen == "2024-01-01"
        assert result.last_seen == "2024-12-01"

    async def test_add_relationship(self, graph: KnowledgeGraph) -> None:
        await graph.upsert_entity(Entity(name="Carlos", entity_type=EntityType.PERSON))
        await graph.upsert_entity(Entity(name="Nanobot", entity_type=EntityType.SYSTEM))
        rel = Relationship(
            source_id="Carlos",
            target_id="Nanobot",
            relation_type=RelationType.WORKS_ON,
            confidence=0.9,
            source_event_id="e1",
            timestamp="2024-01-01",
        )
        await graph.add_relationship(rel)
        neighbors = await graph.get_neighbors("Carlos")
        assert len(neighbors) == 1
        assert neighbors[0]["relation"] == "WORKS_ON"
        assert neighbors[0]["confidence"] == 0.9

    async def test_relationship_confidence_update(self, graph: KnowledgeGraph) -> None:
        rel1 = Relationship(
            source_id="Carlos",
            target_id="Nanobot",
            relation_type=RelationType.WORKS_ON,
            confidence=0.5,
        )
        await graph.add_relationship(rel1)
        rel2 = Relationship(
            source_id="Carlos",
            target_id="Nanobot",
            relation_type=RelationType.WORKS_ON,
            confidence=0.9,
        )
        await graph.add_relationship(rel2)
        neighbors = await graph.get_neighbors("Carlos")
        assert neighbors[0]["confidence"] == 0.9

    async def test_get_entity_by_alias(self, graph: KnowledgeGraph) -> None:
        entity = Entity(
            name="Carlos",
            entity_type=EntityType.PERSON,
            aliases=["Charlie"],
        )
        await graph.upsert_entity(entity)
        result = await graph.get_entity("Charlie")
        assert result is not None
        assert result.name == "Carlos"

    async def test_search_entities(self, graph: KnowledgeGraph) -> None:
        await graph.upsert_entity(Entity(name="Carlos", entity_type=EntityType.PERSON))
        await graph.upsert_entity(Entity(name="Nanobot", entity_type=EntityType.SYSTEM))
        await graph.upsert_entity(Entity(name="Python", entity_type=EntityType.TECHNOLOGY))

        results = await graph.search_entities("carlos")
        assert len(results) == 1
        assert results[0].name == "Carlos"

    async def test_search_entities_with_type_filter(self, graph: KnowledgeGraph) -> None:
        await graph.upsert_entity(Entity(name="Carlos", entity_type=EntityType.PERSON))
        await graph.upsert_entity(Entity(name="Python", entity_type=EntityType.TECHNOLOGY))

        results = await graph.search_entities("", entity_type=EntityType.PERSON, limit=10)
        # Empty query won't match anything via substring
        assert all(r.entity_type == EntityType.PERSON for r in results)

    async def test_get_neighbors_with_depth(self, graph: KnowledgeGraph) -> None:
        for name in ("A", "B", "C"):
            await graph.upsert_entity(Entity(name=name, entity_type=EntityType.UNKNOWN))
        await graph.add_relationship(
            Relationship(
                source_id="A",
                target_id="B",
                relation_type=RelationType.WORKS_WITH,
            )
        )
        await graph.add_relationship(
            Relationship(
                source_id="B",
                target_id="C",
                relation_type=RelationType.WORKS_WITH,
            )
        )

        # depth=1: only direct neighbors
        n1 = await graph.get_neighbors("A", depth=1)
        targets = {e["target"] for e in n1}
        assert "B" in targets

        # depth=2: should reach C
        n2 = await graph.get_neighbors("A", depth=2)
        all_nodes = set()
        for e in n2:
            all_nodes.add(e["source"])
            all_nodes.add(e["target"])
        assert "C" in all_nodes

    async def test_get_neighbors_with_relation_filter(self, graph: KnowledgeGraph) -> None:
        await graph.add_relationship(
            Relationship(
                source_id="A",
                target_id="B",
                relation_type=RelationType.WORKS_WITH,
            )
        )
        await graph.add_relationship(
            Relationship(
                source_id="A",
                target_id="C",
                relation_type=RelationType.USES,
            )
        )
        neighbors = await graph.get_neighbors("A", relation_types=["WORKS_WITH"])
        assert len(neighbors) == 1
        assert neighbors[0]["target"] == "B"

    async def test_find_paths(self, graph: KnowledgeGraph) -> None:
        for name in ("A", "B", "C"):
            await graph.upsert_entity(Entity(name=name, entity_type=EntityType.UNKNOWN))
        await graph.add_relationship(
            Relationship(
                source_id="A",
                target_id="B",
                relation_type=RelationType.WORKS_WITH,
            )
        )
        await graph.add_relationship(
            Relationship(
                source_id="B",
                target_id="C",
                relation_type=RelationType.USES,
            )
        )
        paths = await graph.find_paths("A", "C", max_depth=3)
        assert len(paths) >= 1
        # Path should go A -> B -> C
        assert paths[0][0]["source"] == "A"
        assert paths[0][-1]["target"] == "C"

    async def test_find_paths_no_path(self, graph: KnowledgeGraph) -> None:
        await graph.upsert_entity(Entity(name="A", entity_type=EntityType.UNKNOWN))
        await graph.upsert_entity(Entity(name="B", entity_type=EntityType.UNKNOWN))
        paths = await graph.find_paths("A", "B")
        assert paths == []

    async def test_query_subgraph(self, graph: KnowledgeGraph) -> None:
        await graph.add_relationship(
            Relationship(
                source_id="A",
                target_id="B",
                relation_type=RelationType.WORKS_WITH,
            )
        )
        await graph.add_relationship(
            Relationship(
                source_id="C",
                target_id="D",
                relation_type=RelationType.USES,
            )
        )
        sub = await graph.query_subgraph(["A", "C"], depth=1)
        assert len(sub["nodes"]) >= 2
        assert len(sub["edges"]) >= 2

    async def test_resolve_entity(self, graph: KnowledgeGraph) -> None:
        await graph.upsert_entity(Entity(name="Carlos M", entity_type=EntityType.PERSON))
        resolved = await graph.resolve_entity("Carlos M")
        assert resolved == "carlos_m"

    async def test_resolve_entity_not_found(self, graph: KnowledgeGraph) -> None:
        resolved = await graph.resolve_entity("Unknown Person")
        assert resolved == "unknown_person"

    async def test_ingest_event_triples(self, graph: KnowledgeGraph) -> None:
        triples = [
            Triple(
                subject="Carlos",
                predicate=RelationType.WORKS_ON,
                object="Nanobot",
                confidence=0.9,
            ),
        ]
        await graph.ingest_event_triples("e1", triples, timestamp="2024-01-01")
        entity = await graph.get_entity("Carlos")
        assert entity is not None
        neighbors = await graph.get_neighbors("Carlos")
        assert len(neighbors) >= 1

    async def test_get_related_entity_names_sync(self, graph: KnowledgeGraph) -> None:
        await graph.add_relationship(
            Relationship(
                source_id="Carlos",
                target_id="Team",
                relation_type=RelationType.WORKS_WITH,
            )
        )
        related = graph.get_related_entity_names_sync({"carlos"}, depth=1)
        assert "team" in related

    async def test_get_triples_for_entities_sync(self, graph: KnowledgeGraph) -> None:
        await graph.add_relationship(
            Relationship(
                source_id="Carlos",
                target_id="Team",
                relation_type=RelationType.WORKS_WITH,
            )
        )
        triples = graph.get_triples_for_entities_sync({"carlos"})
        assert len(triples) >= 1
        subjects = {t[0] for t in triples}
        assert "Carlos" in subjects or "carlos" in subjects

    async def test_depth_clamping(self, graph: KnowledgeGraph) -> None:
        """Depth is clamped to [1, 5] for neighbors and [1, 5] for paths."""
        await graph.upsert_entity(Entity(name="A", entity_type=EntityType.UNKNOWN))
        # depth=9 should be clamped to 5 — should not raise
        await graph.get_neighbors("A", depth=9)
        await graph.find_paths("A", "B", max_depth=10)

    async def test_verify_connectivity_when_enabled(self, graph: KnowledgeGraph) -> None:
        assert await graph.verify_connectivity() is True

    async def test_close_saves(self, graph: KnowledgeGraph) -> None:
        await graph.upsert_entity(Entity(name="Test", entity_type=EntityType.PERSON))
        await graph.close()
        assert graph._json_path is not None
        assert graph._json_path.exists()


# ---------------------------------------------------------------------------
# JSON persistence round-trip
# ---------------------------------------------------------------------------


class TestJsonPersistence:
    async def test_save_and_load_roundtrip(self, tmp_path: Path) -> None:
        g1 = KnowledgeGraph(workspace=tmp_path)
        await g1.upsert_entity(
            Entity(
                name="Carlos",
                entity_type=EntityType.PERSON,
                aliases=["Charlie"],
                first_seen="2024-01-01",
                last_seen="2024-06-01",
            )
        )
        await g1.add_relationship(
            Relationship(
                source_id="Carlos",
                target_id="Nanobot",
                relation_type=RelationType.WORKS_ON,
                confidence=0.9,
                source_event_id="e1",
                timestamp="2024-01-01",
            )
        )
        await g1.close()

        # Load into a new instance
        g2 = KnowledgeGraph(workspace=tmp_path)
        entity = await g2.get_entity("Carlos")
        assert entity is not None
        assert entity.name == "Carlos"
        assert "Charlie" in entity.aliases

        neighbors = await g2.get_neighbors("Carlos")
        assert len(neighbors) >= 1
        assert neighbors[0]["relation"] == "WORKS_ON"

    async def test_load_nonexistent_file(self, tmp_path: Path) -> None:
        """First run — no JSON file yet — should start empty."""
        g = KnowledgeGraph(workspace=tmp_path)
        assert g.enabled is True
        assert len(g._graph.nodes) == 0

    async def test_corrupted_json_handled(self, tmp_path: Path) -> None:
        """Corrupted JSON file should be handled gracefully."""
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        (mem_dir / "knowledge_graph.json").write_text("NOT VALID JSON")
        g = KnowledgeGraph(workspace=tmp_path)
        # Should not crash; graph starts empty
        assert g.enabled is True
        assert len(g._graph.nodes) == 0


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

        text = ". ".join(f"Person{i} works on Project{i}" for i in range(20))
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
    def test_builds_lines_from_event_triples(self, tmp_path: Path) -> None:
        from nanobot.agent.memory.store import MemoryStore

        workspace = tmp_path
        store = MemoryStore(workspace)
        store.graph.enabled = True

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

        lines = store.retriever._build_graph_context_lines(
            query="Tell me about Carlos",
            retrieved=[{"entities": ["Carlos"]}],
        )
        assert len(lines) >= 1
        assert "Carlos" in lines[0]
        assert "WORKS_WITH" in lines[0]

    def test_no_lines_when_no_matching_entities(self, tmp_path: Path) -> None:
        from nanobot.agent.memory.store import MemoryStore

        workspace = tmp_path
        store = MemoryStore(workspace)
        store.graph.enabled = True

        events = [
            {
                "id": "e1",
                "type": "fact",
                "summary": "Unrelated fact",
                "entities": ["Unrelated"],
                "timestamp": "2024-01-01T00:00:00Z",
                "triples": [{"subject": "Foo", "predicate": "USES", "object": "Bar"}],
                "salience": 0.5,
                "confidence": 0.5,
            }
        ]
        store.persistence.write_jsonl(store.events_file, events)

        lines = store.retriever._build_graph_context_lines(
            query="Tell me about Carlos",
            retrieved=[],
        )
        assert lines == []
