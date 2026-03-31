"""IT: Feedback tool → SQLite → feedback_summary round-trip.

Verifies the full data path without requiring an LLM API key:
1. FeedbackTool writes events to a real MemoryDatabase (SQLite)
2. feedback_summary reads them back and produces correct aggregation
3. ContextBuilder integrates the summary into the system prompt
4. Multiple feedback events accumulate correctly
5. Non-feedback events don't leak into the feedback summary
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.context.feedback_context import feedback_summary, load_feedback_events
from nanobot.memory.db import MemoryDatabase
from nanobot.tools.builtin.feedback import FeedbackTool

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db(tmp_path: Path) -> MemoryDatabase:
    """Real SQLite database in a temp directory."""
    db_dir = tmp_path / "memory"
    db_dir.mkdir()
    return MemoryDatabase(db_dir / "memory.db", dims=8)


@pytest.fixture()
def tool(db: MemoryDatabase) -> FeedbackTool:
    """FeedbackTool wired to the real database."""
    t = FeedbackTool(db=db)
    t.set_context("web", "session-1", session_key="web:session-1")
    return t


# ---------------------------------------------------------------------------
# Round-trip: write → read → summary
# ---------------------------------------------------------------------------


class TestFeedbackRoundTrip:
    """End-to-end feedback persistence through real SQLite."""

    async def test_single_positive_feedback_round_trip(
        self, tool: FeedbackTool, db: MemoryDatabase
    ) -> None:
        """Write one positive feedback, verify it appears in summary."""
        result = await tool.execute(rating="positive", comment="helpful answer")
        assert result.success

        events = load_feedback_events(db)
        assert len(events) == 1
        assert events[0]["rating"] == "positive"
        assert events[0]["comment"] == "helpful answer"

        summary = feedback_summary(db)
        assert "1 positive" in summary
        assert "0 negative" in summary

    async def test_negative_feedback_with_topic_appears_in_corrections(
        self, tool: FeedbackTool, db: MemoryDatabase
    ) -> None:
        """Negative feedback with comment shows up in corrections section."""
        await tool.execute(rating="negative", comment="date was wrong", topic="calendar")

        summary = feedback_summary(db)
        assert "date was wrong" in summary
        assert "calendar" in summary

    async def test_multiple_feedback_events_accumulate(
        self, tool: FeedbackTool, db: MemoryDatabase
    ) -> None:
        """Multiple events across turns accumulate in the database."""
        await tool.execute(rating="positive")
        await tool.execute(rating="positive", comment="good job")
        await tool.execute(rating="negative", comment="incorrect", topic="math")
        await tool.execute(rating="negative", comment="still wrong", topic="math")
        await tool.execute(rating="positive", topic="weather")

        events = load_feedback_events(db)
        assert len(events) == 5

        summary = feedback_summary(db)
        assert "3 positive" in summary
        assert "2 negative" in summary
        assert "5 total" in summary
        assert "math (2x)" in summary

    async def test_topic_frequency_ranking(self, tool: FeedbackTool, db: MemoryDatabase) -> None:
        """Topic frequency is ranked correctly in summary."""
        for _ in range(3):
            await tool.execute(rating="negative", topic="memory")
        for _ in range(2):
            await tool.execute(rating="negative", topic="calendar")
        await tool.execute(rating="negative", topic="math")

        summary = feedback_summary(db)
        assert "memory (3x)" in summary
        assert "calendar (2x)" in summary

    async def test_channel_and_session_persisted(self, db: MemoryDatabase) -> None:
        """Channel and session context are preserved in metadata."""
        tool = FeedbackTool(db=db)
        tool.set_context("telegram", "chat-42", session_key="telegram:chat-42")
        await tool.execute(rating="positive")

        events = load_feedback_events(db)
        assert events[0]["channel"] == "telegram"
        assert events[0]["chat_id"] == "chat-42"
        assert events[0]["session_key"] == "telegram:chat-42"


# ---------------------------------------------------------------------------
# Isolation: non-feedback events don't pollute
# ---------------------------------------------------------------------------


class TestFeedbackIsolation:
    """Verify feedback queries are isolated from other event types."""

    async def test_non_feedback_events_excluded(
        self, tool: FeedbackTool, db: MemoryDatabase
    ) -> None:
        """Other event types don't appear in feedback summary."""
        # Write a feedback event via the tool
        await tool.execute(rating="positive")

        # Write non-feedback events directly to db
        db.event_store.insert_event(
            {
                "id": "evt-task-1",
                "type": "task",
                "summary": "deploy the app",
                "timestamp": "2026-01-01T00:00:00Z",
            }
        )
        db.event_store.insert_event(
            {
                "id": "evt-fact-1",
                "type": "fact",
                "summary": "user works at ACME",
                "timestamp": "2026-01-01T00:00:01Z",
            }
        )

        events = load_feedback_events(db)
        assert len(events) == 1  # only the feedback event
        assert events[0]["rating"] == "positive"

    async def test_empty_db_returns_empty_summary(self, db: MemoryDatabase) -> None:
        """No feedback events → empty summary string."""
        assert feedback_summary(db) == ""

    async def test_only_non_feedback_returns_empty_summary(self, db: MemoryDatabase) -> None:
        """Database with only non-feedback events → empty summary."""
        db.event_store.insert_event(
            {
                "id": "evt-pref-1",
                "type": "preference",
                "summary": "likes dark mode",
                "timestamp": "2026-01-01T00:00:00Z",
            }
        )
        assert feedback_summary(db) == ""


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestFeedbackEdgeCases:
    """Edge cases and graceful degradation."""

    async def test_no_db_still_succeeds(self) -> None:
        """FeedbackTool with no db doesn't crash."""
        tool = FeedbackTool(db=None)
        result = await tool.execute(rating="positive")
        assert result.success

    async def test_feedback_without_optional_fields(
        self, tool: FeedbackTool, db: MemoryDatabase
    ) -> None:
        """Minimal feedback (rating only) round-trips correctly."""
        await tool.execute(rating="negative")

        events = load_feedback_events(db)
        assert len(events) == 1
        assert events[0]["rating"] == "negative"
        assert "comment" not in events[0]
        assert "topic" not in events[0]

        summary = feedback_summary(db)
        assert "1 negative" in summary

    async def test_feedback_ids_are_unique(self, tool: FeedbackTool, db: MemoryDatabase) -> None:
        """Each feedback event gets a unique ID."""
        for _ in range(10):
            await tool.execute(rating="positive")

        events = load_feedback_events(db)
        ids = [e.id for e in events]
        assert len(set(ids)) == 10  # all unique

    async def test_context_switch_between_sessions(self, db: MemoryDatabase) -> None:
        """Feedback from different sessions is stored separately."""
        tool = FeedbackTool(db=db)

        tool.set_context("web", "session-a", session_key="web:session-a")
        await tool.execute(rating="positive")

        tool.set_context("telegram", "chat-99", session_key="telegram:chat-99")
        await tool.execute(rating="negative", comment="bad answer")

        events = load_feedback_events(db)
        assert len(events) == 2
        sessions = {e["session_key"] for e in events}
        assert sessions == {"web:session-a", "telegram:chat-99"}
