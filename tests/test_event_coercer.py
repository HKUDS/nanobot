"""Tests for nanobot.memory.write.coercion — EventCoercer."""

from __future__ import annotations

from nanobot.memory.write.classification import EventClassifier
from nanobot.memory.write.coercion import (
    EPISODIC_STATUS_OPEN,
    EPISODIC_STATUS_RESOLVED,
    EventCoercer,
)


def _make_coercer() -> EventCoercer:
    return EventCoercer(EventClassifier())


class TestBuildEventId:
    def test_deterministic(self) -> None:
        id1 = EventCoercer.build_event_id("fact", "Hello world", "2025-01-01T00:00")
        id2 = EventCoercer.build_event_id("fact", "Hello world", "2025-01-01T00:00")
        assert id1 == id2
        assert len(id1) == 16

    def test_different_inputs(self) -> None:
        id1 = EventCoercer.build_event_id("fact", "Hello", "2025-01-01T00:00")
        id2 = EventCoercer.build_event_id("fact", "World", "2025-01-01T00:00")
        assert id1 != id2


class TestInferEpisodicStatus:
    def test_task_defaults_to_open(self) -> None:
        c = _make_coercer()
        assert c.infer_episodic_status(event_type="task", summary="Do X") == EPISODIC_STATUS_OPEN

    def test_task_resolved_from_summary(self) -> None:
        c = _make_coercer()
        assert (
            c.infer_episodic_status(event_type="task", summary="Task completed")
            == EPISODIC_STATUS_RESOLVED
        )

    def test_fact_returns_none(self) -> None:
        c = _make_coercer()
        assert c.infer_episodic_status(event_type="fact", summary="A fact") is None

    def test_raw_status_respected(self) -> None:
        c = _make_coercer()
        assert (
            c.infer_episodic_status(event_type="task", summary="Do X", raw_status="resolved")
            == EPISODIC_STATUS_RESOLVED
        )


class TestCoerceEvent:
    def test_valid_event(self) -> None:
        c = _make_coercer()
        result = c.coerce_event(
            {"summary": "User prefers dark mode", "type": "preference"},
            source_span=[0, 10],
        )
        assert result is not None
        assert result.summary == "User prefers dark mode"
        assert result.type == "preference"
        assert result.id

    def test_missing_summary_returns_none(self) -> None:
        c = _make_coercer()
        assert c.coerce_event({"type": "fact"}, source_span=[0, 0]) is None
        assert c.coerce_event({"summary": ""}, source_span=[0, 0]) is None

    def test_invalid_type_falls_back(self) -> None:
        c = _make_coercer()
        result = c.coerce_event({"summary": "Something", "type": "bogus"}, source_span=[0, 5])
        assert result is not None
        assert result.type == "fact"

    def test_triples_parsed(self) -> None:
        c = _make_coercer()
        result = c.coerce_event(
            {
                "summary": "Alice knows Bob",
                "type": "relationship",
                "triples": [{"subject": "Alice", "predicate": "KNOWS", "object": "Bob"}],
            },
            source_span=[0, 5],
        )
        assert result is not None
        assert len(result.triples) == 1


class TestEnsureEventProvenance:
    def test_enriches_event(self) -> None:
        c = _make_coercer()
        event = {
            "id": "evt1",
            "type": "fact",
            "summary": "Python is great",
            "source": "chat",
        }
        result = c.ensure_event_provenance(event)
        assert result["memory_type"] == "semantic"
        assert result["topic"] == "knowledge"
        assert result["canonical_id"] == "evt1"
        assert "evidence" in result

    def test_no_id_skips_canonical(self) -> None:
        c = _make_coercer()
        event = {"type": "fact", "summary": "Test", "source": "chat"}
        result = c.ensure_event_provenance(event)
        assert "canonical_id" not in result
