"""Contract tests for typed memory boundaries.

Verify that typed objects at subsystem boundaries have all fields
that producers set and consumers read.
"""

from __future__ import annotations

from nanobot.memory.persistence.conflict_types import ConflictRecord
from nanobot.memory.read.retrieval_types import RetrievalScores, RetrievedMemory


class TestRetrievedMemoryContract:
    """RetrievedMemory fields match what scorer sets and assembler reads."""

    def test_scorer_fields_exist_on_scores(self) -> None:
        scores = RetrievalScores()
        # Fields set by scoring.py score_items():
        assert hasattr(scores, "final_score")
        assert hasattr(scores, "recency")
        assert hasattr(scores, "type_boost")
        assert hasattr(scores, "stability_boost")
        assert hasattr(scores, "reflection_penalty")
        assert hasattr(scores, "profile_adjustment")
        assert hasattr(scores, "profile_adjustment_reasons")
        assert hasattr(scores, "intent")
        # Fields set by reranker:
        assert hasattr(scores, "ce_score")
        assert hasattr(scores, "blended_score")
        assert hasattr(scores, "reranker_alpha")

    def test_assembler_fields_exist_on_memory(self) -> None:
        mem = RetrievedMemory(id="t", type="fact", summary="test", timestamp="2026-01-01")
        # Fields read by context_assembler.py build():
        assert hasattr(mem, "timestamp")
        assert hasattr(mem, "type")
        assert hasattr(mem, "summary")
        assert hasattr(mem, "scores")
        assert hasattr(mem, "memory_type")
        assert hasattr(mem, "entities")
        assert hasattr(mem, "triples")

    def test_graph_augmenter_fields_exist(self) -> None:
        mem = RetrievedMemory(id="t", type="fact", summary="test", timestamp="2026-01-01")
        # Fields read by graph_augmentation.py:
        assert hasattr(mem, "entities")
        assert hasattr(mem, "triples")

    def test_factory_captures_all_scorer_output_keys(self) -> None:
        """A dict with all keys the scorer produces converts correctly."""
        from nanobot.memory.read.retrieval_types import retrieved_memory_from_dict

        item = {
            "id": "e1",
            "type": "fact",
            "summary": "test",
            "timestamp": "2026-01-01",
            "source": "chat",
            "status": "active",
            "created_at": "2026-01-01",
            "memory_type": "semantic",
            "topic": "tech",
            "stability": "high",
            "entities": ["Python"],
            "triples": [],
            "evidence_refs": ["ev1"],
            "confidence": 0.9,
            "superseded_by_event_id": "",
            "_rrf_score": 0.42,
            "retrieval_reason": {
                "score": 0.8,
                "recency": 0.3,
                "semantic": 0.5,
                "provider": "fts",
            },
        }
        mem = retrieved_memory_from_dict(item)
        assert mem.id == "e1"
        assert mem.memory_type == "semantic"
        assert mem.entities == ["Python"]
        assert mem.scores.rrf_score == 0.42
        assert mem.scores.recency == 0.3


class TestConflictRecordContract:
    """ConflictRecord fields match what conflicts.py sets and consumers read."""

    def test_all_creation_keys_are_fields(self) -> None:
        # Keys set by _apply_profile_updates when creating a conflict:
        record = ConflictRecord(
            timestamp="2026-01-01",
            field="preferences",
            old="tea",
            new="coffee",
            status="open",
            belief_id_old="bf-1",
            belief_id_new="bf-2",
            old_memory_id="ev-1",
            new_memory_id="ev-2",
            old_confidence=0.7,
            new_confidence=0.8,
            old_last_seen_at="2026-01-01",
            new_last_seen_at="2026-01-02",
            source="consolidation",
        )
        assert record.field == "preferences"
        assert record.old_confidence == 0.7

    def test_resolution_fields_exist(self) -> None:
        record = ConflictRecord(timestamp="", field="", old="", new="")
        # Fields set by resolve_conflict_details:
        assert hasattr(record, "resolution")
        assert hasattr(record, "resolved_at")
        assert hasattr(record, "status")

    def test_interaction_fields_exist(self) -> None:
        record = ConflictRecord(timestamp="", field="", old="", new="")
        # Fields set/read by conflict_interaction.py:
        assert hasattr(record, "asked_at")
        assert hasattr(record, "index")

    def test_roundtrip_preserves_all_keys(self) -> None:
        original = ConflictRecord(
            timestamp="2026-01-01",
            field="preferences",
            old="tea",
            new="coffee",
            status="resolved",
            resolution="keep_new",
            resolved_at="2026-01-02",
        )
        d = original.to_dict()
        restored = ConflictRecord.from_dict(d)
        assert restored.field == original.field
        assert restored.resolution == original.resolution
        assert restored.resolved_at == original.resolved_at

    def test_to_dict_excludes_index(self) -> None:
        record = ConflictRecord(timestamp="", field="", old="", new="", index=5)
        d = record.to_dict()
        assert "index" not in d
