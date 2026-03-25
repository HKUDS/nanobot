"""Tests for nanobot.memory.write.dedup — EventDeduplicator."""

from __future__ import annotations

from nanobot.memory.write.classification import EventClassifier
from nanobot.memory.write.coercion import EventCoercer
from nanobot.memory.write.dedup import EventDeduplicator


def _make_dedup(*, conflict_pair_fn: object = None) -> EventDeduplicator:
    classifier = EventClassifier()
    coercer = EventCoercer(classifier)
    return EventDeduplicator(coercer=coercer, conflict_pair_fn=conflict_pair_fn)


class TestEventSimilarity:
    def test_identical_events(self) -> None:
        a = {"type": "fact", "summary": "User likes Python", "entities": ["Python"]}
        lexical, semantic = EventDeduplicator.event_similarity(a, a)
        assert lexical == 1.0
        assert semantic == 1.0

    def test_different_events(self) -> None:
        a = {"type": "fact", "summary": "User likes Python", "entities": ["Python"]}
        b = {"type": "fact", "summary": "Weather is sunny in Tokyo", "entities": ["Tokyo"]}
        lexical, _ = EventDeduplicator.event_similarity(a, b)
        assert lexical < 0.3


class TestFindSemanticDuplicate:
    def test_exact_match(self) -> None:
        d = _make_dedup()
        existing = [
            {"type": "fact", "summary": "User likes Python programming", "entities": ["Python"]}
        ]
        candidate = {
            "type": "fact",
            "summary": "User likes Python programming",
            "entities": ["Python"],
        }
        idx, score = d.find_semantic_duplicate(candidate, existing)
        assert idx == 0
        assert score > 0.5

    def test_different_type_no_match(self) -> None:
        d = _make_dedup()
        existing = [{"type": "fact", "summary": "User likes Python", "entities": ["Python"]}]
        candidate = {"type": "task", "summary": "User likes Python", "entities": ["Python"]}
        idx, _ = d.find_semantic_duplicate(candidate, existing)
        assert idx is None

    def test_no_match(self) -> None:
        d = _make_dedup()
        existing = [{"type": "fact", "summary": "User likes Python", "entities": ["Python"]}]
        candidate = {
            "type": "fact",
            "summary": "Weather in Tokyo is sunny",
            "entities": ["Tokyo"],
        }
        idx, _ = d.find_semantic_duplicate(candidate, existing)
        assert idx is None


class TestFindSemanticSupersession:
    def test_negation_detected(self) -> None:
        d = _make_dedup()
        existing = [
            {
                "type": "preference",
                "summary": "User likes dark mode",
                "entities": ["dark mode"],
                "memory_type": "semantic",
            }
        ]
        candidate = {
            "type": "preference",
            "summary": "User does not like dark mode",
            "entities": ["dark mode"],
            "memory_type": "semantic",
        }
        idx = d.find_semantic_supersession(candidate, existing)
        assert idx == 0

    def test_episodic_not_superseded(self) -> None:
        d = _make_dedup()
        existing = [{"type": "task", "summary": "Deploy v2", "memory_type": "episodic"}]
        candidate = {"type": "task", "summary": "Deploy v2 canceled", "memory_type": "episodic"}
        idx = d.find_semantic_supersession(candidate, existing)
        assert idx is None


class TestMergeEvents:
    def test_entities_unioned(self) -> None:
        d = _make_dedup()
        base = {
            "id": "ev1",
            "type": "fact",
            "summary": "User likes Python",
            "entities": ["Python"],
            "confidence": 0.7,
            "salience": 0.6,
            "source": "chat",
        }
        incoming = {
            "id": "ev2",
            "type": "fact",
            "summary": "User likes Python",
            "entities": ["Python", "coding"],
            "confidence": 0.8,
            "salience": 0.7,
            "source": "chat",
        }
        merged = d.merge_events(base, incoming, similarity=0.9)
        assert "Python" in merged["entities"]
        assert "coding" in merged["entities"]

    def test_confidence_averaged(self) -> None:
        d = _make_dedup()
        base = {
            "id": "ev1",
            "type": "fact",
            "summary": "A fact",
            "entities": [],
            "confidence": 0.6,
            "salience": 0.5,
            "source": "chat",
        }
        incoming = {
            "id": "ev2",
            "type": "fact",
            "summary": "A fact",
            "entities": [],
            "confidence": 0.8,
            "salience": 0.6,
            "source": "chat",
        }
        merged = d.merge_events(base, incoming, similarity=0.85)
        assert 0.72 < merged["confidence"] < 0.74


class TestMergeSourceSpan:
    def test_basic_merge(self) -> None:
        assert EventDeduplicator.merge_source_span([5, 10], [3, 12]) == [3, 12]

    def test_invalid_base(self) -> None:
        assert EventDeduplicator.merge_source_span("bad", [3, 12]) == [0, 12]

    def test_invalid_incoming(self) -> None:
        assert EventDeduplicator.merge_source_span([5, 10], None) == [5, 10]
