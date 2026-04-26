import asyncio
import json
import time

import pytest

from nanobot.cron.service import CronService
from nanobot.cron.types import CronJob, CronPayload, CronSchedule


async def _wait_until(predicate, *, timeout: float = 1.0, interval: float = 0.01) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(interval)
    assert predicate()


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


def test_add_job_preserves_channel_meta_and_session_key(tmp_path) -> None:
    service = CronService(tmp_path / "cron" / "jobs.json")
    meta = {"slack": {"thread_ts": "1234567890.123456", "channel_type": "channel"}}
    job = service.add_job(
        name="thread test",
        schedule=CronSchedule(kind="every", every_ms=60_000),
        message="hello",
        deliver=True,
        channel="slack",
        to="C123",
        channel_meta=meta,
        session_key="slack:C123:1234567890.123456",
    )
    assert job.payload.channel_meta == meta
    assert job.payload.session_key == "slack:C123:1234567890.123456"

    reloaded = service.get_job(job.id)
    assert reloaded is not None
    assert reloaded.payload.channel_meta == meta
    assert reloaded.payload.session_key == "slack:C123:1234567890.123456"


@pytest.mark.asyncio
async def test_execute_job_records_run_history(tmp_path) -> None:
    store_path = tmp_path / "cron" / "jobs.json"
    service = CronService(store_path, on_job=lambda _: asyncio.sleep(0))
    job = service.add_job(
        name="hist",
        schedule=CronSchedule(kind="every", every_ms=60_000),
        message="hello",
    )
    await service.run_job(job.id)

    loaded = service.get_job(job.id)
    assert loaded is not None
    assert len(loaded.state.run_history) == 1
    rec = loaded.state.run_history[0]
    assert rec.status == "ok"
    assert rec.duration_ms >= 0
    assert rec.error is None


@pytest.mark.asyncio
async def test_run_history_records_errors(tmp_path) -> None:
    store_path = tmp_path / "cron" / "jobs.json"

    async def fail(_):
        raise RuntimeError("boom")

    service = CronService(store_path, on_job=fail)
    job = service.add_job(
        name="fail",
        schedule=CronSchedule(kind="every", every_ms=60_000),
        message="hello",
    )
    await service.run_job(job.id)

    loaded = service.get_job(job.id)
    assert len(loaded.state.run_history) == 1
    assert loaded.state.run_history[0].status == "error"
    assert loaded.state.run_history[0].error == "boom"


@pytest.mark.asyncio
async def test_run_history_trimmed_to_max(tmp_path) -> None:
    store_path = tmp_path / "cron" / "jobs.json"
    service = CronService(store_path, on_job=lambda _: asyncio.sleep(0))
    job = service.add_job(
        name="trim",
        schedule=CronSchedule(kind="every", every_ms=60_000),
        message="hello",
    )
    for _ in range(25):
        await service.run_job(job.id)

    loaded = service.get_job(job.id)
    assert len(loaded.state.run_history) == CronService._MAX_RUN_HISTORY


@pytest.mark.asyncio
async def test_run_history_persisted_to_disk(tmp_path) -> None:
    store_path = tmp_path / "cron" / "jobs.json"
    service = CronService(store_path, on_job=lambda _: asyncio.sleep(0))
    job = service.add_job(
        name="persist",
        schedule=CronSchedule(kind="every", every_ms=60_000),
        message="hello",
    )
    await service.run_job(job.id)

    raw = json.loads(store_path.read_text())
    history = raw["jobs"][0]["state"]["runHistory"]
    assert len(history) == 1
    assert history[0]["status"] == "ok"
    assert "runAtMs" in history[0]
    assert "durationMs" in history[0]

    fresh = CronService(store_path)
    loaded = fresh.get_job(job.id)
    assert len(loaded.state.run_history) == 1
    assert loaded.state.run_history[0].status == "ok"


@pytest.mark.asyncio
async def test_run_job_disabled_does_not_flip_running_state(tmp_path) -> None:
    store_path = tmp_path / "cron" / "jobs.json"
    service = CronService(store_path, on_job=lambda _: asyncio.sleep(0))
    job = service.add_job(
        name="disabled",
        schedule=CronSchedule(kind="every", every_ms=60_000),
        message="hello",
    )
    service.enable_job(job.id, enabled=False)

    result = await service.run_job(job.id)

    assert result is False
    assert service._running is False


