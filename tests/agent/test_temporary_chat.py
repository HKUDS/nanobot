import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import GenerationSettings, LLMResponse
from nanobot.runtime_context import RuntimeContextBlock
from nanobot.session.manager import SessionManager


@pytest.mark.asyncio
async def test_temporary_chat_reuses_memory_only_history_without_tools(tmp_path) -> None:
    (tmp_path / "AGENTS.md").write_text("private project instruction", encoding="utf-8")
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings()
    provider.chat_with_retry = AsyncMock(
        side_effect=[
            LLMResponse(content="first answer", usage={}),
            LLMResponse(content="second answer", usage={}),
        ]
    )
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        unified_session=True,
    )
    key = "websocket:temporary-test"
    loop.sessions.get_or_create_transient(key)

    for content in ("first question", "second question"):
        response = await loop._process_message(
            InboundMessage(
                channel="websocket",
                sender_id="user",
                chat_id="temporary-test",
                content=content,
                session_key_override=key,
                transient_session=True,
            )
        )
        assert response is not None

    first_call, second_call = provider.chat_with_retry.await_args_list
    assert first_call.kwargs["tools"] == []
    assert second_call.kwargs["tools"] == []
    assert all(
        message["role"] != "system"
        for call in (first_call, second_call)
        for message in call.kwargs["messages"]
    )
    assert "private project instruction" not in str(first_call.kwargs["messages"])
    assert str(tmp_path) not in str(first_call.kwargs["messages"])
    assert "first answer" in str(second_call.kwargs["messages"])

    transient = loop.sessions.get_cached(key)
    assert transient is not None
    assert [message["role"] for message in transient.messages] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert loop.sessions.read_session_file(key) is None
    assert SessionManager(tmp_path).read_session_file(key) is None


@pytest.mark.asyncio
async def test_temporary_follow_up_does_not_resolve_runtime_context(tmp_path) -> None:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings()
    provider.chat_with_retry = AsyncMock(
        side_effect=[
            LLMResponse(content="first answer", usage={}),
            LLMResponse(content="second answer", usage={}),
        ]
    )
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
    )
    runtime_context_provider = AsyncMock(
        return_value=RuntimeContextBlock(
            source="project",
            content="SECRET LOCAL PROJECT CONTEXT",
        )
    )
    loop.register_runtime_context_provider(runtime_context_provider)

    key = "websocket:temporary-follow-up"
    session = loop.sessions.get_or_create_transient(key)
    pending_queue: asyncio.Queue[InboundMessage] = asyncio.Queue()
    await pending_queue.put(
        InboundMessage(
            channel="websocket",
            sender_id="user",
            chat_id="temporary-follow-up",
            content="follow up",
            session_key_override=key,
            transient_session=True,
        )
    )

    _, _, messages, _, _ = await loop._run_agent_loop(
        [{"role": "user", "content": "first question"}],
        runtime=loop.llm_runtime(),
        session=session,
        channel="websocket",
        chat_id="temporary-follow-up",
        session_key=key,
        pending_queue=pending_queue,
        tools=ToolRegistry(),
    )

    runtime_context_provider.assert_not_awaited()
    assert "SECRET LOCAL PROJECT CONTEXT" not in str(messages)


@pytest.mark.asyncio
async def test_discarding_active_temporary_chat_does_not_create_durable_session(
    tmp_path,
) -> None:
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
    loop.sessions.get_or_create_transient(key)
    message = InboundMessage(
        channel="websocket",
        sender_id="user",
        chat_id="temporary-cancelled",
        content="private",
        session_key_override=key,
        transient_session=True,
    )
    task = asyncio.create_task(loop._dispatch(message))
    active_tasks = loop._active_tasks.setdefault(key, set())
    active_tasks.add(task)
    task.add_done_callback(active_tasks.discard)

    await provider_started.wait()
    assert loop.sessions.discard_transient(key)
    assert await loop.cancel_active_turn(key) == 1

    assert loop.sessions.get_cached(key) is None
    assert loop.sessions.flush_all() == 0
    assert loop.sessions.read_session_file(key) is None
