"""Independent turns and internal controls retain their session inbox semantics."""

import asyncio
import faulthandler
import threading
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.session_helpers import run_session
from nanobot.agent.automation_turns import AutomationTurnError
from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.context import current_request_context
from nanobot.agent.tools.cron import CronTool
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.cron.service import CronService
from nanobot.cron.session_turns import CRON_DEFER_UNTIL_IDLE_META, CRON_TRIGGER_META
from nanobot.providers.base import GenerationSettings, LLMResponse, ToolCallRequest
from nanobot.runtime_context import public_history_messages
from nanobot.session.automation_turns import AUTOMATION_HISTORY_META
from nanobot.session.goal_state import GOAL_STATE_KEY
from nanobot.session.manager import SessionManager
from nanobot.session.recovery import (
    PENDING_FOLLOWUPS_KEY,
    REQUEST_ORIGIN_METADATA_KEY,
    pending_followups,
)
from nanobot.triggers.local_session_turns import LOCAL_TRIGGER_META
from nanobot.webui.recovery import RecoveryCoordinator


@pytest.fixture
async def loop(tmp_path):
    provider = MagicMock(aclose=AsyncMock())
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings(max_tokens=100)
    provider.can_resume_conversation_state.return_value = False
    provider.estimate_prompt_tokens.return_value = (100, "test")
    agent = AgentLoop(
        bus=MessageBus(), provider=provider, workspace=tmp_path, model="test-model",
    )
    agent.tools.get_definitions = MagicMock(return_value=[])
    try:
        yield agent
    finally:
        await agent.aclose()


@pytest.mark.parametrize("rejection", ["stop", "followup", "replaced-followup", "idle"])
async def test_rejected_input_does_not_stop_other_sessions(loop, monkeypatch, rejection):
    state = loop.sessions.state
    session = await state.get("websocket:busy")
    model_started, release_model = asyncio.Event(), asyncio.Event()
    readers_started, release_readers = threading.Event(), threading.Event()
    idle_checked = asyncio.Event()
    active_turn = rejection in {"followup", "replaced-followup"}
    readers = []

    async def chat(**kwargs):
        if active_turn and not model_started.is_set():
            model_started.set()
            await release_model.wait()
        return LLMResponse(content="still responsive")

    async def reply(chat_id):
        async with asyncio.timeout(5):
            while True:
                message = await loop.bus.consume_outbound()
                if message.chat_id == chat_id and message.event is None:
                    return message

    original_list = loop.sessions._store.list_metadata

    def blocked_list():
        readers_started.set()
        assert release_readers.wait(5)
        return original_list()

    loop.provider.chat_stream_with_retry = chat
    if rejection == "idle":
        original_check = loop.auto_compact.check_expired

        async def observed_check(*args, **kwargs):
            try:
                await original_check(*args, **kwargs)
            finally:
                idle_checked.set()

        monkeypatch.setattr(loop.auto_compact, "check_expired", observed_check)
        loop._next_idle_compact_check_at = 0
    run_task = asyncio.create_task(loop.run())
    try:
        if active_turn:
            await loop.bus.publish_inbound(InboundMessage(
                channel="websocket", sender_id="u", chat_id="busy", content="first",
                metadata={"webui": True}, session_generation=session.generation,
            ))
            await asyncio.wait_for(model_started.wait(), timeout=3)
        if rejection == "replaced-followup":
            await state.reset(session.key)
        else:
            monkeypatch.setattr(loop.sessions._store, "list_metadata", blocked_list)
            readers = [asyncio.create_task(state.list_metadata()) for _ in range(64)]
            assert await asyncio.to_thread(readers_started.wait, 2)

        if rejection == "idle":
            await asyncio.wait_for(idle_checked.wait(), timeout=3)
        else:
            rejected = InboundMessage(
                channel="telegram" if rejection == "stop" else "websocket",
                sender_id="u", chat_id="busy",
                content="/stop" if rejection == "stop" else "rejected follow-up",
                metadata={"webui": True}, session_generation=session.generation,
            )
            await loop.bus.publish_inbound(rejected)
            assert (await reply("busy")).content == "Sorry, I encountered an error."
        assert not run_task.done()

        release_readers.set()
        await asyncio.gather(*readers)
        await loop.bus.publish_inbound(InboundMessage(
            channel="telegram", sender_id="u", chat_id="other", content="hello",
        ))
        assert (await reply("other")).content == "still responsive"
        if active_turn:
            assert not release_model.is_set()
            assert loop._pending_queues[session.key].empty()
            saved = await state.read(session.key)
            assert pending_followups(saved) == []
    finally:
        release_readers.set()
        await asyncio.gather(*readers, return_exceptions=True)
        loop.stop()
        run_task.cancel()
        await asyncio.gather(run_task, return_exceptions=True)


