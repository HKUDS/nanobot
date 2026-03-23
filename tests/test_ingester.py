"""Tests for nanobot.agent.memory.ingester — EventIngester."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from nanobot.agent.memory.ingester import EventIngester
from nanobot.agent.memory.persistence import MemoryPersistence


def _make_ingester(
    *,
    rollout: dict[str, Any] | None = None,
    conflict_pair_fn: Any = None,
    mem0_enabled: bool = False,
    graph_enabled: bool = False,
) -> tuple[EventIngester, MagicMock, MagicMock, MagicMock]:
    """Build an ``EventIngester`` with mocked dependencies."""
    persistence = MagicMock(spec=MemoryPersistence)
    persistence.events_file = Path("/tmp/fake/events.jsonl")
    persistence.read_jsonl.return_value = []

    mem0 = MagicMock()
    mem0.enabled = mem0_enabled
    mem0.add_text.return_value = True

    graph = MagicMock()
    graph.enabled = graph_enabled

    ing = EventIngester(
        persistence=persistence,
        mem0=mem0,
        graph=graph,
        rollout=rollout or {},
        conflict_pair_fn=conflict_pair_fn,
    )
    return ing, persistence, mem0, graph


class TestCoerceEvent:
    def test_valid_event_normalizes(self) -> None:
        ing, *_ = _make_ingester()
        result = ing._coerce_event(
            {"summary": "User prefers dark mode", "type": "preference"},
            source_span=[0, 10],
        )
        assert result is not None
        assert result["summary"] == "User prefers dark mode"
        assert result["type"] == "preference"
        assert result["memory_type"] == "semantic"
        assert result["id"]  # should have generated an ID

    def test_invalid_type_falls_back_to_fact(self) -> None:
        ing, *_ = _make_ingester()
        result = ing._coerce_event(
            {"summary": "Something happened", "type": "invalid_type"},
            source_span=[0, 5],
        )
        assert result is not None
        assert result["type"] == "fact"

    def test_missing_summary_returns_none(self) -> None:
        ing, *_ = _make_ingester()
        assert ing._coerce_event({"type": "fact"}, source_span=[0, 0]) is None
        assert ing._coerce_event({"summary": ""}, source_span=[0, 0]) is None
        assert ing._coerce_event({"summary": "   "}, source_span=[0, 0]) is None

    def test_triples_parsed(self) -> None:
        ing, *_ = _make_ingester()
        result = ing._coerce_event(
            {
                "summary": "Alice knows Bob",
                "type": "relationship",
                "triples": [
                    {"subject": "Alice", "predicate": "KNOWS", "object": "Bob"},
                ],
            },
            source_span=[0, 5],
        )
        assert result is not None
        assert len(result["triples"]) == 1
        assert result["triples"][0]["subject"] == "Alice"


class TestClassifyMemoryType:
    def test_semantic_for_fact(self) -> None:
        ing, *_ = _make_ingester()
        memory_type, stability, is_mixed = ing._classify_memory_type(
            event_type="fact", summary="Python is great", source="chat"
        )
        assert memory_type == "semantic"
        assert stability == "high"
        assert not is_mixed

    def test_semantic_for_preference(self) -> None:
        ing, *_ = _make_ingester()
        memory_type, _, _ = ing._classify_memory_type(
            event_type="preference", summary="User prefers vim", source="chat"
        )
        assert memory_type == "semantic"

    def test_episodic_for_task(self) -> None:
        ing, *_ = _make_ingester()
        memory_type, _, _ = ing._classify_memory_type(
            event_type="task", summary="Deploy v2", source="chat"
        )
        assert memory_type == "episodic"

    def test_episodic_for_decision(self) -> None:
        ing, *_ = _make_ingester()
        memory_type, _, _ = ing._classify_memory_type(
            event_type="decision", summary="Chose React", source="chat"
        )
        assert memory_type == "episodic"

    def test_reflection_source(self) -> None:
        ing, *_ = _make_ingester()
        memory_type, stability, _ = ing._classify_memory_type(
            event_type="fact", summary="Any text", source="reflection"
        )
        assert memory_type == "reflection"
        assert stability == "medium"


class TestFindSemanticDuplicate:
    def test_high_similarity_detected(self) -> None:
        ing, *_ = _make_ingester()
        existing = [
            {
                "type": "fact",
                "summary": "User likes Python programming language",
                "entities": ["Python"],
            }
        ]
        candidate = {
            "type": "fact",
            "summary": "User likes Python programming language",
            "entities": ["Python"],
        }
        idx, score = ing._find_semantic_duplicate(candidate, existing)
        assert idx == 0
        assert score > 0.5

    def test_different_events_not_matched(self) -> None:
        ing, *_ = _make_ingester()
        existing = [{"type": "fact", "summary": "User likes Python", "entities": ["Python"]}]
        candidate = {
            "type": "fact",
            "summary": "Weather in Tokyo is sunny today",
            "entities": ["Tokyo"],
        }
        idx, score = ing._find_semantic_duplicate(candidate, existing)
        assert idx is None

    def test_different_types_not_matched(self) -> None:
        ing, *_ = _make_ingester()
        existing = [{"type": "fact", "summary": "User likes Python", "entities": ["Python"]}]
        candidate = {
            "type": "task",
            "summary": "User likes Python",
            "entities": ["Python"],
        }
        idx, _ = ing._find_semantic_duplicate(candidate, existing)
        assert idx is None


class TestMergeEvents:
    def test_entities_unioned(self) -> None:
        ing, *_ = _make_ingester()
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
        merged = ing._merge_events(base, incoming, similarity=0.9)
        assert "Python" in merged["entities"]
        assert "coding" in merged["entities"]

    def test_confidence_averaged(self) -> None:
        ing, *_ = _make_ingester()
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
        merged = ing._merge_events(base, incoming, similarity=0.85)
        # (0.6 + 0.8) / 2 + 0.03 = 0.73
        assert 0.72 < merged["confidence"] < 0.74


class TestAppendEventsDedup:
    def test_duplicate_merged_on_append(self, tmp_path: Path) -> None:
        events_file = tmp_path / "events.jsonl"
        events_file.write_text("")  # empty file so exists() returns True

        persistence = MagicMock(spec=MemoryPersistence)
        persistence.events_file = events_file

        existing_event = {
            "id": "abc123",
            "type": "fact",
            "summary": "User likes Python programming language",
            "entities": ["Python"],
            "confidence": 0.7,
            "salience": 0.6,
            "source": "chat",
            "timestamp": "2025-01-01T00:00:00+00:00",
        }
        persistence.read_jsonl.return_value = [existing_event]

        mem0 = MagicMock()
        mem0.enabled = False
        graph = MagicMock()
        graph.enabled = False

        ing = EventIngester(
            persistence=persistence,
            mem0=mem0,
            graph=graph,
            rollout={},
        )

        # Append a very similar event.
        new_event = {
            "id": "new456",
            "type": "fact",
            "summary": "User likes Python programming language a lot",
            "entities": ["Python"],
            "confidence": 0.8,
            "salience": 0.7,
            "source": "chat",
            "timestamp": "2025-01-02T00:00:00+00:00",
        }
        ing.append_events([new_event])
        # The event should be merged (duplicate detected), so write_jsonl is called
        # to persist the updated (merged) event list.
        assert persistence.write_jsonl.called


class TestSanitizeMem0Text:
    def test_strips_runtime_context(self) -> None:
        ing, *_ = _make_ingester()
        result = ing._sanitize_mem0_text("Hello world [Runtime Context] extra stuff")
        assert "extra stuff" not in result
        assert result == "Hello world"

    def test_empty_string(self) -> None:
        ing, *_ = _make_ingester()
        assert ing._sanitize_mem0_text("") == ""
        assert ing._sanitize_mem0_text("   ") == ""

    def test_blob_like_rejected(self) -> None:
        ing, *_ = _make_ingester()
        assert ing._sanitize_mem0_text("{ json blob }") == ""

    def test_too_long_rejected(self) -> None:
        ing, *_ = _make_ingester(rollout={"memory_fallback_max_summary_chars": 10})
        assert ing._sanitize_mem0_text("A very long text that exceeds the limit") == ""

    def test_too_long_archival_truncated(self) -> None:
        ing, *_ = _make_ingester(rollout={"memory_fallback_max_summary_chars": 20})
        result = ing._sanitize_mem0_text(
            "A very long text that exceeds the limit", allow_archival=True
        )
        assert result.endswith("...")
        assert len(result) <= 23  # 20 + "..."


class TestReadEventsCaching:
    def test_mtime_cache_works(self, tmp_path: Path) -> None:
        events_file = tmp_path / "events.jsonl"
        events_file.write_text('{"id": "1", "summary": "test"}\n')

        persistence = MagicMock(spec=MemoryPersistence)
        persistence.events_file = events_file
        persistence.read_jsonl.return_value = [{"id": "1", "summary": "test"}]

        mem0 = MagicMock()
        mem0.enabled = False
        graph = MagicMock()
        graph.enabled = False

        ing = EventIngester(
            persistence=persistence,
            mem0=mem0,
            graph=graph,
            rollout={},
        )

        # First read — cache miss.
        result1 = ing.read_events()
        assert len(result1) == 1
        assert persistence.read_jsonl.call_count == 1

        # Second read — cache hit (same mtime).
        result2 = ing.read_events()
        assert len(result2) == 1
        assert persistence.read_jsonl.call_count == 1  # NOT called again

        # Touch file to change mtime — cache miss.
        events_file.write_text('{"id": "1", "summary": "test"}\n{"id": "2", "summary": "two"}\n')
        persistence.read_jsonl.return_value = [
            {"id": "1", "summary": "test"},
            {"id": "2", "summary": "two"},
        ]
        result3 = ing.read_events()
        assert len(result3) == 2
        assert persistence.read_jsonl.call_count == 2


class TestBuildEventId:
    def test_deterministic(self) -> None:
        id1 = EventIngester._build_event_id("fact", "Hello world", "2025-01-01T00:00")
        id2 = EventIngester._build_event_id("fact", "Hello world", "2025-01-01T00:00")
        assert id1 == id2
        assert len(id1) == 16

    def test_different_inputs(self) -> None:
        id1 = EventIngester._build_event_id("fact", "Hello", "2025-01-01T00:00")
        id2 = EventIngester._build_event_id("fact", "World", "2025-01-01T00:00")
        assert id1 != id2


class TestMergeSourceSpan:
    def test_basic_merge(self) -> None:
        assert EventIngester._merge_source_span([5, 10], [3, 12]) == [3, 12]

    def test_invalid_base(self) -> None:
        assert EventIngester._merge_source_span("bad", [3, 12]) == [0, 12]

    def test_invalid_incoming(self) -> None:
        assert EventIngester._merge_source_span([5, 10], None) == [5, 10]


class TestDefaultTopicForEventType:
    def test_known_types(self) -> None:
        assert EventIngester._default_topic_for_event_type("preference") == "user_preference"
        assert EventIngester._default_topic_for_event_type("task") == "task_progress"
        assert EventIngester._default_topic_for_event_type("fact") == "knowledge"

    def test_unknown_type(self) -> None:
        assert EventIngester._default_topic_for_event_type("unknown") == "general"


class TestDistillSemanticSummary:
    def test_strips_causal_clause(self) -> None:
        result = EventIngester._distill_semantic_summary("User likes vim because it is fast")
        assert result == "User likes vim"

    def test_keeps_short_text(self) -> None:
        result = EventIngester._distill_semantic_summary("short because x")
        # "short" is < 12 chars, so full text is returned.
        assert result == "short because x"

    def test_empty(self) -> None:
        assert EventIngester._distill_semantic_summary("") == ""


class TestSanitizeMetadata:
    def test_strips_none(self) -> None:
        result = EventIngester._sanitize_mem0_metadata({"a": 1, "b": None, "c": "ok"})
        assert result == {"a": 1, "c": "ok"}

    def test_flattens_nested(self) -> None:
        result = EventIngester._sanitize_mem0_metadata({"x": {"nested": True}})
        assert isinstance(result["x"], str)


class TestLooksBlobLikeSummary:
    def test_empty_is_blob(self) -> None:
        assert EventIngester._looks_blob_like_summary("") is True

    def test_normal_text(self) -> None:
        assert EventIngester._looks_blob_like_summary("User prefers dark mode") is False

    def test_json_blob(self) -> None:
        assert EventIngester._looks_blob_like_summary('{"key": "val"}') is True

    def test_multiline_blob(self) -> None:
        assert EventIngester._looks_blob_like_summary("a\nb\nc\nd\ne") is True


class TestIngesterWithUnifiedDB:
    """Tests for ingester writing to UnifiedMemoryDB."""

    def _make_ingester_with_db(self, tmp_path: Path) -> tuple[EventIngester, Any, MagicMock]:
        from nanobot.agent.memory.unified_db import UnifiedMemoryDB

        db = UnifiedMemoryDB(tmp_path / "memory.db", dims=4)
        persistence = MagicMock()
        mem0 = MagicMock()
        mem0.enabled = False
        graph = MagicMock()
        graph.enabled = False

        ingester = EventIngester(
            persistence=persistence,
            mem0=mem0,
            graph=graph,
            rollout={},
            conflict_pair_fn=lambda old, new: False,
            db=db,
            embedder=None,
        )
        return ingester, db, persistence

    def test_events_written_to_db_not_persistence(self, tmp_path: Path) -> None:
        ingester, db, persistence = self._make_ingester_with_db(tmp_path)
        ingester.append_events(
            [
                {
                    "id": "test-001",
                    "type": "fact",
                    "summary": "User likes coffee",
                    "timestamp": "2026-01-01T00:00:00Z",
                }
            ]
        )
        events = db.read_events(limit=10)
        assert len(events) >= 1
        assert any("coffee" in e["summary"] for e in events)
        # persistence.write_jsonl should NOT have been called
        persistence.write_jsonl.assert_not_called()
        db.close()

    def test_read_events_from_db(self, tmp_path: Path) -> None:
        ingester, db, persistence = self._make_ingester_with_db(tmp_path)
        ingester.append_events(
            [
                {
                    "id": "test-002",
                    "type": "fact",
                    "summary": "Test event",
                    "timestamp": "2026-01-01T00:00:00Z",
                }
            ]
        )
        events = ingester.read_events(limit=10)
        assert len(events) >= 1
        db.close()

    def test_sync_events_to_mem0_noop_with_db(self, tmp_path: Path) -> None:
        ingester, db, _persistence = self._make_ingester_with_db(tmp_path)
        result = ingester._sync_events_to_mem0([{"type": "fact", "summary": "ignored", "id": "x"}])
        assert result == 0
        db.close()

    def test_old_path_used_when_db_is_none(self, tmp_path: Path) -> None:
        """When db is None, persistence.write_jsonl IS called."""
        persistence = MagicMock(spec=MemoryPersistence)
        persistence.events_file = tmp_path / "events.jsonl"
        persistence.read_jsonl.return_value = []
        mem0 = MagicMock()
        mem0.enabled = False
        graph = MagicMock()
        graph.enabled = False

        ingester = EventIngester(
            persistence=persistence,
            mem0=mem0,
            graph=graph,
            rollout={},
            conflict_pair_fn=lambda old, new: False,
            db=None,
            embedder=None,
        )
        ingester.append_events(
            [
                {
                    "id": "test-003",
                    "type": "fact",
                    "summary": "Old path event",
                    "timestamp": "2026-01-01T00:00:00Z",
                }
            ]
        )
        persistence.write_jsonl.assert_called_once()
