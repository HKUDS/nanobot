from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from nanobot.agent.tools.cron import CronTool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.cron import service as cron_service
from nanobot.cron.service import CronJobSkippedError, CronService
from nanobot.cron.types import CronSchedule


def _registry(service: CronService) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(CronTool(service))
    return registry


def _job(service: CronService):
    return service.add_job(
        name="Daily report",
        schedule=CronSchedule(kind="cron", expr="0 9 * * *", tz="America/Denver"),
        message="Check open pull requests",
        session_key="websocket:chat-1", origin_channel="websocket", origin_chat_id="chat-1",
    )


async def test_history_reads_recent_runs_without_changing_job(tmp_path: Path, monkeypatch) -> None:
    now = 1773673200000
    monkeypatch.setattr(cron_service, "_now_ms", lambda: now)
    outcomes = iter(["ok"] * 5 + ["error", "skipped"])

    async def run(_job):
        nonlocal now
        now += 125
        outcome = next(outcomes)
        if outcome == "error":
            raise RuntimeError("Report failed")
        if outcome == "skipped":
            raise CronJobSkippedError("Chat busy")
        return "Report ready"

    path = tmp_path / "jobs.json"
    service = CronService(path, on_job=run)
    job = _job(service)
    for _ in range(7):
        await service.run_job(job.id, force=True)
        now += 60_000
    service.enable_job(job.id, enabled=False)
    reloaded = CronService(path)
    saved_job = reloaded.get_job(job.id)
    assert saved_job is not None
    before = path.read_bytes()
    registry = _registry(reloaded)

    default = await registry.execute("cron", {"action": "history", "job_id": job.id})
    assert len([line for line in default.splitlines() if line.startswith("- ")]) == 5
    limited = await registry.execute("cron", {"action": "history", "job_id": job.id, "limit": 2})
    assert "Report failed" in limited and "Chat busy" in limited
    assert "125ms" in limited and "America/Denver" in limited
    assert "ok" not in limited
    assert limited.index("skipped") < limited.index("error")
    latest = saved_job.state.run_history[-1]
    timestamp = datetime.fromtimestamp(latest.run_at_ms / 1000, ZoneInfo("America/Denver")).isoformat()
    assert timestamp in limited
    assert path.read_bytes() == before


async def test_history_reports_no_runs_for_existing_job(tmp_path: Path) -> None:
    service = CronService(tmp_path / "jobs.json")
    job = _job(service)
    result = await _registry(service).execute("cron", {"action": "history", "job_id": job.id})
    assert "No recorded runs" in result
    assert job.id in result


async def test_history_requires_job_id(tmp_path: Path) -> None:
    result = await _registry(CronService(tmp_path / "jobs.json")).execute("cron", {"action": "history"})
    assert "job_id is required" in result


async def test_history_reports_unknown_job(tmp_path: Path) -> None:
    result = await _registry(CronService(tmp_path / "jobs.json")).execute(
        "cron", {"action": "history", "job_id": "missing"},
    )
    assert "job missing not found" in result


@pytest.mark.parametrize("limit", [0, 21])
async def test_history_validates_limit(tmp_path: Path, limit: int) -> None:
    result = await _registry(CronService(tmp_path / "jobs.json")).execute(
        "cron", {"action": "history", "job_id": "test", "limit": limit},
    )
    assert "limit must be" in result
