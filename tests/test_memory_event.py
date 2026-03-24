"""Tests for the typed MemoryEvent model."""

from __future__ import annotations

import pytest

from nanobot.memory.event import KnowledgeTriple, MemoryEvent


class TestMemoryEvent:
    def test_minimal_construction(self) -> None:
        e = MemoryEvent(summary="User prefers dark mode.")
        assert e.summary == "User prefers dark mode."
        assert e.type == "fact"
        assert e.salience == 0.6
        assert e.confidence == 0.7
        assert e.memory_type == "episodic"
        assert e.stability == "medium"
        assert e.source == "chat"
        assert e.triples == []

    def test_full_construction(self) -> None:
        e = MemoryEvent(
            id="abc123",
            timestamp="2026-03-01T09:00:00+00:00",
            channel="telegram",
            chat_id="c1",
            type="preference",
            summary="User likes Python.",
            entities=["user", "python"],
            salience=0.9,
            confidence=0.95,
            source_span=[1, 5],
            ttl_days=30,
            memory_type="semantic",
            topic="user_preference",
            stability="high",
            source="chat",
            evidence_refs=["evt-001"],
            status="open",
            metadata={"custom": True},
            triples=[KnowledgeTriple(subject="user", predicate="USES", object="python")],
        )
        assert e.id == "abc123"
        assert e.type == "preference"
        assert e.entities == ["user", "python"]
        assert len(e.triples) == 1
        assert e.triples[0].predicate == "USES"

    def test_summary_whitespace_stripped(self) -> None:
        e = MemoryEvent(summary="  spaced  ")
        assert e.summary == "spaced"

    def test_empty_summary_rejected(self) -> None:
        with pytest.raises(ValueError, match="summary must not be empty"):
            MemoryEvent(summary="   ")

    def test_invalid_type_coerced_via_from_dict(self) -> None:
        e = MemoryEvent.from_dict({"type": "bogus", "summary": "test"})
        assert e.type == "fact"

    def test_negative_ttl_becomes_none(self) -> None:
        e = MemoryEvent(summary="test", ttl_days=-5)
        assert e.ttl_days is None

    def test_zero_ttl_becomes_none(self) -> None:
        e = MemoryEvent(summary="test", ttl_days=0)
        assert e.ttl_days is None

    def test_to_dict_roundtrip(self) -> None:
        e = MemoryEvent(
            id="x",
            summary="roundtrip test",
            type="task",
            triples=[KnowledgeTriple(subject="a", object="b")],
        )
        d = e.to_dict()
        assert isinstance(d, dict)
        assert d["type"] == "task"
        assert d["triples"][0]["predicate"] == "RELATED_TO"
        # Roundtrip
        e2 = MemoryEvent.from_dict(d)
        assert e2.id == e.id
        assert e2.summary == e.summary

    def test_from_dict_with_seed_data(self) -> None:
        """Parse a dict matching case/memory_seed_events.jsonl format."""
        raw = {
            "id": "seed-evt-001",
            "timestamp": "2026-03-01T09:00:00+00:00",
            "type": "preference",
            "summary": "User prefers concise bullet-point responses.",
            "entities": ["user", "response-style"],
            "source": "profile",
            "status": "open",
            "metadata": {
                "memory_type": "semantic",
                "topic": "user_preference",
                "stability": "high",
                "source": "profile",
            },
        }
        e = MemoryEvent.from_dict(raw)
        assert e.id == "seed-evt-001"
        assert e.type == "preference"
        assert e.source == "profile"

    def test_extra_fields_allowed(self) -> None:
        """Extra fields in the dict are preserved (model_config extra=allow)."""
        e = MemoryEvent.from_dict({"summary": "test", "custom_field": 42})
        assert e.model_extra is not None
        assert e.model_extra.get("custom_field") == 42


class TestKnowledgeTriple:
    def test_defaults(self) -> None:
        t = KnowledgeTriple(subject="a", object="b")
        assert t.predicate == "RELATED_TO"
        assert t.confidence == 0.7

    def test_confidence_clamped(self) -> None:
        t = KnowledgeTriple(subject="a", object="b", confidence=0.0)
        assert t.confidence == 0.0
        t2 = KnowledgeTriple(subject="a", object="b", confidence=1.0)
        assert t2.confidence == 1.0
