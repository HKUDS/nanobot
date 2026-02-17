"""Tests for cron service behavior and persistence edges."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from nanobot.cron.service import CronService, _compute_next_run
from nanobot.cron.types import CronSchedule


def test_compute_next_run_at_invalid_when_past_or_now() -> None:
    """Returns no next run for expired one-shot schedules."""
    now_ms = 1_000
    assert _compute_next_run(CronSchedule(kind="at", at_ms=now_ms), now_ms) is None
    assert _compute_next_run(CronSchedule(kind="at", at_ms=now_ms - 1), now_ms) is None


@pytest.mark.parametrize("every_ms", [None, 0, -1])
def test_compute_next_run_every_invalid_values(every_ms: int | None) -> None:
    """Returns no next run for invalid every intervals."""
    assert _compute_next_run(CronSchedule(kind="every", every_ms=every_ms), 1_000) is None


def test_add_remove_enable_and_status_flow(tmp_path) -> None:
    """Supports add/remove/enable updates and reflects status."""
    service = CronService(tmp_path / "jobs.json")

    job = service.add_job(
        name="heartbeat",
        schedule=CronSchedule(kind="every", every_ms=1_000),
        message="ping",
    )
    assert job.enabled is True
    assert job.state.next_run_at_ms is not None

    status_after_add = service.status()
    assert status_after_add["jobs"] == 1
    assert status_after_add["next_wake_at_ms"] is not None

    disabled = service.enable_job(job.id, enabled=False)
    assert disabled is not None
    assert disabled.enabled is False
    assert disabled.state.next_run_at_ms is None

    enabled = service.enable_job(job.id, enabled=True)
    assert enabled is not None
    assert enabled.enabled is True
    assert enabled.state.next_run_at_ms is not None

    assert service.remove_job(job.id) is True
    assert service.remove_job(job.id) is False
    assert service.status()["jobs"] == 0


@pytest.mark.asyncio
async def test_run_job_force_allows_disabled_execution(tmp_path) -> None:
    """Runs disabled jobs only when force is enabled."""
    on_job = AsyncMock(return_value="ok")
    service = CronService(tmp_path / "jobs.json", on_job=on_job)

    job = service.add_job(
        name="manual",
        schedule=CronSchedule(kind="every", every_ms=1_000),
        message="run",
    )
    service.enable_job(job.id, enabled=False)

    ran_without_force = await service.run_job(job.id, force=False)
    assert ran_without_force is False
    on_job.assert_not_awaited()

    ran_with_force = await service.run_job(job.id, force=True)
    assert ran_with_force is True
    on_job.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_job_error_updates_state(tmp_path) -> None:
    """Stores error status and message when execution fails."""

    async def _boom(_job):
        raise RuntimeError("boom")

    service = CronService(tmp_path / "jobs.json", on_job=_boom)
    job = service.add_job(
        name="fails",
        schedule=CronSchedule(kind="every", every_ms=1_000),
        message="fail",
    )

    assert await service.run_job(job.id, force=True) is True

    reloaded = service.list_jobs(include_disabled=True)[0]
    assert reloaded.state.last_status == "error"
    assert reloaded.state.last_error == "boom"
    assert reloaded.state.last_run_at_ms is not None
    assert reloaded.state.next_run_at_ms is not None


def test_corrupt_json_load_falls_back_to_empty_store(tmp_path) -> None:
    """Recovers from invalid store JSON by using an empty store."""
    store_path = tmp_path / "jobs.json"
    store_path.write_text("{not-valid-json")

    service = CronService(store_path)
    assert service.list_jobs(include_disabled=True) == []
    assert service.status()["jobs"] == 0