def _automation_message(kind: str, name: str) -> InboundMessage:
    metadata = (
        {
            CRON_TRIGGER_META: {"job_id": name, "run_id": name, "persist_content": name},
            CRON_DEFER_UNTIL_IDLE_META: True,
        }
        if kind == "cron"
        else {
            LOCAL_TRIGGER_META: {
                "trigger_id": name, "delivery_id": name, "persist_content": name,
            },
        }
    )
    return InboundMessage(
        channel="websocket", sender_id=kind, chat_id="test", content=name, metadata=metadata,
    )


@pytest.mark.parametrize("kind", ["cron", "local_trigger"])
async def test_automation_turn_is_deferred_while_session_active(loop, kind):
    key = "websocket:test"
    pending = asyncio.Queue()
    loop._pending_queues[key] = pending
    coordinator = loop._cron_turns if kind == "cron" else loop._local_trigger_turns
    pending_ids = (
        loop.pending_cron_job_ids_for_session
        if kind == "cron"
        else loop.pending_local_trigger_ids_for_session
    )
    msg = _automation_message(kind, "deferred")
    run_task = asyncio.create_task(loop.run())

    try:
        await loop.bus.publish_inbound(msg)
        async with asyncio.timeout(3):
            while not coordinator.deferred_queues.get(key):
                await asyncio.sleep(0)
        assert pending.empty()
        assert loop._active_tasks == {}
        assert coordinator.deferred_queues[key] == [msg]
        assert pending_ids(key) == {"deferred"}

        loop._process_message = AsyncMock(return_value=None)
        await loop._run_session_queue(key, pending)
        assert loop._process_message.await_args.args[0] is msg
        assert key not in coordinator.deferred_queues
        assert pending_ids(key) == set()
    finally:
        loop.stop()
        if not run_task.done():
            run_task.cancel()
        await asyncio.gather(run_task, return_exceptions=True)


@pytest.mark.parametrize("kind", ["cron", "local_trigger"])
async def test_submitted_automation_reports_pending_until_completed(loop, kind):
    coordinator = loop._cron_turns if kind == "cron" else loop._local_trigger_turns
    coordinator._enqueue = AsyncMock()
    submit = loop.submit_cron_turn if kind == "cron" else loop.submit_local_trigger_turn
    pending_ids = (
        loop.pending_cron_job_ids_for_session
        if kind == "cron"
        else loop.pending_local_trigger_ids_for_session
    )
    msg = _automation_message(kind, "pending")
    submit_task = asyncio.create_task(submit(msg))

    try:
        await asyncio.sleep(0)
        assert pending_ids(msg.session_key) == {"pending"}

        response = OutboundMessage(channel="websocket", chat_id="test", content="done")
        coordinator.complete(msg, response=response)

        assert await asyncio.wait_for(submit_task, timeout=1) is response
        assert pending_ids(msg.session_key) == set()
    finally:
        if not submit_task.done():
            submit_task.cancel()
        await asyncio.gather(submit_task, return_exceptions=True)


