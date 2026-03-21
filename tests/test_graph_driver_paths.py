"""Tests for KnowledgeGraph networkx implementation — write/read paths and lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from nanobot.agent.memory.graph import KnowledgeGraph
from nanobot.agent.memory.ontology import Entity, EntityType, RelationType, Triple


@dataclass
class _Validation:
    valid: bool
    reason: str = ""


async def test_init_verify_and_close(tmp_path: Path) -> None:
    g = KnowledgeGraph(workspace=tmp_path)
    assert g.enabled is True

    assert await g.verify_connectivity() is True
    await g.close()

    # Disabled graph
    g2 = KnowledgeGraph()
    assert g2.enabled is False
    assert await g2.verify_connectivity() is False


async def test_write_and_read_paths(tmp_path: Path) -> None:
    g = KnowledgeGraph(workspace=tmp_path)

    # Upsert entities
    await g.upsert_entity(Entity(name="Carlos", entity_type=EntityType.PERSON, aliases=["C"]))
    await g.upsert_entity(Entity(name="Team", entity_type=EntityType.ORGANIZATION))

    # Add relationship
    from nanobot.agent.memory.ontology import Relationship

    await g.add_relationship(
        Relationship(
            source_id="Carlos",
            target_id="Team",
            relation_type=RelationType.WORKS_WITH,
            confidence=0.9,
            source_event_id="e1",
            timestamp="t1",
        )
    )

    # Read back
    ent = await g.get_entity("Carlos")
    assert ent is not None
    assert ent.name == "Carlos"

    results = await g.search_entities("carlos")
    assert len(results) == 1

    neighbors = await g.get_neighbors("Carlos", depth=1, relation_types=["WORKS_WITH"])
    assert neighbors and neighbors[0]["source"] == "Carlos"

    paths = await g.find_paths("Carlos", "Team", max_depth=3)
    assert paths and paths[0][0]["relation"] == "WORKS_WITH"

    sub = await g.query_subgraph(["Carlos", "Team"], depth=1)
    assert "nodes" in sub and "edges" in sub

    await g.ensure_indexes()  # no-op, should not raise


async def test_ingest_event_triples_and_resolve_entity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    g = KnowledgeGraph(workspace=tmp_path)

    upserts: list[str] = []
    rel_conf: list[float] = []

    async def _upsert(entity: Entity) -> None:
        upserts.append(entity.name)

    async def _add_rel(rel: object) -> None:
        rel_conf.append(rel.confidence)  # type: ignore[attr-defined]

    async def _get_entity(_name: str) -> object:
        return SimpleNamespace(canonical_name="carlos")

    g.upsert_entity = _upsert  # type: ignore[method-assign]
    g.add_relationship = _add_rel  # type: ignore[method-assign]
    g.get_entity = _get_entity  # type: ignore[method-assign]

    monkeypatch.setattr(
        "nanobot.agent.memory.graph.validate_triple_types",
        lambda predicate, s, o: _Validation(valid=False, reason="domain mismatch"),
    )

    triples = [
        Triple(subject="Carlos", predicate=RelationType.WORKS_WITH, object="Team", confidence=0.8)
    ]
    await g.ingest_event_triples("e1", triples, timestamp="2026-01-01")

    assert len(upserts) == 2
    assert rel_conf and rel_conf[0] == pytest.approx(0.4)

    resolved = await g.resolve_entity("Carlos")
    assert resolved == "carlos"


async def test_sync_helpers_paths_and_error_handling(tmp_path: Path) -> None:
    from nanobot.agent.memory.ontology import Relationship

    g = KnowledgeGraph(workspace=tmp_path)

    await g.add_relationship(
        Relationship(
            source_id="Carlos",
            target_id="Team Alpha",
            relation_type=RelationType.WORKS_WITH,
            confidence=0.8,
        )
    )

    names = g.get_related_entity_names_sync({"carlos"}, depth=9)
    assert "team_alpha" in names

    triples = g.get_triples_for_entities_sync({"carlos"})
    assert len(triples) >= 1
    sources = {t[0] for t in triples}
    relations = {t[1] for t in triples}
    assert "WORKS_WITH" in relations
    assert "Carlos" in sources or "carlos" in sources
