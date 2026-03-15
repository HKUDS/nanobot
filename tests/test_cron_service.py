import asyncio

import pytest

from nanobot.cron.service import CronService
from nanobot.cron.types import CronSchedule


def test_add_job_rejects_unknown_timezone(tmp_path) -> None:
    service = CronService(tmp_path / "cron" / "jobs.json")

    with pytest.raises(ValueError, match="unknown timezone 'America/Vancovuer'"):
        service.add_job(
            name="tz typo",
            schedule=CronSchedule(kind="cron", expr="0 9 * * *", tz="America/Vancovuer"),
            message="hello",
        )

    assert service.list_jobs(include_disabled=True) == []


def test_add_job_accepts_valid_timezone(tmp_path) -> None:
    service = CronService(tmp_path / "cron" / "jobs.json")

    job = service.add_job(
        name="tz ok",
        schedule=CronSchedule(kind="cron", expr="0 9 * * *", tz="America/Vancouver"),
        message="hello",
    )

    assert job.schedule.tz == "America/Vancouver"
    assert job.state.next_run_at_ms is not None


def test_multi_instance_list_sees_jobs_from_other_instance(tmp_path) -> None:
    """Instance B should see jobs added by instance A (no stale cache)."""
    store_path = tmp_path / "cron" / "jobs.json"
    schedule = CronSchedule(kind="every", every_ms=60_000)

    service_a = CronService(store_path)
    service_b = CronService(store_path)

    # Prime service_b cache
    assert service_b.list_jobs(include_disabled=True) == []

    # A adds a job
    service_a.add_job(name="from_a", schedule=schedule, message="hello")

    # B should see it without restart
    jobs_b = service_b.list_jobs(include_disabled=True)
    assert [j.name for j in jobs_b] == ["from_a"]


def test_multi_instance_remove_does_not_clobber_other_jobs(tmp_path) -> None:
    """Removing a job from instance B must not drop unrelated jobs added by A."""
    store_path = tmp_path / "cron" / "jobs.json"
    schedule = CronSchedule(kind="every", every_ms=60_000)

    service_a = CronService(store_path)
    service_b = CronService(store_path)

    first = service_a.add_job(name="first", schedule=schedule, message="first")

    # Prime service_b cache with snapshot containing only "first"
    assert [j.name for j in service_b.list_jobs(include_disabled=True)] == ["first"]

    # A adds a second job
    service_a.add_job(name="second", schedule=schedule, message="second")

    # B removes the first job — must not clobber "second"
    assert service_b.remove_job(first.id) is True

    # Fresh reader should still see "second"
    reloaded = CronService(store_path)
    names = [j.name for j in reloaded.list_jobs(include_disabled=True)]
    assert names == ["second"]

@pytest.mark.asyncio
async def test_running_service_honors_external_disable(tmp_path) -> None:
    store_path = tmp_path / "cron" / "jobs.json"
    called: list[str] = []

    async def on_job(job) -> None:
        called.append(job.id)

    service = CronService(store_path, on_job=on_job)
    job = service.add_job(
        name="external-disable",
        schedule=CronSchedule(kind="every", every_ms=200),
        message="hello",
    )
    await service.start()
    try:
        # Wait slightly to ensure file mtime is definitively different
        await asyncio.sleep(0.05)
        external = CronService(store_path)
        updated = external.enable_job(job.id, enabled=False)
        assert updated is not None
        assert updated.enabled is False

        await asyncio.sleep(0.35)
        assert called == []
    finally:
        service.stop()
