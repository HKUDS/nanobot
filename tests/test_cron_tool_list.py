"""Tests for CronTool._list_jobs() output formatting."""

from nanobot.cron.service import CronService
from nanobot.cron.types import CronJob, CronJobState, CronSchedule
from nanobot.agent.tools.cron import CronTool


def _make_tool(tmp_path) -> CronTool:
    service = CronService(tmp_path / "cron" / "jobs.json")
    return CronTool(service)


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
    assert "enabled" in result


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


def test_list_at_job_shows_iso_timestamp(tmp_path) -> None:
    tool = _make_tool(tmp_path)
    tool._cron.add_job(
        name="One-shot",
        schedule=CronSchedule(kind="at", at_ms=1773684000000),
        message="fire",
    )
    result = tool._list_jobs()
    assert "at 2026-" in result


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
