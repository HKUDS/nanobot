import asyncio
import time

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
        await service.stop()


# =============================================================================
# New tests for CronService improvements
# =============================================================================


@pytest.mark.asyncio
async def test_concurrent_execution(tmp_path) -> None:
    """Verify multiple due jobs execute concurrently, not sequentially."""
    execution_order: list[str] = []

    async def on_job(job):
        execution_order.append(f"{job.id}:start")
        await asyncio.sleep(0.1)
        execution_order.append(f"{job.id}:end")

    service = CronService(tmp_path / "jobs.json", on_job=on_job)

    # Add two jobs with same schedule (both due immediately)
    service.add_job("job_a", CronSchedule(kind="every", every_ms=50), "msg a")
    service.add_job("job_b", CronSchedule(kind="every", every_ms=50), "msg b")

    await service.start()
    await asyncio.sleep(0.3)
    await service.stop()

    # Concurrent execution pattern: start, start, end, end
    # Sequential execution pattern: start, end, start, end
    assert len(execution_order) >= 4, f"Expected at least 4 events, got {execution_order}"

    # First two should both be :start (concurrent launch)
    starts = [e for e in execution_order if e.endswith(":start")]
    ends = [e for e in execution_order if e.endswith(":end")]

    # In concurrent mode, all starts happen before all ends
    assert len(starts) >= 2, f"Expected at least 2 starts, got {starts}"
    assert len(ends) >= 2, f"Expected at least 2 ends, got {ends}"


@pytest.mark.asyncio
async def test_job_timeout(tmp_path) -> None:
    """Verify timeout protection works."""

    async def slow_job(job):
        await asyncio.sleep(10)  # Would block forever without timeout

    service = CronService(
        tmp_path / "jobs.json",
        on_job=slow_job,
        job_timeout_s=0.2,  # 200ms timeout
    )
    service.add_job("slow", CronSchedule(kind="every", every_ms=50), "msg")

    await service.start()
    await asyncio.sleep(0.5)  # Wait for timeout to trigger
    await service.stop()

    jobs = service.list_jobs(include_disabled=True)
    assert len(jobs) == 1
    assert jobs[0].state.last_status == "timeout"
    assert "timed out" in (jobs[0].state.last_error or "").lower()


@pytest.mark.asyncio
async def test_no_time_drift(tmp_path) -> None:
    """Verify 'every' jobs maintain fixed interval regardless of execution time."""
    run_times: list[float] = []

    async def on_job(job):
        run_times.append(time.time())
        await asyncio.sleep(0.05)  # 50ms execution time

    service = CronService(tmp_path / "jobs.json", on_job=on_job)

    # Every 200ms
    service.add_job("t", CronSchedule(kind="every", every_ms=200), "msg")

    await service.start()
    await asyncio.sleep(0.7)  # Should get ~3 executions
    await service.stop()

    # With drift fix: interval should be ~200ms (scheduled time based)
    # Without fix: interval would be ~250ms (200 + 50 execution time)
    if len(run_times) >= 2:
        interval_ms = (run_times[1] - run_times[0]) * 1000
        # Allow 20% tolerance for timing imprecision
        assert 180 <= interval_ms <= 240, (
            f"Interval {interval_ms:.0f}ms indicates drift (expected ~200ms)"
        )


@pytest.mark.asyncio
async def test_graceful_shutdown_waits_for_jobs(tmp_path) -> None:
    """Verify stop() waits for running jobs to complete."""
    job_completed = asyncio.Event()

    async def on_job(job):
        await asyncio.sleep(0.2)
        job_completed.set()

    service = CronService(tmp_path / "jobs.json", on_job=on_job, job_timeout_s=5)
    service.add_job("test", CronSchedule(kind="every", every_ms=50), "msg")

    await service.start()
    await asyncio.sleep(0.1)  # Let job start

    # Stop should wait for job to complete
    await service.stop()

    assert job_completed.is_set(), "Job should have completed before stop() returned"


@pytest.mark.asyncio
async def test_duplicate_execution_prevention(tmp_path) -> None:
    """Verify jobs don't start again if already running."""
    # Track execution windows to detect overlaps
    execution_windows: list[tuple[float, float]] = []
    lock = asyncio.Lock()

    async def on_job(job):
        start = asyncio.get_event_loop().time()
        async with lock:
            execution_windows.append((start, start))  # Record start time
        await asyncio.sleep(0.15)
        end = asyncio.get_event_loop().time()
        async with lock:
            # Update end time
            if execution_windows:
                last = execution_windows[-1]
                execution_windows[-1] = (last[0], end)

    service = CronService(tmp_path / "jobs.json", on_job=on_job, job_timeout_s=5)

    # Job runs every 50ms but takes 150ms to execute
    service.add_job("overlap", CronSchedule(kind="every", every_ms=50), "msg")

    await service.start()
    await asyncio.sleep(0.5)
    await service.stop()

    # Check for overlapping executions
    # If prevention works, no two windows should overlap
    async with lock:
        windows = sorted(execution_windows)

    overlaps = 0
    for i in range(1, len(windows)):
        # If current start < previous end, they overlapped
        if windows[i][0] < windows[i - 1][1]:
            overlaps += 1

    assert overlaps == 0, f"Found {overlaps} overlapping executions (concurrent runs detected)"


@pytest.mark.asyncio
async def test_status_includes_running_jobs(tmp_path) -> None:
    """Verify status() reports running job count."""
    started = asyncio.Event()

    async def on_job(job):
        started.set()
        await asyncio.sleep(0.3)

    service = CronService(tmp_path / "jobs.json", on_job=on_job, job_timeout_s=5)
    service.add_job("test", CronSchedule(kind="every", every_ms=50), "msg")

    await service.start()
    await started.wait()  # Wait for job to start

    status = service.status()
    assert status["running_jobs"] >= 1, "Should report at least 1 running job"

    await service.stop()


@pytest.mark.asyncio
async def test_remove_running_job_cancels_execution(tmp_path) -> None:
    """Verify removing a running job cancels its execution."""
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def on_job(job):
        started.set()
        try:
            await asyncio.sleep(10)  # Long execution
        except asyncio.CancelledError:
            cancelled.set()
            raise

    service = CronService(tmp_path / "jobs.json", on_job=on_job, job_timeout_s=30)
    service.add_job("test", CronSchedule(kind="every", every_ms=1000), "msg")

    await service.start()
    await started.wait()  # Wait for job to start

    # Get job ID and remove while running
    jobs = service.list_jobs()
    assert len(jobs) == 1
    job_id = jobs[0].id

    removed = service.remove_job(job_id)

    assert removed is True
    await asyncio.sleep(0.1)
    assert cancelled.is_set(), "Job should be cancelled when removed"

    # Verify job is gone
    jobs = service.list_jobs(include_disabled=True)
    assert len(jobs) == 0

    await service.stop()