@pytest.mark.asyncio
async def test_run_job_preserves_running_service_state(tmp_path) -> None:
    store_path = tmp_path / "cron" / "jobs.json"
    service = CronService(store_path, on_job=lambda _: asyncio.sleep(0))
    service._running = True
    job = service.add_job(
        name="manual",
        schedule=CronSchedule(kind="every", every_ms=60_000),
        message="hello",
    )

    result = await service.run_job(job.id, force=True)

    assert result is True
    assert service._running is True
    service.stop()


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


def test_remove_job_refuses_system_jobs(tmp_path) -> None:
    service = CronService(tmp_path / "cron" / "jobs.json")
    service.register_system_job(CronJob(
        id="dream",
        name="dream",
        schedule=CronSchedule(kind="cron", expr="0 */2 * * *", tz="UTC"),
        payload=CronPayload(kind="system_event"),
    ))

    result = service.remove_job("dream")

    assert result == "protected"
    assert service.get_job("dream") is not None


@pytest.mark.asyncio
async def test_start_server_not_jobs(tmp_path):
    store_path = tmp_path / "cron" / "jobs.json"
    called = []
    async def on_job(job):
        called.append(job.name)

    service = CronService(store_path, on_job=on_job, max_sleep_ms=100)
    await service.start()
    assert len(service.list_jobs()) == 0

    service2 = CronService(tmp_path / "cron" / "jobs.json")
    service2.add_job(
        name="hist",
        schedule=CronSchedule(kind="every", every_ms=100),
        message="hello",
    )
    assert len(service.list_jobs()) == 1
    await _wait_until(lambda: bool(called), timeout=0.8)
    assert len(called) != 0
    service.stop()


@pytest.mark.asyncio
async def test_subsecond_job_not_delayed_to_one_second(tmp_path):
    store_path = tmp_path / "cron" / "jobs.json"
    called = []

    async def on_job(job):
        called.append(job.name)

    service = CronService(store_path, on_job=on_job, max_sleep_ms=5000)
    service.add_job(
        name="fast",
        schedule=CronSchedule(kind="every", every_ms=100),
        message="hello",
    )
    await service.start()
    try:
        await asyncio.sleep(0.35)
        assert called
    finally:
        service.stop()


@pytest.mark.asyncio
async def test_running_service_picks_up_external_add(tmp_path):
    """A running service should detect and execute a job added by another instance."""
    store_path = tmp_path / "cron" / "jobs.json"
    called: list[str] = []

    async def on_job(job):
        called.append(job.name)

    service = CronService(store_path, on_job=on_job, max_sleep_ms=100)
    service.add_job(
        name="heartbeat",
        schedule=CronSchedule(kind="every", every_ms=100),
        message="tick",
    )
    await service.start()
    try:
        await asyncio.sleep(0.05)

        external = CronService(store_path)
        external.add_job(
            name="external",
            schedule=CronSchedule(kind="every", every_ms=100),
            message="ping",
        )

        await _wait_until(lambda: "external" in called, timeout=0.8)
        assert "external" in called
    finally:
        service.stop()


@pytest.mark.asyncio
async def test_add_job_during_jobs_exec(tmp_path):
    store_path = tmp_path / "cron" / "jobs.json"
    run_once = True

    async def on_job(job):
        nonlocal run_once
        if run_once:
            service2 = CronService(store_path, on_job=lambda x: asyncio.sleep(0))
            service2.add_job(
                name="test",
                schedule=CronSchedule(kind="every", every_ms=150),
                message="tick",
            )
            run_once = False

    service = CronService(store_path, on_job=on_job, max_sleep_ms=100)
    service.add_job(
        name="heartbeat",
        schedule=CronSchedule(kind="every", every_ms=100),
        message="tick",
    )
    assert len(service.list_jobs()) == 1
    await service.start()
    try:
        await _wait_until(lambda: len(service.list_jobs()) == 2, timeout=0.8)
        jobs = service.list_jobs()
        assert len(jobs) == 2
        assert "test" in [j.name for j in jobs]
    finally:
        service.stop()