@pytest.mark.parametrize(
    ("first_kind", "second_fails", "bus_running"),
    [
        ("cron", False, False),
        ("cron", True, True),
        ("local_trigger", False, True),
        ("local_trigger", True, False),
    ],
)
async def test_automation_turns_complete_independently(loop, first_kind, second_fails, bus_running):
    started, release = asyncio.Event(), asyncio.Event()
    release_second = asyncio.Event()
    senders = []

    async def chat(**kwargs):
        senders.append(current_request_context().sender_id)
        if len(senders) == 1:
            started.set()
            await release.wait()
            return LLMResponse(content="first response")
        await release_second.wait()
        if second_fails:
            raise RuntimeError("second task failed")
        return LLMResponse(content="second response")

    loop.provider.chat_stream_with_retry = chat
    second_kind = "local_trigger" if first_kind == "cron" else "cron"
    submit = {"cron": loop.submit_cron_turn, "local_trigger": loop.submit_local_trigger_turn}
    tasks = []
    if bus_running:
        tasks.append(asyncio.create_task(loop.run()))
        await asyncio.sleep(0)
    first = asyncio.create_task(submit[first_kind](_automation_message(first_kind, "first")))
    tasks.append(first)
    try:
        await asyncio.wait_for(started.wait(), timeout=3)
        second = asyncio.create_task(submit[second_kind](_automation_message(second_kind, "second")))
        tasks.append(second)
        await asyncio.sleep(0)
        assert not second.done()
        release.set()
        first_response = await asyncio.wait_for(first, timeout=3)
        assert first_response.content == "first response"
        assert not second.done()
        release_second.set()
        if second_fails:
            with pytest.raises(AutomationTurnError, match="second task failed"):
                await asyncio.wait_for(second, timeout=3)
        else:
            second_response = await asyncio.wait_for(second, timeout=3)
            assert second_response.content == "second response"
        assert senders == [first_kind, second_kind]
        assert loop.pending_cron_job_ids_for_session("websocket:test") == set()
        assert loop.pending_local_trigger_ids_for_session("websocket:test") == set()
        loop.sessions.invalidate("websocket:test")
        session = loop.sessions.get_or_create("websocket:test")
        user_rows = [message for message in session.messages if message["role"] == "user"]
        assert [message[AUTOMATION_HISTORY_META]["kind"] for message in user_rows] == [
            first_kind, second_kind,
        ]
        assert PENDING_FOLLOWUPS_KEY not in session.metadata
    finally:
        release.set()
        release_second.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def test_cancelled_session_completes_queued_automation_waiters(loop):
    started = asyncio.Event()

    async def chat(**kwargs):
        started.set()
        await asyncio.Event().wait()

    loop.provider.chat_stream_with_retry = chat
    worker = asyncio.create_task(run_session(loop, InboundMessage(
        channel="websocket", sender_id="u", chat_id="test", content="user request",
    )))
    tasks = [worker]
    try:
        await asyncio.wait_for(started.wait(), timeout=3)
        cron = asyncio.create_task(loop.submit_cron_turn(_automation_message("cron", "cron")))
        trigger = asyncio.create_task(loop.submit_local_trigger_turn(
            _automation_message("local_trigger", "trigger"),
        ))
        tasks.extend([cron, trigger])
        await asyncio.sleep(0)
        assert len(loop._deferred_automation_turns["websocket:test"]) == 2
        worker.cancel()
        with pytest.raises(asyncio.CancelledError):
            await worker
        for task in (cron, trigger):
            with pytest.raises(AutomationTurnError, match="CancelledError"):
                await asyncio.wait_for(task, timeout=3)
        assert "websocket:test" not in loop._pending_queues
        assert loop.pending_cron_job_ids_for_session("websocket:test") == set()
        assert loop.pending_local_trigger_ids_for_session("websocket:test") == set()
        session = loop.sessions.get_or_create("websocket:test")
        assert PENDING_FOLLOWUPS_KEY not in session.metadata
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.parametrize("followup_still_queued", [True, False])
@pytest.mark.parametrize("shutdown", [True, False])
async def test_stopped_followups_are_not_recovered_but_shutdown_preserves_them(
    loop,
    tmp_path,
    followup_still_queued,
    shutdown,
):
    started = asyncio.Event()

    async def chat(**kwargs):
        started.set()
        await asyncio.Event().wait()

    loop.provider.chat_stream_with_retry = chat
    key = "websocket:test"
    (await loop._enqueue_session_message(InboundMessage(
        channel="websocket", sender_id="u", chat_id="test", content="first",
        metadata={"webui": True},
    )))
    await asyncio.wait_for(started.wait(), timeout=3)
    (await loop._enqueue_session_message(InboundMessage(
        channel="websocket", sender_id="u", chat_id="test", content="cancel me",
        metadata={"webui": True},
    )))

    if not followup_still_queued:
        consumed = loop._pending_queues[key].get_nowait()
        assert consumed.content == "cancel me"
    session = loop.sessions.get_or_create(key)
    assert [message.content for message in pending_followups(session)] == ["cancel me"]

    if shutdown:
        loop.preserve_inflight_turns_on_shutdown()
        await loop.aclose()
    else:
        stop = InboundMessage(
            channel="websocket", sender_id="u", chat_id="test", content="/stop",
        )
        await loop._dispatch_command_inline(stop, key, "/stop", loop.commands.dispatch_priority)

    # Use fresh managers and the real startup scan: a cache-only assertion can
    # miss the canceled journal being replayed from disk on the next restart.
    expected = ["cancel me"] if shutdown else []
    for _ in range(2):
        restarted = SessionManager(tmp_path)
        bus = MessageBus()
        assert key in {item["key"] for item in restarted.list_sessions()}
        assert [message.content for message in pending_followups(
            restarted.get_or_create(key)
        )] == expected
        await RecoveryCoordinator(restarted, bus).scan()
        recovered = []
        while not bus.inbound.empty():
            recovered.append((await bus.consume_inbound()).content)
        assert recovered == expected


