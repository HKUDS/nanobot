"""Real FIFO/exit boundaries drive runtime state, independently of delivery."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.session_helpers import visible_message
from nanobot.agent.turn_delivery import TurnDelivery
from nanobot.bus.events import (
    INBOUND_META_EXECUTION_ID,
    INBOUND_META_STOP_EXECUTION_ID,
    InboundMessage,
    OutboundMessage,
)
from nanobot.bus.runtime_events import TurnExecutionChanged
from nanobot.providers.base import LLMResponse, ToolCallRequest
from nanobot.session.state import SessionOperationQueueFullError
from nanobot.webui.run_state import RunStateAuthority


def message(content="hello", **kwargs):
    return InboundMessage(
        channel="websocket", sender_id="user", chat_id="execution-chat", content=content,
        **kwargs,
    )


async def finish_worker(loop, key):
    async with asyncio.timeout(3):
        while tasks := tuple(loop._active_tasks.get(key, ())):
            await asyncio.gather(*tasks, return_exceptions=True)
            await asyncio.sleep(0)


async def test_accepted_queued_is_not_running_until_concurrency_slot_is_acquired(loop_factory, monkeypatch):
    loop = loop_factory()
    authority = RunStateAuthority(loop.bus, "gateway")
    loop._concurrency_gate = asyncio.Semaphore(0)
    entered, release = asyncio.Event(), asyncio.Event()

    async def process(msg, **kwargs):
        entered.set()
        await release.wait()
        return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content="answer")

    monkeypatch.setattr(loop, "_process_message", process)
    msg = message()
    try:
        await loop._dispatch_inbound(msg)
        await asyncio.sleep(0)
        queued = authority.snapshot(msg.session_key)
        assert queued["runs"][0]["phase"] == "queued"
        assert queued["runs"][0]["started_at"] is None
        loop._concurrency_gate.release()
        await asyncio.wait_for(entered.wait(), 2)
        running = authority.snapshot(msg.session_key)
        assert running["runs"][0]["run_id"] == queued["runs"][0]["run_id"]
        assert running["runs"][0]["phase"] == "running"
        assert running["runs"][0]["started_at"] is not None
        release.set()
        await finish_worker(loop, msg.session_key)
        assert authority.snapshot(msg.session_key)["runs"] == []
        assert authority.snapshot(msg.session_key)["completed"][0]["outcome"] == "completed"
    finally:
        release.set()
        await loop.aclose()


@pytest.mark.parametrize("waiting_for", ["worker_start", "session_lock", "capacity"])
async def test_queued_cancellation_exits_once_without_entering_execution(
    loop_factory, monkeypatch, waiting_for,
):
    loop = loop_factory()
    authority = RunStateAuthority(loop.bus, "gateway")
    facts = []
    loop.bus.subscribe(facts.append, TurnExecutionChanged)
    msg = message()
    blocker = loop._get_session_lock(msg.session_key)
    if waiting_for == "capacity":
        blocker = loop._concurrency_gate = asyncio.Semaphore(1)
    await blocker.acquire()
    waiting = asyncio.Event()
    acquire = blocker.acquire

    async def wait_for_blocker():
        waiting.set()
        return await acquire()

    monkeypatch.setattr(blocker, "acquire", wait_for_blocker)
    loop._process_message = AsyncMock()
    cancel_children, terminate_exec = AsyncMock(return_value=0), AsyncMock(return_value=0)
    monkeypatch.setattr(loop.subagents, "cancel_by_session", cancel_children)
    monkeypatch.setattr(loop._exec_session_manager, "terminate_by_owner", terminate_exec)
    try:
        await loop._dispatch_inbound(msg)
        owner = authority.snapshot(msg.session_key)["runs"][0]["run_id"]
        if waiting_for != "worker_start":
            await asyncio.wait_for(waiting.wait(), 2)
        assert await loop._cancel_execution(msg.session_key, owner) == 1
        await finish_worker(loop, msg.session_key)
        snapshot = authority.snapshot(msg.session_key)
        assert snapshot["runs"] == []
        assert snapshot["completed"] == [{
            "run_id": owner, "turn_id": None, "outcome": "cancelled",
        }]
        assert [(fact.phase, fact.outcome) for fact in facts if fact.phase == "exited"] == [
            ("exited", "cancelled"),
        ]
        loop._process_message.assert_not_awaited()
        cancel_children.assert_not_awaited()
        terminate_exec.assert_not_awaited()
        assert await loop._cancel_execution(msg.session_key, owner) == 0
        assert authority.snapshot(msg.session_key) == snapshot
        assert len([fact for fact in facts if fact.phase == "exited"]) == 1
    finally:
        blocker.release()
        await loop.aclose()


@pytest.mark.parametrize("failure", ["internal", "provider", "delivery"])
async def test_failure_always_ends_execution_owner(loop_factory, monkeypatch, failure):
    loop = loop_factory()
    authority = RunStateAuthority(loop.bus, "gateway")

    async def process(msg, **kwargs):
        if failure == "internal":
            raise RuntimeError("context construction failed")
        return OutboundMessage(
            channel=msg.channel, chat_id=msg.chat_id, content="answer",
            metadata={"_stop_reason": "error"} if failure == "provider" else {},
        )

    monkeypatch.setattr(loop, "_process_message", process)
    if failure == "delivery":
        monkeypatch.setattr(TurnDelivery, "complete", AsyncMock(side_effect=OSError("persistence failed")))
        monkeypatch.setattr(TurnDelivery, "fail", AsyncMock(side_effect=OSError("still unavailable")))
    msg = message()
    try:
        await loop._dispatch_inbound(msg)
        await finish_worker(loop, msg.session_key)
        snapshot = authority.snapshot(msg.session_key)
        assert snapshot["runs"] == []
        assert snapshot["completed"][0]["outcome"] == "failed"
    finally:
        await loop.aclose()


@pytest.mark.parametrize("cleanup", ["process", "checkpoint", "stream", "subagents", "exec"])
async def test_stop_a_preserves_worker_and_queue_until_cleanup_then_runs_b(
    loop_factory, monkeypatch, cleanup,
):
    loop = loop_factory()
    authority = RunStateAuthority(loop.bus, "gateway")
    facts = []
    loop.bus.subscribe(facts.append, TurnExecutionChanged)
    a_started, cleaning, release_cleanup = asyncio.Event(), asyncio.Event(), asyncio.Event()
    b_started, b_exit = asyncio.Event(), asyncio.Event()
    roots, queues = {}, []
    cancellations = 0

    async def pause_cleanup():
        cleaning.set()
        await release_cleanup.wait()

    if cleanup == "stream":
        original = TurnDelivery.abort_stream

        async def abort_stream(delivery):
            await pause_cleanup()
            await original(delivery)

        monkeypatch.setattr(TurnDelivery, "abort_stream", abort_stream)
    elif cleanup in {"checkpoint", "subagents", "exec"}:
        target, method = {
            "checkpoint": (loop.sessions.state, "finish_turn"),
            "subagents": (loop.subagents, "cancel_by_session"),
            "exec": (loop._exec_session_manager, "terminate_by_owner"),
        }[cleanup]
        original = getattr(target, method)

        async def cleanup_owner(*args, **kwargs):
            await pause_cleanup()
            return await original(*args, **kwargs)

        monkeypatch.setattr(target, method, cleanup_owner)

    async def process(msg, **kwargs):
        nonlocal cancellations
        roots[msg.content] = asyncio.current_task()
        queues.append(kwargs["pending_queue"])
        if msg.content == "A":
            if cleanup == "checkpoint":
                session = await loop.sessions.state.get(msg.session_key)
                await loop._set_runtime_checkpoint(session, {
                    "phase": "final_response",
                    "assistant_message": {"role": "assistant", "content": "A partial"},
                    "completed_tool_results": [], "pending_tool_calls": [],
                })
            a_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancellations += 1
                if cleanup == "process":
                    await pause_cleanup()
                raise
        b_started.set()
        await b_exit.wait()
        return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content="B answer")

    monkeypatch.setattr(loop, "_process_message", process)
    a, b = message("A"), message("/compact")
    stop_tasks = []
    try:
        await loop._dispatch_inbound(a)
        await asyncio.wait_for(a_started.wait(), 2)
        worker, = loop._active_tasks[a.session_key]
        queue = loop._pending_queues[a.session_key]
        assert roots["A"] is not worker
        await loop._dispatch_inbound(b)
        owner_a, owner_b = (msg.metadata[INBOUND_META_EXECUTION_ID] for msg in (a, b))
        cancel = asyncio.create_task(loop._cancel_execution(a.session_key, owner_a))
        stop_tasks.append(cancel)
        await asyncio.wait_for(cleaning.wait(), 2)
        pending = authority.snapshot(a.session_key)
        assert [(run["run_id"], run["phase"]) for run in pending["runs"]] == [
            (owner_a, "stopping"), (owner_b, "queued"),
        ]
        assert pending["completed"] == []
        assert not b_started.is_set()
        assert loop._active_tasks[a.session_key] == {worker}
        assert loop._pending_queues[a.session_key] is queue
        assert not worker.cancelling()
        cancellation_count = roots["A"].cancelling()
        assert await loop.executions.request_stop(a.session_key, owner_a)
        assert roots["A"].cancelling() == cancellation_count
        assert not b_started.is_set()
        assert not worker.cancelling()
        release_cleanup.set()
        await asyncio.wait_for(cancel, 2)
        await asyncio.wait_for(b_started.wait(), 2)
        assert loop._active_tasks[a.session_key] == {worker}
        assert loop._pending_queues[a.session_key] is queue
        assert roots["A"].done()
        assert roots["A"] is not roots["/compact"]
        assert roots["/compact"] is not worker
        assert all(pending_queue is queue for pending_queue in queues)
        active = authority.snapshot(a.session_key)
        assert [run["run_id"] for run in active["runs"]] == [owner_b]
        assert active["completed"] == [{
            "run_id": owner_a, "turn_id": None, "outcome": "cancelled",
        }]
        assert await loop._cancel_execution(a.session_key, owner_a) == 0
        assert authority.snapshot(a.session_key) == active
        b_exit.set()
        await finish_worker(loop, a.session_key)
        assert cancellations == 1
        assert authority.snapshot(a.session_key)["runs"] == []
        assert [(fact.phase, fact.outcome) for fact in facts if fact.execution_id == owner_a] == [
            ("queued", "unknown"), ("running", "unknown"),
            ("stopping", "unknown"), ("exited", "cancelled"),
        ]
        assert [fact.phase for fact in facts if fact.execution_id == owner_b] == [
            "queued", "running", "exited",
        ]
    finally:
        release_cleanup.set()
        b_exit.set()
        await asyncio.gather(*stop_tasks, return_exceptions=True)
        await loop.aclose()


async def test_real_runner_steering_input_does_not_own_another_execution(loop_factory):
    loop = loop_factory()
    loop.provider.provider_name = "test"
    authority = RunStateAuthority(loop.bus, "gateway")
    calls = 0

    async def chat(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            await loop._dispatch_inbound(message("steer"))
            assert len(authority.snapshot("websocket:execution-chat")["runs"]) == 1
        return LLMResponse(content="answer", finish_reason="stop")

    loop.provider.chat_stream_with_retry = chat
    msg = message()
    try:
        await loop._dispatch_inbound(msg)
        await finish_worker(loop, msg.session_key)
        snapshot = authority.snapshot(msg.session_key)
        assert snapshot["runs"] == []
        assert len(snapshot["completed"]) == 1
        assert snapshot["completed"][0]["outcome"] == "completed"
        assert calls >= 2
    finally:
        await loop.aclose()


async def test_system_session_message_executes_under_target_session(loop_factory):
    loop = loop_factory()
    loop.provider.provider_name = "test"
    authority = RunStateAuthority(loop.bus, "gateway")
    seen = []
    authority.subscribe(lambda key, state: seen.append((key, state)))
    loop.provider.chat_stream_with_retry = AsyncMock(return_value=LLMResponse(content="system answer"))
    msg = InboundMessage(
        channel="system", sender_id="session-message", chat_id="source-session",
        content="answer this target", input_role="user",
        session_key_override="websocket:target-chat",
    )
    try:
        await loop._dispatch_inbound(msg)
        await finish_worker(loop, msg.session_key)
        assert {key for key, _ in seen} == {msg.session_key}
        assert [state["runs"][0]["phase"] for _, state in seen if state["runs"]] == ["queued", "running"]
        snapshot = authority.snapshot(msg.session_key)
        assert snapshot["runs"] == []
        assert snapshot["completed"][0]["outcome"] == "completed"
        assert authority.snapshot("websocket:source-session")["runs"] == []
    finally:
        await loop.aclose()


async def test_stale_existing_session_input_retires_accepted_owner(loop_factory):
    loop = loop_factory()
    authority = RunStateAuthority(loop.bus, "gateway")
    msg = message(require_existing_session=True)
    admission = await loop.executions.reserve_if_idle(msg, msg.session_key)
    assert admission is not None
    msg.execution_admission = admission
    msg.metadata[INBOUND_META_EXECUTION_ID] = admission.execution_id
    try:
        await loop._dispatch_inbound(msg)
        snapshot = authority.snapshot(msg.session_key)
        assert snapshot["runs"] == []
        assert snapshot["completed"][0]["outcome"] == "cancelled"
        assert msg.session_key not in loop._pending_queues
    finally:
        await loop.aclose()


async def test_bus_admission_rejection_releases_transport_reservation(loop_factory, monkeypatch):
    loop = loop_factory()
    authority = RunStateAuthority(loop.bus, "gateway")
    msg = message(require_existing_session=True)
    admission = await loop.executions.reserve_if_idle(msg, msg.session_key)
    assert admission is not None
    monkeypatch.setattr(loop.sessions.state, "read_metadata", AsyncMock(
        side_effect=SessionOperationQueueFullError("session storage busy"),
    ))
    runner = asyncio.create_task(loop.run())
    try:
        await loop.bus.publish_inbound(msg)
        failed = await asyncio.wait_for(loop.bus.consume_outbound(), 2)
        assert failed.chat_id == msg.chat_id
        assert "error" in failed.content
        assert authority.snapshot(msg.session_key)["runs"] == []
        assert not await loop.executions.request_stop(msg.session_key, admission.execution_id)
        replacement = await loop.executions.reserve_if_idle(message("retry"), msg.session_key)
        assert replacement is not None
        await loop.executions.reject(replacement)
    finally:
        runner.cancel()
        await asyncio.gather(runner, return_exceptions=True)
        authority.close()


async def test_targeted_stop_acknowledges_steering_journal_without_a_new_owner(loop_factory):
    from nanobot.session.recovery import pending_followups

    loop = loop_factory()
    loop.provider.provider_name = "test"
    authority = RunStateAuthority(loop.bus, "gateway")
    entered = asyncio.Event()

    async def chat(**kwargs):
        entered.set()
        await asyncio.Event().wait()

    loop.provider.chat_stream_with_retry = chat
    msg = message(metadata={"webui": True, "webui_turn_id": "root"})
    try:
        await loop._dispatch_inbound(msg)
        await asyncio.wait_for(entered.wait(), 2)
        await loop._dispatch_inbound(message("steer", metadata={"webui": True, "webui_turn_id": "steer"}))
        session = await loop.sessions.state.read(msg.session_key)
        assert session is not None and pending_followups(session)
        assert len(authority.snapshot(msg.session_key)["runs"]) == 1
        owner = msg.metadata[INBOUND_META_EXECUTION_ID]
        assert await loop._cancel_execution(msg.session_key, owner) == 1
        session = await loop.sessions.state.read(msg.session_key)
        assert session is not None and not pending_followups(session)
        state = authority.snapshot(msg.session_key)
        assert state["runs"] == []
        assert len(state["completed"]) == 1
        assert state["completed"][0]["outcome"] == "cancelled"
    finally:
        await loop.aclose()


async def test_internal_continuation_is_admitted_before_previous_owner_exits(loop_factory):
    from nanobot.session.goal_state import GOAL_STATE_KEY

    loop = loop_factory()
    loop.provider.provider_name = "test"
    loop.max_iterations = 1
    loop.tools.prepare_call = MagicMock(return_value=(None, {}, None))
    loop.tools.execute = AsyncMock(return_value="ok")
    authority = RunStateAuthority(loop.bus, "gateway")
    observed, facts = [], []
    authority.subscribe(lambda key, state: observed.append(state))
    loop.bus.subscribe(facts.append, TurnExecutionChanged)
    msg = message()
    await loop.sessions.state.get(msg.session_key)
    await loop.sessions.state.update_metadata(msg.session_key, {
        GOAL_STATE_KEY: {"status": "active", "objective": "finish"},
    })
    calls = 0

    async def chat(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return LLMResponse(content="working", finish_reason="tool_calls", tool_calls=[
                ToolCallRequest(id="call-1", name="noop", arguments={}),
            ])
        await loop.sessions.state.update_metadata(msg.session_key, {
            GOAL_STATE_KEY: {"status": "complete", "objective": "finish"},
        })
        return LLMResponse(content="continued answer")

    loop.provider.chat_stream_with_retry = chat
    try:
        await loop._dispatch_inbound(msg)
        await finish_worker(loop, msg.session_key)
        assert calls == 2
        assert all(state["runs"] for state in observed[:-1])
        assert any(len(state["runs"]) == 2 for state in observed)
        final = authority.snapshot(msg.session_key)
        assert final["runs"] == []
        assert len({receipt["run_id"] for receipt in final["completed"]}) == 2
        assert [receipt["outcome"] for receipt in final["completed"]] == ["completed", "completed"]
        owners = [fact.execution_id for fact in facts if fact.phase == "queued"]
        assert len(owners) == len(set(owners)) == 2
        assert [fact.phase for fact in facts] == [
            "queued", "running", "queued", "exited", "running", "exited",
        ]
    finally:
        await loop.aclose()


async def test_stop_before_root_first_frame_settles_once_and_keeps_fifo(loop_factory, monkeypatch):
    loop = loop_factory()
    authority = RunStateAuthority(loop.bus, "gateway")
    facts, roots, stops = [], [], []
    loop.bus.subscribe(facts.append, TurnExecutionChanged)
    b_started, release_b = asyncio.Event(), asyncio.Event()
    calls = []

    async def process(msg, **kwargs):
        calls.append(msg.content)
        b_started.set()
        await release_b.wait()
        return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content="B answer")

    monkeypatch.setattr(loop, "_process_message", process)
    a, b = message("A"), message("/compact")
    create_task = asyncio.create_task
    armed = False

    def stop_ahead_of_first_root(coro, *args, **kwargs):
        nonlocal armed
        if armed:
            armed = False
            # Schedule the trusted Stop one event-loop step ahead of the new
            # root, after the FIFO has begun but before that child can run.
            stops.append(create_task(loop.executions.request_stop(
                a.session_key, a.execution_admission.execution_id,
            )))
            root = create_task(coro, *args, **kwargs)
            roots.append(root)
            return root
        return create_task(coro, *args, **kwargs)

    try:
        await loop._enqueue_session_message(a)
        await loop._enqueue_session_message(b)
        worker, = loop._active_tasks[a.session_key]
        queue = loop._pending_queues[a.session_key]
        monkeypatch.setattr(asyncio, "create_task", stop_ahead_of_first_root)
        armed = True
        await asyncio.wait_for(b_started.wait(), 2)
        assert await asyncio.gather(*stops) == [True]
        assert len(roots) == 1 and roots[0].cancelled()
        assert calls == ["/compact"]
        assert loop._active_tasks[a.session_key] == {worker}
        assert loop._pending_queues[a.session_key] is queue
        assert not worker.cancelling()
        owner_a = a.execution_admission.execution_id
        assert [fact.phase for fact in facts if fact.execution_id == owner_a] == [
            "queued", "stopping", "exited",
        ]
        assert authority.snapshot(a.session_key)["completed"] == [{
            "run_id": owner_a, "turn_id": None, "outcome": "cancelled",
        }]
        release_b.set()
        await finish_worker(loop, a.session_key)
        assert [receipt["outcome"] for receipt in authority.snapshot(a.session_key)["completed"]] == [
            "cancelled", "completed",
        ]
    finally:
        armed = False
        release_b.set()
        await asyncio.gather(*stops, return_exceptions=True)
        await loop.aclose()


async def test_new_input_during_stop_cleanup_becomes_a_durable_independent_root(
    loop_factory, monkeypatch,
):
    from nanobot.session.recovery import pending_followups

    loop = loop_factory()
    loop.provider.provider_name = "test"
    authority = RunStateAuthority(loop.bus, "gateway")
    started, cleaning, release_cleanup = asyncio.Event(), asyncio.Event(), asyncio.Event()
    b_started, release_b = asyncio.Event(), asyncio.Event()
    requests, facts = [], []
    loop.bus.subscribe(facts.append, TurnExecutionChanged)
    original_abort = TurnDelivery.abort_stream

    async def abort_stream(delivery):
        cleaning.set()
        await release_cleanup.wait()
        await original_abort(delivery)

    monkeypatch.setattr(TurnDelivery, "abort_stream", abort_stream)

    async def chat(*, messages, **kwargs):
        requests.append(messages)
        if len(requests) == 1:
            started.set()
            await asyncio.Event().wait()
        b_started.set()
        await release_b.wait()
        return LLMResponse(content="B answer")

    loop.provider.chat_stream_with_retry = chat
    a = message("A", metadata={"webui": True, "webui_turn_id": "turn-a"})
    b = message("B after Stop", metadata={"webui": True, "webui_turn_id": "turn-b"})
    stop = None
    try:
        await loop._dispatch_inbound(a)
        await asyncio.wait_for(started.wait(), 2)
        worker, = loop._active_tasks[a.session_key]
        queue = loop._pending_queues[a.session_key]
        await loop._dispatch_inbound(message("steer A", metadata={"webui": True}))
        owner_a = a.metadata[INBOUND_META_EXECUTION_ID]
        stop = asyncio.create_task(loop._cancel_execution(a.session_key, owner_a))
        await asyncio.wait_for(cleaning.wait(), 2)
        await loop._dispatch_inbound(b)
        snapshot = authority.snapshot(a.session_key)
        assert [(run["turn_id"], run["phase"]) for run in snapshot["runs"]] == [
            ("turn-a", "stopping"), ("turn-b", "queued"),
        ]
        assert not b_started.is_set()
        saved = await loop.sessions.state.read(a.session_key)
        assert [followup.content for followup in pending_followups(saved)] == ["steer A", "B after Stop"]
        release_cleanup.set()
        await asyncio.wait_for(stop, 2)
        await asyncio.wait_for(b_started.wait(), 2)
        assert loop._active_tasks[a.session_key] == {worker}
        assert loop._pending_queues[a.session_key] is queue
        next_prompt = visible_message(requests[1][-1])["content"]
        assert next_prompt.endswith("B after Stop")
        assert "steer A" not in next_prompt
        release_b.set()
        await finish_worker(loop, a.session_key)
        saved = await loop.sessions.state.read(a.session_key)
        assert pending_followups(saved) == []
        assert [row["content"] for row in map(visible_message, saved.messages) if row["role"] == "user"] == [
            "A", "B after Stop",
        ]
        final = authority.snapshot(a.session_key)
        assert final["runs"] == []
        assert [(receipt["turn_id"], receipt["outcome"]) for receipt in final["completed"]] == [
            ("turn-a", "cancelled"), ("turn-b", "completed"),
        ]
        assert len([fact for fact in facts if fact.phase == "queued"]) == 2
        assert len([fact for fact in facts if fact.phase == "exited"]) == 2
    finally:
        release_cleanup.set()
        release_b.set()
        if stop is not None:
            await asyncio.gather(stop, return_exceptions=True)
        await loop.aclose()


async def test_stop_does_not_ack_followup_committed_before_its_enqueue_returns(
    loop_factory, monkeypatch,
):
    from nanobot.session.manager import SessionManager
    from nanobot.session.recovery import pending_followups

    loop = loop_factory()
    loop.provider.provider_name = "test"
    authority = RunStateAuthority(loop.bus, "gateway")
    a_started, cleaning, release_cleanup = asyncio.Event(), asyncio.Event(), asyncio.Event()
    journaled, release_journal = asyncio.Event(), asyncio.Event()
    b_waiting = asyncio.Event()
    roots, tasks = [], []
    original_abort = TurnDelivery.abort_stream
    original_queue = loop.sessions.state.queue_followup
    a = message("A", metadata={"webui": True, "webui_turn_id": "turn-a"})
    b = message("B after Stop", metadata={"webui": True, "webui_turn_id": "turn-b"})
    closed = False

    async def abort_stream(delivery):
        cleaning.set()
        await release_cleanup.wait()
        await original_abort(delivery)

    async def queue_followup(key, msg):
        identifier = await original_queue(key, msg)
        if msg is b:
            journaled.set()
            await release_journal.wait()
        return identifier

    async def chat(**kwargs):
        roots.append(asyncio.current_task())
        a_started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(TurnDelivery, "abort_stream", abort_stream)
    monkeypatch.setattr(loop.sessions.state, "queue_followup", queue_followup)
    loop.provider.chat_stream_with_retry = chat
    try:
        await loop._dispatch_inbound(a)
        await asyncio.wait_for(a_started.wait(), 2)
        queue = loop._pending_queues[a.session_key]
        await loop._dispatch_inbound(message("steer A", metadata={"webui": True}))
        owner_a = a.metadata[INBOUND_META_EXECUTION_ID]
        stop = asyncio.create_task(loop._cancel_execution(a.session_key, owner_a))
        tasks.append(stop)
        await asyncio.wait_for(cleaning.wait(), 2)
        dispatch_b = asyncio.create_task(loop._dispatch_inbound(b))
        tasks.append(dispatch_b)
        await asyncio.wait_for(journaled.wait(), 2)
        assert not dispatch_b.done()
        assert queue.qsize() == 1, "B must still be outside the FIFO while its journal call awaits"
        saved = await loop.sessions.state.read(a.session_key)
        assert [item.content for item in pending_followups(saved)] == ["steer A", b.content]

        release_cleanup.set()
        assert await asyncio.wait_for(stop, 2) == 1
        await finish_worker(loop, a.session_key)
        assert a.session_key not in loop._pending_queues
        assert not dispatch_b.done()
        saved = await loop.sessions.state.read(a.session_key)
        assert [item.content for item in pending_followups(saved)] == [b.content], (
            "A's Stop acknowledged B's committed journal entry before B entered the FIFO"
        )

        # Keep B queued on real capacity: once it starts processing, recovery
        # legitimately transfers its journal entry into the turn checkpoint.
        gate = loop._concurrency_gate = asyncio.Semaphore(0)
        acquire = gate.acquire

        async def wait_for_capacity():
            roots.append(asyncio.current_task())
            b_waiting.set()
            return await acquire()

        monkeypatch.setattr(gate, "acquire", wait_for_capacity)
        release_journal.set()
        await asyncio.wait_for(dispatch_b, 2)
        await asyncio.wait_for(b_waiting.wait(), 2)
        active = authority.snapshot(a.session_key)
        assert [(run["turn_id"], run["phase"]) for run in active["runs"]] == [("turn-b", "queued")]
        assert active["runs"][0]["run_id"] != owner_a
        assert active["completed"] == [{
            "run_id": owner_a, "turn_id": "turn-a", "outcome": "cancelled",
        }]
        assert roots[0].done() and roots[1] is not roots[0]
        assert loop._pending_queues[a.session_key] is not queue

        loop.preserve_inflight_turns_on_shutdown()
        await asyncio.wait_for(loop.aclose(), 3)
        closed = True
        fresh = SessionManager(loop.sessions.workspace)
        try:
            saved = await fresh.state.read(a.session_key)
            assert saved is not None
            assert [item.content for item in pending_followups(saved)] == [b.content], (
                "B must remain recoverable from fresh storage after shutdown of its independent root"
            )
        finally:
            await fresh.state.aclose()
    finally:
        release_cleanup.set()
        release_journal.set()
        await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 3)
        if not closed:
            await asyncio.wait_for(loop.aclose(), 3)


async def test_bus_scoped_stop_of_queued_b_does_not_block_dispatch_of_session_c(
    loop_factory, monkeypatch,
):
    loop = loop_factory()
    authority = RunStateAuthority(loop.bus, "gateway")
    a_started, release_a, a_cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()
    b_dispatched, b_started, c_dispatched = asyncio.Event(), asyncio.Event(), asyncio.Event()
    facts, roots = [], {}
    loop.bus.subscribe(facts.append, TurnExecutionChanged)
    a, b = message("A"), message("/compact")
    c = InboundMessage(
        channel="websocket", sender_id="user", chat_id="other-execution-chat", content="C",
    )
    original_dispatch = loop._dispatch_inbound

    async def dispatch(msg):
        await original_dispatch(msg)
        if msg is b:
            b_dispatched.set()
        elif msg is c:
            c_dispatched.set()

    async def process(msg, **kwargs):
        roots[msg.content] = asyncio.current_task()
        if msg is a:
            a_started.set()
            try:
                await release_a.wait()
            except asyncio.CancelledError:
                a_cancelled.set()
                raise
        elif msg is b:
            b_started.set()
        return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content="answer")

    monkeypatch.setattr(loop, "_dispatch_inbound", dispatch)
    monkeypatch.setattr(loop, "_process_message", process)
    run_task = asyncio.create_task(loop.run())
    try:
        await loop.bus.publish_inbound(a)
        await asyncio.wait_for(a_started.wait(), 2)
        await loop.bus.publish_inbound(b)
        await asyncio.wait_for(b_dispatched.wait(), 2)
        owner_a, owner_b = (msg.metadata[INBOUND_META_EXECUTION_ID] for msg in (a, b))
        assert [(run["run_id"], run["phase"]) for run in authority.snapshot(a.session_key)["runs"]] == [
            (owner_a, "running"), (owner_b, "queued"),
        ]
        await loop.bus.publish_inbound(message(
            "/stop", metadata={INBOUND_META_STOP_EXECUTION_ID: owner_b},
        ))
        await loop.bus.publish_inbound(c)
        try:
            await asyncio.wait_for(c_dispatched.wait(), 2)
        except TimeoutError:
            pytest.fail(
                "bus scoped Stop B waited for physical exit behind A, blocking session C dispatch",
                pytrace=False,
            )
        assert not release_a.is_set()
        assert not a_cancelled.is_set() and not roots["A"].cancelling(), "Stop B must not cancel A"
        assert not b_started.is_set(), "a stopped queued root must never run"
        waiting = authority.snapshot(a.session_key)
        assert [(run["run_id"], run["phase"]) for run in waiting["runs"]] == [
            (owner_a, "running"), (owner_b, "stopping"),
        ]
        assert waiting["completed"] == [], "B cannot physically exit until A releases the FIFO"

        release_a.set()
        await finish_worker(loop, a.session_key)
        await finish_worker(loop, c.session_key)
        assert not b_started.is_set() and not a_cancelled.is_set()
        final = authority.snapshot(a.session_key)
        assert final["runs"] == []
        assert [(receipt["run_id"], receipt["outcome"]) for receipt in final["completed"]] == [
            (owner_a, "completed"), (owner_b, "cancelled"),
        ]
        assert [fact.phase for fact in facts if fact.execution_id == owner_b] == [
            "queued", "stopping", "exited",
        ]
        assert authority.snapshot(c.session_key)["completed"][0]["outcome"] == "completed"
    finally:
        release_a.set()
        loop.stop()
        run_task.cancel()
        await asyncio.wait_for(asyncio.gather(run_task, return_exceptions=True), 3)


async def test_cancellation_during_recovery_admission_unregisters_the_root(loop_factory, monkeypatch):
    from nanobot.session.recovery import PENDING_USER_TURN_KEY, RECOVERY_METADATA_KEY
    from nanobot.webui.recovery import RecoveryCoordinator

    loop = loop_factory()
    authority = RunStateAuthority(loop.bus, "gateway")
    coordinator = RecoveryCoordinator(loop.sessions, loop.bus)
    loop._recovery_admission = coordinator
    msg = message("interrupted request")
    session = loop.sessions.get_or_create(msg.session_key)
    session.add_message("user", msg.content)
    session.metadata[PENDING_USER_TURN_KEY] = True
    loop.sessions.save(session)
    await coordinator.scan()
    state = (await loop.sessions.state.read_metadata(msg.session_key))["metadata"][RECOVERY_METADATA_KEY]
    await coordinator.handle_action("continue", {
        "chat_id": msg.chat_id, "recovery_id": state["recovery_id"],
    })
    recovery = await loop.bus.consume_inbound()
    admitting, release_admission = asyncio.Event(), asyncio.Event()
    original_get = loop.sessions.state.get

    async def get_for_admission(key, **kwargs):
        admitting.set()
        await release_admission.wait()
        return await original_get(key, **kwargs)

    monkeypatch.setattr(loop.sessions.state, "get", get_for_admission)
    loop._process_message = AsyncMock()
    facts = []
    loop.bus.subscribe(facts.append, TurnExecutionChanged)
    try:
        await loop._dispatch_inbound(recovery)
        await asyncio.wait_for(admitting.wait(), 2)
        root = coordinator._active_recovery_tasks[msg.session_key]
        worker, = loop._active_tasks[msg.session_key]
        assert root is not worker
        owner = recovery.metadata[INBOUND_META_EXECUTION_ID]
        assert await loop._cancel_execution(msg.session_key, owner) == 1
        await finish_worker(loop, msg.session_key)
        assert root.cancelled()
        assert coordinator._active_recovery_tasks == {}
        assert not worker.cancelling()
        loop._process_message.assert_not_awaited()
        assert authority.snapshot(msg.session_key)["completed"] == [{
            "run_id": owner, "turn_id": recovery.metadata.get("webui_turn_id"), "outcome": "cancelled",
        }]
        assert [fact.phase for fact in facts] == ["queued", "stopping", "exited"]
    finally:
        release_admission.set()
        await loop.aclose()


async def test_stop_drains_children_even_when_journal_commit_fails(loop_factory, monkeypatch):
    loop = loop_factory()
    msg = message()
    admission = await loop.executions.admit(msg, msg.session_key)
    assert admission is not None
    await loop.executions.running(admission)
    assert loop.executions.accept_steering(msg.session_key, "consumed-input")
    await loop.executions.request_stop(msg.session_key, admission.execution_id)
    cancel_children = AsyncMock(return_value=0)
    terminate_exec = AsyncMock(return_value=0)
    monkeypatch.setattr(loop.subagents, "cancel_by_session", cancel_children)
    monkeypatch.setattr(loop._exec_session_manager, "terminate_by_owner", terminate_exec)
    monkeypatch.setattr(loop.sessions.state, "acknowledge_followups", AsyncMock(
        side_effect=OSError("journal commit failed"),
    ))
    try:
        with pytest.raises(OSError, match="journal commit failed"):
            await loop._settle_cancelled_execution(msg, asyncio.Queue(), True, worker=None)
        cancel_children.assert_awaited_once_with(msg.session_key)
        terminate_exec.assert_awaited_once_with(msg.session_key)
    finally:
        await loop.executions.retire(admission, "exited", outcome="cancelled")
        await loop.aclose()
