"""Tests for AgentRunner error handling: tool errors, LLM errors,
session message isolation, and tool result preservation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.config.schema import AgentDefaults
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest

_MAX_TOOL_RESULT_CHARS = AgentDefaults().max_tool_result_chars


@pytest.mark.asyncio
async def test_runner_returns_structured_tool_error():
    from nanobot.agent.runner import AgentRunSpec, AgentRunner

    provider = MagicMock(spec=LLMProvider)
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content="working",
        tool_calls=[ToolCallRequest(id="call_1", name="list_dir", arguments={})],
    ))
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(side_effect=RuntimeError("boom"))

    runner = AgentRunner(provider)

    result = await runner.run(AgentRunSpec(
        initial_messages=[],
        tools=tools,
        model="test-model",
        max_iterations=2,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        fail_on_tool_error=True,
    ))

    assert result.stop_reason == "tool_error"
    assert result.error == "Error: RuntimeError: boom"
    assert result.tool_events == [
        {"name": "list_dir", "status": "error", "detail": "boom"}
    ]


@pytest.mark.asyncio
async def test_llm_error_not_appended_to_session_messages():
    """When LLM returns finish_reason='error', the error content must NOT be
    appended to the messages list (prevents polluting session history)."""
    from nanobot.agent.runner import (
        AgentRunSpec,
        AgentRunner,
        _PERSISTED_MODEL_ERROR_PLACEHOLDER,
    )

    provider = MagicMock(spec=LLMProvider)
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content="429 rate limit exceeded", finish_reason="error", tool_calls=[], usage={},
    ))
    tools = MagicMock()
    tools.get_definitions.return_value = []

    runner = AgentRunner(provider)
    result = await runner.run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "hello"}],
        tools=tools,
        model="test-model",
        max_iterations=5,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    assert result.stop_reason == "error"
    assert result.final_content == "429 rate limit exceeded"
    assistant_msgs = [m for m in result.messages if m.get("role") == "assistant"]
    assert all("429" not in (m.get("content") or "") for m in assistant_msgs), \
        "Error content should not appear in session messages"
    assert assistant_msgs[-1]["content"] == _PERSISTED_MODEL_ERROR_PLACEHOLDER


@pytest.mark.asyncio
async def test_runner_tool_error_sets_final_content():
    from nanobot.agent.runner import AgentRunSpec, AgentRunner

    provider = MagicMock(spec=LLMProvider)

    async def chat_with_retry(*, messages, **kwargs):
        return LLMResponse(
            content="working",
            tool_calls=[ToolCallRequest(id="call_1", name="read_file", arguments={"path": "x"})],
            usage={},
        )

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(side_effect=RuntimeError("boom"))

    runner = AgentRunner(provider)
    result = await runner.run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "do task"}],
        tools=tools,
        model="test-model",
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        fail_on_tool_error=True,
    ))

    assert result.final_content == "Error: RuntimeError: boom"
    assert result.stop_reason == "tool_error"


@pytest.mark.asyncio
async def test_runner_tool_error_preserves_tool_results_in_messages():
    """When a tool raises a fatal error, its results must still be appended
    to messages so the session never contains orphan tool_calls (#2943)."""
    from nanobot.agent.runner import AgentRunSpec, AgentRunner

    provider = MagicMock(spec=LLMProvider)

    async def chat_with_retry(*, messages, **kwargs):
        return LLMResponse(
            content=None,
            tool_calls=[
                ToolCallRequest(id="tc1", name="read_file", arguments={"path": "a"}),
                ToolCallRequest(id="tc2", name="exec", arguments={"cmd": "bad"}),
            ],
            usage={},
        )

    provider.chat_with_retry = chat_with_retry
    provider.chat_stream_with_retry = chat_with_retry

    call_idx = 0

    async def fake_execute(name, args, **kw):
        nonlocal call_idx
        call_idx += 1
        if call_idx == 2:
            raise RuntimeError("boom")
        return "file content"

    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(side_effect=fake_execute)

    runner = AgentRunner(provider)
    result = await runner.run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "do stuff"}],
        tools=tools,
        model="test-model",
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        fail_on_tool_error=True,
    ))

    assert result.stop_reason == "tool_error"
    # Both tool results must be in messages even though tc2 had a fatal error.
    tool_msgs = [m for m in result.messages if m.get("role") == "tool"]
    assert len(tool_msgs) == 2
    assert tool_msgs[0]["tool_call_id"] == "tc1"
    assert tool_msgs[1]["tool_call_id"] == "tc2"
    # The assistant message with tool_calls must precede the tool results.
    asst_tc_idx = next(
        i for i, m in enumerate(result.messages)
        if m.get("role") == "assistant" and m.get("tool_calls")
    )
    tool_indices = [
        i for i, m in enumerate(result.messages) if m.get("role") == "tool"
    ]
    assert all(ti > asst_tc_idx for ti in tool_indices)
