import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import (
    INBOUND_META_RUNTIME_CONTROL,
    RUNTIME_CONTROL_MEMORY_ONLY_SESSION_DISCARD,
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
        memory_only_session=True,
    )


@pytest.mark.asyncio
async def test_temporary_chat_keeps_safe_capabilities_and_only_live_history(tmp_path) -> None:
    (tmp_path / "AGENTS.md").write_text("project instruction", encoding="utf-8")
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings()
    provider.chat_with_retry = AsyncMock(side_effect=[
        LLMResponse(content="first answer", usage={}),
        LLMResponse(content="second answer", usage={}),
    ])
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        cron_service=MagicMock(),
    )
    loop.context.memory.write_memory("# Memory\n- private remembered detail")
    key = "websocket:temporary-test"
    loop.sessions.get_or_create_memory_only(key)

    await loop._process_message(_message(key, "first question"))
    await loop._process_message(_message(key, "second question"))

    first_call, second_call = provider.chat_with_retry.await_args_list
    tool_names = {
        definition["function"]["name"]
        for definition in first_call.kwargs["tools"]
    }
    assert "read_session" in tool_names
    assert {"create_goal", "update_goal", "spawn", "cron"}.isdisjoint(tool_names)
    assert "project instruction" in str(first_call.kwargs["messages"])
    assert "private remembered detail" not in str(first_call.kwargs["messages"])
    assert "first answer" in str(second_call.kwargs["messages"])
    session = loop.sessions.get_cached(key)
    assert session is not None
    assert [message["role"] for message in session.messages] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert loop.sessions.read_session_file(key) is None


@pytest.mark.asyncio
async def test_temporary_chat_compacts_only_in_memory(tmp_path) -> None:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings(max_tokens=256)
    provider.estimate_prompt_tokens.return_value = (100, "test")
    provider.chat_with_retry = AsyncMock(
        return_value=LLMResponse(content="Earlier temporary decisions.", usage={})
    )
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        context_window_tokens=4096,
    )
    key = "websocket:temporary-compact"
    session = loop.sessions.get_or_create_memory_only(key)
    for index in range(6):
        session.add_message("user", f"question {index}")
        session.add_message("assistant", f"answer {index}")

    await loop.consolidator.maybe_consolidate_by_tokens(
        session,
        runtime=loop.runtime_for_session(session),
        replay_max_messages=4,
    )

    assert session.last_consolidated > 0
    assert len(session.messages) == 12
    assert session.metadata["_last_summary"]["text"] == "Earlier temporary decisions."
    assert loop.sessions.read_session_file(key) is None
    assert loop.context.memory.read_unprocessed_history(since_cursor=0) == []
    _, summary = loop.auto_compact.prepare_session(session, key)
    assert summary is not None


@pytest.mark.asyncio
async def test_temporary_chat_uses_the_regular_compaction_pipeline(tmp_path) -> None:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings()
    provider.chat_with_retry = AsyncMock(
        return_value=LLMResponse(content="answer", usage={})
    )
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
    )
    loop.consolidator.maybe_consolidate_by_tokens = AsyncMock()
    key = "websocket:temporary-pipeline"
    loop.sessions.get_or_create_memory_only(key)

    await loop._process_message(_message(key, "question"))

    loop.consolidator.maybe_consolidate_by_tokens.assert_awaited()


@pytest.mark.asyncio
async def test_discarded_temporary_turn_cannot_create_a_session_file(tmp_path) -> None:
    provider_started = asyncio.Event()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings()

    async def block_provider(**_kwargs):
        provider_started.set()
        await asyncio.Event().wait()

    provider.chat_with_retry = AsyncMock(side_effect=block_provider)
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
    )
    key = "websocket:temporary-cancelled"
    loop.sessions.get_or_create_memory_only(key)
    task = asyncio.create_task(loop._dispatch(_message(key, "private")))
    loop._active_tasks.setdefault(key, set()).add(task)

    await provider_started.wait()
    assert loop.sessions.discard_memory_only(key) is True
    assert await loop._cancel_active_tasks(key) == 1

    assert task.cancelled()
    assert loop.sessions.read_session_file(key) is None


@pytest.mark.asyncio
async def test_temporary_chat_stays_isolated_when_unified_session_is_enabled(tmp_path) -> None:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings()
    provider.chat_with_retry = AsyncMock(
        return_value=LLMResponse(content="private answer", usage={})
    )
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        unified_session=True,
    )
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
async def test_stale_message_after_discard_cannot_create_a_durable_session(tmp_path) -> None:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings()
    provider.chat_with_retry = AsyncMock()
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
    )
    loop._connect_mcp = AsyncMock()
    loop.close_mcp = AsyncMock()
    key = "websocket:temporary-stale-message"
    loop.sessions.get_or_create_memory_only(key)
    loop.sessions.discard_memory_only(key)
    run_task = asyncio.create_task(loop.run())
    try:
        await loop.bus.publish_inbound(InboundMessage(
            channel="websocket",
            sender_id="webui",
            chat_id=key.removeprefix("websocket:"),
            content="",
            session_key_override=key,
            metadata={
                INBOUND_META_RUNTIME_CONTROL: RUNTIME_CONTROL_MEMORY_ONLY_SESSION_DISCARD,
            },
        ))
        await loop.bus.publish_inbound(_message(key, "stale private message"))
        for _ in range(100):
            if loop.bus.inbound_size == 0:
                break
            await asyncio.sleep(0.01)

        assert loop.sessions.get_cached(key) is None
        assert loop.sessions.read_session_file(key) is None
        provider.chat_with_retry.assert_not_awaited()
    finally:
        loop.stop()
        await asyncio.wait_for(run_task, timeout=2)
