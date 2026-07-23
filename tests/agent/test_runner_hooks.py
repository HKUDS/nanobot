"""Tests for AgentRunner hook lifecycle: ordering, streaming deltas,
cached-token propagation, and hook context."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.runner_helpers import make_run_spec
from nanobot.config.schema import AgentDefaults
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest

_MAX_TOOL_RESULT_CHARS = AgentDefaults().max_tool_result_chars


@pytest.mark.asyncio
async def test_runner_calls_hooks_in_order():
    from nanobot.agent.hook import AgentHook, AgentHookContext
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)
    call_count = {"n": 0}
    events: list[tuple] = []

    async def chat_with_retry(**kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return LLMResponse(
                content="thinking",
                tool_calls=[ToolCallRequest(id="call_1", name="list_dir", arguments={"path": "."})],
            )
        return LLMResponse(content="done", tool_calls=[], usage={})

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(return_value="tool result")

    class RecordingHook(AgentHook):
        async def before_iteration(self, context: AgentHookContext) -> None:
            events.append(("before_iteration", context.iteration))

        async def before_execute_tools(self, context: AgentHookContext) -> None:
            events.append((
                "before_execute_tools",
                context.iteration,
                [tc.name for tc in context.tool_calls],
            ))

        async def before_execute_tool(self, context, tool_call, tool, params) -> None:
            events.append(("before_execute_tool", context.iteration, tool_call.name, params))

        async def after_execute_tool(self, context, tool_call, tool, params, result) -> None:
            events.append(("after_execute_tool", context.iteration, tool_call.name, result))

        async def after_iteration(self, context: AgentHookContext) -> None:
            events.append((
                "after_iteration",
                context.iteration,
                context.final_content,
                list(context.tool_results),
                list(context.tool_events),
                context.stop_reason,
            ))

        def finalize_content(self, context: AgentHookContext, content: str | None) -> str | None:
            events.append(("finalize_content", context.iteration, content))
            return content.upper() if content else content

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
        initial_messages=[],
        tools=tools,
        model="test-model",
        max_iterations=3,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        hook=RecordingHook(),
    ))

    assert result.final_content == "DONE"
    assert events == [
        ("before_iteration", 0),
        ("before_execute_tools", 0, ["list_dir"]),
        ("before_execute_tool", 0, "list_dir", {"path": "."}),
        ("after_execute_tool", 0, "list_dir", "tool result"),
        (
            "after_iteration",
            0,
            None,
            ["tool result"],
            [{"name": "list_dir", "status": "ok", "detail": "tool result"}],
            None,
        ),
        ("before_iteration", 1),
        ("finalize_content", 1, "done"),
        ("after_iteration", 1, "DONE", [], [], "completed"),
    ]


@pytest.mark.asyncio
async def test_runner_streaming_hook_receives_deltas_and_end_signal():
    from nanobot.agent.hook import AgentHook, AgentHookContext
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)
    streamed: list[str] = []
    endings: list[bool] = []

    async def chat_stream_with_retry(*, on_content_delta, **kwargs):
        await on_content_delta("he")
        await on_content_delta("llo")
        return LLMResponse(content="hello", tool_calls=[], usage={})

    provider.chat_stream_with_retry = chat_stream_with_retry
    provider.chat_with_retry = AsyncMock()
    tools = MagicMock()
    tools.get_definitions.return_value = []

    class StreamingHook(AgentHook):
        def wants_streaming(self) -> bool:
            return True

        async def on_stream(self, context: AgentHookContext, delta: str) -> None:
            streamed.append(delta)

        async def on_stream_end(self, context: AgentHookContext, *, resuming: bool) -> None:
            endings.append(resuming)

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
        initial_messages=[],
        tools=tools,
        model="test-model",
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        hook=StreamingHook(),
    ))

    assert result.final_content == "hello"
    assert streamed == ["he", "llo"]
    assert endings == [False]
    provider.chat_with_retry.assert_not_awaited()


@pytest.mark.asyncio
async def test_runner_length_recovery_streams_segments_once_and_returns_all_content():
    from nanobot.agent.hook import AgentHook, AgentHookContext
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)
    streamed: list[str] = []
    endings: list[bool] = []
    merge_next: list[bool] = []
    responses = iter([
        LLMResponse(content="first ", finish_reason="length"),
        LLMResponse(content="second", finish_reason="stop"),
    ])

    async def chat_stream_with_retry(*, on_content_delta, **kwargs):
        response = next(responses)
        await on_content_delta(response.content or "")
        return response

    provider.chat_stream_with_retry = chat_stream_with_retry
    provider.chat_with_retry = AsyncMock()
    tools = MagicMock()
    tools.get_definitions.return_value = []

    class StreamingHook(AgentHook):
        def wants_streaming(self) -> bool:
            return True

        async def on_stream(self, context: AgentHookContext, delta: str) -> None:
            streamed.append(delta)

        async def on_stream_end(self, context: AgentHookContext, *, resuming: bool) -> None:
            endings.append(resuming)
            merge_next.append(context.stream_continues_current_message)

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
        initial_messages=[{"role": "user", "content": "give a long answer"}],
        tools=tools,
        model="test-model",
        max_iterations=3,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        hook=StreamingHook(),
    ))

    assert result.final_content == "first second"
    assert streamed == ["first ", "second"]
    assert endings == [True, False]
    assert merge_next == [True, False]
    provider.chat_with_retry.assert_not_awaited()


@pytest.mark.asyncio
async def test_runner_passes_cached_tokens_to_hook_context():
    """Hook context.usage should contain cached_tokens."""
    from nanobot.agent.hook import AgentHook, AgentHookContext
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)
    captured_usage: list[dict] = []

    class UsageHook(AgentHook):
        async def after_iteration(self, context: AgentHookContext) -> None:
            captured_usage.append(dict(context.usage))

    async def chat_with_retry(**kwargs):
        return LLMResponse(
            content="done",
            tool_calls=[],
            usage={"prompt_tokens": 200, "completion_tokens": 20, "cached_tokens": 150},
        )

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []

    runner = AgentRunner()
    await runner.run(make_run_spec(provider,
        initial_messages=[],
        tools=tools,
        model="test-model",
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        hook=UsageHook(),
    ))

    assert len(captured_usage) == 1
    assert captured_usage[0]["cached_tokens"] == 150
    assert captured_usage[0]["provider_tokens"] == 220


@pytest.mark.asyncio
async def test_runner_estimates_usage_when_provider_omits_usage(monkeypatch):
    from nanobot.agent.hook import AgentHook, AgentHookContext
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)
    captured_usage: list[dict] = []

    class UsageHook(AgentHook):
        async def after_iteration(self, context: AgentHookContext) -> None:
            captured_usage.append(dict(context.usage))

    async def chat_with_retry(**kwargs):
        return LLMResponse(content="done", tool_calls=[], usage={})

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = [{"type": "function", "function": {"name": "lookup"}}]
    monkeypatch.setattr(
        "nanobot.agent.runner.estimate_prompt_tokens_chain",
        lambda provider, model, messages, tools: (123, "test"),
    )
    monkeypatch.setattr("nanobot.agent.runner.estimate_message_tokens", lambda message: 7)

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
        initial_messages=[{"role": "user", "content": "hi"}],
        tools=tools,
        model="test-model",
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        hook=UsageHook(),
    ))

    assert result.usage["prompt_tokens"] == 123
    assert result.usage["completion_tokens"] == 7
    assert result.usage["total_tokens"] == 130
    assert result.usage["estimated_tokens"] == 130
    assert captured_usage[0]["estimated_tokens"] == 130


@pytest.mark.asyncio
async def test_runner_calls_run_level_hooks_on_success():
    from nanobot.agent.hook import AgentHook, AgentRunHookContext
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)
    events: list[tuple] = []

    async def chat_with_retry(**kwargs):
        events.append(("request_messages", list(kwargs["messages"])))
        return LLMResponse(
            content="done",
            tool_calls=[],
            usage={"prompt_tokens": 3, "completion_tokens": 2},
        )

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []

    class RunHook(AgentHook):
        async def before_run(self, context: AgentRunHookContext) -> None:
            events.append(("before_run", list(context.messages), context.stop_reason))
            context.messages.append({"role": "user", "content": "hook-only"})

        async def after_run(self, context: AgentRunHookContext) -> None:
            events.append((
                "after_run",
                context.final_content,
                context.stop_reason,
                context.error,
                dict(context.usage),
                [msg["role"] for msg in context.messages],
            ))

        async def on_error(self, context: AgentRunHookContext) -> None:
            events.append(("on_error", context.error))

        async def on_finally(self, context: AgentRunHookContext) -> None:
            events.append(("on_finally", context.stop_reason, context.exception))

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
        initial_messages=[{"role": "user", "content": "hi"}],
        tools=tools,
        model="test-model",
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        hook=RunHook(),
    ))

    assert result.final_content == "done"
    assert events == [
        ("before_run", [{"role": "user", "content": "hi"}], None),
        ("request_messages", [{"role": "user", "content": "hi"}]),
        (
            "after_run",
            "done",
            "completed",
            None,
            {
                "prompt_tokens": 3,
                "completion_tokens": 2,
                "total_tokens": 5,
                "provider_tokens": 5,
            },
            ["user", "assistant"],
        ),
        ("on_finally", "completed", None),
    ]


@pytest.mark.asyncio
async def test_runner_run_level_context_is_detached_snapshot():
    from nanobot.agent.hook import AgentHook, AgentRunHookContext
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)
    call_count = {"n": 0}
    request_messages: list[list[dict]] = []

    async def chat_with_retry(**kwargs):
        call_count["n"] += 1
        request_messages.append([dict(msg) for msg in kwargs["messages"]])
        if call_count["n"] == 1:
            return LLMResponse(
                content="thinking",
                tool_calls=[ToolCallRequest(id="call_1", name="list_dir", arguments={"path": "."})],
            )
        return LLMResponse(content="done", tool_calls=[], usage={})

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(return_value="tool result")

    class MutatingRunHook(AgentHook):
        async def before_run(self, context: AgentRunHookContext) -> None:
            context.messages[0]["content"] = "mutated-before"

        async def after_run(self, context: AgentRunHookContext) -> None:
            context.messages[0]["content"] = "mutated-after"
            context.tool_events[0]["status"] = "mutated"
            context.tools_used.append("mutated")

        async def on_finally(self, context: AgentRunHookContext) -> None:
            context.messages[0]["content"] = "mutated-finally"

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
        initial_messages=[{"role": "user", "content": "hi"}],
        tools=tools,
        model="test-model",
        max_iterations=2,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        hook=MutatingRunHook(),
    ))

    assert request_messages[0][0]["content"] == "hi"
    assert result.messages[0]["content"] == "hi"
    assert result.tools_used == ["list_dir"]
    assert result.tool_events == [
        {"name": "list_dir", "status": "ok", "detail": "tool result"}
    ]


@pytest.mark.asyncio
async def test_runner_calls_on_error_for_model_error_result():
    from nanobot.agent.hook import AgentHook, AgentRunHookContext
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)
    events: list[tuple] = []

    async def chat_with_retry(**kwargs):
        return LLMResponse(content="model failed", finish_reason="error", tool_calls=[])

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []

    class ErrorHook(AgentHook):
        async def before_run(self, context: AgentRunHookContext) -> None:
            events.append(("before_run", context.stop_reason))

        async def on_error(self, context: AgentRunHookContext) -> None:
            events.append(("on_error", context.stop_reason, context.error, context.exception))

        async def after_run(self, context: AgentRunHookContext) -> None:
            events.append(("after_run", context.stop_reason, context.error))

        async def on_finally(self, context: AgentRunHookContext) -> None:
            events.append(("on_finally", context.stop_reason, context.error))

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
        initial_messages=[],
        tools=tools,
        model="test-model",
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        hook=ErrorHook(),
    ))

    assert result.stop_reason == "error"
    assert result.error == "model failed"
    assert events == [
        ("before_run", None),
        ("on_error", "error", "model failed", None),
        ("after_run", "error", "model failed"),
        ("on_finally", "error", "model failed"),
    ]


@pytest.mark.asyncio
async def test_runner_calls_on_error_and_finally_for_unhandled_exception():
    from nanobot.agent.hook import AgentHook, AgentRunHookContext
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)
    events: list[tuple] = []

    async def chat_with_retry(**kwargs):
        raise RuntimeError("provider exploded")

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []

    class ExceptionHook(AgentHook):
        async def before_run(self, context: AgentRunHookContext) -> None:
            events.append(("before_run", list(context.messages)))

        async def on_error(self, context: AgentRunHookContext) -> None:
            events.append((
                "on_error",
                context.stop_reason,
                context.error,
                type(context.exception).__name__ if context.exception else None,
            ))

        async def after_run(self, context: AgentRunHookContext) -> None:
            events.append(("after_run", context.stop_reason))

        async def on_finally(self, context: AgentRunHookContext) -> None:
            events.append(("on_finally", context.stop_reason))

    runner = AgentRunner()
    with pytest.raises(RuntimeError, match="provider exploded"):
        await runner.run(make_run_spec(provider,
            initial_messages=[{"role": "user", "content": "hi"}],
            tools=tools,
            model="test-model",
            max_iterations=1,
            max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
            hook=ExceptionHook(),
        ))

    assert events == [
        ("before_run", [{"role": "user", "content": "hi"}]),
        ("on_error", "error", "Error: RuntimeError: provider exploded", "RuntimeError"),
        ("on_finally", "error"),
    ]


@pytest.mark.asyncio
async def test_runner_preserves_original_exception_when_finally_hook_fails():
    from nanobot.agent.hook import AgentHook, AgentRunHookContext
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)

    async def chat_with_retry(**kwargs):
        raise RuntimeError("provider exploded")

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []

    class BadFinallyHook(AgentHook):
        async def on_finally(self, context: AgentRunHookContext) -> None:
            raise RuntimeError("finally exploded")

    runner = AgentRunner()
    with pytest.raises(RuntimeError, match="provider exploded"):
        await runner.run(make_run_spec(provider,
            initial_messages=[{"role": "user", "content": "hi"}],
            tools=tools,
            model="test-model",
            max_iterations=1,
            max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
            hook=BadFinallyHook(),
        ))


@pytest.mark.asyncio
async def test_runner_does_not_report_cancellation_as_error():
    import asyncio

    from nanobot.agent.hook import AgentHook, AgentRunHookContext
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)
    events: list[tuple] = []

    async def chat_with_retry(**kwargs):
        raise asyncio.CancelledError()

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []

    class CancellationHook(AgentHook):
        async def before_run(self, context: AgentRunHookContext) -> None:
            events.append(("before_run", context.stop_reason))

        async def on_error(self, context: AgentRunHookContext) -> None:
            events.append(("on_error", context.stop_reason, context.error))

        async def after_run(self, context: AgentRunHookContext) -> None:
            events.append(("after_run", context.stop_reason))

        async def on_finally(self, context: AgentRunHookContext) -> None:
            events.append((
                "on_finally",
                context.stop_reason,
                context.error,
                type(context.exception).__name__ if context.exception else None,
            ))

    runner = AgentRunner()
    with pytest.raises(asyncio.CancelledError):
        await runner.run(make_run_spec(provider,
            initial_messages=[{"role": "user", "content": "hi"}],
            tools=tools,
            model="test-model",
            max_iterations=1,
            max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
            hook=CancellationHook(),
        ))

    assert events == [
        ("before_run", None),
        ("on_finally", "cancelled", None, "CancelledError"),
    ]


@pytest.mark.asyncio
async def test_runner_preserves_cancellation_when_finally_hook_fails():
    import asyncio

    from nanobot.agent.hook import AgentHook, AgentRunHookContext
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)

    async def chat_with_retry(**kwargs):
        raise asyncio.CancelledError()

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []

    class BadFinallyHook(AgentHook):
        async def on_finally(self, context: AgentRunHookContext) -> None:
            raise RuntimeError("finally exploded")

    runner = AgentRunner()
    with pytest.raises(asyncio.CancelledError):
        await runner.run(make_run_spec(provider,
            initial_messages=[{"role": "user", "content": "hi"}],
            tools=tools,
            model="test-model",
            max_iterations=1,
            max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
            hook=BadFinallyHook(),
        ))
