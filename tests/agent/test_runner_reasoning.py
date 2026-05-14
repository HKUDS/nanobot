"""Tests for AgentRunner reasoning extraction and emission.

Covers the three sources of model reasoning (dedicated ``reasoning_content``,
Anthropic ``thinking_blocks``, inline ``<think>``/``<thought>`` tags) plus
the streaming interaction: reasoning and answer streams are independent
channels, gated by ``context.streamed_reasoning`` rather than
``context.streamed_content``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.hook import AgentHook
from nanobot.config.schema import AgentDefaults
from nanobot.providers.base import LLMResponse, ToolCallRequest

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


@pytest.mark.asyncio
async def test_runner_preserves_reasoning_fields_in_assistant_history():
    """Reasoning fields ride along on the persisted assistant message so
    follow-up provider calls retain the model's prior thinking context."""
    from nanobot.agent.runner import AgentRunSpec, AgentRunner

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
                usage={"prompt_tokens": 5, "completion_tokens": 3},
            )
        captured_second_call[:] = messages
        return LLMResponse(content="done", tool_calls=[], usage={})

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(return_value="tool result")

    runner = AgentRunner(provider)
    result = await runner.run(AgentRunSpec(
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
    from nanobot.agent.runner import AgentRunSpec, AgentRunner

    provider = MagicMock()

    async def chat_with_retry(**kwargs):
        return LLMResponse(
            content="The answer is 42.",
            thinking_blocks=[
                {"type": "thinking", "thinking": "Let me analyze this step by step.", "signature": "sig1"},
                {"type": "thinking", "thinking": "After careful consideration.", "signature": "sig2"},
            ],
            tool_calls=[],
            usage={"prompt_tokens": 5, "completion_tokens": 3},
        )

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []

    hook = _RecordingHook()
    runner = AgentRunner(provider)
    result = await runner.run(AgentRunSpec(
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
    from nanobot.agent.runner import AgentRunSpec, AgentRunner

    provider = MagicMock()

    async def chat_with_retry(**kwargs):
        return LLMResponse(
            content="<think>Let me think about this...\nThe answer is 42.</think>The answer is 42.",
            tool_calls=[],
            usage={"prompt_tokens": 5, "completion_tokens": 3},
        )

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []

    hook = _RecordingHook()
    runner = AgentRunner(provider)
    result = await runner.run(AgentRunSpec(
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
    from nanobot.agent.runner import AgentRunSpec, AgentRunner

    provider = MagicMock()

    async def chat_with_retry(**kwargs):
        return LLMResponse(
            content="<think>inline thinking</think>The answer.",
            reasoning_content="dedicated reasoning field",
            tool_calls=[],
            usage={"prompt_tokens": 5, "completion_tokens": 3},
        )

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []

    hook = _RecordingHook()
    runner = AgentRunner(provider)
    result = await runner.run(AgentRunSpec(
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
    from nanobot.agent.runner import AgentRunSpec, AgentRunner

    provider = MagicMock()
    provider.supports_progress_deltas = True

    async def chat_stream_with_retry(*, on_content_delta=None, **kwargs):
        if on_content_delta:
            await on_content_delta("The ")
            await on_content_delta("answer.")
        return LLMResponse(
            content="The answer.",
            reasoning_content="step-by-step deduction",
            tool_calls=[],
            usage={"prompt_tokens": 5, "completion_tokens": 3},
        )

    provider.chat_stream_with_retry = chat_stream_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []

    progress_calls: list[str] = []

    async def _progress(content: str, **_kwargs):
        progress_calls.append(content)

    hook = _RecordingHook()
    runner = AgentRunner(provider)
    result = await runner.run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "question"}],
        tools=tools,
        model="test-model",
        max_iterations=3,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        hook=hook,
        stream_progress_deltas=True,
        progress_callback=_progress,
    ))

    assert result.final_content == "The answer."
    assert progress_calls, "answer should have streamed via progress callback"
    assert hook.emitted == ["step-by-step deduction"]


@pytest.mark.asyncio
async def test_runner_does_not_double_emit_when_inline_think_already_streamed():
    """Inline `<think>` blocks streamed incrementally during the answer
    stream must not be re-emitted from the final response."""
    from nanobot.agent.runner import AgentRunSpec, AgentRunner

    provider = MagicMock()
    provider.supports_progress_deltas = True

    async def chat_stream_with_retry(*, on_content_delta=None, **kwargs):
        if on_content_delta:
            await on_content_delta("<think>working...</think>")
            await on_content_delta("The answer.")
        return LLMResponse(
            content="<think>working...</think>The answer.",
            tool_calls=[],
            usage={"prompt_tokens": 5, "completion_tokens": 3},
        )

    provider.chat_stream_with_retry = chat_stream_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []

    async def _progress(content: str, **_kwargs):
        pass

    hook = _RecordingHook()
    runner = AgentRunner(provider)
    result = await runner.run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "question"}],
        tools=tools,
        model="test-model",
        max_iterations=3,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        hook=hook,
        stream_progress_deltas=True,
        progress_callback=_progress,
    ))

    assert result.final_content == "The answer."
    assert hook.emitted == ["working..."]
    assert hook.end_calls >= 1, "reasoning stream must be closed once the answer starts"


@pytest.mark.asyncio
async def test_runner_closes_reasoning_stream_after_one_shot_response():
    """A non-streaming response carrying ``reasoning_content`` must emit
    both a reasoning delta and an end marker so channels can finalize the
    in-place bubble."""
    from nanobot.agent.runner import AgentRunSpec, AgentRunner

    provider = MagicMock()

    async def chat_with_retry(**kwargs):
        return LLMResponse(
            content="answer",
            reasoning_content="hidden thought",
            tool_calls=[],
            usage={"prompt_tokens": 5, "completion_tokens": 3},
        )

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []

    hook = _RecordingHook()
    runner = AgentRunner(provider)
    result = await runner.run(AgentRunSpec(
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
