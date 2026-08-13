import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import (
    INBOUND_META_RUNTIME_CONTROL,
    RUNTIME_CONTROL_SESSION_DISCARD,
    InboundMessage,
)
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import GenerationSettings, LLMResponse
from nanobot.session.keys import UNIFIED_SESSION_KEY


def _message(key: str, content: str) -> InboundMessage:
    return InboundMessage(
        channel="websocket",
        sender_id="user",
        chat_id=key.removeprefix("websocket:"),
        content=content,
        session_key_override=key,
        require_existing_session=True,
    )


def _loop(tmp_path, responses: list[str], **kwargs) -> AgentLoop:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings()
    provider.chat_with_retry = AsyncMock(
        side_effect=[LLMResponse(content=response, usage={}) for response in responses]
    )
    return AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        cron_service=MagicMock(),
        **kwargs,
    )


@pytest.mark.asyncio
async def test_transient_session_keeps_history_without_persisting_or_durable_tools(tmp_path) -> None:
    loop = _loop(tmp_path, ["first answer", "second answer"])
    loop.context.memory.write_memory("private durable memory")
    loop.consolidator.maybe_consolidate_by_tokens = AsyncMock()
    key = "websocket:transient-test"
    loop.sessions.get_or_create_transient(
        key,
        disabled_tools={"create_goal", "update_goal", "spawn", "cron"},
    )

    await loop._process_message(_message(key, "first question"))
    await loop._process_message(_message(key, "second question"))

    calls = loop.provider.chat_with_retry.await_args_list
    assert "private durable memory" not in str(calls[0].kwargs["messages"])
    tool_names = {item["function"]["name"] for item in calls[0].kwargs["tools"]}
    assert "read_session" in tool_names
    assert {"create_goal", "update_goal", "spawn", "cron"}.isdisjoint(tool_names)
    assert "first answer" in str(calls[1].kwargs["messages"])
    session = loop.sessions.get_cached(key)
    assert session is not None
    assert [message["role"] for message in session.messages] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert loop.sessions.read_session_file(key) is None
    loop.consolidator.maybe_consolidate_by_tokens.assert_not_awaited()


@pytest.mark.asyncio
async def test_transient_session_stays_outside_unified_session(tmp_path) -> None:
    loop = _loop(tmp_path, ["private answer"], unified_session=True)
    durable = loop.sessions.get_or_create(UNIFIED_SESSION_KEY)
    durable.add_message("user", "durable question")
    loop.sessions.save(durable)
    key = "websocket:transient-unified"
    transient = loop.sessions.get_or_create_transient(key)

    await loop._dispatch(_message(key, "private question"))

    assert [message["content"] for message in transient.messages] == [
        "private question",
        "private answer",
    ]
    assert [message["content"] for message in durable.messages] == ["durable question"]
    assert loop.sessions.read_session_file(key) is None


@pytest.mark.asyncio
async def test_missing_required_session_cannot_fall_back_to_disk(tmp_path) -> None:
    loop = _loop(tmp_path, [])
    key = "websocket:transient-stale"
    loop.sessions.get_or_create_transient(key)
    loop.sessions.invalidate(key)

    with pytest.raises(RuntimeError, match="required session is not active"):
        await loop._process_message(_message(key, "stale private message"))

    loop.provider.chat_with_retry.assert_not_awaited()
    assert loop.sessions.read_session_file(key) is None


@pytest.mark.asyncio
async def test_session_discard_control_cancels_active_turn(tmp_path, monkeypatch) -> None:
    provider_started = asyncio.Event()

    async def block_provider(**_kwargs: object) -> LLMResponse:
        provider_started.set()
        await asyncio.Event().wait()
        raise AssertionError("provider blocker unexpectedly released")

    loop = _loop(tmp_path, [])

    async def wait_for_discard(key: str) -> None:
        while loop.sessions.get_cached(key) is not None or key in loop._discarding_sessions:
            await asyncio.sleep(0)

    loop.provider.chat_with_retry = AsyncMock(side_effect=block_provider)
    monkeypatch.setattr(loop, "aclose", AsyncMock())
    terminate_exec_sessions = AsyncMock(return_value=1)
    monkeypatch.setattr(
        loop._exec_session_manager,
        "terminate_by_owner",
        terminate_exec_sessions,
    )
    key = "websocket:transient-cancelled"
    loop.sessions.get_or_create_transient(
        key,
        disabled_tools={"create_goal", "update_goal", "spawn", "cron"},
    )
    run_task = asyncio.create_task(loop.run())
    await loop.bus.publish_inbound(_message(key, "private"))
    await asyncio.wait_for(provider_started.wait(), timeout=2)
    active_task = next(iter(loop._active_tasks[key]))

    await loop.bus.publish_inbound(
        InboundMessage(
            channel="websocket",
            sender_id="webui",
            chat_id="transient-cancelled",
            content="",
            metadata={
                INBOUND_META_RUNTIME_CONTROL: RUNTIME_CONTROL_SESSION_DISCARD,
            },
            session_key_override=key,
        )
    )

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(active_task, timeout=2)
    await asyncio.wait_for(wait_for_discard(key), timeout=2)
    assert loop.sessions.get_cached(key) is None
    terminate_exec_sessions.assert_awaited_once_with(key)

    loop.stop()
    await loop.bus.publish_inbound(_message(key, "wake"))
    await asyncio.wait_for(run_task, timeout=2)
