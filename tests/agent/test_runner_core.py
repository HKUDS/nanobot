"""Tests for core AgentRunner behavior: message passing, iteration limits,
timeouts, empty-response handling, usage accumulation, and config passthrough."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.runner_helpers import make_run_spec
from nanobot.config.schema import AgentDefaults
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest

_MAX_TOOL_RESULT_CHARS = AgentDefaults().max_tool_result_chars


@pytest.mark.asyncio
async def test_runner_preserves_reasoning_fields_and_tool_results():
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)
    captured_second_call: list[dict] = []
    call_count = {"n": 0}

    async def chat_with_retry(*, messages, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return LLMResponse(
                content="thinking",
                tool_calls=[ToolCallRequest(id="call_1", name="list_dir", arguments={"path": "."})],
                reasoning_content="hidden reasoning",
                thinking_blocks=[{"type": "thinking", "thinking": "step"}],
                usage={"prompt_tokens": 5, "completion_tokens": 3},
            )
        captured_second_call[:] = messages
        return LLMResponse(content="done", tool_calls=[], usage={})

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(return_value="tool result")

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
        initial_messages=[
            {"role": "system", "content": "system"},
            {"role": "user", "content": "do task"},
        ],
        tools=tools,
        model="test-model",
        max_iterations=3,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    assert result.final_content == "done"
    assert result.tools_used == ["list_dir"]
    assert result.tool_events == [
        {"name": "list_dir", "status": "ok", "detail": "tool result"}
    ]

    assistant_messages = [
        msg for msg in captured_second_call
        if msg.get("role") == "assistant" and msg.get("tool_calls")
    ]
    assert len(assistant_messages) == 1
    assert assistant_messages[0]["reasoning_content"] == "hidden reasoning"
    assert assistant_messages[0]["thinking_blocks"] == [{"type": "thinking", "thinking": "step"}]
    assert any(
        msg.get("role") == "tool" and msg.get("content") == "tool result"
        for msg in captured_second_call
    )


@pytest.mark.asyncio
async def test_runner_returns_max_iterations_fallback():
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content="still working",
        tool_calls=[ToolCallRequest(id="call_1", name="list_dir", arguments={"path": "."})],
    ))
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(return_value="tool result")

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
        initial_messages=[],
        tools=tools,
        model="test-model",
        max_iterations=2,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    assert result.stop_reason == "max_iterations"
    assert result.final_content == (
        "I reached the maximum number of tool call iterations (2) "
        "without completing the task. You can try breaking the task into smaller steps."
    )
    assert result.messages[-1]["role"] == "assistant"
    assert result.messages[-1]["content"] == result.final_content
    assert provider.chat_with_retry.await_count == 3
    assert provider.chat_with_retry.await_args_list[-1].kwargs["tools"] is None
    assert tools.execute.await_count == 2


@pytest.mark.asyncio
async def test_runner_uses_no_tools_finalization_after_max_iterations():
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)
    calls: list[dict] = []

    async def chat_with_retry(*, messages, tools=None, **kwargs):
        calls.append({"messages": messages, "tools": tools})
        if len(calls) <= 2:
            return LLMResponse(
                content="still working",
                tool_calls=[
                    ToolCallRequest(
                        id=f"call_{len(calls)}",
                        name="list_dir",
                        arguments={"path": "."},
                    )
                ],
            )
        return LLMResponse(
            content="Read the directory twice. More investigation remains.",
            tool_calls=[],
            usage={"prompt_tokens": 10, "completion_tokens": 7},
        )

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(return_value="tool result")

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
        initial_messages=[{"role": "user", "content": "inspect the repo"}],
        tools=tools,
        model="test-model",
        max_iterations=2,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    assert result.stop_reason == "max_iterations"
    assert result.final_content == "Read the directory twice. More investigation remains."
    assert result.messages[-1] == {
        "role": "assistant",
        "content": "Read the directory twice. More investigation remains.",
    }
    assert len(calls) == 3
    assert calls[-1]["tools"] is None
    assert "tool-call budget" in calls[-1]["messages"][-1]["content"]
    assert tools.execute.await_count == 2


@pytest.mark.asyncio
async def test_runner_times_out_hung_llm_request():
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)

    async def chat_with_retry(**kwargs):
        await asyncio.sleep(3600)

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []

    runner = AgentRunner()
    started = time.monotonic()
    result = await runner.run(make_run_spec(provider,
        initial_messages=[{"role": "user", "content": "hello"}],
        tools=tools,
        model="test-model",
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        llm_timeout_s=0.05,
    ))

    assert (time.monotonic() - started) < 1.0
    assert result.stop_reason == "error"
    assert "timed out" in (result.final_content or "").lower()


@pytest.mark.asyncio
async def test_runner_applies_outer_wall_timeout_to_streaming_requests():
    from nanobot.agent.hook import AgentHook, AgentHookContext
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)
    streamed: list[str] = []

    async def chat_stream_with_retry(*, on_content_delta, **kwargs):
        await asyncio.sleep(0)
        await on_content_delta("still ")
        await asyncio.sleep(0)
        await on_content_delta("alive")
        return LLMResponse(content="still alive", tool_calls=[])

    provider.chat_stream_with_retry = chat_stream_with_retry
    provider.chat_with_retry = AsyncMock()
    tools = MagicMock()
    tools.get_definitions.return_value = []

    class StreamingHook(AgentHook):
        def wants_streaming(self) -> bool:
            return True

        async def on_stream(self, context: AgentHookContext, delta: str) -> None:
            streamed.append(delta)

    runner = AgentRunner()
    wait_for_calls: list[float] = []

    async def fake_wait_for(coro, *, timeout):
        wait_for_calls.append(timeout)
        return await coro

    with patch("nanobot.agent.runner.asyncio.wait_for", fake_wait_for):
        result = await runner.run(make_run_spec(provider,
            initial_messages=[{"role": "user", "content": "think for a while"}],
            tools=tools,
            model="test-model",
            max_iterations=1,
            max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
            hook=StreamingHook(),
            llm_timeout_s=0.01,
        ))

    assert result.stop_reason == "completed"
    assert result.final_content == "still alive"
    assert streamed == ["still ", "alive"]
    provider.chat_with_retry.assert_not_awaited()
    assert wait_for_calls == [300.0]


@pytest.mark.asyncio
async def test_runner_times_out_never_ending_streaming_request():
    from nanobot.agent.hook import AgentHook
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)

    async def chat_stream_with_retry(*, on_content_delta, **kwargs):
        await asyncio.sleep(3600)

    provider.chat_stream_with_retry = chat_stream_with_retry
    provider.chat_with_retry = AsyncMock()
    tools = MagicMock()
    tools.get_definitions.return_value = []

    class StreamingHook(AgentHook):
        def wants_streaming(self) -> bool:
            return True

    async def fake_wait_for(coro, *, timeout):
        coro.close()
        raise asyncio.TimeoutError

    runner = AgentRunner()
    with patch("nanobot.agent.runner.asyncio.wait_for", fake_wait_for):
        result = await runner.run(make_run_spec(provider,
            initial_messages=[{"role": "user", "content": "think forever"}],
            tools=tools,
            model="test-model",
            max_iterations=1,
            max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
            hook=StreamingHook(),
            llm_timeout_s=200,
        ))

    assert result.stop_reason == "error"
    assert result.final_content == "Error calling LLM: timed out after 400s"
    provider.chat_with_retry.assert_not_awaited()


@pytest.mark.asyncio
async def test_runner_closes_progress_reasoning_on_streaming_wall_timeout():
    from nanobot.agent.hook import AgentHook
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)
    provider.supports_progress_deltas = True
    events: list[tuple[str, str | None]] = []

    async def chat_stream_with_retry(*, on_content_delta, **kwargs):
        try:
            await on_content_delta("<think>working...</think>")
            await asyncio.sleep(3600)
        finally:
            events.append(("provider_cancelled", None))

    provider.chat_stream_with_retry = chat_stream_with_retry
    provider.chat_with_retry = AsyncMock()
    tools = MagicMock()
    tools.get_definitions.return_value = []

    class ProgressReasoningHook(AgentHook):
        async def emit_reasoning(self, reasoning_content: str | None) -> None:
            if reasoning_content:
                events.append(("reasoning", reasoning_content))

        async def emit_reasoning_end(self) -> None:
            events.append(("reasoning_end", None))

    real_wait_for = asyncio.wait_for

    async def fake_wait_for(coro, *, timeout):
        assert timeout == 300.0
        return await real_wait_for(coro, timeout=0.01)

    runner = AgentRunner()
    with patch("nanobot.agent.runner.asyncio.wait_for", fake_wait_for):
        result = await runner.run(make_run_spec(provider,
            initial_messages=[{"role": "user", "content": "think forever"}],
            tools=tools,
            model="test-model",
            max_iterations=1,
            max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
            hook=ProgressReasoningHook(),
            progress_callback=AsyncMock(),
            stream_progress_deltas=True,
            llm_timeout_s=1,
        ))

    assert result.stop_reason == "error"
    assert result.final_content == "Error calling LLM: timed out after 300s"
    assert events == [
        ("reasoning", "working..."),
        ("provider_cancelled", None),
        ("reasoning_end", None),
    ]
    provider.chat_with_retry.assert_not_awaited()


@pytest.mark.asyncio
async def test_runner_replaces_empty_tool_result_with_marker():
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)
    captured_second_call: list[dict] = []
    call_count = {"n": 0}

    async def chat_with_retry(*, messages, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return LLMResponse(
                content="working",
                tool_calls=[ToolCallRequest(id="call_1", name="noop", arguments={})],
                usage={},
            )
        captured_second_call[:] = messages
        return LLMResponse(content="done", tool_calls=[], usage={})

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(return_value="")

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
        initial_messages=[{"role": "user", "content": "do task"}],
        tools=tools,
        model="test-model",
        max_iterations=2,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    assert result.final_content == "done"
    tool_message = next(msg for msg in captured_second_call if msg.get("role") == "tool")
    assert tool_message["content"] == "(noop completed with no output)"


@pytest.mark.asyncio
async def test_runner_retries_empty_final_response_with_summary_prompt():
    """Empty responses get 2 silent retries before finalization kicks in."""
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)
    calls: list[dict] = []

    async def chat_with_retry(*, messages, tools=None, **kwargs):
        calls.append({"messages": messages, "tools": tools})
        if len(calls) <= 2:
            return LLMResponse(
                content=None,
                tool_calls=[],
                usage={"prompt_tokens": 5, "completion_tokens": 1},
            )
        return LLMResponse(
            content="final answer",
            tool_calls=[],
            usage={"prompt_tokens": 3, "completion_tokens": 7},
        )

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
        initial_messages=[{"role": "user", "content": "do task"}],
        tools=tools,
        model="test-model",
        max_iterations=3,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    assert result.final_content == "final answer"
    # 2 silent retries (iterations 0,1) + finalization on iteration 1
    assert len(calls) == 3
    assert calls[0]["tools"] is not None
    assert calls[1]["tools"] is not None
    assert calls[2]["tools"] is None
    assert result.usage["prompt_tokens"] == 13
    assert result.usage["completion_tokens"] == 9


@pytest.mark.asyncio
async def test_runner_uses_specific_message_after_empty_finalization_retry():
    """After silent retries + finalization all return empty, stop_reason is empty_final_response."""
    from nanobot.agent.runner import AgentRunner
    from nanobot.utils.runtime import EMPTY_FINAL_RESPONSE_MESSAGE

    provider = MagicMock(spec=LLMProvider)

    async def chat_with_retry(*, messages, **kwargs):
        return LLMResponse(content=None, tool_calls=[], usage={})

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
        initial_messages=[{"role": "user", "content": "do task"}],
        tools=tools,
        model="test-model",
        max_iterations=3,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    assert result.final_content == EMPTY_FINAL_RESPONSE_MESSAGE
    assert result.stop_reason == "empty_final_response"


@pytest.mark.asyncio
async def test_runner_length_recovery_returns_all_segments():
    """Recovered output segments are returned together instead of only the tail."""
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)
    provider.chat_with_retry = AsyncMock(side_effect=[
        LLMResponse(content="first ", finish_reason="length"),
        LLMResponse(content="second ", finish_reason="length"),
        LLMResponse(content="third", finish_reason="stop"),
    ])
    tools = MagicMock()
    tools.get_definitions.return_value = []

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
        initial_messages=[{"role": "user", "content": "give a long answer"}],
        tools=tools,
        model="test-model",
        max_iterations=5,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    assert result.final_content == "first second third"
    assert [
        message["content"]
        for message in result.messages
        if message.get("role") == "assistant"
    ] == ["first", "second", "third"]
    assert provider.chat_with_retry.await_count == 3


@pytest.mark.asyncio
async def test_runner_length_recovery_does_not_leak_across_tool_calls():
    """A recovered prefix belongs only to its contiguous response chain."""
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)
    provider.chat_with_retry = AsyncMock(side_effect=[
        LLMResponse(content="working", finish_reason="length"),
        LLMResponse(
            content=None,
            tool_calls=[ToolCallRequest(id="call_1", name="read_file", arguments={"path": "x"})],
            finish_reason="tool_calls",
        ),
        LLMResponse(content="final answer", finish_reason="stop"),
    ])
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(return_value="file content")

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
        initial_messages=[{"role": "user", "content": "inspect a file"}],
        tools=tools,
        model="test-model",
        max_iterations=5,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    assert result.final_content == "final answer"
    assert result.tools_used == ["read_file"]


@pytest.mark.asyncio
async def test_runner_empty_response_does_not_break_tool_chain():
    """An empty intermediate response must not kill an ongoing tool chain.

    Sequence: tool_call -> empty -> tool_call -> final text.
    The runner should recover via silent retry and complete normally.
    """
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)
    call_count = 0

    async def chat_with_retry(*, messages, tools=None, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return LLMResponse(
                content=None,
                tool_calls=[ToolCallRequest(id="tc1", name="read_file", arguments={"path": "a.txt"})],
                usage={"prompt_tokens": 10, "completion_tokens": 5},
            )
        if call_count == 2:
            return LLMResponse(content=None, tool_calls=[], usage={"prompt_tokens": 10, "completion_tokens": 1})
        if call_count == 3:
            return LLMResponse(
                content=None,
                tool_calls=[ToolCallRequest(id="tc2", name="read_file", arguments={"path": "b.txt"})],
                usage={"prompt_tokens": 10, "completion_tokens": 5},
            )
        return LLMResponse(
            content="Here are the results.",
            tool_calls=[],
            usage={"prompt_tokens": 10, "completion_tokens": 10},
        )

    provider.chat_with_retry = chat_with_retry
    provider.chat_stream_with_retry = chat_with_retry

    async def fake_tool(name, args, **kw):
        return "file content"

    tool_registry = MagicMock()
    tool_registry.get_definitions.return_value = [{"type": "function", "function": {"name": "read_file"}}]
    tool_registry.execute = AsyncMock(side_effect=fake_tool)

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
        initial_messages=[{"role": "user", "content": "read both files"}],
        tools=tool_registry,
        model="test-model",
        max_iterations=10,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    assert result.final_content == "Here are the results."
    assert result.stop_reason == "completed"
    assert call_count == 4
    assert "read_file" in result.tools_used


@pytest.mark.asyncio
async def test_runner_accumulates_usage_and_preserves_cached_tokens():
    """Runner should accumulate prompt/completion tokens across iterations
    and preserve cached_tokens from provider responses."""
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)
    call_count = {"n": 0}

    async def chat_with_retry(*, messages, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return LLMResponse(
                content="thinking",
                tool_calls=[ToolCallRequest(id="call_1", name="read_file", arguments={"path": "x"})],
                usage={"prompt_tokens": 100, "completion_tokens": 10, "cached_tokens": 80},
            )
        return LLMResponse(
            content="done",
            tool_calls=[],
            usage={"prompt_tokens": 200, "completion_tokens": 20, "cached_tokens": 150},
        )

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(return_value="file content")

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
        initial_messages=[{"role": "user", "content": "do task"}],
        tools=tools,
        model="test-model",
        max_iterations=3,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    # Usage should be accumulated across iterations
    assert result.usage["prompt_tokens"] == 300  # 100 + 200
    assert result.usage["completion_tokens"] == 30  # 10 + 20
    assert result.usage["cached_tokens"] == 230  # 80 + 150


@pytest.mark.asyncio
async def test_runner_binds_on_retry_wait_to_retry_callback_not_progress():
    """Regression: provider retry heartbeats must route through
    ``retry_wait_callback``, not ``progress_callback``. Binding them to
    the progress callback (as an earlier runtime refactor did) caused
    internal retry diagnostics like "Model request failed, retry in 1s"
    to leak to end-user channels as normal progress updates.
    """
    from nanobot.agent.runner import AgentRunner

    captured: dict = {}

    async def chat_with_retry(**kwargs):
        captured.update(kwargs)
        return LLMResponse(content="done", tool_calls=[], usage={})

    provider = MagicMock(spec=LLMProvider)
    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []

    progress_cb = AsyncMock()
    retry_wait_cb = AsyncMock()

    runner = AgentRunner()
    await runner.run(make_run_spec(provider,
        initial_messages=[
            {"role": "system", "content": "system"},
            {"role": "user", "content": "hi"},
        ],
        tools=tools,
        model="test-model",
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        progress_callback=progress_cb,
        retry_wait_callback=retry_wait_cb,
    ))

    assert captured["on_retry_wait"] is retry_wait_cb
    assert captured["on_retry_wait"] is not progress_cb


# ---------------------------------------------------------------------------
# Config passthrough tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_passes_temperature_to_provider():
    """temperature from AgentRunSpec should reach provider.chat_with_retry."""
    from nanobot.agent.runner import AgentRunner

    captured: dict = {}

    async def chat_with_retry(**kwargs):
        captured.update(kwargs)
        return LLMResponse(content="done", tool_calls=[], usage={})

    provider = MagicMock(spec=LLMProvider)
    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []

    runner = AgentRunner()
    await runner.run(make_run_spec(provider,
        initial_messages=[{"role": "user", "content": "hi"}],
        tools=tools,
        model="test-model",
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        temperature=0.7,
    ))

    assert captured["temperature"] == 0.7


@pytest.mark.asyncio
async def test_runner_passes_max_tokens_to_provider():
    """max_tokens from AgentRunSpec should reach provider.chat_with_retry."""
    from nanobot.agent.runner import AgentRunner

    captured: dict = {}

    async def chat_with_retry(**kwargs):
        captured.update(kwargs)
        return LLMResponse(content="done", tool_calls=[], usage={})

    provider = MagicMock(spec=LLMProvider)
    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []

    runner = AgentRunner()
    await runner.run(make_run_spec(provider,
        initial_messages=[{"role": "user", "content": "hi"}],
        tools=tools,
        model="test-model",
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        max_tokens=8192,
    ))

    assert captured["max_tokens"] == 8192


@pytest.mark.asyncio
async def test_runner_passes_reasoning_effort_to_provider():
    """reasoning_effort from AgentRunSpec should reach provider.chat_with_retry."""
    from nanobot.agent.runner import AgentRunner

    captured: dict = {}

    async def chat_with_retry(**kwargs):
        captured.update(kwargs)
        return LLMResponse(content="done", tool_calls=[], usage={})

    provider = MagicMock(spec=LLMProvider)
    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []

    runner = AgentRunner()
    await runner.run(make_run_spec(provider,
        initial_messages=[{"role": "user", "content": "hi"}],
        tools=tools,
        model="test-model",
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        reasoning_effort="high",
    ))

    assert captured["reasoning_effort"] == "high"
