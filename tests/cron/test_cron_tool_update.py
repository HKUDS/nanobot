"""Update scheduled tasks through the public tool boundary."""

from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import pytest

from nanobot.agent.tools.cron import CronTool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.cron.service import CronService
from nanobot.cron.types import CronJob, CronPayload, CronSchedule


def _registry(service):
    tools = ToolRegistry()
    tools.register(CronTool(service, default_timezone="UTC"))
    return tools


def _job(service, *, delete_after_run=False):
    schedule = CronSchedule(kind="cron", expr="0 9 * * *", tz="America/Denver")
    if delete_after_run:
        schedule = CronSchedule(kind="at", at_ms=int(datetime(2099, 1, 2, tzinfo=timezone.utc).timestamp() * 1000))
    return service.add_job(
        name="Daily report", message="Check open issues",
        schedule=schedule,
        session_key="websocket:reports", origin_channel="websocket", origin_chat_id="reports",
        delete_after_run=delete_after_run,
    )


async def test_update_text_keeps_schedule_routing_and_history(tmp_path: Path):
    async def run(_job):
        return "Report ready"

    path = tmp_path / "jobs.json"
    service = CronService(path, on_job=run)
    job = _job(service)
    await service.run_job(job.id, force=True)
    before = service.get_job(job.id)
    identity = (before.id, asdict(before.schedule), before.state.next_run_at_ms, list(before.state.run_history))
    route = (before.payload.session_key, before.payload.origin_channel, before.payload.origin_chat_id)
    result = await _registry(service).execute("cron", {
        "action": "update", "job_id": job.id, "name": "Issue report", "message": "Check only assigned issues",
    })
    assert "Updated" in result
    saved = CronService(path).get_job(job.id)
    assert saved.name == "Issue report" and saved.payload.message == "Check only assigned issues"
    assert (saved.id, asdict(saved.schedule), saved.state.next_run_at_ms, saved.state.run_history) == identity
    assert (saved.payload.session_key, saved.payload.origin_channel, saved.payload.origin_chat_id) == route


@pytest.mark.parametrize("tz, supplied_tz, expected", [
    ("America/Denver", None, "America/Denver"),
    (None, None, None),
    ("America/Denver", "UTC", "UTC"),
])
async def test_update_cron_uses_supplied_or_existing_timezone(tmp_path: Path, tz, supplied_tz, expected):
    service = CronService(tmp_path / "jobs.json")
    job = _job(service)
    service.update_job(job.id, schedule=CronSchedule(kind="cron", expr="0 9 * * *", tz=tz))
    before = service.get_job(job.id)
    next_run = before.state.next_run_at_ms
    params = {"action": "update", "job_id": job.id, "cron_expr": "0 10 * * *"}
    if supplied_tz is not None:
        params["tz"] = supplied_tz
    result = await _registry(service).execute("cron", params)
    assert "Updated" in result
    saved = service.get_job(job.id)
    assert saved.schedule.expr == "0 10 * * *"
    assert saved.schedule.tz == expected
    assert saved.state.next_run_at_ms != next_run
    assert saved.payload.message == "Check open issues"


async def test_update_keeps_disabled_task_disabled(tmp_path: Path):
    service = CronService(tmp_path / "jobs.json")
    job = _job(service)
    service.enable_job(job.id, False)
    result = await _registry(service).execute("cron", {
        "action": "update", "job_id": job.id, "every_seconds": 120,
    })
    assert "Updated" in result
    saved = service.get_job(job.id)
    assert saved.schedule.kind == "every" and saved.schedule.every_ms == 120_000
    assert not saved.enabled and saved.state.next_run_at_ms is None


@pytest.mark.parametrize("delete_after_run", [False, True])
async def test_update_preserves_existing_one_time_deletion_policy(tmp_path: Path, delete_after_run):
    service = CronService(tmp_path / "jobs.json")
    job = _job(service, delete_after_run=delete_after_run)
    result = await _registry(service).execute("cron", {
        "action": "update", "job_id": job.id, "at": "2099-01-01T09:00:00+00:00",
    })
    assert "Updated" in result
    assert service.get_job(job.id).delete_after_run == delete_after_run
    await service.run_job(job.id, force=True)
    saved = service.get_job(job.id)
    if delete_after_run:
        assert saved is None
    else:
        assert saved is not None and not saved.enabled
        assert len(saved.state.run_history) == 1


@pytest.mark.parametrize("changes, error", [
    ({}, "at least one"),
    ({"name": " "}, "name must not be empty"),
    ({"message": " "}, "message must not be empty"),
    ({"every_seconds": 30, "cron_expr": "0 10 * * *"}, "exactly one"),
    ({"name": "Renamed", "message": "New instruction", "cron_expr": "not a cron"}, "invalid cron expression"),
    ({"cron_expr": "0 10 * * *", "tz": "Bad/Zone"}, "unknown timezone"),
    ({"tz": "UTC"}, "tz can only"),
    ({"at": "2000-01-01T00:00:00+00:00"}, "not in the future"),
])
async def test_invalid_update_keeps_task_unchanged(tmp_path: Path, changes, error):
    service = CronService(tmp_path / "jobs.json")
    job = _job(service)
    before = asdict(service.get_job(job.id))
    result = await _registry(service).execute("cron", {"action": "update", "job_id": job.id, **changes})
    assert error in result
    assert asdict(service.get_job(job.id)) == before


async def test_update_requires_job_id(tmp_path: Path):
    result = await _registry(CronService(tmp_path / "jobs.json")).execute("cron", {"action": "update", "name": "Renamed"})
    assert "job_id is required" in result


async def test_update_reports_missing_task(tmp_path: Path):
    result = await _registry(CronService(tmp_path / "jobs.json")).execute("cron", {"action": "update", "job_id": "missing", "name": "Renamed"})
    assert "job missing not found" in result


async def test_update_protects_system_task(tmp_path: Path):
    service = CronService(tmp_path / "jobs.json")
    job = service.register_system_job(CronJob(
        id="dream", name="dream", schedule=CronSchedule(kind="every", every_ms=60_000),
        payload=CronPayload(kind="system_event"),
    ))
    result = await _registry(service).execute("cron", {"action": "update", "job_id": job.id, "name": "Renamed"})
    assert "protected" in result
    assert service.get_job(job.id).name == "dream"
