import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.cron.session_turns import CRON_DEFER_UNTIL_IDLE_META, CRON_TRIGGER_META
from nanobot.providers.base import GenerationSettings, LLMResponse
from nanobot.session.webui_turns import WebuiTurnCoordinator


def _make_loop(tmp_path):
    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings(max_tokens=0)
    provider.estimate_prompt_tokens.return_value = (0, "test-counter")
    response = LLMResponse(content="done", tool_calls=[])
    provider.chat_with_retry = AsyncMock(return_value=response)
    provider.chat_stream_with_retry = AsyncMock(return_value=response)

    loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=tmp_path,
        model="test-model",
    )
    WebuiTurnCoordinator(
        bus=bus,
        sessions=loop.sessions,
        schedule_background=lambda coro: loop._schedule_background(coro),
    ).subscribe(loop.runtime_events)
    loop.tools.get_definitions = MagicMock(return_value=[])
    return loop


@pytest.mark.asyncio
async def test_process_direct_websocket_clears_run_status(tmp_path) -> None:
    loop = _make_loop(tmp_path)

    response = await loop.process_direct(
        "deliver reminder",
        session_key="cron:reminder-1",
        channel="websocket",
        chat_id="chat-1",
    )

    assert response is not None
    assert response.content == "done"

    events = []
    while loop.bus.outbound_size:
        events.append(await loop.bus.consume_outbound())

    statuses = [
        event.metadata
        for event in events
        if event.metadata.get("_goal_status") is True
    ]
    assert [status["goal_status"] for status in statuses] == ["running", "idle"]
    assert isinstance(statuses[0].get("started_at"), float)
    assert "started_at" not in statuses[1]


@pytest.mark.asyncio
async def test_process_direct_reuses_existing_session_lock(tmp_path) -> None:
    loop = _make_loop(tmp_path)
    loop._connect_mcp = AsyncMock()
    session_key = "api:fixed"
    lock = loop._session_locks.setdefault(session_key, asyncio.Lock())
    await lock.acquire()
    entered = asyncio.Event()

    async def _process_message(msg, **_kwargs):
        entered.set()
        return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content=msg.content)

    loop._process_message = _process_message
    task = asyncio.create_task(loop.process_direct("direct", session_key=session_key))
    try:
        await asyncio.sleep(0)
        assert not entered.is_set()

        lock.release()
        response = await asyncio.wait_for(task, timeout=1.0)

        assert entered.is_set()
        assert response is not None
        assert response.content == "direct"
    finally:
        if lock.locked():
            lock.release()
        if not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task


@pytest.mark.asyncio
async def test_process_direct_applies_per_run_hooks(tmp_path) -> None:
    from nanobot.agent.hook import AgentHook, AgentRunHookContext

    loop = _make_loop(tmp_path)
    events: list[tuple[str, str | None]] = []

    class RecordingHook(AgentHook):
        async def before_run(self, context: AgentRunHookContext) -> None:
            events.append(("before", None))

        async def after_run(self, context: AgentRunHookContext) -> None:
            events.append(("after", context.final_content))

    response = await loop.process_direct(
        "hello",
        session_key="api:per-run-hook",
        hooks=[RecordingHook()],
    )

    assert response is not None
    assert response.content == "done"
    assert events == [("before", None), ("after", "done")]


@pytest.mark.asyncio
async def test_process_direct_creates_and_cleans_up_pending_queue(tmp_path) -> None:
    """process_direct should register a pending_queue during execution and remove it after."""
    loop = _make_loop(tmp_path)
    session_key = "cron:test-queue"

    assert session_key not in loop._pending_queues

    await loop.process_direct("hello", session_key=session_key)

    assert session_key not in loop._pending_queues


@pytest.mark.asyncio
async def test_process_direct_passes_pending_queue_to_process_message(tmp_path) -> None:
    """process_direct should pass a non-None pending_queue to _process_message."""
    loop = _make_loop(tmp_path)
    loop._connect_mcp = AsyncMock()
    captured_kwargs = {}

    async def _process_message(msg, **kwargs):
        captured_kwargs.update(kwargs)
        return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content=msg.content)

    loop._process_message = _process_message

    await loop.process_direct("hello", session_key="cron:test-pq")

    assert "pending_queue" in captured_kwargs
    assert captured_kwargs["pending_queue"] is not None


@pytest.mark.asyncio
async def test_process_direct_republishes_leftover_queue_messages(tmp_path) -> None:
    """Messages left in the pending queue after process_direct should be re-published to the bus."""
    loop = _make_loop(tmp_path)
    loop._connect_mcp = AsyncMock()
    session_key = "cron:test-leftover"

    async def _process_message(msg, **kwargs):
        # Simulate a subagent result arriving in the pending queue
        # during execution but not consumed by the runner.
        pq = kwargs.get("pending_queue")
        if pq is not None:
            from nanobot.bus.events import InboundMessage
            pq.put_nowait(InboundMessage(
                channel="system", sender_id="subagent", chat_id="cli:c",
                content="subagent result",
            ))
        return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content=msg.content)

    loop._process_message = _process_message

    await loop.process_direct("hello", session_key=session_key)

    # The leftover message should have been re-published to the bus
    msgs = []
    while loop.bus.inbound_size:
        msgs.append(await asyncio.wait_for(loop.bus.consume_inbound(), timeout=0.5))
    contents = [m.content for m in msgs]
    assert "subagent result" in contents


@pytest.mark.asyncio
async def test_process_direct_publishes_deferred_cron_turn_after_pending_queue(tmp_path) -> None:
    loop = _make_loop(tmp_path)
    loop._connect_mcp = AsyncMock()
    session_key = "cron:test-deferred"

    async def _process_message(msg, **_kwargs):
        deferred = InboundMessage(
            channel="websocket",
            sender_id="cron",
            chat_id="chat-1",
            content="deferred cron turn",
            metadata={
                CRON_TRIGGER_META: {"job_id": "job-1", "run_id": "run-1"},
                CRON_DEFER_UNTIL_IDLE_META: True,
            },
        )
        assert loop._cron_turns.defer_if_active(
            deferred,
            session_key=session_key,
            active_session_keys=loop._pending_queues.keys(),
        )
        return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content=msg.content)

    loop._process_message = _process_message

    await loop.process_direct("hello", session_key=session_key)

    msg = await asyncio.wait_for(loop.bus.consume_inbound(), timeout=0.5)
    assert msg.content == "deferred cron turn"
    assert session_key not in loop._cron_turns.deferred_queues