@pytest.mark.asyncio
async def test_external_update_preserves_run_history_records(tmp_path):
    store_path = tmp_path / "cron" / "jobs.json"
    service = CronService(store_path, on_job=lambda _: asyncio.sleep(0))
    job = service.add_job(
        name="history",
        schedule=CronSchedule(kind="every", every_ms=60_000),
        message="hello",
    )
    await service.run_job(job.id, force=True)

    external = CronService(store_path)
    updated = external.enable_job(job.id, enabled=False)
    assert updated is not None

    fresh = CronService(store_path)
    loaded = fresh.get_job(job.id)
    assert loaded is not None
    assert loaded.state.run_history
    assert loaded.state.run_history[0].status == "ok"

    fresh._running = True
    fresh._save_store()


# ── timer race regression tests ──


@pytest.mark.asyncio
async def test_timer_execution_is_not_rolled_back_by_list_jobs_reload(tmp_path):
    """list_jobs() during _on_timer should not replace the active store and re-run the same due job."""
    store_path = tmp_path / "cron" / "jobs.json"
    calls: list[str] = []

    async def on_job(job):
        calls.append(job.id)
        # Simulate frontend polling list_jobs while the timer callback is mid-execution.
        service.list_jobs(include_disabled=True)
        await asyncio.sleep(0)

    service = CronService(store_path, on_job=on_job)
    service._running = True
    service._load_store()
    service._arm_timer = lambda: None

    job = service.add_job(
        name="race",
        schedule=CronSchedule(kind="every", every_ms=60_000),
        message="hello",
    )
    job.state.next_run_at_ms = max(1, int(time.time() * 1000) - 1_000)
    service._save_store()

    await service._on_timer()
    await service._on_timer()

    assert calls == [job.id]
    loaded = service.get_job(job.id)
    assert loaded is not None
    assert loaded.state.last_run_at_ms is not None
    assert loaded.state.next_run_at_ms is not None
    assert loaded.state.next_run_at_ms > loaded.state.last_run_at_ms


# ── update_job tests ──


def test_update_job_changes_name(tmp_path) -> None:
    service = CronService(tmp_path / "cron" / "jobs.json")
    job = service.add_job(
        name="old name",
        schedule=CronSchedule(kind="every", every_ms=60_000),
        message="hello",
    )
    result = service.update_job(job.id, name="new name")
    assert isinstance(result, CronJob)
    assert result.name == "new name"
    assert result.payload.message == "hello"


def test_update_job_changes_schedule(tmp_path) -> None:
    service = CronService(tmp_path / "cron" / "jobs.json")
    job = service.add_job(
        name="sched",
        schedule=CronSchedule(kind="every", every_ms=60_000),
        message="hello",
    )
    old_next = job.state.next_run_at_ms

    new_sched = CronSchedule(kind="every", every_ms=120_000)
    result = service.update_job(job.id, schedule=new_sched)
    assert isinstance(result, CronJob)
    assert result.schedule.every_ms == 120_000
    assert result.state.next_run_at_ms != old_next


def test_update_job_changes_message(tmp_path) -> None:
    service = CronService(tmp_path / "cron" / "jobs.json")
    job = service.add_job(
        name="msg",
        schedule=CronSchedule(kind="every", every_ms=60_000),
        message="old message",
    )
    result = service.update_job(job.id, message="new message")
    assert isinstance(result, CronJob)
    assert result.payload.message == "new message"


def test_update_job_changes_cron_expression(tmp_path) -> None:
    service = CronService(tmp_path / "cron" / "jobs.json")
    job = service.add_job(
        name="cron-job",
        schedule=CronSchedule(kind="cron", expr="0 9 * * *", tz="UTC"),
        message="hello",
    )
    result = service.update_job(
        job.id,
        schedule=CronSchedule(kind="cron", expr="0 18 * * *", tz="UTC"),
    )
    assert isinstance(result, CronJob)
    assert result.schedule.expr == "0 18 * * *"
    assert result.state.next_run_at_ms is not None


def test_update_job_not_found(tmp_path) -> None:
    service = CronService(tmp_path / "cron" / "jobs.json")
    result = service.update_job("nonexistent", name="x")
    assert result == "not_found"


def test_update_job_rejects_system_job(tmp_path) -> None:
    service = CronService(tmp_path / "cron" / "jobs.json")
    service.register_system_job(CronJob(
        id="dream",
        name="dream",
        schedule=CronSchedule(kind="cron", expr="0 */2 * * *", tz="UTC"),
        payload=CronPayload(kind="system_event"),
    ))
    result = service.update_job("dream", name="hacked")
    assert result == "protected"
    assert service.get_job("dream").name == "dream"


