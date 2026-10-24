"""A manual run and a due timer must not execute the same job concurrently."""

import asyncio
from pathlib import Path

import pytest

from nanobot.cron.service import CronService
from nanobot.cron.types import CronJob, CronSchedule


@pytest.mark.parametrize(
    "first_entry,second_entry", [("manual", "manual"), ("timer", "manual"), ("manual", "timer")],
)
async def test_overlapping_runs_execute_job_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, first_entry: str, second_entry: str,
) -> None:
    now = 1_900_000_000_000
    monkeypatch.setattr("nanobot.cron.service._now_ms", lambda: now)
    entered = asyncio.Event()
    release = asyncio.Event()
    calls: list[str] = []

    async def execute(job: CronJob) -> None:
        calls.append(job.id)
        if len(calls) == 1:
            entered.set()
            await release.wait()

    service = CronService(tmp_path / "cron" / "jobs.json", on_job=execute)
    job = service.add_job(
        name="Report", schedule=CronSchedule(kind="every", every_ms=60_000),
        message="Summarize the latest figures", session_key="websocket:report",
        origin_channel="websocket", origin_chat_id="report",
    )
    assert job.state.next_run_at_ms is not None
    now = job.state.next_run_at_ms
    first = asyncio.create_task(
        service.run_job(job.id) if first_entry == "manual" else service._on_timer()
    )
    try:
        async with asyncio.timeout(2):
            await entered.wait()
            if second_entry == "manual":
                assert await service.run_job(job.id) is False
                assert await service.run_job(job.id, force=True) is False
            else:
                await service._on_timer()
            assert calls == [job.id]
    finally:
        release.set()
        await first
        service.stop()

    saved = CronService(service.store_path).get_job(job.id)
    assert saved is not None
    assert len(saved.state.run_history) == 1
    assert saved.state.last_status == "ok"
    # Finishing releases ownership; an intentional later manual run still works.
    assert await service.run_job(job.id) is True
    assert calls == [job.id, job.id]


async def test_cancelled_run_releases_job_for_later_execution(tmp_path: Path) -> None:
    entered = asyncio.Event()
    calls: list[str] = []

    async def execute(job: CronJob) -> None:
        calls.append(job.id)
        if len(calls) == 1:
            entered.set()
            await asyncio.Event().wait()

    service = CronService(tmp_path / "cron" / "jobs.json", on_job=execute)
    job = service.add_job(
        name="Report", schedule=CronSchedule(kind="every", every_ms=60_000),
        message="Summarize the latest figures", session_key="websocket:report",
        origin_channel="websocket", origin_chat_id="report",
    )
    first = asyncio.create_task(service.run_job(job.id))
    try:
        async with asyncio.timeout(2):
            await entered.wait()
    finally:
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        service.stop()

    assert await service.run_job(job.id) is True
    assert calls == [job.id, job.id]
