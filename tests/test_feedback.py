"""Tests for the feedback tool and reaction → feedback pipeline (Step 8)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from nanobot.agent.reaction import classify_reaction
from nanobot.bus.events import ReactionEvent
from nanobot.context.feedback_context import feedback_summary, load_feedback_events
from nanobot.memory.unified_db import UnifiedMemoryDB
from nanobot.tools.builtin.feedback import FeedbackTool

# ---------------------------------------------------------------------------
# FeedbackTool unit tests
# ---------------------------------------------------------------------------


class TestFeedbackTool:
    """Test the FeedbackTool schema, validation, and persistence."""

    @pytest.fixture()
    def db(self, tmp_path: Path) -> UnifiedMemoryDB:
        return UnifiedMemoryDB(tmp_path / "memory.db", dims=8)

    @pytest.fixture()
    def tool(self, db: UnifiedMemoryDB) -> FeedbackTool:
        t = FeedbackTool(db=db)
        t.set_context("telegram", "chat123", session_key="telegram:chat123")
        return t

    def test_schema_has_required_fields(self, tool: FeedbackTool) -> None:
        schema = tool.parameters
        assert "rating" in schema["properties"]
        assert schema["properties"]["rating"]["enum"] == ["positive", "negative"]
        assert "rating" in schema["required"]

    def test_name_and_description(self, tool: FeedbackTool) -> None:
        assert tool.name == "feedback"
        assert "feedback" in tool.description.lower()

    async def test_positive_feedback(self, tool: FeedbackTool, db: UnifiedMemoryDB) -> None:
        result = await tool.execute(rating="positive", comment="great answer")
        assert result.success
        assert "positive" in result.output.lower()

        # Verify persisted in database
        events = db.read_events(type="feedback")
        assert len(events) == 1
        event = events[0]
        assert event["type"] == "feedback"
        meta = json.loads(event["metadata"])
        assert meta["rating"] == "positive"
        assert meta["comment"] == "great answer"
        assert meta["channel"] == "telegram"

    async def test_negative_feedback_with_topic(
        self, tool: FeedbackTool, db: UnifiedMemoryDB
    ) -> None:
        result = await tool.execute(rating="negative", comment="wrong date", topic="calendar")
        assert result.success
        assert "negative" in result.output.lower()

        events = db.read_events(type="feedback")
        assert len(events) == 1
        meta = json.loads(events[0]["metadata"])
        assert meta["rating"] == "negative"
        assert meta["topic"] == "calendar"

    async def test_invalid_rating(self, tool: FeedbackTool) -> None:
        result = await tool.execute(rating="maybe")
        assert not result.success
        assert "positive" in result.output or "negative" in result.output

    async def test_minimal_feedback(self, tool: FeedbackTool, db: UnifiedMemoryDB) -> None:
        """Only rating is required."""
        result = await tool.execute(rating="positive")
        assert result.success
        events = db.read_events(type="feedback")
        meta = json.loads(events[0]["metadata"])
        assert "comment" not in meta  # omitted when empty

    async def test_multiple_events_appended(self, tool: FeedbackTool, db: UnifiedMemoryDB) -> None:
        await tool.execute(rating="positive")
        await tool.execute(rating="negative", comment="fix this")
        await tool.execute(rating="positive", topic="weather")
        events = db.read_events(type="feedback", limit=100)
        assert len(events) == 3

    async def test_no_db(self) -> None:
        """When db is None, feedback still succeeds (just not persisted)."""
        tool = FeedbackTool(db=None)
        result = await tool.execute(rating="positive")
        assert result.success


# ---------------------------------------------------------------------------
# ReactionEvent tests
# ---------------------------------------------------------------------------


class TestReactionEvent:
    """Test emoji → rating mapping."""

    @pytest.mark.parametrize(
        "emoji,expected",
        [
            ("\U0001f44d", "positive"),  # 👍
            ("+1", "positive"),
            ("THUMBSUP", "positive"),
            ("heart", "positive"),
            ("\u2764", "positive"),
            ("DONE", "positive"),
            ("\U0001f44e", "negative"),  # 👎
            ("-1", "negative"),
            ("THUMBSDOWN", "negative"),
            ("angry", "negative"),
            ("fire", None),  # unmapped
            ("\U0001f525", None),  # 🔥
        ],
    )
    def test_rating_mapping(self, emoji: str, expected: str | None) -> None:
        event = ReactionEvent(
            channel="telegram",
            sender_id="user1",
            chat_id="chat1",
            emoji=emoji,
        )
        assert classify_reaction(event.emoji) == expected


# ---------------------------------------------------------------------------
# feedback_summary / load_feedback_events tests
# ---------------------------------------------------------------------------


def _insert_feedback(db: UnifiedMemoryDB, events: list[dict[str, Any]]) -> None:
    """Insert feedback events into the database for testing."""
    for i, e in enumerate(events):
        event_type = e.get("type", "feedback")
        # Build metadata from feedback-specific fields
        metadata: dict[str, Any] = {}
        for key in ("rating", "comment", "topic", "channel", "chat_id", "session_key"):
            if key in e:
                metadata[key] = e[key]

        summary = e.get("summary", e.get("rating", ""))
        db.insert_event(
            {
                "id": e.get("id", f"test-{i}"),
                "type": event_type,
                "summary": summary,
                "timestamp": e.get("timestamp", f"2026-01-01T00:00:{i:02d}Z"),
                "metadata": metadata if metadata else None,
            }
        )


class TestFeedbackSummary:
    """Test aggregation helpers."""

    @pytest.fixture()
    def db(self, tmp_path: Path) -> UnifiedMemoryDB:
        return UnifiedMemoryDB(tmp_path / "memory.db", dims=8)

    def test_empty_db(self, db: UnifiedMemoryDB) -> None:
        assert feedback_summary(db) == ""

    def test_load_filters_by_type(self, db: UnifiedMemoryDB) -> None:
        _insert_feedback(
            db,
            [
                {"type": "feedback", "rating": "positive"},
                {"type": "preference", "summary": "likes coffee"},
                {"type": "feedback", "rating": "negative"},
            ],
        )
        items = load_feedback_events(db)
        assert len(items) == 2
        assert all(e.get("rating") in ("positive", "negative") for e in items)

    def test_summary_counts(self, db: UnifiedMemoryDB) -> None:
        _insert_feedback(
            db,
            [
                {"type": "feedback", "rating": "positive"},
                {"type": "feedback", "rating": "positive"},
                {
                    "type": "feedback",
                    "rating": "negative",
                    "comment": "wrong answer",
                    "topic": "math",
                },
            ],
        )
        result = feedback_summary(db)
        assert "2 positive" in result
        assert "1 negative" in result
        assert "3 total" in result

    def test_summary_includes_corrections(self, db: UnifiedMemoryDB) -> None:
        _insert_feedback(
            db,
            [
                {
                    "type": "feedback",
                    "rating": "negative",
                    "comment": "that date was wrong",
                    "topic": "calendar",
                },
                {"type": "feedback", "rating": "negative", "comment": "incorrect formula"},
            ],
        )
        result = feedback_summary(db)
        assert "that date was wrong" in result
        assert "incorrect formula" in result

    def test_summary_topic_frequency(self, db: UnifiedMemoryDB) -> None:
        _insert_feedback(
            db,
            [
                {"type": "feedback", "rating": "negative", "topic": "math"},
                {"type": "feedback", "rating": "negative", "topic": "math"},
                {"type": "feedback", "rating": "negative", "topic": "calendar"},
            ],
        )
        result = feedback_summary(db)
        assert "math (2x)" in result

    def test_non_feedback_events_ignored_in_summary(self, db: UnifiedMemoryDB) -> None:
        _insert_feedback(
            db,
            [
                {"type": "task", "summary": "deploy app"},
                {"type": "fact", "summary": "sky is blue"},
            ],
        )
        assert feedback_summary(db) == ""
