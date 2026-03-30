"""Tests for EventStore -- event CRUD and search operations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from nanobot.memory.db import EventStore, MemoryDatabase


@pytest.fixture()
def db(tmp_path: Path) -> MemoryDatabase:
    d = MemoryDatabase(tmp_path / "test.db", dims=4)
    yield d  # type: ignore[misc]
    d.close()


@pytest.fixture()
def store(db: MemoryDatabase) -> EventStore:
    return db.event_store


def _make_event(
    id: str = "e1",
    type: str = "fact",
    summary: str = "Test event",
    timestamp: str = "2026-03-30T00:00:00Z",
    **kwargs: Any,
) -> dict[str, Any]:
    return {"id": id, "type": type, "summary": summary, "timestamp": timestamp, **kwargs}


class TestEventCRUD:
    def test_insert_and_read(self, store: EventStore) -> None:
        store.insert_event(_make_event())
        rows = store.read_events(limit=10)
        assert len(rows) == 1
        assert rows[0]["id"] == "e1"
        assert rows[0]["summary"] == "Test event"

    def test_insert_with_embedding(self, store: EventStore) -> None:
        store.insert_event(_make_event(), embedding=[0.1, 0.2, 0.3, 0.4])
        rows = store.read_events(limit=10)
        assert len(rows) == 1

    def test_read_with_status_filter(self, store: EventStore) -> None:
        store.insert_event(_make_event(id="a1", status="active"))
        store.insert_event(_make_event(id="a2", status="resolved"))
        active = store.read_events(status="active")
        assert all(r["status"] == "active" for r in active)

    def test_read_with_type_filter(self, store: EventStore) -> None:
        store.insert_event(_make_event(id="t1", type="fact"))
        store.insert_event(_make_event(id="t2", type="preference"))
        facts = store.read_events(type="fact")
        assert all(r["type"] == "fact" for r in facts)

    def test_insert_replaces_existing(self, store: EventStore) -> None:
        store.insert_event(_make_event(summary="old"))
        store.insert_event(_make_event(summary="new"))
        rows = store.read_events(limit=10)
        assert len(rows) == 1
        assert rows[0]["summary"] == "new"

    def test_metadata_dict_serialized(self, store: EventStore) -> None:
        store.insert_event(_make_event(metadata={"topic": "test", "count": 42}))
        rows = store.read_events(limit=10)
        assert rows[0]["metadata"] is not None

    def test_mixed_type_metadata(self, store: EventStore) -> None:
        """Mixed-type dict arguments matching production data patterns."""
        store.insert_event(
            _make_event(
                id="mix1",
                metadata={
                    "topic": "deployment",
                    "retries": 3,
                    "tags": ["ci", "prod"],
                    "notes": None,
                },
                source="agent",
                status="active",
            )
        )
        rows = store.read_events(limit=10)
        assert len(rows) == 1
        meta = json.loads(rows[0]["metadata"])
        assert meta["retries"] == 3
        assert meta["tags"] == ["ci", "prod"]

    def test_production_format_event(self, store: EventStore) -> None:
        """Event dict matching exact production format from MemoryExtractor."""
        event = {
            "id": "mem-2026-03-30-abc123",
            "type": "fact",
            "summary": "User prefers dark mode in all applications",
            "timestamp": "2026-03-30T14:22:00Z",
            "source": "extraction",
            "status": "active",
            "metadata": json.dumps({"topic": "preferences", "confidence": 0.95}),
            "created_at": "2026-03-30T14:22:01Z",
        }
        store.insert_event(event, embedding=[0.5, 0.5, 0.5, 0.5])
        rows = store.read_events(limit=10)
        assert rows[0]["id"] == "mem-2026-03-30-abc123"
        assert rows[0]["source"] == "extraction"

    def test_empty_summary_boundary(self, store: EventStore) -> None:
        """Boundary: empty string summary."""
        store.insert_event(_make_event(summary=""))
        rows = store.read_events(limit=10)
        assert rows[0]["summary"] == ""

    def test_long_summary_boundary(self, store: EventStore) -> None:
        """Boundary: very long summary."""
        long_text = "x" * 10000
        store.insert_event(_make_event(summary=long_text))
        rows = store.read_events(limit=10)
        assert rows[0]["summary"] == long_text


class TestFTSSearch:
    def test_search_finds_matching_terms(self, store: EventStore) -> None:
        store.insert_event(_make_event(id="f1", summary="Python programming language"))
        store.insert_event(_make_event(id="f2", summary="JavaScript framework"))
        results = store.search_fts("Python", k=10)
        assert any(r["id"] == "f1" for r in results)

    def test_search_empty_query(self, store: EventStore) -> None:
        assert store.search_fts("", k=10) == []

    def test_search_no_matches(self, store: EventStore) -> None:
        store.insert_event(_make_event(summary="hello world"))
        assert store.search_fts("zzzzzzz", k=10) == []

    def test_replace_updates_fts_and_vector(self, store: EventStore) -> None:
        """Replacing an event updates both FTS index and vector embedding."""
        store.insert_event(
            _make_event(id="r1", summary="User likes tea"), embedding=[1.0, 0.0, 0.0, 0.0]
        )
        store.insert_event(
            _make_event(id="r1", summary="User likes coffee"), embedding=[0.0, 1.0, 0.0, 0.0]
        )
        # Old term gone from FTS
        assert len(store.search_fts("tea", k=5)) == 0
        # New term present
        results = store.search_fts("coffee", k=5)
        assert len(results) == 1
        assert results[0]["id"] == "r1"
        # Vector search finds new embedding
        vec_results = store.search_vector([0.0, 1.0, 0.0, 0.0], k=5)
        assert len(vec_results) == 1
        assert vec_results[0]["id"] == "r1"


class TestVectorSearch:
    def test_knn_returns_nearest(self, store: EventStore) -> None:
        store.insert_event(_make_event(id="v1", summary="close"), embedding=[1.0, 0.0, 0.0, 0.0])
        store.insert_event(_make_event(id="v2", summary="far"), embedding=[0.0, 0.0, 0.0, 1.0])
        results = store.search_vector([1.0, 0.0, 0.0, 0.0], k=2)
        assert len(results) >= 1
        assert results[0]["id"] == "v1"


class TestMetadataSearch:
    def test_search_by_topic(self, store: EventStore) -> None:
        store.insert_event(_make_event(id="m1", metadata=json.dumps({"topic": "python"})))
        store.insert_event(_make_event(id="m2", metadata=json.dumps({"topic": "rust"})))
        results = store.search_by_metadata(topic="python", k=10)
        assert any(r["id"] == "m1" for r in results)

    def test_search_empty_conditions(self, store: EventStore) -> None:
        assert store.search_by_metadata(k=10) == []

    def test_search_by_memory_type(self, store: EventStore) -> None:
        store.insert_event(_make_event(id="mt1", type="preference"))
        store.insert_event(_make_event(id="mt2", type="fact"))
        results = store.search_by_metadata(memory_type="preference", k=10)
        assert len(results) == 1
        assert results[0]["id"] == "mt1"
