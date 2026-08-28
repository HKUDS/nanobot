"""Tests for AgentRunner error handling: tool errors, LLM errors,
session message isolation, and tool result preservation."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.runner_helpers import make_run_spec
from nanobot.agent.hook import AgentHook, AgentHookContext
from nanobot.agent.tools import ToolResult
from nanobot.agent.tools.execution import execute_tool_calls
from nanobot.config.schema import AgentDefaults
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest

_MAX_TOOL_RESULT_CHARS = AgentDefaults().max_tool_result_chars


@pytest.mark.asyncio
async def test_runner_returns_tool_exception_to_model_for_recovery():
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)
    provider.chat_with_retry = AsyncMock(side_effect=[
        LLMResponse(
            content="working",
            tool_calls=[ToolCallRequest(id="call_1", name="list_dir", arguments={})],
        ),
        LLMResponse(content="recovered", tool_calls=[]),
    ])
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
    ))

    assert provider.chat_with_retry.await_count == 2
    assert result.stop_reason == "completed"
    assert result.error is None
    assert result.final_content == "recovered"
    assert result.tool_events == [
        {"name": "list_dir", "status": "error", "detail": "boom"}
    ]
    tool_message = next(message for message in result.messages if message.get("role") == "tool")
    retry_hint = "[Analyze the error above and try a different approach.]"
    assert "Error: RuntimeError: boom" in tool_message["content"]
    assert tool_message["content"].count(retry_hint) == 1


@pytest.mark.asyncio
async def test_tool_execution_does_not_duplicate_existing_retry_hint():
    retry_hint = "\n\n[Analyze the error above and try a different approach.]"
    tools = SimpleNamespace(
        execute=AsyncMock(return_value=ToolResult.error("Error: boom" + retry_hint)),
    )

    results, events = await execute_tool_calls(
        tools,
        [ToolCallRequest(id="call_1", name="list_dir", arguments={})],
        concurrent=False,
        external_lookup_counts={},
        workspace_violation_counts={},
        hook=AgentHook(),
        context=AgentHookContext(iteration=0, messages=[]),
    )

    assert results == ["Error: boom" + retry_hint]
    assert results[0].count(retry_hint) == 1
    assert events[0]["status"] == "error"


@pytest.mark.asyncio
@pytest.mark.parametrize("control_error", [KeyboardInterrupt, SystemExit])
async def test_tool_execution_propagates_control_flow_exceptions(control_error: type[BaseException]):
    async def execute(_name, _args):
        raise control_error("stop")

    tools = SimpleNamespace(
        get_definitions=lambda: [],
        execute=execute,
    )
    with pytest.raises(control_error):
        await execute_tool_calls(
            tools,
            [ToolCallRequest(id="call_1", name="list_dir", arguments={})],
            concurrent=False,
            external_lookup_counts={},
            workspace_violation_counts={},
            hook=AgentHook(),
            context=AgentHookContext(iteration=0, messages=[]),
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
        content="429 rate limit exceeded", finish_reason="error", tool_calls=[], usage=None,
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
        usage=None,
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
async def test_runner_returns_structured_tool_error_to_model_for_recovery():
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)

    provider.chat_with_retry = AsyncMock(side_effect=[
        LLMResponse(
            content="working",
            tool_calls=[ToolCallRequest(id="call_1", name="read_file", arguments={"path": "x"})],
            usage=None,
        ),
        LLMResponse(content="used another path", tool_calls=[], usage=None),
    ])
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(return_value=ToolResult.error("Error: File not found: x"))

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
        initial_messages=[{"role": "user", "content": "do task"}],
        tools=tools,
        model="test-model",
        max_iterations=2,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    assert provider.chat_with_retry.await_count == 2
    assert result.final_content == "used another path"
    assert result.stop_reason == "completed"
    assert result.tool_events == [
        {"name": "read_file", "status": "error", "detail": "Error: File not found: x"}
    ]


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
                usage=None,
            )
        return LLMResponse(content="done", usage=None)

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
    ))

    assert result.final_content == "done"
    assert result.stop_reason == "completed"
    assert result.tool_events == [
        {"name": "exec", "status": "ok", "detail": "Error: generated report successfully  Exit code: 0"}
    ]


@pytest.mark.asyncio
async def test_runner_preserves_tool_error_results_in_messages():
    """Tool errors stay paired with their calls so the model can recover (#2943)."""
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)

    async def chat_with_retry(*, messages, **kwargs):
        return LLMResponse(
            content=None,
            tool_calls=[
                ToolCallRequest(id="tc1", name="read_file", arguments={"path": "a"}),
                ToolCallRequest(id="tc2", name="exec", arguments={"cmd": "bad"}),
            ],
            usage=None,
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
    ))

    assert result.stop_reason == "max_iterations"
    # Both tool results must be in messages even though tc2 returned an error.
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


@pytest.mark.asyncio
async def test_length_finish_with_blank_content_routes_to_length_recovery():
    """Regression test for #5133.

    A response with finish_reason='length' and blank content (e.g. the model
    spent its whole output budget on a tool call whose closing tag was
    truncated) must take the length-recovery path, not the empty-response
    retry path. Retrying the same prompt cannot recover from output-budget
    exhaustion.
    """
    from nanobot.agent.runner import AgentRunner
    from nanobot.utils.runtime import LENGTH_RECOVERY_PROMPT

    provider = MagicMock(spec=LLMProvider)
    # First call: truncated (length) with blank content and a dropped tool call.
    # Second call: normal completion so the loop can terminate.
    provider.chat_with_retry = AsyncMock(side_effect=[
        LLMResponse(
            content="",
            finish_reason="length",
            tool_calls=[ToolCallRequest(id="call_1", name="exec", arguments={})],
            usage=None,
        ),
        LLMResponse(content="done", finish_reason="stop", tool_calls=[], usage=None),
    ])
    tools = MagicMock()
    tools.get_definitions.return_value = []

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
        initial_messages=[{"role": "user", "content": "do a long task"}],
        tools=tools,
        model="test-model",
        max_iterations=5,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    # The runner must have injected a length-recovery prompt and continued,
    # rather than exhausting empty-response retries into a generic apology.
    user_msgs = [m.get("content") or "" for m in result.messages if m.get("role") == "user"]
    assert any(LENGTH_RECOVERY_PROMPT in c for c in user_msgs), (
        "expected a length-recovery message to be appended for a "
        "finish_reason='length' response with blank content"
    )
    assert result.final_content == "done"
