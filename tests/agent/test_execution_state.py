"""Real FIFO/exit boundaries drive runtime state, independently of delivery."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from nanobot.agent.turn_delivery import TurnDelivery
from nanobot.bus.events import INBOUND_META_EXECUTION_ID, InboundMessage, OutboundMessage
from nanobot.providers.base import LLMResponse
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


@pytest.mark.parametrize("before_start", [True, False])
async def test_queued_cancellation_exits_even_without_entering_execution(loop_factory, before_start):
    loop = loop_factory()
    authority = RunStateAuthority(loop.bus, "gateway")
    msg = message()
    lock = loop._get_session_lock(msg.session_key)
    await lock.acquire()
    try:
        await loop._dispatch_inbound(msg)
        owner = authority.snapshot(msg.session_key)["runs"][0]["run_id"]
        if not before_start:
            await asyncio.sleep(0)
        assert await loop._cancel_execution(msg.session_key, owner) == 1
        snapshot = authority.snapshot(msg.session_key)
        assert snapshot["runs"] == []
        assert snapshot["completed"][0]["outcome"] == "cancelled"
        assert msg.session_key not in loop._execution_roots
    finally:
        lock.release()
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


async def test_stop_a_preserves_queued_b_and_waits_for_a_to_exit(loop_factory, monkeypatch):
    loop = loop_factory()
    authority = RunStateAuthority(loop.bus, "gateway")
    a_started, a_unwinding, a_exit = asyncio.Event(), asyncio.Event(), asyncio.Event()
    b_started, b_exit = asyncio.Event(), asyncio.Event()

    async def process(msg, **kwargs):
        if msg.content == "A":
            a_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                a_unwinding.set()
                await a_exit.wait()
                raise
        b_started.set()
        await b_exit.wait()
        return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content="B answer")

    monkeypatch.setattr(loop, "_process_message", process)
    a, b = message("A"), message("/compact")
    try:
        await loop._dispatch_inbound(a)
        await asyncio.wait_for(a_started.wait(), 2)
        await loop._dispatch_inbound(b)
        owner_a, owner_b = (msg.metadata[INBOUND_META_EXECUTION_ID] for msg in (a, b))
        cancel = asyncio.create_task(loop._cancel_execution(a.session_key, owner_a))
        await asyncio.wait_for(a_unwinding.wait(), 2)
        pending = authority.snapshot(a.session_key)
        assert [(run["run_id"], run["phase"]) for run in pending["runs"]] == [
            (owner_a, "stopping"), (owner_b, "queued"),
        ]
        assert pending["completed"] == []
        a_exit.set()
        await asyncio.wait_for(cancel, 2)
        await asyncio.wait_for(b_started.wait(), 2)
        active = authority.snapshot(a.session_key)
        assert [run["run_id"] for run in active["runs"]] == [owner_b]
        assert active["completed"][0]["outcome"] == "cancelled"
        assert await loop._cancel_execution(a.session_key, owner_a) == 0
        assert authority.snapshot(a.session_key) == active
        b_exit.set()
        await finish_worker(loop, a.session_key)
        assert authority.snapshot(a.session_key)["runs"] == []
    finally:
        a_exit.set()
        b_exit.set()
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
    admission = authority.admit_if_idle(msg.session_key, "accepted", msg.session_key)
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


async def test_internal_continuation_is_admitted_before_previous_owner_exits(loop_factory, monkeypatch):
    from types import SimpleNamespace

    from nanobot.agent.tools.context import RequestContext
    from nanobot.session.turn_continuation import maybe_continue_turn

    loop = loop_factory()
    authority = RunStateAuthority(loop.bus, "gateway")
    observed = []
    authority.subscribe(lambda key, state: observed.append(state))

    async def process(msg, **kwargs):
        if msg.content == "hello":
            metadata = {"goal_state": {"status": "active", "objective": "finish"}}
            await loop.sessions.state.get(msg.session_key)
            await loop.sessions.state.update_metadata(msg.session_key, metadata)
            ctx = SimpleNamespace(
                msg=msg, session_key=msg.session_key, session=SimpleNamespace(metadata=metadata),
                request_context=RequestContext(channel=msg.channel, chat_id=msg.chat_id, turn_id="logical-turn"),
                pending_queue=kwargs["pending_queue"], delivery=kwargs["delivery"],
                stop_reason="max_iterations", final_content="", all_messages=[],
                suppress_response=False, visible_run_started_at=10,
            )
            assert await maybe_continue_turn(ctx, session_metadata=metadata)
            return None
        return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content="continued answer")

    monkeypatch.setattr(loop, "_process_message", process)
    msg = message()
    try:
        await loop._dispatch_inbound(msg)
        await finish_worker(loop, msg.session_key)
        assert all(state["runs"] for state in observed[:-1])
        assert any(len(state["runs"]) == 2 for state in observed)
        final = authority.snapshot(msg.session_key)
        assert final["runs"] == []
        assert len({receipt["run_id"] for receipt in final["completed"]}) == 2
    finally:
        await loop.aclose()
