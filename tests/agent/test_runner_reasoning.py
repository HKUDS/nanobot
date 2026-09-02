"""Tests for AgentRunner reasoning extraction and emission.

Covers the three sources of model reasoning (dedicated ``reasoning_content``,
Anthropic ``thinking_blocks``, inline ``<think>``/``<thought>`` tags) plus
the streaming interaction: reasoning and answer streams are independent
channels, gated by ``context.streamed_reasoning`` rather than
``context.streamed_content``.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.runner_helpers import make_run_spec
from nanobot.agent.hook import AgentHook, AgentHookContext
from nanobot.agent.progress_hook import AgentProgressHook
from nanobot.config.schema import AgentDefaults
from nanobot.providers.base import LLMResponse, LLMUsage, ToolCallRequest

_MAX_TOOL_RESULT_CHARS = AgentDefaults().max_tool_result_chars


class _RecordingHook(AgentHook):
    def __init__(self) -> None:
        super().__init__()
        self.emitted: list[str] = []
        self.end_calls = 0

    async def emit_reasoning(self, reasoning_content: str | None) -> None:
        if reasoning_content:
            self.emitted.append(reasoning_content)

    async def emit_reasoning_end(self) -> None:
        self.end_calls += 1


class _StreamRecordingHook(_RecordingHook):
    def __init__(self) -> None:
        super().__init__()
        self.streamed: list[str] = []

    def wants_streaming(self) -> bool:
        return True

    async def on_stream(self, _ctx: AgentHookContext, delta: str) -> None:
        self.streamed.append(delta)


class _LifecycleRecordingHook(AgentHook):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[str] = []

    def wants_streaming(self) -> bool:
        return True

    async def emit_reasoning(self, reasoning_content: str | None) -> None:
        if reasoning_content:
            self.events.append(f"reasoning:{reasoning_content}")

    async def emit_reasoning_end(self) -> None:
        self.events.append("reasoning_end")

    async def on_stream(self, _ctx: AgentHookContext, delta: str) -> None:
        self.events.append(f"content:{delta}")

    async def on_stream_end(self, _ctx: AgentHookContext, *, resuming: bool) -> None:
        self.events.append(f"stream_end:{resuming}")

    async def before_execute_tools(self, context: AgentHookContext) -> None:
        names = ",".join(call.name for call in context.tool_calls)
        self.events.append(f"local_tools:{names}")

    async def on_provider_tool_event(
        self,
        _context: AgentHookContext,
        event: dict[str, Any],
    ) -> None:
        self.events.append(f"hosted_tool:{event.get('phase')}")


class _BlockingReasoningEndHook(_LifecycleRecordingHook):
    def __init__(self) -> None:
        super().__init__()
        self.reasoning_end_started = asyncio.Event()
        self.release_reasoning_end = asyncio.Event()

    async def emit_reasoning_end(self) -> None:
        self.reasoning_end_started.set()
        await self.release_reasoning_end.wait()
        await super().emit_reasoning_end()


@pytest.mark.asyncio
async def test_runner_preserves_reasoning_fields_in_assistant_history():
    """Reasoning fields ride along on the persisted assistant message so
    follow-up provider calls retain the model's prior thinking context."""
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock()
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
                usage=LLMUsage.reported(input_tokens=5, output_tokens=3),
            )
        captured_second_call[:] = messages
        return LLMResponse(content="done", tool_calls=[], usage=None)

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
    assistant_messages = [
        msg for msg in captured_second_call
        if msg.get("role") == "assistant" and msg.get("tool_calls")
    ]
    assert len(assistant_messages) == 1
    assert assistant_messages[0]["reasoning_content"] == "hidden reasoning"
    assert assistant_messages[0]["thinking_blocks"] == [{"type": "thinking", "thinking": "step"}]


@pytest.mark.asyncio
async def test_runner_emits_anthropic_thinking_blocks():
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock()

    async def chat_with_retry(**kwargs):
        return LLMResponse(
            content="The answer is 42.",
            thinking_blocks=[
                {"type": "thinking", "thinking": "Let me analyze this step by step.", "signature": "sig1"},
                {"type": "thinking", "thinking": "After careful consideration.", "signature": "sig2"},
            ],
            tool_calls=[],
            usage=LLMUsage.reported(input_tokens=5, output_tokens=3),
        )

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []

    hook = _RecordingHook()
    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
        initial_messages=[{"role": "user", "content": "question"}],
        tools=tools,
        model="test-model",
        max_iterations=3,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        hook=hook,
    ))

    assert result.final_content == "The answer is 42."
    assert len(hook.emitted) == 1
    assert "Let me analyze this" in hook.emitted[0]
    assert "After careful consideration" in hook.emitted[0]


