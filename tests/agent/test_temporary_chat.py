from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
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
        memory_only_session=True,
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
async def test_memory_only_chat_keeps_history_without_persisting_or_durable_tools(tmp_path) -> None:
    loop = _loop(tmp_path, ["first answer", "second answer"])
    loop.consolidator.maybe_consolidate_by_tokens = AsyncMock()
    key = "websocket:temporary-test"
    loop.sessions.get_or_create_memory_only(key)

    await loop._process_message(_message(key, "first question"))
    await loop._process_message(_message(key, "second question"))

    calls = loop.provider.chat_with_retry.await_args_list
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
async def test_memory_only_chat_stays_outside_unified_session(tmp_path) -> None:
    loop = _loop(tmp_path, ["private answer"], unified_session=True)
    durable = loop.sessions.get_or_create(UNIFIED_SESSION_KEY)
    durable.add_message("user", "durable question")
    loop.sessions.save(durable)
    key = "websocket:temporary-unified"
    memory_only = loop.sessions.get_or_create_memory_only(key)

    await loop._dispatch(_message(key, "private question"))

    assert [message["content"] for message in memory_only.messages] == [
        "private question",
        "private answer",
    ]
    assert [message["content"] for message in durable.messages] == ["durable question"]
    assert loop.sessions.read_session_file(key) is None


@pytest.mark.asyncio
async def test_discarded_memory_only_message_cannot_fall_back_to_disk(tmp_path) -> None:
    loop = _loop(tmp_path, [])
    key = "websocket:temporary-stale"
    loop.sessions.get_or_create_memory_only(key)
    loop.sessions.invalidate(key)

    with pytest.raises(RuntimeError, match="memory-only session is not active"):
        await loop._process_message(_message(key, "stale private message"))

    loop.provider.chat_with_retry.assert_not_awaited()
    assert loop.sessions.read_session_file(key) is None
