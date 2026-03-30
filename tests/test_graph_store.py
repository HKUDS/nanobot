"""Tests for GraphStore -- entity/edge CRUD and BFS traversal."""

from __future__ import annotations

from pathlib import Path
from typing import Generator

import pytest

from nanobot.memory.db import GraphStore, MemoryDatabase


@pytest.fixture()
def db(tmp_path: Path) -> Generator[MemoryDatabase, None, None]:
    d = MemoryDatabase(tmp_path / "test.db", dims=4)
    yield d
    d.close()


@pytest.fixture()
def store(db: MemoryDatabase) -> GraphStore:
    return db.graph_store


class TestEntityCRUD:
    def test_upsert_and_get(self, store: GraphStore) -> None:
        store.upsert_entity("Python", type="technology", first_seen="2026-01-01")
        entity = store.get_entity("Python")
        assert entity is not None
        assert entity["name"] == "Python"
        assert entity["type"] == "technology"

    def test_get_missing_returns_none(self, store: GraphStore) -> None:
        assert store.get_entity("nonexistent") is None

    def test_upsert_updates_existing(self, store: GraphStore) -> None:
        store.upsert_entity("Python", type="language")
        store.upsert_entity("Python", type="technology", last_seen="2026-03-30")
        entity = store.get_entity("Python")
        assert entity is not None
        assert entity["type"] == "technology"

    def test_search_entities_by_name(self, store: GraphStore) -> None:
        store.upsert_entity("Python", type="language")
        store.upsert_entity("JavaScript", type="language")
        results = store.search_entities("Pyth", limit=10)
        assert len(results) == 1
        assert results[0]["name"] == "Python"

    def test_search_entities_by_alias(self, store: GraphStore) -> None:
        store.upsert_entity("Python", aliases="py,python3")
        results = store.search_entities("python3", limit=10)
        assert len(results) == 1

    def test_upsert_with_all_fields(self, store: GraphStore) -> None:
        store.upsert_entity(
            "Nanobot",
            type="project",
            aliases="nb,nanobot-framework",
            properties='{"language": "python", "version": 42}',
            first_seen="2025-01-01",
            last_seen="2026-03-30",
        )
        entity = store.get_entity("Nanobot")
        assert entity is not None
        assert entity["aliases"] == "nb,nanobot-framework"
        assert entity["properties"] == '{"language": "python", "version": 42}'
        assert entity["first_seen"] == "2025-01-01"

    def test_search_empty_query(self, store: GraphStore) -> None:
        store.upsert_entity("Alpha")
        results = store.search_entities("", limit=10)
        # Empty string matches everything via LIKE '%%'
        assert len(results) >= 1


class TestEdgeCRUD:
    def test_add_and_get_edges_from(self, store: GraphStore) -> None:
        store.upsert_entity("Alice", type="person")
        store.upsert_entity("ProjectX", type="project")
        store.add_edge("Alice", "ProjectX", relation="WORKS_ON")
        edges = store.get_edges_from("Alice")
        assert len(edges) == 1
        assert edges[0]["target"] == "ProjectX"
        assert edges[0]["relation"] == "WORKS_ON"

    def test_get_edges_to(self, store: GraphStore) -> None:
        store.upsert_entity("Alice", type="person")
        store.upsert_entity("ProjectX", type="project")
        store.add_edge("Alice", "ProjectX", relation="WORKS_ON")
        edges = store.get_edges_to("ProjectX")
        assert len(edges) == 1
        assert edges[0]["source"] == "Alice"

    def test_edge_confidence_takes_max(self, store: GraphStore) -> None:
        store.upsert_entity("A")
        store.upsert_entity("B")
        store.add_edge("A", "B", relation="R", confidence=0.5)
        store.add_edge("A", "B", relation="R", confidence=0.9)
        edges = store.get_edges_from("A")
        assert edges[0]["confidence"] == 0.9

    def test_edge_confidence_does_not_decrease(self, store: GraphStore) -> None:
        store.upsert_entity("A")
        store.upsert_entity("B")
        store.add_edge("A", "B", relation="R", confidence=0.9)
        store.add_edge("A", "B", relation="R", confidence=0.3)
        edges = store.get_edges_from("A")
        assert edges[0]["confidence"] == 0.9

    def test_add_edge_with_all_fields(self, store: GraphStore) -> None:
        store.upsert_entity("X")
        store.upsert_entity("Y")
        store.add_edge(
            "X",
            "Y",
            relation="DEPENDS_ON",
            confidence=0.85,
            event_id="evt-123",
            timestamp="2026-03-30T10:00:00Z",
        )
        edges = store.get_edges_from("X")
        assert len(edges) == 1
        assert edges[0]["event_id"] == "evt-123"
        assert edges[0]["timestamp"] == "2026-03-30T10:00:00Z"

    def test_get_edges_from_empty(self, store: GraphStore) -> None:
        assert store.get_edges_from("nobody") == []

    def test_get_edges_to_empty(self, store: GraphStore) -> None:
        assert store.get_edges_to("nobody") == []


class TestBFSTraversal:
    def test_get_neighbors_depth_1(self, store: GraphStore) -> None:
        store.upsert_entity("A")
        store.upsert_entity("B")
        store.upsert_entity("C")
        store.add_edge("A", "B", relation="KNOWS")
        store.add_edge("B", "C", relation="KNOWS")
        neighbors = store.get_neighbors("A", depth=1)
        names = {n["name"] for n in neighbors}
        assert "B" in names
        assert "C" not in names  # depth 1 only reaches B

    def test_get_neighbors_depth_2(self, store: GraphStore) -> None:
        store.upsert_entity("A")
        store.upsert_entity("B")
        store.upsert_entity("C")
        store.add_edge("A", "B", relation="KNOWS")
        store.add_edge("B", "C", relation="KNOWS")
        neighbors = store.get_neighbors("A", depth=2)
        names = {n["name"] for n in neighbors}
        assert "B" in names
        assert "C" in names

    def test_depth_clamped_to_max_5(self, store: GraphStore) -> None:
        # Just verify it doesn't error with large depth
        store.upsert_entity("X")
        store.get_neighbors("X", depth=100)  # should clamp to 5

    def test_neighbors_excludes_self(self, store: GraphStore) -> None:
        store.upsert_entity("A")
        store.upsert_entity("B")
        store.add_edge("A", "B", relation="KNOWS")
        neighbors = store.get_neighbors("A", depth=1)
        names = {n["name"] for n in neighbors}
        assert "A" not in names

    def test_neighbors_bidirectional(self, store: GraphStore) -> None:
        store.upsert_entity("A")
        store.upsert_entity("B")
        store.add_edge("A", "B", relation="KNOWS")
        # B should find A as neighbor via reverse edge traversal
        neighbors = store.get_neighbors("B", depth=1)
        names = {n["name"] for n in neighbors}
        assert "A" in names

    def test_neighbors_no_entity(self, store: GraphStore) -> None:
        result = store.get_neighbors("nonexistent", depth=1)
        assert result == []


class TestGraphStoreProperty:
    def test_lazy_property_returns_same_instance(self, db: MemoryDatabase) -> None:
        store1 = db.graph_store
        store2 = db.graph_store
        assert store1 is store2