@pytest.mark.asyncio
async def test_runner_emits_inline_think_content_as_reasoning():
    """Models embedding reasoning in <think>...</think> blocks should have
    that content extracted and emitted, and stripped from the answer."""
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock()

    async def chat_with_retry(**kwargs):
        return LLMResponse(
            content="<think>Let me think about this...\nThe answer is 42.</think>The answer is 42.",
            tool_calls=[],
            usage=LLMUsage.reported(input_tokens=5, output_tokens=3),
        )

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []

    hook = _RecordingHook()
    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
        initial_messages=[{"role": "user", "content": "what is the answer?"}],
        tools=tools,
        model="test-model",
        max_iterations=3,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        hook=hook,
    ))

    assert result.final_content == "The answer is 42."
    assert len(hook.emitted) == 1
    assert "Let me think about this" in hook.emitted[0]


@pytest.mark.asyncio
async def test_runner_prefers_reasoning_content_over_inline_think():
    """Fallback priority: dedicated reasoning_content wins; inline <think>
    is still scrubbed from the answer content."""
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock()

    async def chat_with_retry(**kwargs):
        return LLMResponse(
            content="<think>inline thinking</think>The answer.",
            reasoning_content="dedicated reasoning field",
            tool_calls=[],
            usage=LLMUsage.reported(input_tokens=5, output_tokens=3),
        )

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []

    hook = _RecordingHook()
    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
        initial_messages=[{"role": "user", "content": "question"}],
        tools=tools,
        model="test-model",
        max_iterations=3,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        hook=hook,
    ))

    assert result.final_content == "The answer."
    assert hook.emitted == ["dedicated reasoning field"]


@pytest.mark.asyncio
async def test_runner_emits_reasoning_content_even_when_answer_was_streamed():
    """`reasoning_content` arrives only on the final response; streaming the
    answer must not suppress it (the answer stream and the reasoning channel
    are independent — only the reasoning-already-emitted bit matters)."""
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock()

    async def chat_stream_with_retry(*, on_content_delta=None, **kwargs):
        if on_content_delta:
            await on_content_delta("The ")
            await on_content_delta("answer.")
        return LLMResponse(
            content="The answer.",
            reasoning_content="step-by-step deduction",
            tool_calls=[],
            usage=LLMUsage.reported(input_tokens=5, output_tokens=3),
        )

    provider.chat_stream_with_retry = chat_stream_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []

    hook = _StreamRecordingHook()
    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
        initial_messages=[{"role": "user", "content": "question"}],
        tools=tools,
        model="test-model",
        max_iterations=3,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        hook=hook,
    ))

    assert result.final_content == "The answer."
    assert hook.streamed == ["The ", "answer."]
    assert hook.emitted == ["step-by-step deduction"]


@pytest.mark.asyncio
async def test_runner_does_not_double_emit_when_inline_think_already_streamed():
    """Inline `<think>` blocks streamed incrementally during the answer
    stream must not be re-emitted from the final response."""
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock()

    async def chat_stream_with_retry(*, on_content_delta=None, **kwargs):
        if on_content_delta:
            await on_content_delta("<think>working...</think>")
            await on_content_delta("The answer.")
        return LLMResponse(
            content="<think>working...</think>The answer.",
            tool_calls=[],
            usage=LLMUsage.reported(input_tokens=5, output_tokens=3),
        )

    provider.chat_stream_with_retry = chat_stream_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []

    reasoning_events: list[str] = []

    async def _progress(content: str, *, reasoning: bool = False, **_kwargs):
        if reasoning:
            reasoning_events.append(content)

    async def _stream(_content: str) -> None:
        pass

    hook = AgentProgressHook(on_progress=_progress, on_stream=_stream)
    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
        initial_messages=[{"role": "user", "content": "question"}],
        tools=tools,
        model="test-model",
        max_iterations=3,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        hook=hook,
    ))

    assert result.final_content == "The answer."
    assert reasoning_events == ["working..."]


