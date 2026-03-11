from __future__ import annotations

from types import SimpleNamespace

import pytest

from nanobot.cron.service import CronService, _compute_next_run, _validate_schedule_for_add
from nanobot.cron.types import CronSchedule


def test_compute_next_run_variants() -> None:
    now = 1_000_000
    assert _compute_next_run(CronSchedule(kind="at", at_ms=now + 10), now) == now + 10
    assert _compute_next_run(CronSchedule(kind="at", at_ms=now - 1), now) is None
    assert _compute_next_run(CronSchedule(kind="every", every_ms=1000), now) == now + 1000
    assert _compute_next_run(CronSchedule(kind="every", every_ms=0), now) is None
    assert _compute_next_run(CronSchedule(kind="cron", expr="not a cron"), now) is None


def test_validate_schedule_for_add_non_cron_tz() -> None:
    with pytest.raises(ValueError, match="tz can only be used"):
        _validate_schedule_for_add(CronSchedule(kind="every", every_ms=1000, tz="UTC"))


def test_load_store_invalid_json(tmp_path) -> None:
    path = tmp_path / "cron" / "jobs.json"
    path.parent.mkdir(parents=True)
    path.write_text("not json", encoding="utf-8")
    service = CronService(path)
    assert service.list_jobs(include_disabled=True) == []


@pytest.mark.asyncio
async def test_start_status_stop(tmp_path) -> None:
    service = CronService(tmp_path / "cron" / "jobs.json")
    await service.start()
    status = service.status()
    assert status["enabled"] is True
    service.stop()
    assert service.status()["enabled"] is False


@pytest.mark.asyncio
async def test_execute_job_success_and_error_paths(tmp_path) -> None:
    path = tmp_path / "cron" / "jobs.json"

    called = {"ok": 0}

    async def _ok(job):
        called["ok"] += 1
        return "done"

    service = CronService(path, on_job=_ok)
    job = service.add_job(name="j1", schedule=CronSchedule(kind="every", every_ms=1000), message="hello")

    assert await service.run_job(job.id) is True
    assert called["ok"] == 1

    async def _boom(job):
        raise RuntimeError("boom")

    service.on_job = _boom
    assert await service.run_job(job.id, force=True) is True
    jobs = service.list_jobs(include_disabled=True)
    found = next(j for j in jobs if j.id == job.id)
    assert found.state.last_status in {"ok", "error"}


@pytest.mark.asyncio
async def test_run_job_force_disabled_and_not_found(tmp_path) -> None:
    service = CronService(tmp_path / "cron" / "jobs.json")
    job = service.add_job(name="j2", schedule=CronSchedule(kind="every", every_ms=1000), message="hello")
    service.enable_job(job.id, enabled=False)

    assert await service.run_job(job.id, force=False) is False
    assert await service.run_job(job.id, force=True) is True
    assert await service.run_job("missing") is False


def test_remove_and_enable_job_paths(tmp_path) -> None:
    service = CronService(tmp_path / "cron" / "jobs.json")
    job = service.add_job(name="j3", schedule=CronSchedule(kind="every", every_ms=1000), message="x")
    assert service.enable_job(job.id, enabled=False) is not None
    assert service.enable_job("missing", enabled=True) is None
    assert service.remove_job("missing") is False
    assert service.remove_job(job.id) is True


@pytest.mark.asyncio
async def test_at_job_delete_after_run(tmp_path) -> None:
    service = CronService(tmp_path / "cron" / "jobs.json")
    job = service.add_job(
        name="once",
        schedule=CronSchedule(kind="at", at_ms=9_999_999_999_999),
        message="once",
        delete_after_run=True,
    )
    await service._execute_job(job)
    assert not any(j.id == job.id for j in service.list_jobs(include_disabled=True))