def test_update_job_validates_schedule(tmp_path) -> None:
    service = CronService(tmp_path / "cron" / "jobs.json")
    job = service.add_job(
        name="validate",
        schedule=CronSchedule(kind="every", every_ms=60_000),
        message="hello",
    )
    with pytest.raises(ValueError, match="unknown timezone"):
        service.update_job(
            job.id,
            schedule=CronSchedule(kind="cron", expr="0 9 * * *", tz="Bad/Zone"),
        )


@pytest.mark.asyncio
async def test_update_job_preserves_run_history(tmp_path) -> None:
    import asyncio
    store_path = tmp_path / "cron" / "jobs.json"
    service = CronService(store_path, on_job=lambda _: asyncio.sleep(0))
    job = service.add_job(
        name="hist",
        schedule=CronSchedule(kind="every", every_ms=60_000),
        message="hello",
    )
    await service.run_job(job.id)

    result = service.update_job(job.id, name="renamed")
    assert isinstance(result, CronJob)
    assert len(result.state.run_history) == 1
    assert result.state.run_history[0].status == "ok"


def test_update_job_offline_writes_action(tmp_path) -> None:
    service = CronService(tmp_path / "cron" / "jobs.json")
    job = service.add_job(
        name="offline",
        schedule=CronSchedule(kind="every", every_ms=60_000),
        message="hello",
    )
    service.update_job(job.id, name="updated-offline")

    action_path = tmp_path / "cron" / "action.jsonl"
    assert action_path.exists()
    lines = [l for l in action_path.read_text().strip().split("\n") if l]
    last = json.loads(lines[-1])
    assert last["action"] == "update"
    assert last["params"]["name"] == "updated-offline"


def test_update_job_sentinel_channel_and_to(tmp_path) -> None:
    """Passing None clears channel/to; omitting leaves them unchanged."""
    service = CronService(tmp_path / "cron" / "jobs.json")
    job = service.add_job(
        name="sentinel",
        schedule=CronSchedule(kind="every", every_ms=60_000),
        message="hello",
        channel="telegram",
        to="user123",
    )
    assert job.payload.channel == "telegram"
    assert job.payload.to == "user123"

    result = service.update_job(job.id, name="renamed")
    assert isinstance(result, CronJob)
    assert result.payload.channel == "telegram"
    assert result.payload.to == "user123"

    result = service.update_job(job.id, channel=None, to=None)
    assert isinstance(result, CronJob)
    assert result.payload.channel is None
    assert result.payload.to is None


@pytest.mark.asyncio
async def test_list_jobs_during_on_job_does_not_cause_stale_reload(tmp_path) -> None:
    """Regression: if the bot calls list_jobs (which reloads from disk) during
    on_job execution, the in-memory next_run_at_ms update must not be lost.
    Previously this caused an infinite re-trigger loop."""
    store_path = tmp_path / "cron" / "jobs.json"
    execution_count = 0

    async def on_job_that_lists(job):
        nonlocal execution_count
        execution_count += 1
        # Simulate the bot calling cron(action=list) mid-execution
        service.list_jobs()

    service = CronService(store_path, on_job=on_job_that_lists, max_sleep_ms=100)
    await service.start()

    # Add two jobs scheduled in the past so they're immediately due
    now_ms = int(time.time() * 1000)
    for name in ("job-a", "job-b"):
        service.add_job(
            name=name,
            schedule=CronSchedule(kind="every", every_ms=3_600_000),
            message="test",
        )
    # Force next_run to the past so _on_timer picks them up
    for job in service._store.jobs:
        job.state.next_run_at_ms = now_ms - 1000
    service._save_store()
    service._arm_timer()

    # Let the timer fire once
    await asyncio.sleep(0.3)
    service.stop()

    # Each job should have run exactly once, not looped
    assert execution_count == 2

    # Verify next_run_at_ms was persisted correctly (in the future)
    raw = json.loads(store_path.read_text())
    for j in raw["jobs"]:
        next_run = j["state"]["nextRunAtMs"]
        assert next_run is not None
        assert next_run > now_ms, f"Job '{j['name']}' next_run should be in the future"
