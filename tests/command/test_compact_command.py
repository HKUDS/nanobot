"""Manual context compaction command behavior."""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.outbound_events import ContextCompactionEvent
from nanobot.bus.queue import MessageBus
from nanobot.bus.runtime_events import TurnCompleted
from nanobot.command.builtin import cmd_stop
from nanobot.command.router import CommandContext
from nanobot.providers.base import GenerationSettings, LLMResponse, ProviderConversationState


@pytest.fixture
async def loop(tmp_path):
    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings(max_tokens=100)
    provider.can_resume_conversation_state.return_value = True
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content="Portable checkpoint.",
        finish_reason="stop",
    ))
    loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        context_window_tokens=128_000,
    )
    loop.tools.get_definitions = MagicMock(return_value=[])
    try:
        yield loop
    finally:
        await loop.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["/compact", " /COMPACT@nanobot "])
async def test_compact_emits_one_lifecycle_and_keeps_the_session(loop, command) -> None:
    bus = loop.bus
    session = loop.sessions.get_or_create("cli:test")
    session.add_message("user", "important question")
    session.add_message("assistant", "important answer")
    session.provider_state = ProviderConversationState(
        kind="openai_responses",
        provider="openai:test",
        model="test-model",
        version=1,
        payload={"items": []},
    )
    loop.sessions.save(session)

    msg = InboundMessage(channel="cli", sender_id="user", chat_id="test", content=command)
    response = await loop._process_message(msg, runtime=loop.llm_runtime())

    assert response is None
    assert bus.outbound_size == 2
    started = bus.outbound.get_nowait().event
    completed = bus.outbound.get_nowait().event
    assert isinstance(started, ContextCompactionEvent)
    assert isinstance(completed, ContextCompactionEvent)
    assert started.phase == "started"
    assert completed.phase == "succeeded"
    assert started.compaction_id == completed.compaction_id

    loop.sessions.invalidate("cli:test")
    reloaded = loop.sessions.get_or_create("cli:test")
    assert reloaded.provider_state is None
    assert reloaded.messages == session.messages
    assert reloaded.last_archived == 2
    assert len(loop.consolidator.store.read_unprocessed_history(0)) == 1

    response = await loop._process_message(msg, runtime=loop.llm_runtime())
    assert response is None
    assert bus.outbound_size == 0
    loop.provider.chat_with_retry.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy_commands", [False, True])
async def test_empty_compact_finishes_silently_and_does_not_schedule_idle_archive(
    loop, legacy_commands,
) -> None:
    key = "websocket:test"
    session = loop.sessions.get_or_create(key)
    session.add_message("user", "already archived")
    session.add_message("assistant", "old answer")
    session.last_archived = 2
    if legacy_commands:
        session.add_message("user", "/compact", _command=True)
        session.add_message("assistant", "Nothing to compact.", _command=True)
    loop.sessions.save(session)
    completions = []
    loop.runtime_events.subscribe(completions.append, TurnCompleted)

    await loop._dispatch(InboundMessage(
        channel="websocket", sender_id="user", chat_id="test", content="/compact",
        metadata={"webui_turn_id": "compact-turn"},
    ))

    assert loop.bus.outbound_size == 0
    assert len(completions) == 1
    assert completions[0].context.metadata["webui_turn_id"] == "compact-turn"
    loop.sessions.invalidate(key)
    reloaded = loop.sessions.get_or_create(key)
    assert reloaded.messages == session.messages
    assert reloaded.last_archived == 2
    assert loop.consolidator.store.read_unprocessed_history(0) == []

    reloaded.updated_at = datetime.now() - timedelta(minutes=30)
    loop.sessions.save(reloaded)
    loop.auto_compact._ttl = 1
    schedule = MagicMock()
    loop.auto_compact.check_expired(schedule, loop.runtime_for_session)
    schedule.assert_not_called()


@pytest.mark.asyncio
async def test_compact_during_active_turn_waits_for_the_session_lock(loop) -> None:
    key = "websocket:test"
    msg = InboundMessage(
        channel="websocket", sender_id="user", chat_id="test", content="/COMPACT@nanobot",
    )
    lock = loop._get_session_lock(key)
    async with lock:
        await loop._dispatch_command_inline(msg, key, msg.content, loop.commands.dispatch)
        tasks = list(loop._active_tasks[key])
        assert len(tasks) == 1
        await asyncio.sleep(0)
        assert not tasks[0].done()
        assert loop.bus.outbound_size == 0
        session = loop.sessions.get_or_create(key)
        session.add_message("user", "active turn question")
        session.add_message("assistant", "active turn answer")
        loop.sessions.save(session)

    await asyncio.wait_for(asyncio.gather(*tasks), timeout=5)
    assert loop.bus.outbound_size == 2
    assert loop.sessions.get_or_create(key).last_archived == 2
    loop.provider.chat_with_retry.assert_awaited_once()


@pytest.mark.asyncio
async def test_stop_completes_a_compact_command_waiting_for_the_session_lock(loop) -> None:
    key = "websocket:test"
    msg = InboundMessage(
        channel="websocket", sender_id="user", chat_id="test", content="/compact",
        metadata={"webui_turn_id": "queued-compact"},
    )
    completions = []
    loop.runtime_events.subscribe(completions.append, TurnCompleted)
    async with loop._get_session_lock(key):
        await loop._dispatch_command_inline(msg, key, msg.content, loop.commands.dispatch)
        reply = await cmd_stop(CommandContext(
            msg=msg, session=None, key=key, raw="/stop", loop=loop,
        ))
    assert reply.content == "Stopped 1 task(s)."
    assert len(completions) == 1
    assert completions[0].context.metadata["webui_turn_id"] == "queued-compact"


@pytest.mark.asyncio
async def test_stop_finishes_inflight_compaction_as_cancelled(loop) -> None:
    key = "websocket:test"
    session = loop.sessions.get_or_create(key)
    session.add_message("user", "important question")
    session.add_message("assistant", "important answer")
    loop.sessions.save(session)
    entered = asyncio.Event()

    async def wait_for_cancel(**_kwargs):
        entered.set()
        await asyncio.Event().wait()

    loop.provider.chat_with_retry.side_effect = wait_for_cancel
    completions = []
    loop.runtime_events.subscribe(completions.append, TurnCompleted)
    msg = InboundMessage(
        channel="websocket", sender_id="user", chat_id="test", content="/compact",
        metadata={"webui_turn_id": "compact-turn"},
    )
    task = asyncio.create_task(loop._dispatch(msg))
    loop._track_active_task(key, task)
    await asyncio.wait_for(entered.wait(), timeout=5)

    reply = await cmd_stop(CommandContext(
        msg=msg, session=session, key=key, raw="/stop", loop=loop,
    ))

    assert reply.content == "Stopped 1 task(s)."
    assert task.cancelled()
    assert len(completions) == 1
    assert completions[0].context.metadata["webui_turn_id"] == "compact-turn"
    events = [loop.bus.outbound.get_nowait().event for _ in range(loop.bus.outbound_size)]
    assert all(isinstance(event, ContextCompactionEvent) for event in events)
    assert [event.phase for event in events] == ["started", "cancelled"]
    assert events[0].compaction_id == events[1].compaction_id
    loop.sessions.invalidate(key)
    reloaded = loop.sessions.get_or_create(key)
    assert reloaded.messages == session.messages
    assert reloaded.last_archived == 0
