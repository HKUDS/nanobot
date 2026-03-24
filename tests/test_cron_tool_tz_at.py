"""Tests for CronTool at+tz timezone handling."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from nanobot.agent.tools.cron import CronTool
from nanobot.cron.service import CronService


def _make_tool(tmp_path) -> CronTool:
    service = CronService(tmp_path / "cron" / "jobs.json")
    tool = CronTool(service)
    tool.set_context("test-channel", "test-chat")
    return tool


@pytest.mark.asyncio
async def test_at_with_tz_naive_datetime(tmp_path) -> None:
    """Naive datetime + tz should be interpreted in the given timezone."""
    tool = _make_tool(tmp_path)
    result = await tool.execute(
        action="add",
        message="Shanghai reminder",
        at="2026-03-18T14:00:00",
        tz="Asia/Shanghai",
    )
    assert "Created job" in result

    jobs = tool._cron.list_jobs()
    assert len(jobs) == 1
    # Asia/Shanghai is UTC+8, so 14:00 Shanghai = 06:00 UTC
    expected_dt = datetime(2026, 3, 18, 14, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    expected_ms = int(expected_dt.timestamp() * 1000)
    assert jobs[0].schedule.at_ms == expected_ms


@pytest.mark.asyncio
async def test_at_with_tz_aware_datetime_preserves_original(tmp_path) -> None:
    """Datetime that already has tzinfo should not be overridden by tz param."""
    tool = _make_tool(tmp_path)
    # Pass an aware datetime (UTC) with a different tz param
    result = await tool.execute(
        action="add",
        message="UTC reminder",
        at="2026-03-18T06:00:00+00:00",
        tz="Asia/Shanghai",
    )
    assert "Created job" in result

    jobs = tool._cron.list_jobs()
    assert len(jobs) == 1
    # The +00:00 offset should be preserved (dt.tzinfo is not None, so tz is ignored)
    expected_dt = datetime(2026, 3, 18, 6, 0, 0, tzinfo=timezone.utc)
    expected_ms = int(expected_dt.timestamp() * 1000)
    assert jobs[0].schedule.at_ms == expected_ms


@pytest.mark.asyncio
async def test_tz_without_cron_or_at_fails(tmp_path) -> None:
    """Passing tz without cron_expr or at should return an error."""
    tool = _make_tool(tmp_path)
    result = await tool.execute(
        action="add",
        message="Bad config",
        tz="America/Vancouver",
    )
    assert "Error" in result
    assert "tz can only be used with cron_expr or at" in result


@pytest.mark.asyncio
async def test_at_without_tz_unchanged(tmp_path) -> None:
    """Naive datetime without tz should use system-local interpretation (existing behavior)."""
    tool = _make_tool(tmp_path)
    result = await tool.execute(
        action="add",
        message="Local reminder",
        at="2026-03-18T14:00:00",
    )
    assert "Created job" in result

    jobs = tool._cron.list_jobs()
    assert len(jobs) == 1
    # fromisoformat without tz → system local; just verify job was created
    local_dt = datetime.fromisoformat("2026-03-18T14:00:00")
    expected_ms = int(local_dt.timestamp() * 1000)
    assert jobs[0].schedule.at_ms == expected_ms


@pytest.mark.asyncio
async def test_at_with_invalid_tz_fails(tmp_path) -> None:
    """Invalid timezone should return an error."""
    tool = _make_tool(tmp_path)
    result = await tool.execute(
        action="add",
        message="Bad tz",
        at="2026-03-18T14:00:00",
        tz="Invalid/Timezone",
    )
    assert "Error" in result
    assert "unknown timezone" in result