async def test_cancel_preserves_followups_accepted_after_cancellation_started(loop):
    key = "websocket:test"
    session = await loop.sessions.state.get(key)

    async def journal(content):
        await loop.sessions.state.queue_followup(key, InboundMessage(
            channel="websocket", sender_id="u", chat_id="test", content=content,
            metadata={"webui": True}, session_generation=session.generation,
        ))

    await journal("old followup")
    started = asyncio.Event()
    cancelling = asyncio.Event()
    release = asyncio.Event()

    async def worker():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelling.set()
            await release.wait()

    task = asyncio.create_task(worker())
    loop._track_active_task(key, task)
    await started.wait()
    stop = asyncio.create_task(loop._cancel_active_tasks(key))
    try:
        await asyncio.wait_for(cancelling.wait(), timeout=3)
        await journal("new followup")
    finally:
        release.set()
        await stop

    loop.sessions.invalidate(key)
    assert [message.content for message in pending_followups(
        loop.sessions.get_or_create(key)
    )] == ["new followup"]


@pytest.mark.parametrize("action", ["stop", "close"])
async def test_cancel_before_worker_runs_completes_automation(loop, action):
    loop.provider.chat_stream_with_retry = AsyncMock(return_value=LLMResponse(content="unused"))
    submit = asyncio.create_task(loop.submit_cron_turn(_automation_message("cron", "queued")))
    try:
        await asyncio.sleep(0)
        assert "websocket:test" in loop._pending_queues
        if action == "stop":
            await loop._cancel_active_tasks("websocket:test")
        else:
            await loop.aclose()
        with pytest.raises(AutomationTurnError, match="CancelledError"):
            await asyncio.wait_for(submit, timeout=3)
        loop.provider.chat_stream_with_retry.assert_not_awaited()
        assert "websocket:test" not in loop._pending_queues
        assert loop.pending_cron_job_ids_for_session("websocket:test") == set()
    finally:
        if not submit.done():
            submit.cancel()
        await asyncio.gather(submit, return_exceptions=True)


@pytest.mark.parametrize(
    ("kind", "action", "waiting_for"),
    [
        ("cron", "stop", "session_lock"),
        ("cron", "close", "capacity"),
        ("local_trigger", "stop", "capacity"),
        ("local_trigger", "close", "session_lock"),
    ],
)
async def test_cancel_before_execution_completes_automation(loop, kind, action, waiting_for):
    key = "websocket:test"
    if waiting_for == "capacity":
        blocker = loop._concurrency_gate = asyncio.Semaphore(1)
    else:
        blocker = loop._get_session_lock(key)
    await blocker.acquire()
    loop.provider.chat_stream_with_retry = AsyncMock(return_value=LLMResponse(content="unused"))
    submit_turn = loop.submit_cron_turn if kind == "cron" else loop.submit_local_trigger_turn
    submitted = asyncio.create_task(submit_turn(_automation_message(kind, "waiting")))
    try:
        async with asyncio.timeout(3):
            while key not in loop._pending_queues or not loop._pending_queues[key].empty():
                await asyncio.sleep(0)
        if action == "stop":
            await loop._cancel_active_tasks(key)
        else:
            await loop.aclose()
        with pytest.raises(AutomationTurnError, match="CancelledError"):
            await asyncio.wait_for(asyncio.shield(submitted), timeout=1)
        loop.provider.chat_stream_with_retry.assert_not_awaited()
    finally:
        blocker.release()
        if not submitted.done():
            submitted.cancel()
        await asyncio.gather(submitted, return_exceptions=True)


