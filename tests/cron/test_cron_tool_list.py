"""Tests for CronTool._list_jobs() output formatting."""

from datetime import datetime, timezone

from janniebot.agent.tools.cron import CronTool
from janniebot.cron.service import CronService
from janniebot.cron.types import CronJob, CronJobState, CronPayload, CronSchedule


def _make_tool(tmp_path) -> CronTool:
    service = CronService(tmp_path / "cron" / "jobs.json")
    return CronTool(service)


def _make_tool_with_tz(tmp_path, tz: str) -> CronTool:
    service = CronService(tmp_path / "cron" / "jobs.json")
    return CronTool(service, default_timezone=tz)


# -- _format_timing tests --


def test_format_timing_cron_with_tz(tmp_path) -> None:
    tool = _make_tool(tmp_path)
    s = CronSchedule(kind="cron", expr="0 9 * * 1-5", tz="America/Denver")
    assert tool._format_timing(s) == "cron: 0 9 * * 1-5 (America/Denver)"


def test_format_timing_cron_without_tz(tmp_path) -> None:
    tool = _make_tool(tmp_path)
    s = CronSchedule(kind="cron", expr="*/5 * * * *")
    assert tool._format_timing(s) == "cron: */5 * * * *"


def test_format_timing_every_hours(tmp_path) -> None:
    tool = _make_tool(tmp_path)
    s = CronSchedule(kind="every", every_ms=7_200_000)
    assert tool._format_timing(s) == "every 2h"


def test_format_timing_every_minutes(tmp_path) -> None:
    tool = _make_tool(tmp_path)
    s = CronSchedule(kind="every", every_ms=1_800_000)
    assert tool._format_timing(s) == "every 30m"


def test_format_timing_every_seconds(tmp_path) -> None:
    tool = _make_tool(tmp_path)
    s = CronSchedule(kind="every", every_ms=30_000)
    assert tool._format_timing(s) == "every 30s"


def test_format_timing_every_non_minute_seconds(tmp_path) -> None:
    tool = _make_tool(tmp_path)
    s = CronSchedule(kind="every", every_ms=90_000)
    assert tool._format_timing(s) == "every 90s"


def test_format_timing_every_milliseconds(tmp_path) -> None:
    tool = _make_tool(tmp_path)
    s = CronSchedule(kind="every", every_ms=200)
    assert tool._format_timing(s) == "every 200ms"


def test_format_timing_at(tmp_path) -> None:
    tool = _make_tool_with_tz(tmp_path, "Asia/Shanghai")
    s = CronSchedule(kind="at", at_ms=1773684000000)
    result = tool._format_timing(s)
    assert "Asia/Shanghai" in result
    assert result.startswith("at 2026-")


def test_format_timing_fallback(tmp_path) -> None:
    tool = _make_tool(tmp_path)
    s = CronSchedule(kind="every")  # no every_ms
    assert tool._format_timing(s) == "every"


# -- _format_state tests --


def test_format_state_empty(tmp_path) -> None:
    tool = _make_tool(tmp_path)
    state = CronJobState()
    assert tool._format_state(state, CronSchedule(kind="every")) == []


def test_format_state_last_run_ok(tmp_path) -> None:
    tool = _make_tool(tmp_path)
    state = CronJobState(last_run_at_ms=1773673200000, last_status="ok")
    lines = tool._format_state(state, CronSchedule(kind="cron", expr="0 9 * * *", tz="UTC"))
    assert len(lines) == 1
    assert "Last run:" in lines[0]
    assert "ok" in lines[0]


def test_format_state_last_run_with_error(tmp_path) -> None:
    tool = _make_tool(tmp_path)
    state = CronJobState(last_run_at_ms=1773673200000, last_status="error", last_error="timeout")
    lines = tool._format_state(state, CronSchedule(kind="cron", expr="0 9 * * *", tz="UTC"))
    assert len(lines) == 1
    assert "error" in lines[0]
    assert "timeout" in lines[0]


def test_format_state_next_run_only(tmp_path) -> None:
    tool = _make_tool(tmp_path)
    state = CronJobState(next_run_at_ms=1773684000000)
    lines = tool._format_state(state, CronSchedule(kind="cron", expr="0 9 * * *", tz="UTC"))
    assert len(lines) == 1
    assert "Next run:" in lines[0]


