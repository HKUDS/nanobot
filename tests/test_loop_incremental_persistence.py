import asyncio
from unittest.mock import AsyncMock, MagicMock

from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.base import Tool
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMResponse, ToolCallRequest
from nanobot.session.manager import SessionManager


class DemoTool(Tool):
    @property
    def name(self) -> str:
        return "demo_tool"

    @property
    def description(self) -> str:
        return "Demo tool for loop persistence tests."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        }

    async def execute(self, **kwargs):
        return f"tool:{kwargs['value']}"


def _make_loop(tmp_path) -> AgentLoop:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.chat_with_retry = AsyncMock()
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
    )
    loop.memory_consolidator.maybe_consolidate_by_tokens = AsyncMock(return_value=None)  # type: ignore[method-assign]
    loop._schedule_background = lambda coro: coro.close()  # type: ignore[method-assign]
    loop.tools.register(DemoTool())
    return loop


def test_persists_completed_tool_loop_before_next_llm_call(tmp_path) -> None:
    loop = _make_loop(tmp_path)
    session_key = "cli:test"
    tool_response = LLMResponse(
        content="thinking",
        tool_calls=[ToolCallRequest(id="call_1", name="demo_tool", arguments={"value": "first"})],
    )
    final_response = LLMResponse(content="done", tool_calls=[])
    call_count = 0

    async def fake_chat_with_retry(**_kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return tool_response
        persisted = SessionManager(tmp_path).get_or_create(session_key)
        assert [message["role"] for message in persisted.messages] == ["user", "assistant", "tool"]
        assert persisted.messages[1]["tool_calls"][0]["function"]["name"] == "demo_tool"
        assert persisted.messages[2]["content"] == "tool:first"
        return final_response

    loop.provider.chat_with_retry = fake_chat_with_retry

    result = asyncio.run(loop.process_direct("hello", session_key=session_key))

    assert result == "done"
    persisted = SessionManager(tmp_path).get_or_create(session_key)
    assert [message["role"] for message in persisted.messages] == ["user", "assistant", "tool", "assistant"]
    assert persisted.messages[-1]["content"] == "done"


def test_crash_keeps_previously_completed_tool_loop(tmp_path) -> None:
    loop = _make_loop(tmp_path)
    session_key = "cli:test"
    loop.provider.chat_with_retry = AsyncMock(side_effect=[
        LLMResponse(
            content="thinking",
            tool_calls=[ToolCallRequest(id="call_1", name="demo_tool", arguments={"value": "first"})],
        ),
        RuntimeError("boom"),
    ])

    try:
        asyncio.run(loop.process_direct("hello", session_key=session_key))
    except RuntimeError as exc:
        assert str(exc) == "boom"
    else:
        raise AssertionError("expected RuntimeError")

    persisted = SessionManager(tmp_path).get_or_create(session_key)
    assert [message["role"] for message in persisted.messages] == ["user", "assistant", "tool"]
    assert persisted.get_history(max_messages=0) == [
        {"role": "user", "content": "hello"},
        {
            "role": "assistant",
            "content": "thinking",
            "tool_calls": persisted.messages[1]["tool_calls"],
        },
        {
            "role": "tool",
            "content": "tool:first",
            "tool_call_id": "call_1",
            "name": "demo_tool",
        },
    ]


def test_final_response_persists_once_without_duplicates(tmp_path) -> None:
    loop = _make_loop(tmp_path)
    session_key = "cli:test"
    loop.provider.chat_with_retry = AsyncMock(side_effect=[
        LLMResponse(
            content="thinking",
            tool_calls=[ToolCallRequest(id="call_1", name="demo_tool", arguments={"value": "first"})],
        ),
        LLMResponse(content="done", tool_calls=[]),
    ])

    result = asyncio.run(loop.process_direct("hello", session_key=session_key))

    assert result == "done"
    persisted = SessionManager(tmp_path).get_or_create(session_key)
    assert [message["role"] for message in persisted.messages] == ["user", "assistant", "tool", "assistant"]
    assert [message.get("content") for message in persisted.messages] == [
        "hello",
        "thinking",
        "tool:first",
        "done",
    ]


def test_no_tool_response_persists_once(tmp_path) -> None:
    loop = _make_loop(tmp_path)
    session_key = "cli:test"
    loop.provider.chat_with_retry = AsyncMock(return_value=LLMResponse(content="done", tool_calls=[]))

    result = asyncio.run(loop.process_direct("hello", session_key=session_key))

    assert result == "done"
    persisted = SessionManager(tmp_path).get_or_create(session_key)
    assert [message["role"] for message in persisted.messages] == ["user", "assistant"]
    assert [message.get("content") for message in persisted.messages] == ["hello", "done"]