@pytest.mark.parametrize("bus_running", [False, True])
async def test_ingress_sources_share_one_session_worker(loop, bus_running):
    started, release = asyncio.Event(), asyncio.Event()
    handled = []
    workers = []
    key = "websocket:test"

    async def process(msg, **kwargs):
        handled.append(msg.content)
        workers.append(asyncio.current_task())
        if msg.content == "first":
            started.set()
            await release.wait()
        return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content=msg.content)

    loop._process_message = process
    tasks = []
    if bus_running:
        tasks.append(asyncio.create_task(loop.run()))
    try:
        first = InboundMessage(channel="websocket", sender_id="u", chat_id="test", content="first")
        if bus_running:
            await loop.bus.publish_inbound(first)
        else:
            (await loop._enqueue_session_message(first))
        await asyncio.wait_for(started.wait(), timeout=3)
        cron = asyncio.create_task(loop.submit_cron_turn(_automation_message("cron", "cron")))
        trigger = asyncio.create_task(loop.submit_local_trigger_turn(
            _automation_message("local_trigger", "trigger"),
        ))
        tasks.extend([cron, trigger])
        await asyncio.sleep(0)
        second = InboundMessage(channel="websocket", sender_id="u", chat_id="test", content="second")
        if bus_running:
            await loop.bus.publish_inbound(second)
            async with asyncio.timeout(3):
                while loop._pending_queues[key].empty():
                    await asyncio.sleep(0)
        else:
            (await loop._enqueue_session_message(second))
        compact = InboundMessage(channel="websocket", sender_id="u", chat_id="test", content="/compact")
        await loop._dispatch_command_inline(compact, key, compact.content, loop.commands.dispatch)
        assert len(loop._active_tasks[key]) == 1
        release.set()
        results = await asyncio.wait_for(asyncio.gather(cron, trigger), timeout=3)
        assert [result.content for result in results] == ["cron", "trigger"]
        assert handled == ["first", "second", "/compact", "cron", "trigger"]
        assert len(set(workers)) == 1
        assert loop.bus.inbound_size == 0
        assert key not in loop._pending_queues
        assert key not in loop._deferred_automation_turns
    finally:
        release.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.parametrize("start_with_cron", [False, True])
async def test_cron_restriction_follows_the_current_turn(loop, tmp_path, start_with_cron):
    cron = CronService(tmp_path / "jobs.json")
    tool = CronTool(cron)
    started, release = asyncio.Event(), asyncio.Event()
    attempts = []
    workers = []

    async def chat(**kwargs):
        workers.append(asyncio.current_task())
        result = await tool.execute(action="add", message="reminder", every_seconds=60)
        attempts.append(result)
        if len(attempts) == 1:
            started.set()
            await release.wait()
        return LLMResponse(content="done")

    loop.provider.chat_stream_with_retry = chat
    if start_with_cron:
        first = asyncio.create_task(loop.submit_cron_turn(_automation_message("cron", "first")))
    else:
        first = asyncio.create_task(run_session(loop, InboundMessage(
            channel="websocket", sender_id="u", chat_id="test", content="first",
        )))
    tasks = [first]
    try:
        await asyncio.wait_for(started.wait(), timeout=3)
        if not start_with_cron:
            tasks.append(asyncio.create_task(loop.submit_cron_turn(
                _automation_message("cron", "cron"),
            )))
        tasks.append(asyncio.create_task(loop.submit_local_trigger_turn(
            _automation_message("local_trigger", "trigger"),
        )))
        await asyncio.sleep(0)
        release.set()
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=3)
        assert [result.startswith("Created job") for result in attempts] == (
            [False, True] if start_with_cron else [True, False, True]
        )
        blocked = attempts[0 if start_with_cron else 1]
        assert blocked == "Error: cannot schedule new jobs from within a cron job execution"
        assert len(set(workers)) == 1
    finally:
        release.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.parametrize("complete_on_followup", [False, True])
