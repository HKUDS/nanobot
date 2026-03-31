"""Tests for retrieval pipeline typed data objects."""

from __future__ import annotations

import json

from nanobot.memory.read.retrieval_types import (
    RetrievalScores,
    RetrievedMemory,
    retrieved_memory_from_dict,
)


class TestRetrievalScoresDefaults:
    def test_all_defaults_zero_or_empty(self) -> None:
        s = RetrievalScores()
        assert s.final_score == 0.0
        assert s.recency == 0.0
        assert s.intent == ""
        assert s.profile_adjustment_reasons == []
        assert s.ce_score is None

    def test_mutable(self) -> None:
        s = RetrievalScores()
        s.final_score = 0.85
        s.recency = 0.3
        assert s.final_score == 0.85


class TestRetrievedMemoryDefaults:
    def test_required_fields(self) -> None:
        m = RetrievedMemory(id="t1", type="fact", summary="test", timestamp="2026-01-01")
        assert m.id == "t1"
        assert m.memory_type == "episodic"
        assert m.entities == []
        assert m.scores.final_score == 0.0

    def test_mutable_scores(self) -> None:
        m = RetrievedMemory(id="t1", type="fact", summary="test", timestamp="2026-01-01")
        m.scores.final_score = 0.9
        m.scores.recency = 0.5
        assert m.scores.final_score == 0.9


class TestFactoryFunction:
    def test_minimal_dict(self) -> None:
        item = {"id": "e1", "type": "fact", "summary": "hello", "timestamp": "2026-01-01"}
        m = retrieved_memory_from_dict(item)
        assert m.id == "e1"
        assert m.memory_type == "episodic"
        assert m.entities == []

    def test_full_dict(self) -> None:
        item = {
            "id": "e2",
            "type": "preference",
            "summary": "likes coffee",
            "timestamp": "2026-01-01",
            "source": "chat",
            "status": "active",
            "memory_type": "semantic",
            "topic": "food",
            "stability": "high",
            "entities": ["coffee"],
            "confidence": 0.9,
            "evidence_refs": ["ev1"],
            "superseded_by_event_id": "",
        }
        m = retrieved_memory_from_dict(item)
        assert m.type == "preference"
        assert m.memory_type == "semantic"
        assert m.entities == ["coffee"]
        assert m.confidence == 0.9

    def test_metadata_json_string_parsed(self) -> None:
        item = {
            "id": "e3",
            "type": "fact",
            "summary": "test",
            "timestamp": "2026-01-01",
            "metadata": json.dumps({"topic": "tech", "stability": "low"}),
        }
        m = retrieved_memory_from_dict(item)
        assert m.raw_metadata == {"topic": "tech", "stability": "low"}

    def test_rrf_score_captured(self) -> None:
        item = {
            "id": "e4",
            "type": "fact",
            "summary": "test",
            "timestamp": "2026-01-01",
            "_rrf_score": 0.42,
        }
        m = retrieved_memory_from_dict(item)
        assert m.scores.rrf_score == 0.42

    def test_retrieval_reason_mapped_to_scores(self) -> None:
        item = {
            "id": "e5",
            "type": "fact",
            "summary": "test",
            "timestamp": "2026-01-01",
            "retrieval_reason": {
                "score": 0.8,
                "recency": 0.3,
                "semantic": 0.5,
                "provider": "fts",
            },
        }
        m = retrieved_memory_from_dict(item)
        assert m.scores.rrf_score == 0.8
        assert m.scores.recency == 0.3
        assert m.scores.semantic == 0.5
        assert m.scores.provider == "fts"

    def test_non_list_entities_default_to_empty(self) -> None:
        item = {
            "id": "e6",
            "type": "fact",
            "summary": "test",
            "timestamp": "2026-01-01",
            "entities": "not a list",
        }
        m = retrieved_memory_from_dict(item)
        assert m.entities == []

    def test_missing_metadata_default_to_empty_dict(self) -> None:
        item = {"id": "e7", "type": "fact", "summary": "test", "timestamp": "2026-01-01"}
        m = retrieved_memory_from_dict(item)
        assert m.raw_metadata == {}

    def test_mixed_type_dict_arguments(self) -> None:
        """Test with mixed types matching production data shapes."""
        item = {
            "id": "e8",
            "type": "fact",
            "summary": "vault path is C:\\Users\\test",
            "timestamp": "2026-01-15T10:30:00Z",
            "source": "chat",
            "status": "active",
            "created_at": "2026-01-15T10:30:00Z",
            "memory_type": "semantic",
            "topic": "configuration",
            "stability": "high",
            "entities": ["vault", "obsidian"],
            "triples": [{"subject": "vault", "predicate": "located_at", "object": "C:\\Users"}],
            "evidence_refs": [],
            "confidence": 0.95,
            "superseded_by_event_id": "",
            "metadata": {"topic": "configuration", "_extra": {"custom_key": 42}},
            "_rrf_score": 0.67,
            "retrieval_reason": {
                "score": 0.85,
                "recency": 0.4,
                "semantic": 0.7,
                "provider": "vector",
            },
        }
        m = retrieved_memory_from_dict(item)
        assert m.id == "e8"
        assert m.confidence == 0.95
        assert m.entities == ["vault", "obsidian"]
        assert len(m.triples) == 1
        assert m.scores.rrf_score == 0.67  # _rrf_score overrides retrieval_reason score
        assert m.scores.recency == 0.4

    def test_boundary_empty_strings(self) -> None:
        """Empty strings for all string fields."""
        item = {
            "id": "",
            "type": "",
            "summary": "",
            "timestamp": "",
            "source": "",
        }
        m = retrieved_memory_from_dict(item)
        assert m.id == ""
        assert m.summary == ""

    def test_metadata_invalid_json_string(self) -> None:
        """Invalid JSON metadata string falls back to empty dict."""
        item = {
            "id": "e9",
            "type": "fact",
            "summary": "test",
            "timestamp": "2026-01-01",
            "metadata": "not valid json {{{",
        }
        m = retrieved_memory_from_dict(item)
        assert m.raw_metadata == {}

    def test_metadata_non_dict_value(self) -> None:
        """Non-dict metadata (e.g. a list) falls back to empty dict."""
        item = {
            "id": "e10",
            "type": "fact",
            "summary": "test",
            "timestamp": "2026-01-01",
            "metadata": ["not", "a", "dict"],
        }
        m = retrieved_memory_from_dict(item)
        assert m.raw_metadata == {}
