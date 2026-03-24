"""Tests for CheckEmailTool."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest

from nanobot.tools.builtin.email import CheckEmailTool


def _sample_messages(n: int = 2) -> list[dict[str, Any]]:
    """Return sample email dicts matching EmailChannel's _fetch_messages format."""
    msgs = []
    for i in range(1, n + 1):
        msgs.append(
            {
                "sender": f"user{i}@example.com",
                "subject": f"Subject {i}",
                "message_id": f"<msg{i}@example.com>",
                "content": f"Email received.\nFrom: user{i}@example.com\nSubject: Subject {i}\n\nBody of email {i}",
                "metadata": {
                    "message_id": f"<msg{i}@example.com>",
                    "subject": f"Subject {i}",
                    "date": f"Mon, {i} Jan 2026 09:00:00 +0000",
                    "sender_email": f"user{i}@example.com",
                    "uid": str(100 + i),
                },
            }
        )
    return msgs


class TestCheckEmailToolNoop:
    """When no callbacks are set, tool reports the channel as unavailable."""

    @pytest.fixture()
    def tool(self) -> CheckEmailTool:
        return CheckEmailTool()

    async def test_no_callbacks_returns_fail(self, tool: CheckEmailTool) -> None:
        result = await tool.execute()
        assert not result.success
        assert "not configured" in result.output.lower() or "not available" in result.output.lower()

    async def test_date_range_no_callbacks_returns_fail(self, tool: CheckEmailTool) -> None:
        result = await tool.execute(start_date="2026-01-01", end_date="2026-01-02")
        assert not result.success


class TestCheckEmailToolUnread:
    """Unread fetch mode."""

    async def test_unread_returns_messages(self) -> None:
        msgs = _sample_messages(2)
        tool = CheckEmailTool(fetch_unread_callback=lambda limit: msgs[:limit])
        result = await tool.execute(period="unread", limit=10)
        assert result.success
        assert "2 email(s)" in result.output
        assert "user1@example.com" in result.output
        assert "Subject 2" in result.output

    async def test_unread_empty(self) -> None:
        tool = CheckEmailTool(fetch_unread_callback=lambda limit: [])
        result = await tool.execute(period="unread")
        assert result.success
        assert "No emails found" in result.output

    async def test_default_period_is_unread(self) -> None:
        called_with: list[int] = []

        def cb(limit: int) -> list[dict[str, Any]]:
            called_with.append(limit)
            return []

        tool = CheckEmailTool(fetch_unread_callback=cb)
        await tool.execute()
        assert len(called_with) == 1

    async def test_unread_fallback_to_today_range(self) -> None:
        """If only fetch_callback (date range) is set, unread falls back to today."""
        today = date.today()
        called_dates: list[tuple[date, date]] = []

        def fetch_cb(start: date, end: date, limit: int) -> list[dict[str, Any]]:
            called_dates.append((start, end))
            return []

        tool = CheckEmailTool(fetch_callback=fetch_cb)
        result = await tool.execute(period="unread")
        assert result.success
        assert len(called_dates) == 1
        assert called_dates[0][0] == today


class TestCheckEmailToolDateRange:
    """Date-range fetch mode."""

    async def test_today(self) -> None:
        today = date.today()
        called: list[tuple[date, date, int]] = []

        def cb(start: date, end: date, limit: int) -> list[dict[str, Any]]:
            called.append((start, end, limit))
            return _sample_messages(1)

        tool = CheckEmailTool(fetch_callback=cb)
        result = await tool.execute(period="today")
        assert result.success
        assert called[0][0] == today
        assert called[0][1] == today + timedelta(days=1)

    async def test_yesterday(self) -> None:
        today = date.today()
        called: list[tuple[date, date, int]] = []

        def cb(start: date, end: date, limit: int) -> list[dict[str, Any]]:
            called.append((start, end, limit))
            return []

        tool = CheckEmailTool(fetch_callback=cb)
        result = await tool.execute(period="yesterday")
        assert result.success
        assert called[0][0] == today - timedelta(days=1)
        assert called[0][1] == today

    async def test_last_3_days(self) -> None:
        today = date.today()
        called: list[tuple[date, date, int]] = []

        def cb(start: date, end: date, limit: int) -> list[dict[str, Any]]:
            called.append((start, end, limit))
            return []

        tool = CheckEmailTool(fetch_callback=cb)
        result = await tool.execute(period="last_3_days")
        assert result.success
        assert called[0][0] == today - timedelta(days=3)

    async def test_last_7_days(self) -> None:
        today = date.today()
        called: list[tuple[date, date, int]] = []

        def cb(start: date, end: date, limit: int) -> list[dict[str, Any]]:
            called.append((start, end, limit))
            return []

        tool = CheckEmailTool(fetch_callback=cb)
        result = await tool.execute(period="last_7_days")
        assert result.success
        assert called[0][0] == today - timedelta(days=7)

    async def test_explicit_dates(self) -> None:
        called: list[tuple[date, date, int]] = []

        def cb(start: date, end: date, limit: int) -> list[dict[str, Any]]:
            called.append((start, end, limit))
            return _sample_messages(1)

        tool = CheckEmailTool(fetch_callback=cb)
        result = await tool.execute(start_date="2026-03-01", end_date="2026-03-10", limit=5)
        assert result.success
        assert called[0] == (date(2026, 3, 1), date(2026, 3, 10), 5)

    async def test_invalid_start_date(self) -> None:
        tool = CheckEmailTool(fetch_callback=lambda s, e, lim: [])
        result = await tool.execute(start_date="not-a-date")
        assert not result.success
        assert "Invalid start_date" in result.output

    async def test_invalid_end_date(self) -> None:
        tool = CheckEmailTool(fetch_callback=lambda s, e, lim: [])
        result = await tool.execute(start_date="2026-01-01", end_date="bad")
        assert not result.success
        assert "Invalid end_date" in result.output

    async def test_unknown_period(self) -> None:
        tool = CheckEmailTool(fetch_callback=lambda s, e, lim: [])
        result = await tool.execute(period="last_year")
        assert not result.success
        assert "Unknown period" in result.output


class TestCheckEmailToolFormatting:
    """Output formatting tests."""

    async def test_body_truncation(self) -> None:
        msgs = [
            {
                "sender": "alice@example.com",
                "subject": "Long email",
                "message_id": "<m@e.com>",
                "content": "X" * 1000,
                "metadata": {"date": "Mon, 1 Jan 2026 09:00:00 +0000"},
            }
        ]
        tool = CheckEmailTool(fetch_unread_callback=lambda limit: msgs)
        result = await tool.execute()
        assert result.success
        assert "\u2026" in result.output  # truncation marker
        # Body should be at most _MAX_BODY_PREVIEW + ellipsis
        body_line = [ln for ln in result.output.split("\n") if ln.startswith("Body:")][0]
        # 500 chars + "Body: " prefix + ellipsis
        assert len(body_line) <= 510

    async def test_limit_clamped(self) -> None:
        """Limit is clamped between 1 and 100."""
        tool = CheckEmailTool(fetch_unread_callback=lambda limit: [])
        result = await tool.execute(limit=0)
        assert result.success  # Should not crash; limit clamped to 1

    async def test_tool_schema(self) -> None:
        tool = CheckEmailTool()
        assert tool.name == "check_email"
        assert tool.readonly is True
        schema = tool.parameters
        assert "period" in schema["properties"]
        assert "start_date" in schema["properties"]
        assert "limit" in schema["properties"]
