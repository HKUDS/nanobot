import asyncio
import inspect
import json
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nanobot.agent.runner import AgentRunResult
from nanobot.bus.events import InboundMessage
from nanobot.bus.runtime_events import RuntimeModelChanged
from nanobot.cron.service import CronService
from nanobot.cron.types import CronSchedule
from nanobot.providers.base import LLMResponse
from nanobot.runtime_admission import RuntimeBusyError, RuntimeMaintenanceError
from nanobot.session.sqlite_store import SessionConflictError
from nanobot.triggers.local_runner import run_local_trigger_queue
from nanobot.triggers.local_store import LocalTriggerStore
from nanobot.utils.llm_runtime import LLMRuntime


@pytest.fixture
async def agent(loop_factory):
    loop = loop_factory()
    loop.provider.provider_name = "test"
    loop.provider.chat_stream_with_retry = AsyncMock(return_value=LLMResponse(content="done"))
    loop.provider.can_resume_conversation_state.return_value = False
    loop.provider.aclose = AsyncMock()
    try:
        yield loop
    finally:
        loop.stop()
        await loop.aclose()


def message(content="hello", *, kind=None):
    metadata = {}
    if kind == "cron":
        metadata = {"_cron_trigger": {"job_id": "job", "run_id": "run"}}
    elif kind == "trigger":
        metadata = {"_local_trigger": {"trigger_id": "trigger", "delivery_id": "delivery"}}
    return InboundMessage("cli", "user", "direct", content, metadata=metadata)


async def settle(agent):
    async with asyncio.timeout(3):
        while agent._has_pending_work():
            await asyncio.sleep(0)


async def test_idle_maintenance_refuses_new_work_and_abort_restores_it(agent):
    background = asyncio.sleep(0)
    with pytest.raises(ValueError, match="abort"):
        with agent.maintenance():
            with pytest.raises(RuntimeMaintenanceError):
                await agent.bus.publish_inbound(message())
            with pytest.raises(RuntimeMaintenanceError):
                await agent.process_direct("not accepted")
            with pytest.raises(RuntimeMaintenanceError):
                await agent.discard_session("cli:direct")
            with pytest.raises(RuntimeMaintenanceError):
                await agent.submit_cron_turn(message(kind="cron"))
            with pytest.raises(RuntimeMaintenanceError):
                await agent.submit_local_trigger_turn(message(kind="trigger"))
            with pytest.raises(RuntimeMaintenanceError):
                await agent.subagents.spawn("not accepted")
            with pytest.raises(RuntimeMaintenanceError):
                agent.schedule_background(background)
            assert inspect.getcoroutinestate(background) == inspect.CORO_CLOSED
            assert agent.bus.inbound_size == 0
            assert not agent._pending_queues
            assert agent.sessions.get_existing("cli:direct") is None
            with pytest.raises(RuntimeMaintenanceError):
                with agent.maintenance():
                    pytest.fail("duplicate maintenance was admitted")
            assert agent.bus.admission.paused
            raise ValueError("abort")
    assert not agent.bus.admission.paused
    response = await agent.process_direct("accepted after abort")
    assert response.content == "done"


