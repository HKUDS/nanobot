"""Editing task instructions must not postpone or drop an existing occurrence."""

from dataclasses import replace

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
