"""Tests for AgentRunner hook lifecycle: ordering, streaming deltas,
cached-token propagation, and hook context."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.config.schema import AgentDefaults
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest

_MAX_TOOL_RESULT_CHARS = AgentDefaults().max_tool_result_chars


@pytest.mark.asyncio
async def test_runner_calls_hooks_in_order():
    from nanobot.agent.hook import AgentHook, AgentHookContext
    from nanobot.agent.runner import AgentRunSpec, AgentRunner

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

    runner = AgentRunner(provider)
    result = await runner.run(AgentRunSpec(
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
    from nanobot.agent.runner import AgentRunSpec, AgentRunner

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

    runner = AgentRunner(provider)
    result = await runner.run(AgentRunSpec(
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
async def test_runner_passes_cached_tokens_to_hook_context():
    """Hook context.usage should contain cached_tokens."""
    from nanobot.agent.hook import AgentHook, AgentHookContext
    from nanobot.agent.runner import AgentRunSpec, AgentRunner

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

    runner = AgentRunner(provider)
    await runner.run(AgentRunSpec(
        initial_messages=[],
        tools=tools,
        model="test-model",
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        hook=UsageHook(),
    ))

    assert len(captured_usage) == 1
    assert captured_usage[0]["cached_tokens"] == 150