@pytest.mark.asyncio
async def test_runner_closes_reasoning_stream_after_one_shot_response():
    """A non-streaming response carrying ``reasoning_content`` must emit
    both a reasoning delta and an end marker so channels can finalize the
    in-place bubble."""
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock()

    async def chat_with_retry(**kwargs):
        return LLMResponse(
            content="answer",
            reasoning_content="hidden thought",
            tool_calls=[],
            usage=LLMUsage.reported(input_tokens=5, output_tokens=3),
        )

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []

    hook = _RecordingHook()
    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
        initial_messages=[{"role": "user", "content": "q"}],
        tools=tools,
        model="test-model",
        max_iterations=3,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        hook=hook,
    ))

    assert result.final_content == "answer"
    assert hook.emitted == ["hidden thought"]
    assert hook.end_calls == 1


@pytest.mark.asyncio
async def test_runner_streams_native_thinking_deltas_without_post_hoc_dup():
    """Anthropic-style ``on_thinking_delta`` should fan out to ``emit_reasoning``;
    final ``thinking_blocks`` must not emit again when already streamed."""
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock()

    async def chat_stream_with_retry(
        *, on_content_delta=None, on_thinking_delta=None, **kwargs
    ):
        if on_thinking_delta:
            await on_thinking_delta("part1")
            await on_thinking_delta("part2")
        if on_content_delta:
            await on_content_delta("done")
        return LLMResponse(
            content="done",
            tool_calls=[],
            thinking_blocks=[{"type": "thinking", "thinking": "part1part2"}],
            usage=LLMUsage.reported(input_tokens=1, output_tokens=2),
        )

    provider.chat_stream_with_retry = chat_stream_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []

    hook = _StreamRecordingHook()
    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
        initial_messages=[{"role": "user", "content": "q"}],
        tools=tools,
        model="test-model",
        max_iterations=3,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        hook=hook,
    ))

    assert result.final_content == "done"
    assert hook.emitted == ["part1", "part2"]


@pytest.mark.asyncio
async def test_runner_closes_native_reasoning_before_streaming_answer():
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock()

    async def chat_stream_with_retry(
        *, on_content_delta=None, on_thinking_delta=None, **kwargs
    ):
        if on_thinking_delta:
            await on_thinking_delta("inspect")
        if on_content_delta:
            await on_content_delta("done")
        return LLMResponse(content="done", tool_calls=[], usage=None)

    provider.chat_stream_with_retry = chat_stream_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []
    hook = _LifecycleRecordingHook()

    result = await AgentRunner().run(make_run_spec(
        provider,
        initial_messages=[{"role": "user", "content": "q"}],
        tools=tools,
        model="test-model",
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        hook=hook,
    ))

    assert result.final_content == "done"
    assert hook.events == [
        "reasoning:inspect",
        "reasoning_end",
        "content:done",
        "stream_end:False",
    ]


@pytest.mark.asyncio
async def test_runner_closes_native_reasoning_before_local_tool_execution():
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock()
    responses = iter([
        LLMResponse(
            content="",
            finish_reason="tool_calls",
            tool_calls=[ToolCallRequest(id="call-1", name="list_dir", arguments={"path": "."})],
            usage=None,
        ),
        LLMResponse(content="done", tool_calls=[], usage=None),
    ])

    async def chat_stream_with_retry(
        *, on_content_delta=None, on_thinking_delta=None, **kwargs
    ):
        response = next(responses)
        if response.tool_calls:
            if on_thinking_delta:
                await on_thinking_delta("inspect")
        elif on_content_delta:
            await on_content_delta("done")
        return response

    provider.chat_stream_with_retry = chat_stream_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(return_value="tool result")
    hook = _LifecycleRecordingHook()

    result = await AgentRunner().run(make_run_spec(
        provider,
        initial_messages=[{"role": "user", "content": "inspect"}],
        tools=tools,
        model="test-model",
        max_iterations=2,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        hook=hook,
    ))

    assert result.final_content == "done"
    assert hook.events == [
        "reasoning:inspect",
        "reasoning_end",
        "stream_end:True",
        "local_tools:list_dir",
        "content:done",
        "stream_end:False",
    ]


