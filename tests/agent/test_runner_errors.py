"""Tests for AgentRunner error handling: tool errors, LLM errors,
session message isolation, and tool result preservation."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.runner_helpers import make_run_spec
from nanobot.config.schema import AgentDefaults
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest

_MAX_TOOL_RESULT_CHARS = AgentDefaults().max_tool_result_chars


@pytest.mark.asyncio
async def test_runner_returns_structured_tool_error():
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content="working",
        tool_calls=[ToolCallRequest(id="call_1", name="list_dir", arguments={})],
    ))
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(side_effect=RuntimeError("boom"))

    runner = AgentRunner()

    result = await runner.run(make_run_spec(provider,
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
@pytest.mark.parametrize("control_error", [KeyboardInterrupt, SystemExit])
async def test_runner_propagates_tool_control_flow_exceptions(control_error: type[BaseException]):
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)

    async def execute(_name, _args):
        raise control_error("stop")

    tools = SimpleNamespace(
        get_definitions=lambda: [],
        execute=execute,
    )
    runner = AgentRunner()
    spec = make_run_spec(
        provider,
        initial_messages=[],
        tools=tools,
        model="test-model",
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    )

    with pytest.raises(control_error):
        await runner._run_tool(
            spec,
            ToolCallRequest(id="call_1", name="list_dir", arguments={}),
            external_lookup_counts={},
            workspace_violation_counts={},
        )


@pytest.mark.asyncio
async def test_llm_error_not_appended_to_session_messages():
    """When LLM returns finish_reason='error', the error content must NOT be
    appended to the messages list (prevents polluting session history)."""
    from nanobot.agent.runner import (
        _PERSISTED_MODEL_ERROR_PLACEHOLDER,
        AgentRunner,
    )

    provider = MagicMock(spec=LLMProvider)
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content="429 rate limit exceeded", finish_reason="error", tool_calls=[], usage={},
    ))
    tools = MagicMock()
    tools.get_definitions.return_value = []

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
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
async def test_llm_arrearage_error_surfaces_clear_message():
    """Arrearage errors yield a clear user-facing message, not a raw dump (#3006)."""
    from nanobot.agent.runner import _ARREARAGE_ERROR_MESSAGE, AgentRunner

    provider = MagicMock(spec=LLMProvider)
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content="HTTP 402 insufficient_quota", finish_reason="error", error_status_code=402,
    ))
    tools = MagicMock()
    tools.get_definitions.return_value = []

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
        initial_messages=[{"role": "user", "content": "hello"}],
        tools=tools,
        model="test-model",
        max_iterations=5,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    assert result.stop_reason == "error"
    assert result.final_content == _ARREARAGE_ERROR_MESSAGE


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("finish_reason", "expected_stop_reason"),
    [
        ("refusal", "completed"),
        ("content_filter", "completed"),
        ("error", "error"),
    ],
)
async def test_runner_ignores_tool_calls_when_finish_reason_blocks_execution(
    finish_reason: str,
    expected_stop_reason: str,
):
    """Provider/gateway-injected tool calls under terminal block reasons must not run."""
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content="Request blocked by provider policy.",
        finish_reason=finish_reason,
        tool_calls=[ToolCallRequest(id="call_1", name="exec", arguments={"command": "echo nope"})],
        usage={},
    ))
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(return_value="should not run")

    result = await AgentRunner().run(make_run_spec(provider,
        initial_messages=[{"role": "user", "content": "run a command"}],
        tools=tools,
        model="test-model",
        max_iterations=2,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    tools.execute.assert_not_awaited()
    assert result.stop_reason == expected_stop_reason
    assert result.tools_used == []
    assert result.final_content == "Request blocked by provider policy."
    assert not any(msg.get("role") == "tool" for msg in result.messages)


@pytest.mark.asyncio
async def test_runner_tool_error_sets_final_content():
    from nanobot.agent.runner import AgentRunner

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

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
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
async def test_runner_preserves_successful_exec_output_that_starts_with_error():
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)

    async def chat_with_retry(*, messages, **kwargs):
        if not any(msg.get("role") == "tool" for msg in messages):
            return LLMResponse(
                content="working",
                tool_calls=[
                    ToolCallRequest(id="call_1", name="exec", arguments={"command": "report"})
                ],
                usage={},
            )
        return LLMResponse(content="done", usage={})

    provider.chat_with_retry = chat_with_retry
    output = "Error: generated report successfully\n\nExit code: 0"
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(return_value=output)

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
        initial_messages=[{"role": "user", "content": "run report"}],
        tools=tools,
        model="test-model",
        max_iterations=2,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        fail_on_tool_error=True,
    ))

    assert result.final_content == "done"
    assert result.stop_reason == "completed"
    assert result.tool_events == [
        {"name": "exec", "status": "ok", "detail": "Error: generated report successfully  Exit code: 0"}
    ]


@pytest.mark.asyncio
async def test_runner_tool_error_preserves_tool_results_in_messages():
    """When a tool raises a fatal error, its results must still be appended
    to messages so the session never contains orphan tool_calls (#2943)."""
    from nanobot.agent.runner import AgentRunner

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

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
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
