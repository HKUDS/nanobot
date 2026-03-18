from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from nanobot.agent.memory.graph import KnowledgeGraph
from nanobot.agent.memory.ontology import Entity, EntityType, RelationType, Triple


@dataclass
class _Validation:
    valid: bool
    reason: str = ""


class _AsyncResult:
    def __init__(self, *, single=None, data=None):
        self._single = single
        self._data = data or []

    async def single(self):
        return self._single

    async def data(self):
        return self._data


class _AsyncSession:
    def __init__(self, sink: list[tuple[str, dict]], responses: list[_AsyncResult] | None = None):
        self._sink = sink
        self._responses = responses or []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def run(self, statement: str, **params):
        self._sink.append((statement, params))
        if self._responses:
            return self._responses.pop(0)
        return _AsyncResult()


class _AsyncDriver:
    def __init__(self, responses: list[_AsyncResult] | None = None, fail_verify: bool = False):
        self._sink: list[tuple[str, dict]] = []
        self._responses = responses or []
        self._fail_verify = fail_verify
        self.closed = False

    async def verify_connectivity(self):
        if self._fail_verify:
            raise RuntimeError("offline")

    def session(self, database: str = "neo4j"):
        return _AsyncSession(self._sink, self._responses)

    async def close(self):
        self.closed = True


class _SyncSession:
    def __init__(self, rows: list[dict[str, str]], fail: bool = False):
        self._rows = rows
        self._fail = fail

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def run(self, query: str, **params):
        if self._fail:
            raise RuntimeError("sync fail")
        return list(self._rows)


class _SyncDriver:
    def __init__(self, rows: list[dict[str, str]] | None = None, fail: bool = False):
        self._rows = rows or []
        self._fail = fail
        self.closed = False

    def session(self, database: str = "neo4j"):
        return _SyncSession(self._rows, self._fail)

    def close(self):
        self.closed = True


async def test_init_verify_and_close_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    async_driver = _AsyncDriver()
    sync_driver = _SyncDriver()

    monkeypatch.setattr("nanobot.agent.memory.graph._HAS_NEO4J", True)
    monkeypatch.setattr(
        "nanobot.agent.memory.graph.AsyncGraphDatabase",
        SimpleNamespace(driver=lambda uri, auth: async_driver),
    )
    monkeypatch.setattr(
        "nanobot.agent.memory.graph.GraphDatabase",
        SimpleNamespace(driver=lambda uri, auth: sync_driver),
    )

    g = KnowledgeGraph(uri="bolt://x", auth="u/p")
    assert g.enabled is True

    assert await g.verify_connectivity() is True
    await g.close()
    assert async_driver.closed is True
    assert sync_driver.closed is True

    failing = _AsyncDriver(fail_verify=True)
    g2 = KnowledgeGraph.__new__(KnowledgeGraph)
    g2._database = "neo4j"
    g2._driver = failing
    g2._sync_driver = None
    g2.enabled = True
    g2.error = None
    assert await g2.verify_connectivity() is False
    assert g2.enabled is False


async def test_write_and_read_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = [
        _AsyncResult(
            single={"e": {"name": "Carlos", "entity_type": "person", "aliases_text": "C"}}
        ),
        _AsyncResult(
            data=[{"node": {"name": "Carlos", "entity_type": "person", "aliases_text": "C"}}]
        ),
        _AsyncResult(
            data=[
                {"source": "Carlos", "relation": "WORKS_WITH", "target": "Team", "confidence": 0.9}
            ]
        ),
        _AsyncResult(data=[{"nodes": ["Carlos", "Team"], "relations": ["WORKS_WITH"]}]),
    ]
    driver = _AsyncDriver(responses=responses)

    g = KnowledgeGraph.__new__(KnowledgeGraph)
    g._database = "neo4j"
    g._driver = driver
    g._sync_driver = None
    g.enabled = True
    g.error = None

    ent = await g.get_entity("Carlos")
    assert ent is not None
    results = await g.search_entities("carlos")
    assert len(results) == 1

    neighbors = await g.get_neighbors("Carlos", depth=9, relation_types=["WORKS_WITH"])
    assert neighbors and neighbors[0]["source"] == "Carlos"

    paths = await g.find_paths("Carlos", "Team", max_depth=10)
    assert paths and paths[0][0]["relation"] == "WORKS_WITH"

    sub = await g.query_subgraph(["Carlos", "Team"], depth=1)
    assert "nodes" in sub and "edges" in sub

    await g.ensure_indexes()
    await g.upsert_entity(Entity(name="Carlos", entity_type=EntityType.PERSON))
    rel = SimpleNamespace(
        source_id="Carlos",
        target_id="Team",
        relation_type=SimpleNamespace(value="WORKS_WITH"),
        confidence=0.7,
        source_event_id="e1",
        timestamp="t1",
    )
    await g.add_relationship(rel)


async def test_ingest_event_triples_and_resolve_entity(monkeypatch: pytest.MonkeyPatch) -> None:
    g = KnowledgeGraph.__new__(KnowledgeGraph)
    g.enabled = True
    g._driver = object()
    g._sync_driver = None
    g._database = "neo4j"

    upserts: list[str] = []
    rel_conf: list[float] = []

    async def _upsert(entity):
        upserts.append(entity.name)

    async def _add_rel(rel):
        rel_conf.append(rel.confidence)

    async def _get_entity(_name: str):
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


def test_sync_helpers_paths_and_error_handling() -> None:
    g = KnowledgeGraph.__new__(KnowledgeGraph)
    g.enabled = True
    g._database = "neo4j"
    g._driver = None
    g._sync_driver = _SyncDriver(rows=[{"cn": "team_alpha", "n": "Team Alpha"}])

    names = g.get_related_entity_names_sync({"Carlos"}, depth=9)
    assert "team_alpha" in names
    assert "team alpha" in names

    g._sync_driver = _SyncDriver(
        rows=[{"source": "Carlos", "relation": "WORKS_WITH", "target": "Team"}]
    )
    triples = g.get_triples_for_entities_sync({"Carlos"})
    assert triples == [("Carlos", "WORKS_WITH", "Team")]

    g._sync_driver = _SyncDriver(fail=True)
    assert g.get_related_entity_names_sync({"Carlos"}) == set()
    assert g.get_triples_for_entities_sync({"Carlos"}) == []