@pytest.mark.asyncio
async def test_runner_closes_native_reasoning_before_hosted_tool_event():
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock()

    async def chat_stream_with_retry(
        *, on_content_delta=None, on_thinking_delta=None, on_tool_call_delta=None, **kwargs
    ):
        if on_thinking_delta:
            await on_thinking_delta("search")
        if on_tool_call_delta:
            await on_tool_call_delta({
                "kind": "hosted_tool",
                "phase": "start",
                "call_id": "search-1",
                "name": "web_search",
                "arguments": {"query": "nanobot"},
            })
            await on_tool_call_delta({
                "kind": "hosted_tool",
                "phase": "end",
                "call_id": "search-1",
                "name": "web_search",
                "arguments": {"query": "nanobot"},
                "result": {"count": 1},
            })
        if on_content_delta:
            await on_content_delta("done")
        return LLMResponse(content="done", tool_calls=[], usage=None)

    provider.chat_stream_with_retry = chat_stream_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []
    hook = _LifecycleRecordingHook()

    result = await AgentRunner().run(make_run_spec(
        provider,
        initial_messages=[{"role": "user", "content": "search"}],
        tools=tools,
        model="test-model",
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        hook=hook,
    ))

    assert result.final_content == "done"
    assert hook.events == [
        "reasoning:search",
        "reasoning_end",
        "hosted_tool:start",
        "hosted_tool:end",
        "content:done",
        "stream_end:False",
    ]


@pytest.mark.asyncio
async def test_runner_closes_native_reasoning_when_stream_is_cancelled():
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock()
    reasoning_started = asyncio.Event()
    release_provider = asyncio.Event()

    async def chat_stream_with_retry(
        *, on_thinking_delta=None, **kwargs
    ):
        if on_thinking_delta:
            await on_thinking_delta("inspect")
        reasoning_started.set()
        await release_provider.wait()
        raise AssertionError("the cancelled provider call should not complete")

    provider.chat_stream_with_retry = chat_stream_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []
    hook = _LifecycleRecordingHook()

    task = asyncio.create_task(AgentRunner().run(make_run_spec(
        provider,
        initial_messages=[{"role": "user", "content": "inspect"}],
        tools=tools,
        model="test-model",
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        hook=hook,
    )))
    await reasoning_started.wait()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert hook.events == ["reasoning:inspect", "reasoning_end"]


@pytest.mark.asyncio
async def test_runner_settles_native_reasoning_end_before_propagating_cancellation():
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock()

    async def chat_stream_with_retry(
        *, on_content_delta=None, on_thinking_delta=None, **kwargs
    ):
        if on_thinking_delta:
            await on_thinking_delta("inspect")
        if on_content_delta:
            await on_content_delta("done")
        raise AssertionError("the cancelled provider call should not complete")

    provider.chat_stream_with_retry = chat_stream_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []
    hook = _BlockingReasoningEndHook()

    task = asyncio.create_task(AgentRunner().run(make_run_spec(
        provider,
        initial_messages=[{"role": "user", "content": "inspect"}],
        tools=tools,
        model="test-model",
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        hook=hook,
    )))
    await hook.reasoning_end_started.wait()

    task.cancel()
    await asyncio.sleep(0)
    hook.release_reasoning_end.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert hook.events == ["reasoning:inspect", "reasoning_end"]


@pytest.mark.asyncio
async def test_runner_strips_thinking_tags_from_native_thinking_deltas():
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock()

    async def chat_stream_with_retry(
        *, on_content_delta=None, on_thinking_delta=None, **kwargs
    ):
        if on_thinking_delta:
            await on_thinking_delta("<thinking")
            await on_thinking_delta(">Preparing final response")
            await on_thinking_delta("</thinking>")
        if on_content_delta:
            await on_content_delta("done")
        return LLMResponse(content="done", tool_calls=[], usage=None)

    provider.chat_stream_with_retry = chat_stream_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []

    hook = _StreamRecordingHook()
    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
        initial_messages=[{"role": "user", "content": "q"}],
        tools=tools,
        model="test-model",
        max_iterations=3,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        hook=hook,
    ))

    assert result.final_content == "done"
    assert hook.emitted == ["Preparing final response"]


@pytest.mark.asyncio
async def test_runner_ignores_empty_thinking_marker_before_final_reasoning():
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock()

    async def chat_stream_with_retry(
        *, on_content_delta=None, on_thinking_delta=None, **kwargs
    ):
        if on_thinking_delta:
            await on_thinking_delta("<thinking/>")
        if on_content_delta:
            await on_content_delta("done")
        return LLMResponse(
            content="done",
            reasoning_content="Preparing final response",
            tool_calls=[],
            usage=None,
        )

    provider.chat_stream_with_retry = chat_stream_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []

    hook = _StreamRecordingHook()
    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
        initial_messages=[{"role": "user", "content": "q"}],
        tools=tools,
        model="test-model",
        max_iterations=3,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        hook=hook,
    ))

    assert result.final_content == "done"
    assert hook.emitted == ["Preparing final response"]
