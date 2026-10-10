"""Editing task instructions must not postpone or drop an existing occurrence."""

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from nanobot.cron.service import CronService
from nanobot.cron.types import CronJob, CronSchedule


@pytest.mark.parametrize("kind", ["every", "cron", "at"])
@pytest.mark.parametrize("resend_schedule", [False, True])
async def test_metadata_edit_preserves_due_occurrence(tmp_path, monkeypatch, kind, resend_schedule):
    now = 1_900_000_000_000
    monkeypatch.setattr("nanobot.cron.service._now_ms", lambda: now)
    schedules = {
        "every": CronSchedule(kind="every", every_ms=60_000),
        "cron": CronSchedule(kind="cron", expr="* * * * *", tz="UTC"),
        "at": CronSchedule(kind="at", at_ms=now + 60_000),
    }
    store_path = tmp_path / "cron" / "jobs.json"
    service = CronService(store_path)
    job = service.add_job(
        name="Daily report",
        schedule=schedules[kind],
        message="Summarize yesterday",
        session_key="websocket:report",
        origin_channel="websocket",
        origin_chat_id="report",
        delete_after_run=kind == "at",
    )
    due_at = job.state.next_run_at_ms
    assert due_at is not None
    now = due_at + 1_000

    updated = service.update_job(
        job.id,
        name="Updated report",
        message="Include the latest figures",
        schedule=replace(job.schedule) if resend_schedule else None,
    )
    assert isinstance(updated, CronJob)
    assert updated.state.next_run_at_ms == due_at

    calls = []

    async def execute(job):
        calls.append((job.id, job.name, job.payload.message))

    # A separate service consumes the persisted edit, as the gateway does.
    reader = CronService(store_path, on_job=execute)
    loaded = reader.get_job(job.id)
    assert loaded is not None
    assert loaded.state.next_run_at_ms == due_at
    await reader._on_timer()
    await reader._on_timer()
    assert calls == [(job.id, "Updated report", "Include the latest figures")]

    finished = reader.get_job(job.id)
    if kind == "at":
        assert finished is None
    else:
        assert finished is not None
        assert finished.state.next_run_at_ms > now
        assert len(finished.state.run_history) == 1
        assert finished.state.last_status == "ok"


@pytest.mark.parametrize("original_kind,delete_after_run", [("at", False), ("at", True), ("every", False)])
@pytest.mark.parametrize("replacement_kind", ["at", "every"])
@pytest.mark.parametrize("roundtrip", [False, True])
async def test_reschedule_during_execution_preserves_new_occurrence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    original_kind: str,
    delete_after_run: bool,
    replacement_kind: str,
    roundtrip: bool,
) -> None:
    now = 1_900_000_000_000
    monkeypatch.setattr("nanobot.cron.service._now_ms", lambda: now)
    entered = asyncio.Event()
    release = asyncio.Event()
    calls: list[str] = []

    async def execute(job: CronJob) -> None:
        calls.append(job.id)
        entered.set()
        await release.wait()

    service = CronService(tmp_path / "cron" / "jobs.json", on_job=execute)
    original = (
        CronSchedule(kind="at", at_ms=now + 60_000)
        if original_kind == "at"
        else CronSchedule(kind="every", every_ms=60_000)
    )
    job = service.add_job(
        name="Report",
        schedule=original,
        message="Summarize the latest figures",
        session_key="websocket:report",
        origin_channel="websocket",
        origin_chat_id="report",
        delete_after_run=delete_after_run,
    )
    pending = asyncio.create_task(service.run_job(job.id))
    try:
        async with asyncio.timeout(2):
            await entered.wait()
            replacement = (
                CronSchedule(kind="at", at_ms=now + 120_000)
                if replacement_kind == "at"
                else CronSchedule(kind="every", every_ms=120_000)
            )
            updated = service.update_job(job.id, schedule=replacement)
            assert isinstance(updated, CronJob)
            if roundtrip:
                now += 5_000
                replacement = original
                updated = service.update_job(job.id, schedule=original)
                assert isinstance(updated, CronJob)
            next_run = updated.state.next_run_at_ms
            assert next_run is not None
            now += 10_000
            release.set()
            assert await pending
    finally:
        release.set()
        await asyncio.gather(pending, return_exceptions=True)

    restored = CronService(service.store_path, on_job=execute)
    saved = restored.get_job(job.id)
    assert saved is not None
    assert saved.enabled
    assert saved.schedule == replacement
    assert saved.state.next_run_at_ms == next_run
    assert saved.state.last_status == "ok"
    assert len(saved.state.run_history) == 1

    now = next_run
    await restored._on_timer()
    assert calls == [job.id, job.id]