def test_format_state_both(tmp_path) -> None:
    tool = _make_tool(tmp_path)
    state = CronJobState(
        last_run_at_ms=1773673200000, last_status="ok", next_run_at_ms=1773684000000
    )
    lines = tool._format_state(state, CronSchedule(kind="cron", expr="0 9 * * *", tz="UTC"))
    assert len(lines) == 2
    assert "Last run:" in lines[0]
    assert "Next run:" in lines[1]


def test_format_state_unknown_status(tmp_path) -> None:
    tool = _make_tool(tmp_path)
    state = CronJobState(last_run_at_ms=1773673200000, last_status=None)
    lines = tool._format_state(state, CronSchedule(kind="cron", expr="0 9 * * *", tz="UTC"))
    assert "unknown" in lines[0]


# -- _list_jobs integration tests --


def test_list_empty(tmp_path) -> None:
    tool = _make_tool(tmp_path)
    assert tool._list_jobs() == "No scheduled jobs."


def test_list_cron_job_shows_expression_and_timezone(tmp_path) -> None:
    tool = _make_tool(tmp_path)
    tool._cron.add_job(
        name="Morning scan",
        schedule=CronSchedule(kind="cron", expr="0 9 * * 1-5", tz="America/Denver"),
        message="scan",
    )
    result = tool._list_jobs()
    assert "cron: 0 9 * * 1-5 (America/Denver)" in result


def test_list_every_job_shows_human_interval(tmp_path) -> None:
    tool = _make_tool(tmp_path)
    tool._cron.add_job(
        name="Frequent check",
        schedule=CronSchedule(kind="every", every_ms=1_800_000),
        message="check",
    )
    result = tool._list_jobs()
    assert "every 30m" in result


def test_list_every_job_hours(tmp_path) -> None:
    tool = _make_tool(tmp_path)
    tool._cron.add_job(
        name="Hourly check",
        schedule=CronSchedule(kind="every", every_ms=7_200_000),
        message="check",
    )
    result = tool._list_jobs()
    assert "every 2h" in result


def test_list_every_job_seconds(tmp_path) -> None:
    tool = _make_tool(tmp_path)
    tool._cron.add_job(
        name="Fast check",
        schedule=CronSchedule(kind="every", every_ms=30_000),
        message="check",
    )
    result = tool._list_jobs()
    assert "every 30s" in result


def test_list_every_job_non_minute_seconds(tmp_path) -> None:
    tool = _make_tool(tmp_path)
    tool._cron.add_job(
        name="Ninety-second check",
        schedule=CronSchedule(kind="every", every_ms=90_000),
        message="check",
    )
    result = tool._list_jobs()
    assert "every 90s" in result


def test_list_every_job_milliseconds(tmp_path) -> None:
    tool = _make_tool(tmp_path)
    tool._cron.add_job(
        name="Sub-second check",
        schedule=CronSchedule(kind="every", every_ms=200),
        message="check",
    )
    result = tool._list_jobs()
    assert "every 200ms" in result


def test_list_at_job_shows_iso_timestamp(tmp_path) -> None:
    tool = _make_tool_with_tz(tmp_path, "Asia/Shanghai")
    tool._cron.add_job(
        name="One-shot",
        schedule=CronSchedule(kind="at", at_ms=1773684000000),
        message="fire",
    )
    result = tool._list_jobs()
    assert "at 2026-" in result
    assert "Asia/Shanghai" in result


def test_list_shows_last_run_state(tmp_path) -> None:
    tool = _make_tool(tmp_path)
    job = tool._cron.add_job(
        name="Stateful job",
        schedule=CronSchedule(kind="cron", expr="0 9 * * *", tz="UTC"),
        message="test",
    )
    # Simulate a completed run by updating state in the store
    job.state.last_run_at_ms = 1773673200000
    job.state.last_status = "ok"
    tool._cron._save_store()

    result = tool._list_jobs()
    assert "Last run:" in result
    assert "ok" in result
    assert "(UTC)" in result


