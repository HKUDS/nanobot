"""Tests for the feedback tool and reaction → feedback pipeline (Step 8)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nanobot.agent.reaction import classify_reaction
from nanobot.bus.events import ReactionEvent
from nanobot.context.feedback_context import feedback_summary, load_feedback_events
from nanobot.tools.builtin.feedback import FeedbackTool

# ---------------------------------------------------------------------------
# FeedbackTool unit tests
# ---------------------------------------------------------------------------


class TestFeedbackTool:
    """Test the FeedbackTool schema, validation, and persistence."""

    @pytest.fixture()
    def events_file(self, tmp_path: Path) -> Path:
        return tmp_path / "memory" / "events.jsonl"

    @pytest.fixture()
    def tool(self, events_file: Path) -> FeedbackTool:
        t = FeedbackTool(events_file=events_file)
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

    async def test_positive_feedback(self, tool: FeedbackTool, events_file: Path) -> None:
        result = await tool.execute(rating="positive", comment="great answer")
        assert result.success
        assert "positive" in result.output.lower()

        # Verify persisted
        lines = events_file.read_text().strip().splitlines()
        assert len(lines) == 1
        event = json.loads(lines[0])
        assert event["type"] == "feedback"
        assert event["rating"] == "positive"
        assert event["comment"] == "great answer"
        assert event["channel"] == "telegram"

    async def test_negative_feedback_with_topic(
        self, tool: FeedbackTool, events_file: Path
    ) -> None:
        result = await tool.execute(rating="negative", comment="wrong date", topic="calendar")
        assert result.success
        assert "negative" in result.output.lower()

        event = json.loads(events_file.read_text().strip())
        assert event["rating"] == "negative"
        assert event["topic"] == "calendar"

    async def test_invalid_rating(self, tool: FeedbackTool) -> None:
        result = await tool.execute(rating="maybe")
        assert not result.success
        assert "positive" in result.output or "negative" in result.output

    async def test_minimal_feedback(self, tool: FeedbackTool, events_file: Path) -> None:
        """Only rating is required."""
        result = await tool.execute(rating="positive")
        assert result.success
        event = json.loads(events_file.read_text().strip())
        assert "comment" not in event  # omitted when empty

    async def test_multiple_events_appended(self, tool: FeedbackTool, events_file: Path) -> None:
        await tool.execute(rating="positive")
        await tool.execute(rating="negative", comment="fix this")
        await tool.execute(rating="positive", topic="weather")
        lines = events_file.read_text().strip().splitlines()
        assert len(lines) == 3

    async def test_no_events_file(self) -> None:
        """When events_file is None, feedback still succeeds (just not persisted)."""
        tool = FeedbackTool(events_file=None)
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


class TestFeedbackSummary:
    """Test aggregation helpers."""

    @pytest.fixture()
    def events_file(self, tmp_path: Path) -> Path:
        return tmp_path / "events.jsonl"

    def _write_events(self, path: Path, events: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for e in events:
                f.write(json.dumps(e) + "\n")

    def test_empty_file(self, events_file: Path) -> None:
        assert feedback_summary(events_file) == ""

    def test_missing_file(self, tmp_path: Path) -> None:
        assert feedback_summary(tmp_path / "nonexistent.jsonl") == ""

    def test_load_filters_by_type(self, events_file: Path) -> None:
        self._write_events(
            events_file,
            [
                {"type": "feedback", "rating": "positive"},
                {"type": "preference", "summary": "likes coffee"},
                {"type": "feedback", "rating": "negative"},
            ],
        )
        items = load_feedback_events(events_file)
        assert len(items) == 2
        assert all(e["type"] == "feedback" for e in items)

    def test_summary_counts(self, events_file: Path) -> None:
        self._write_events(
            events_file,
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
        result = feedback_summary(events_file)
        assert "2 positive" in result
        assert "1 negative" in result
        assert "3 total" in result

    def test_summary_includes_corrections(self, events_file: Path) -> None:
        self._write_events(
            events_file,
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
        result = feedback_summary(events_file)
        assert "that date was wrong" in result
        assert "incorrect formula" in result

    def test_summary_topic_frequency(self, events_file: Path) -> None:
        self._write_events(
            events_file,
            [
                {"type": "feedback", "rating": "negative", "topic": "math"},
                {"type": "feedback", "rating": "negative", "topic": "math"},
                {"type": "feedback", "rating": "negative", "topic": "calendar"},
            ],
        )
        result = feedback_summary(events_file)
        assert "math (2x)" in result

    def test_non_feedback_events_ignored_in_summary(self, events_file: Path) -> None:
        self._write_events(
            events_file,
            [
                {"type": "task", "summary": "deploy app"},
                {"type": "fact", "summary": "sky is blue"},
            ],
        )
        assert feedback_summary(events_file) == ""