async def test_goal_continuation_after_followup_keeps_control_identity(loop, complete_on_followup):
    loop.max_iterations = 1
    loop.tools.prepare_call = MagicMock(return_value=(None, {}, None))
    loop.tools.execute = AsyncMock(return_value="ok")
    session = loop.sessions.get_or_create("cli:test")
    session.metadata[GOAL_STATE_KEY] = {"status": "active", "objective": "Finish the long goal"}
    loop.sessions.save(session)
    requests = []

    async def chat(*, messages, **kwargs):
        requests.append([dict(message) for message in messages])
        if len(requests) == 1:
            await loop.bus.publish_inbound(InboundMessage(
                channel="cli", sender_id="u", chat_id="test", content="Inspect file B first",
            ))
            async with asyncio.timeout(3):
                while loop._pending_queues["cli:test"].empty():
                    await asyncio.sleep(0)
        elif complete_on_followup or len(requests) == 3:
            await loop.sessions.state.update_metadata(session.key, {
                GOAL_STATE_KEY: {"status": "complete", "objective": "Finish the long goal"},
            })
            return LLMResponse(content="done")
        return LLMResponse(
            content="working", finish_reason="tool_calls",
            tool_calls=[ToolCallRequest(id=f"call-{len(requests)}", name="noop", arguments={})],
        )

    loop.provider.chat_stream_with_retry = chat
    run_task = asyncio.create_task(loop.run())
    try:
        await loop.bus.publish_inbound(InboundMessage(
            channel="cli", sender_id="u", chat_id="test", content="Start the goal",
        ))
        async with asyncio.timeout(5):
            while not requests or "cli:test" in loop._pending_queues:
                await asyncio.sleep(0.01)
        assert len(requests) == (2 if complete_on_followup else 3)
        continuation_text = "Continue the active sustained goal after the previous turn"
        assert continuation_text not in str(requests[1])
        if not complete_on_followup:
            assert continuation_text in str(requests[2])
        loop.sessions.invalidate("cli:test")
        history = public_history_messages(loop.sessions.get_or_create("cli:test").messages)
        assert [message["content"] for message in history if message["role"] == "user"] == [
            "Start the goal", "Inspect file B first",
        ]
    finally:
        loop.stop()
        await asyncio.wait_for(run_task, timeout=3)


async def test_queued_continuation_keeps_its_origin_after_another_chat_runs(loop):
    loop._unified_session = True
    loop.max_iterations = 1
    loop.tools.prepare_call = MagicMock(return_value=(None, {}, None))
    loop.tools.execute = AsyncMock(return_value="ok")
    key = "unified:default"
    session = loop.sessions.get_or_create(key)
    session.metadata[GOAL_STATE_KEY] = {"status": "active", "objective": "Finish the goal"}
    loop.sessions.save(session)
    requests = []
    persisted_origin = None

    async def chat(**kwargs):
        nonlocal persisted_origin
        context = current_request_context()
        requests.append((context.chat_id, context.message_id, context.turn_id))
        if len(requests) == 1:
            await loop.bus.publish_inbound(InboundMessage(
                channel="feishu", sender_id="user", chat_id="chat-b", content="Inspect B first",
                metadata={"message_id": "message-b"},
            ))
            async with asyncio.timeout(3):
                while loop._pending_queues[key].empty():
                    await asyncio.sleep(0)
        elif len(requests) == 3:
            persisted = SessionManager(loop.workspace).get_or_create(key)
            persisted_origin = persisted.metadata[REQUEST_ORIGIN_METADATA_KEY]
            await loop.tools.get("message").execute(content="Continuation reply")
            await loop.sessions.state.mutate_metadata(
                key, lambda metadata: metadata[GOAL_STATE_KEY].update(status="complete"),
            )
            return LLMResponse(content="done")
        return LLMResponse(content="working", finish_reason="tool_calls", tool_calls=[
            ToolCallRequest(id=f"call-{len(requests)}", name="noop", arguments={}),
        ])

    loop.provider.chat_stream_with_retry = chat
    worker = asyncio.create_task(loop.run())
    try:
        await loop.bus.publish_inbound(InboundMessage(
            channel="feishu", sender_id="user", chat_id="chat-a", content="Start the goal",
            metadata={"message_id": "message-a"},
        ))
        async with asyncio.timeout(5):
            while not requests or key in loop._pending_queues:
                await asyncio.sleep(0.01)
        assert [request[:2] for request in requests] == [
            ("chat-a", "message-a"), ("chat-b", "message-b"), ("chat-a", "message-a"),
        ]
        assert requests[2][2] == requests[0][2]
        assert persisted_origin == {"message_id": "message-a", "turn_id": requests[0][2]}
        replies = []
        while not loop.bus.outbound.empty():
            reply = loop.bus.outbound.get_nowait()
            if reply.content == "Continuation reply":
                replies.append((reply.chat_id, reply.metadata.get("message_id")))
        assert replies == [("chat-a", "message-a")]
    finally:
        loop.stop()
        try:
            await asyncio.wait_for(worker, timeout=3)
        except TimeoutError:
            # Native Windows CI has timed out after the routing assertions.
            # Preserve the deadline and expose the shielded storage drain.
            close_task = loop.sessions.state._close_task
            if close_task is not None:
                close_task.print_stack()
            faulthandler.dump_traceback()
            raise