def test_list_shows_error_message(tmp_path) -> None:
    tool = _make_tool(tmp_path)
    job = tool._cron.add_job(
        name="Failed job",
        schedule=CronSchedule(kind="cron", expr="0 9 * * *", tz="UTC"),
        message="test",
    )
    job.state.last_run_at_ms = 1773673200000
    job.state.last_status = "error"
    job.state.last_error = "timeout"
    tool._cron._save_store()

    result = tool._list_jobs()
    assert "error" in result
    assert "timeout" in result


def test_list_shows_next_run(tmp_path) -> None:
    tool = _make_tool(tmp_path)
    tool._cron.add_job(
        name="Upcoming job",
        schedule=CronSchedule(kind="cron", expr="0 9 * * *", tz="UTC"),
        message="test",
    )
    result = tool._list_jobs()
    assert "Next run:" in result
    assert "(UTC)" in result


def test_list_includes_protected_dream_system_job_with_memory_purpose(tmp_path) -> None:
    tool = _make_tool(tmp_path)
    tool._cron.register_system_job(CronJob(
        id="dream",
        name="dream",
        schedule=CronSchedule(kind="cron", expr="0 */2 * * *", tz="UTC"),
        payload=CronPayload(kind="system_event"),
    ))

    result = tool._list_jobs()

    assert "- dream (id: dream, cron: 0 */2 * * * (UTC))" in result
    assert "Dream memory consolidation for long-term memory." in result
    assert "cannot be removed" in result


def test_remove_protected_dream_job_returns_clear_feedback(tmp_path) -> None:
    tool = _make_tool(tmp_path)
    tool._cron.register_system_job(CronJob(
        id="dream",
        name="dream",
        schedule=CronSchedule(kind="cron", expr="0 */2 * * *", tz="UTC"),
        payload=CronPayload(kind="system_event"),
    ))

    result = tool._remove_job("dream")

    assert "Cannot remove job `dream`." in result
    assert "Dream memory consolidation job for long-term memory" in result
    assert "cannot be removed" in result
    assert tool._cron.get_job("dream") is not None


def test_add_cron_job_defaults_to_tool_timezone(tmp_path) -> None:
    tool = _make_tool_with_tz(tmp_path, "Asia/Shanghai")
    tool.set_context("telegram", "chat-1")

    result = tool._add_job("Morning standup", None, "0 8 * * *", None, None)

    assert result.startswith("Created job")
    job = tool._cron.list_jobs()[0]
    assert job.schedule.tz == "Asia/Shanghai"


def test_add_at_job_uses_default_timezone_for_naive_datetime(tmp_path) -> None:
    tool = _make_tool_with_tz(tmp_path, "Asia/Shanghai")
    tool.set_context("telegram", "chat-1")

    result = tool._add_job("Morning reminder", None, None, None, "2026-03-25T08:00:00")

    assert result.startswith("Created job")
    job = tool._cron.list_jobs()[0]
    expected = int(datetime(2026, 3, 25, 0, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
    assert job.schedule.at_ms == expected


def test_add_job_delivers_by_default(tmp_path) -> None:
    tool = _make_tool(tmp_path)
    tool.set_context("telegram", "chat-1")

    result = tool._add_job("Morning standup", 60, None, None, None)

    assert result.startswith("Created job")
    job = tool._cron.list_jobs()[0]
    assert job.payload.deliver is True


def test_add_job_can_disable_delivery(tmp_path) -> None:
    tool = _make_tool(tmp_path)
    tool.set_context("telegram", "chat-1")

    result = tool._add_job("Background refresh", 60, None, None, None, deliver=False)

    assert result.startswith("Created job")
    job = tool._cron.list_jobs()[0]
    assert job.payload.deliver is False


def test_list_excludes_disabled_jobs(tmp_path) -> None:
    tool = _make_tool(tmp_path)
    job = tool._cron.add_job(
        name="Paused job",
        schedule=CronSchedule(kind="cron", expr="0 9 * * *", tz="UTC"),
        message="test",
    )
    tool._cron.enable_job(job.id, enabled=False)

    result = tool._list_jobs()
    assert "Paused job" not in result
    assert result == "No scheduled jobs."
