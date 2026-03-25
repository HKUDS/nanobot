"""Tests for nanobot.memory.write.classification — EventClassifier."""

from __future__ import annotations

from nanobot.memory.write.classification import (
    EVENT_TYPES,
    MEMORY_STABILITY,
    MEMORY_TYPES,
    EventClassifier,
)


class TestEventClassifier:
    def test_constants_exposed(self) -> None:
        assert "fact" in EVENT_TYPES
        assert "semantic" in MEMORY_TYPES
        assert "high" in MEMORY_STABILITY

    def test_semantic_for_fact(self) -> None:
        c = EventClassifier()
        memory_type, stability, is_mixed = c.classify_memory_type(
            event_type="fact", summary="Python is great", source="chat"
        )
        assert memory_type == "semantic"
        assert stability == "high"
        assert not is_mixed

    def test_episodic_for_task(self) -> None:
        c = EventClassifier()
        memory_type, stability, _ = c.classify_memory_type(
            event_type="task", summary="Deploy v2", source="chat"
        )
        assert memory_type == "episodic"
        assert stability == "medium"

    def test_reflection_source(self) -> None:
        c = EventClassifier()
        memory_type, stability, _ = c.classify_memory_type(
            event_type="fact", summary="Any text", source="reflection"
        )
        assert memory_type == "reflection"
        assert stability == "medium"

    def test_mixed_flag(self) -> None:
        c = EventClassifier()
        _, _, is_mixed = c.classify_memory_type(
            event_type="fact",
            summary="Python failed because of a bug yesterday",
            source="chat",
        )
        assert is_mixed

    def test_default_topic_for_known_types(self) -> None:
        assert EventClassifier.default_topic_for_event_type("preference") == "user_preference"
        assert EventClassifier.default_topic_for_event_type("task") == "task_progress"
        assert EventClassifier.default_topic_for_event_type("fact") == "knowledge"

    def test_default_topic_for_unknown(self) -> None:
        assert EventClassifier.default_topic_for_event_type("unknown") == "general"

    def test_distill_semantic_summary(self) -> None:
        assert (
            EventClassifier.distill_semantic_summary("User likes vim because it is fast")
            == "User likes vim"
        )

    def test_distill_keeps_short(self) -> None:
        assert EventClassifier.distill_semantic_summary("short because x") == "short because x"

    def test_distill_empty(self) -> None:
        assert EventClassifier.distill_semantic_summary("") == ""

    def test_normalize_memory_metadata_basic(self) -> None:
        c = EventClassifier()
        metadata, is_mixed = c.normalize_memory_metadata(
            None, event_type="fact", summary="Python is great", source="chat"
        )
        assert metadata["memory_type"] == "semantic"
        assert metadata["stability"] == "high"
        assert metadata["topic"] == "knowledge"
        assert not is_mixed

    def test_normalize_memory_metadata_reflection_no_evidence(self) -> None:
        c = EventClassifier()
        metadata, _ = c.normalize_memory_metadata(
            {"memory_type": "reflection"},
            event_type="fact",
            summary="I think X",
            source="reflection",
        )
        # Reflection without evidence_refs gets downgraded
        assert metadata["memory_type"] == "episodic"
        assert metadata["stability"] == "low"
        assert metadata["reflection_safety_downgraded"] is True