@pytest.mark.parametrize("cancel", [False, True])
async def test_direct_turn_including_final_notification_stays_busy(agent, cancel):
    entered, release, notifying, notified = (asyncio.Event() for _ in range(4))

    async def reply(*args, **kwargs):
        entered.set()
        await release.wait()
        return LLMResponse(content="done")

    original = agent.runtime_event_publisher.run_status_changed

    async def notify(msg, key, status, *args, **kwargs):
        if status == "idle":
            notifying.set()
            await notified.wait()
        await original(msg, key, status, *args, **kwargs)

    agent.provider.chat_stream_with_retry.side_effect = reply
    agent.runtime_event_publisher.run_status_changed = notify
    task = asyncio.create_task(agent.process_direct("work"))
    try:
        async with asyncio.timeout(3):
            await entered.wait()
            with pytest.raises(RuntimeBusyError):
                with agent.maintenance():
                    pytest.fail("active direct turn was missed")
            assert not agent.bus.admission.paused
            assert not task.done()
            if cancel:
                task.cancel()
            else:
                release.set()
            await notifying.wait()
            with pytest.raises(RuntimeBusyError):
                with agent.maintenance():
                    pytest.fail("final notification was missed")
            notified.set()
            if cancel:
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                await task
        await settle(agent)
        with agent.maintenance():
            assert agent.bus.admission.paused
    finally:
        release.set()
        notified.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_dequeue_and_inline_dispatch_have_no_false_idle_gap(agent, monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()
    outcomes = []
    consume = agent.bus.consume_inbound

    def attempt_maintenance():
        try:
            with agent.maintenance():
                outcomes.append("incorrectly idle")
        except RuntimeBusyError:
            outcomes.append("busy")

    async def dequeue():
        msg = await consume()
        asyncio.get_running_loop().call_soon(attempt_maintenance)
        return msg

    async def accept(*args, **kwargs):
        entered.set()
        await release.wait()

    monkeypatch.setattr(agent.bus, "consume_inbound", dequeue)
    monkeypatch.setattr(agent.runtime_event_publisher, "user_input_accepted", accept)
    await agent.bus.publish_inbound(message())
    with pytest.raises(RuntimeBusyError):
        with agent.maintenance():
            pytest.fail("queued message was missed")
    consumer = asyncio.create_task(agent.run())
    try:
        async with asyncio.timeout(3):
            await entered.wait()
            await asyncio.sleep(0)
            assert outcomes == ["busy"]
            assert agent.bus.inbound_size == 0
            assert not agent._active_tasks
            with pytest.raises(RuntimeBusyError):
                with agent.maintenance():
                    pytest.fail("inline acceptance was missed")
            release.set()
            await agent.bus.consume_outbound()
            await settle(agent)
        with agent.maintenance():
            assert agent.bus.admission.paused
    finally:
        release.set()
        consumer.cancel()
        await asyncio.gather(consumer, return_exceptions=True)


async def test_rejected_input_keeps_failure_delivery_owned(agent, monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()

    async def reject(msg):
        raise SessionConflictError("session changed before admission")

    async def fail(**kwargs):
        entered.set()
        await release.wait()

    monkeypatch.setattr(agent, "_dispatch_inbound", reject)
    monkeypatch.setattr(agent.turn_delivery_factory, "unrouted",
                        lambda *args: SimpleNamespace(fail=fail))
    await agent.bus.publish_inbound(message())
    consumer = asyncio.create_task(agent.run())
    try:
        async with asyncio.timeout(3):
            await entered.wait()
        assert agent.bus.inbound_size == 0
        assert not agent._active_tasks
        with pytest.raises(RuntimeBusyError):
            with agent.maintenance():
                pytest.fail("failure notification was interrupted by maintenance")
    finally:
        release.set()
        consumer.cancel()
        await asyncio.gather(consumer, return_exceptions=True)


async def test_scheduled_background_work_blocks_before_it_starts(agent):
    entered, release = asyncio.Event(), asyncio.Event()

    async def work():
        entered.set()
        await release.wait()

    agent.schedule_background(work())
    try:
        with pytest.raises(RuntimeBusyError):
            with agent.maintenance():
                pytest.fail("scheduled task was missed")
        async with asyncio.timeout(3):
            await entered.wait()
        with pytest.raises(RuntimeBusyError):
            with agent.maintenance():
                pytest.fail("running task was missed")
    finally:
        release.set()
        await settle(agent)
    with agent.maintenance():
        await agent._check_expired_sessions_if_due()
        assert not agent._background_tasks


async def test_queued_event_dispatch_cannot_be_overtaken_by_maintenance(agent):
    entered, release = asyncio.Event(), asyncio.Event()
    background_finished = asyncio.Event()

    async def background():
        background_finished.set()

    async def observe(event):
        entered.set()
        await release.wait()
        agent.schedule_background(background())

    disconnect = agent.bus.subscribe(observe, RuntimeModelChanged)
    agent.bus.publish_nowait(RuntimeModelChanged("test-model", None))
    try:
        with pytest.raises(RuntimeBusyError):
            with agent.maintenance():
                pytest.fail("queued event was missed")
        async with asyncio.timeout(3):
            await entered.wait()
        with pytest.raises(RuntimeBusyError):
            with agent.maintenance():
                pytest.fail("awaiting subscriber was missed")
    finally:
        release.set()
        await agent.bus.drain()
        await settle(agent)
        disconnect()
    with agent.maintenance():
        assert background_finished.is_set()
        assert not agent.bus.has_pending_events


async def test_async_idle_scan_keeps_storage_work_owned(agent, monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()

    async def scan(*args, **kwargs):
        entered.set()
        await release.wait()

    monkeypatch.setattr(agent.auto_compact, "check_expired", scan)
    agent._next_idle_compact_check_at = 0
    task = asyncio.create_task(agent._check_expired_sessions_if_due())
    try:
        async with asyncio.timeout(3):
            await entered.wait()
        with pytest.raises(RuntimeBusyError):
            with agent.maintenance():
                pytest.fail("SQLite idle scan was mistaken for an idle runtime")
    finally:
        release.set()
        await task
    with agent.maintenance():
        assert agent.bus.admission.paused


async def test_cancelled_exec_startup_stays_busy_until_cleanup_finishes(agent, tmp_path, monkeypatch):
    manager = agent._exec_session_manager
    entered, cancelling, release = (asyncio.Event() for _ in range(3))

    async def spawn(*args, **kwargs):
        entered.set()
        try:
            await asyncio.Future()
        finally:
            cancelling.set()
            await release.wait()

    monkeypatch.setattr(manager, "_spawn", spawn)
    task = asyncio.create_task(manager.start(
        command=[sys.executable, "-c", "pass"], cwd=str(tmp_path), env=dict(os.environ),
        timeout=10, shell_program=None, login=False, yield_time_ms=0,
        max_output_chars=1000, owner_session_key="cli:direct",
    ))
    stop = None
    try:
        async with asyncio.timeout(3):
            await entered.wait()
        with pytest.raises(RuntimeBusyError):
            with agent.maintenance():
                pytest.fail("launch reservation was missed")
        stop = asyncio.create_task(manager.terminate_by_owner("cli:direct"))
        async with asyncio.timeout(3):
            await cancelling.wait()
        assert not manager._starting
        with pytest.raises(RuntimeBusyError):
            with agent.maintenance():
                pytest.fail("cancelled launch cleanup was missed")
    finally:
        release.set()
        await asyncio.gather(task, *([stop] if stop is not None else []), return_exceptions=True)
    with agent.maintenance():
        assert not manager.has_pending_work


async def test_detached_real_exec_blocks_maintenance_without_being_killed(agent, tmp_path):
    manager = agent._exec_session_manager
    session_id, result = await manager.start(
        command=[sys.executable, "-I", "-c", "import sys; print('ready', flush=True); sys.stdin.readline()"],
        cwd=str(tmp_path), env=dict(os.environ), timeout=10, shell_program=None,
        login=False, yield_time_ms=100, max_output_chars=1000, owner_session_key="cli:direct",
    )
    assert not result.done
    with pytest.raises(RuntimeBusyError):
        with agent.maintenance():
            pytest.fail("detached command was missed")
    assert (await manager.list(owner_session_key="cli:direct"))[0].returncode is None
    result = await manager.write(
        session_id=session_id, chars="finish\n", close_stdin=False, terminate=False,
        yield_time_ms=3000, max_output_chars=1000, owner_session_key="cli:direct",
    )
    assert result.done and result.exit_code == 0 and result.finish_reason == "exit"
    with agent.maintenance():
        assert not manager.has_pending_work


@pytest.mark.parametrize("operation", ["close_all", "terminate_by_owner", "discard_session"])
async def test_exec_cleanup_is_owned_through_failure_and_retry(agent, tmp_path, monkeypatch, operation):
    manager = agent._exec_session_manager
    session_id, _ = await manager.start(
        command=[sys.executable, "-I", "-c", "import sys; sys.stdin.readline()"],
        cwd=str(tmp_path), env=dict(os.environ), timeout=10, shell_program=None,
        login=False, yield_time_ms=0, max_output_chars=1000, owner_session_key="cli:direct",
    )
    session = manager._sessions[session_id]
    original = session._kill
    entered, release = asyncio.Event(), asyncio.Event()
    fail = True

    async def cleanup():
        entered.set()
        await release.wait()
        await original()
        if fail:
            raise OSError("cleanup was not confirmed")

    async def terminate():
        if operation == "close_all":
            await manager.close_all()
        elif operation == "terminate_by_owner":
            await manager.terminate_by_owner("cli:direct")
        else:
            await agent.discard_session("cli:direct")

    monkeypatch.setattr(session, "_kill", cleanup)
    task = asyncio.create_task(terminate())
    try:
        async with asyncio.timeout(3):
            await entered.wait()
        with pytest.raises(RuntimeBusyError):
            with agent.maintenance():
                pytest.fail("in-flight process cleanup was missed")
        release.set()
        with pytest.raises(OSError, match="cleanup was not confirmed"):
            await task
        assert session.process.returncode is not None
        with pytest.raises(RuntimeBusyError):
            with agent.maintenance():
                pytest.fail("failed cleanup was treated as idle")
        fail = False
        await terminate()
        with agent.maintenance():
            assert not manager.has_pending_work
    finally:
        fail = False
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        await manager.close_all()


async def test_cancelled_exec_close_keeps_unfinished_cleanup_owned(agent, tmp_path, monkeypatch):
    manager = agent._exec_session_manager
    session_id, _ = await manager.start(
        command=[sys.executable, "-I", "-c", "import sys; sys.stdin.readline()"],
        cwd=str(tmp_path), env=dict(os.environ), timeout=10, shell_program=None,
        login=False, yield_time_ms=0, max_output_chars=1000, owner_session_key="cli:direct",
    )
    session = manager._sessions[session_id]
    original = session._kill
    entered, release = asyncio.Event(), asyncio.Event()

    async def cleanup():
        entered.set()
        await release.wait()
        await original()

    monkeypatch.setattr(session, "_kill", cleanup)
    task = asyncio.create_task(manager.close_all())
    try:
        async with asyncio.timeout(3):
            await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(RuntimeBusyError):
            with agent.maintenance():
                pytest.fail("cancelled close lost its still-running cleanup")
        release.set()
        await manager.close_all()
        with agent.maintenance():
            assert not manager.has_pending_work
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        await manager.close_all()


async def test_subagent_execution_and_cleanup_are_both_busy(agent, monkeypatch):
    manager = agent.subagents
    manager.runner.run = AsyncMock(return_value=AgentRunResult(messages=[], final_content="finished"))
    runtime = LLMRuntime.capture(agent.provider, "test-model", context_window_tokens=4096)
    await manager.spawn("child", runtime=runtime)
    record = next(iter(manager._tasks.values()))
    cleaning, release = asyncio.Event(), asyncio.Event()
    original = record.exec_manager.close_all

    async def cleanup():
        cleaning.set()
        await release.wait()
        return await original()

    monkeypatch.setattr(record.exec_manager, "close_all", cleanup)
    try:
        with pytest.raises(RuntimeBusyError):
            with agent.maintenance():
                pytest.fail("subagent was missed")
        async with asyncio.timeout(3):
            await cleaning.wait()
        with pytest.raises(RuntimeBusyError):
            with agent.maintenance():
                pytest.fail("subagent cleanup was missed")
    finally:
        release.set()
        await manager.close()
        await agent.bus.drain()
    assert not manager.has_pending_work


@pytest.mark.parametrize("stop", [False, True])
async def test_cron_timer_waits_without_consuming_and_manual_run_is_refused(agent, tmp_path, stop):
    ran = asyncio.Event()

    async def callback(job):
        with pytest.raises(RuntimeBusyError):
            with agent.maintenance():
                pytest.fail("cron callback was missed")
        ran.set()

    cron = CronService(tmp_path / "cron/jobs.json", callback, admission=agent.bus.admission)
    await cron.start()
    job = cron.add_job(
        name="scheduled", schedule=CronSchedule(kind="every", every_ms=3600000),
        message="work", session_key="websocket:test", origin_channel="websocket",
        origin_chat_id="test",
    )
    timer = None
    try:
        with agent.maintenance():
            job.state.next_run_at_ms = 1
            cron._save_store()
            before = cron.store_path.read_bytes()
            cron._arm_timer()
            timer = cron._timer_task
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            assert not ran.is_set() and not timer.done()
            with pytest.raises(RuntimeMaintenanceError):
                await cron.run_job(job.id, force=True)
            assert cron.store_path.read_bytes() == before
            if stop:
                cron.stop()
                await asyncio.gather(timer, return_exceptions=True)
        if stop:
            assert not ran.is_set()
        else:
            with agent.maintenance():
                await asyncio.sleep(0)
                assert not ran.is_set() and not timer.done()
                assert cron.store_path.read_bytes() == before
            async with asyncio.timeout(3):
                await ran.wait()
            await asyncio.gather(timer, return_exceptions=True)
            assert len(cron.get_job(job.id).state.run_history) == 1
            assert cron._timer_task is not timer and not cron._timer_task.done()
    finally:
        timer = cron._timer_task
        cron.stop()
        if timer is not None:
            await asyncio.gather(timer, return_exceptions=True)


async def test_trigger_intake_does_not_claim_until_maintenance_released(agent, tmp_path):
    store = LocalTriggerStore(tmp_path)
    trigger = store.create(name="test", channel="cli", chat_id="test", session_key="cli:test")
    delivery = store.enqueue(trigger.id, "work")
    entered, release = asyncio.Event(), asyncio.Event()

    async def submit(msg):
        entered.set()
        await release.wait()

    worker = None
    try:
        with agent.maintenance():
            worker = asyncio.create_task(run_local_trigger_queue(
                store=store, submit_turn=submit, is_channel_enabled=lambda name: True,
                poll_interval_s=0.01, admission=agent.bus.admission,
            ))
            await asyncio.sleep(0)
            assert not entered.is_set()
            assert len(list(store.inbox_dir.glob("*.json"))) == 1
            assert not list(store.processing_dir.glob("*.json"))
        async with asyncio.timeout(3):
            await entered.wait()
            with pytest.raises(RuntimeBusyError):
                with agent.maintenance():
                    pytest.fail("claimed trigger batch was missed")
            release.set()
            path = store.runs_dir / f"{delivery.id}.json"
            while json.loads(path.read_text())["status"] != "ok":
                await asyncio.sleep(0)
        with agent.maintenance():
            assert not list(store.inbox_dir.glob("*.json"))
    finally:
        release.set()
        if worker is not None:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
