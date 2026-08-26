"""Tests for core AgentRunner behavior: message passing, iteration limits,
timeouts, empty-response handling, usage accumulation, and config passthrough."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.runner_helpers import make_run_spec
from nanobot.config.schema import AgentDefaults
from nanobot.providers.base import (
    LLMProvider,
    LLMResponse,
    LLMUsage,
    ProviderCallContext,
    ProviderConversationState,
    ToolCallRequest,
)

_MAX_TOOL_RESULT_CHARS = AgentDefaults().max_tool_result_chars


def _make_usage_spec(provider, tools):
    return make_run_spec(
        provider,
        initial_messages=[{"role": "user", "content": "hello"}],
        tools=tools,
        model="test-model",
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    )


def test_usage_or_estimate_replaces_reported_zero_for_content(monkeypatch) -> None:
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)
    tools = MagicMock()
    tools.get_definitions.return_value = []
    monkeypatch.setattr(
        "nanobot.agent.runner.estimate_prompt_tokens_chain",
        lambda provider, model, messages, definitions: (12, "test"),
    )
    monkeypatch.setattr("nanobot.agent.runner.estimate_message_tokens", lambda message: 7)
    response = LLMResponse(
        content="answer",
        usage=LLMUsage.reported(input_tokens=0, output_tokens=0),
        generation_ms=25,
        ttft_ms=5,
    )

    usage = AgentRunner()._usage_or_estimate(
        _make_usage_spec(provider, tools),
        [{"role": "user", "content": "hello"}],
        response,
    )

    assert usage == LLMUsage.estimated(input_tokens=12, output_tokens=7).with_timing(
        generation_ms=25,
        ttft_ms=5,
    )
    assert usage.source == "estimated"
    assert usage.total_tokens == 19


def test_usage_or_estimate_counts_tool_call_output_for_reported_zero(monkeypatch) -> None:
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)
    tools = MagicMock()
    tools.get_definitions.return_value = []
    captured_message: dict = {}
    monkeypatch.setattr(
        "nanobot.agent.runner.estimate_prompt_tokens_chain",
        lambda provider, model, messages, definitions: (13, "test"),
    )

    def estimate_output(message):
        captured_message.update(message)
        return 9

    monkeypatch.setattr("nanobot.agent.runner.estimate_message_tokens", estimate_output)
    response = LLMResponse(
        content=None,
        tool_calls=[
            ToolCallRequest(
                id="call_1",
                name="lookup",
                arguments={"query": "nanobot"},
            )
        ],
        finish_reason="tool_calls",
        usage=LLMUsage.reported(input_tokens=0, output_tokens=0),
    )

    usage = AgentRunner()._usage_or_estimate(
        _make_usage_spec(provider, tools),
        [{"role": "user", "content": "hello"}],
        response,
    )

    assert usage == LLMUsage.estimated(input_tokens=13, output_tokens=9)
    assert usage.total_tokens == 22
    assert captured_message["tool_calls"][0]["function"]["name"] == "lookup"


@pytest.mark.parametrize(
    "provider_usage",
    [None, LLMUsage.reported(input_tokens=0, output_tokens=0)],
)
def test_usage_or_estimate_counts_error_without_estimating_tokens(
    monkeypatch,
    provider_usage: LLMUsage | None,
) -> None:
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)
    tools = MagicMock()
    estimate = MagicMock()
    runner = AgentRunner()
    monkeypatch.setattr(runner, "_estimate_response_usage", estimate)
    response = LLMResponse(
        content="upstream failed",
        finish_reason="error",
        usage=provider_usage,
    )

    usage = runner._usage_or_estimate(
        _make_usage_spec(provider, tools),
        [{"role": "user", "content": "hello"}],
        response,
    )

    assert usage is not None
    assert usage.total_tokens == 0
    assert usage.request_count == 1
    assert usage.context_tokens is None
    aggregate = LLMUsage.reported(input_tokens=12, output_tokens=3) + usage
    assert aggregate.context_tokens == 12
    assert aggregate.request_count == 2
    estimate.assert_not_called()


def test_usage_or_estimate_trusts_positive_reported_total(monkeypatch) -> None:
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)
    tools = MagicMock()
    estimate = MagicMock()
    runner = AgentRunner()
    monkeypatch.setattr(runner, "_estimate_response_usage", estimate)
    response = LLMResponse(
        content="answer",
        usage=LLMUsage.reported(
            input_tokens=15,
            output_tokens=18,
            total_tokens=175,
        ),
        generation_ms=30,
        ttft_ms=6,
    )

    usage = runner._usage_or_estimate(
        _make_usage_spec(provider, tools),
        [{"role": "user", "content": "hello"}],
        response,
    )

    assert usage is not None
    assert usage.source == "reported"
    assert usage.input_tokens == 15
    assert usage.output_tokens == 18
    assert usage.total_tokens == 175
    assert usage.reported_tokens == 175
    assert usage.generation_ms == 30
    assert usage.ttft_ms == 6
    estimate.assert_not_called()


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
async def test_runner_replays_provider_state_without_chat_projection_duplicates():
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)
    provider.can_resume_conversation_state.return_value = True
    provider.supports_native_compaction.return_value = False
    captured_second_kwargs: dict = {}
    checkpoints: list[dict] = []
    calls = 0

    async def checkpoint(payload: dict) -> None:
        checkpoints.append(payload)

    first_state = ProviderConversationState(
        kind="openai_responses",
        provider="openai:test",
        model="gpt-5.6",
        version=1,
        payload={"items": [{"type": "reasoning", "encrypted_content": "opaque"}]},
    )
    second_state = ProviderConversationState(
        kind="openai_responses",
        provider="openai:test",
        model="gpt-5.6",
        version=1,
        payload={"items": [{"type": "message", "role": "assistant"}]},
    )

    async def chat_with_retry(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            provider_context = kwargs["provider_context"]
            assert isinstance(provider_context, ProviderCallContext)
            assert provider_context.conversation_state is None
            return LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(
                        id="call_1|fc_1",
                        name="list_dir",
                        arguments={"path": "."},
                    ),
                ],
                provider_state=first_state,
            )
        captured_second_kwargs.update(kwargs)
        return LLMResponse(content="done", provider_state=second_state)

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(return_value="tool result")

    result = await AgentRunner().run(make_run_spec(
        provider,
        initial_messages=[
            {"role": "system", "content": "system"},
            {"role": "user", "content": "do task"},
        ],
        tools=tools,
        model="gpt-5.6",
        max_iterations=3,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        checkpoint_callback=checkpoint,
    ))

    provider_context = captured_second_kwargs["provider_context"]
    assert isinstance(provider_context, ProviderCallContext)
    assert provider_context.conversation_state is not None
    assert provider_context.conversation_state.payload == first_state.payload
    assert provider_context.conversation_state.pending_messages == [{
        "role": "tool",
        "tool_call_id": "call_1|fc_1",
        "name": "list_dir",
        "content": "tool result",
    }]
    assert not any(
        message.get("role") == "assistant"
        for message in provider_context.conversation_state.pending_messages
    )
    assert result.provider_state is not None
    assert result.provider_state.payload == second_state.payload
    assert result.provider_state.pending_messages == []
    assert checkpoints[0]["phase"] == "awaiting_tools"
    assert "provider_state" not in checkpoints[0]
    assert checkpoints[1]["phase"] == "tools_completed"
    assert checkpoints[1]["provider_state"].pending_messages == [{
        "role": "tool",
        "tool_call_id": "call_1|fc_1",
        "name": "list_dir",
        "content": "tool result",
    }]
    assert checkpoints[2]["phase"] == "final_response"
    assert checkpoints[2]["provider_state"].payload == second_state.payload


@pytest.mark.asyncio
async def test_runner_governs_tool_result_before_adding_it_to_provider_state():
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)
    provider.can_resume_conversation_state.return_value = True
    provider.supports_native_compaction.return_value = False
    calls = 0
    captured_context: ProviderCallContext | None = None
    checkpoints: list[dict] = []
    state = ProviderConversationState(
        kind="openai_responses",
        provider="openai:test",
        model="gpt-5.6",
        version=1,
        payload={"items": [{"type": "reasoning", "encrypted_content": "opaque"}]},
    )

    async def chat_with_retry(**kwargs):
        nonlocal calls, captured_context
        calls += 1
        if calls == 1:
            return LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(
                        id="call_1",
                        name="read_file",
                        arguments={"path": "large.txt"},
                    ),
                ],
                provider_state=state,
            )
        captured_context = kwargs["provider_context"]
        return LLMResponse(content="done")

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(return_value="x" * 5_000)

    async def checkpoint(payload: dict) -> None:
        checkpoints.append(payload)

    await AgentRunner().run(make_run_spec(
        provider,
        initial_messages=[
            {"role": "system", "content": "system"},
            {"role": "user", "content": "read the file"},
        ],
        tools=tools,
        model="gpt-5.6",
        context_window_tokens=3_000,
        context_block_limit=200,
        max_tokens=1_000,
        max_iterations=3,
        max_tool_result_chars=10_000,
        checkpoint_callback=checkpoint,
    ))

    assert captured_context is not None
    assert captured_context.conversation_state is not None
    pending = captured_context.conversation_state.pending_messages
    assert len(pending) == 1
    assert pending[0]["role"] == "tool"
    assert "compacted to fit context" in pending[0]["content"]
    assert pending[0]["content"] != "x" * 5_000
    completed_checkpoint = next(
        checkpoint
        for checkpoint in checkpoints
        if checkpoint["phase"] == "tools_completed"
    )
    checkpoint_pending = completed_checkpoint["provider_state"].pending_messages
    assert "compacted to fit context" in checkpoint_pending[0]["content"]
    assert checkpoint_pending[0]["content"] != "x" * 5_000


@pytest.mark.asyncio
async def test_injected_final_response_checkpoint_includes_provider_state():
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)
    provider.can_resume_conversation_state.return_value = True
    provider.supports_native_compaction.return_value = False
    first_state = ProviderConversationState(
        kind="openai_responses",
        provider="openai:test",
        model="gpt-5.6",
        version=1,
        payload={"items": [{"type": "message", "content": "first answer"}]},
    )
    second_state = ProviderConversationState(
        kind="openai_responses",
        provider="openai:test",
        model="gpt-5.6",
        version=1,
        payload={"items": [{"type": "message", "content": "second answer"}]},
    )
    provider.chat_with_retry = AsyncMock(side_effect=[
        LLMResponse(content="first answer", provider_state=first_state),
        LLMResponse(content="second answer", provider_state=second_state),
    ])
    tools = MagicMock()
    tools.get_definitions.return_value = []
    checkpoints: list[dict] = []
    injections = [[{"role": "user", "content": "follow up"}], []]

    async def checkpoint(payload: dict) -> None:
        checkpoints.append(payload)

    async def inject() -> list[dict]:
        return injections.pop(0)

    await AgentRunner().run(make_run_spec(
        provider,
        initial_messages=[{"role": "user", "content": "start"}],
        tools=tools,
        model="gpt-5.6",
        max_iterations=3,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        checkpoint_callback=checkpoint,
        injection_callback=inject,
    ))

    assert checkpoints[0]["phase"] == "final_response"
    assert checkpoints[0]["provider_state"].payload == first_state.payload


@pytest.mark.asyncio
async def test_runner_preserves_last_completed_provider_state_on_model_error():
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)
    provider.can_resume_conversation_state.return_value = True
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content="temporary upstream failure",
        finish_reason="error",
        error_kind="timeout",
    ))
    tools = MagicMock()
    tools.get_definitions.return_value = []
    state = ProviderConversationState(
        kind="openai_responses",
        provider="openai:test",
        model="gpt-5.6",
        version=1,
        payload={"items": [{"type": "reasoning", "encrypted_content": "opaque"}]},
    )
    unsaved_input = {"role": "user", "content": "ephemeral follow-up"}

    result = await AgentRunner().run(make_run_spec(
        provider,
        initial_messages=[
            {"role": "system", "content": "system"},
            unsaved_input,
        ],
        tools=tools,
        model="gpt-5.6",
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        provider_state=state.with_pending_messages([unsaved_input]),
    ))

    assert result.stop_reason == "error"
    assert result.provider_state is not None
    assert result.provider_state.payload == state.payload
    assert result.provider_state.pending_messages[0] == unsaved_input
    assert result.provider_state.pending_messages[1]["role"] == "assistant"
    assert "model error" in result.provider_state.pending_messages[1]["content"]


@pytest.mark.asyncio
async def test_runner_discards_provider_state_on_non_retryable_model_error():
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)
    provider.can_resume_conversation_state.return_value = True
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content="context length exceeded",
        finish_reason="error",
        error_status_code=400,
        error_should_retry=False,
    ))
    tools = MagicMock()
    tools.get_definitions.return_value = []
    state = ProviderConversationState(
        kind="openai_responses",
        provider="openai:test",
        model="gpt-5.6",
        version=1,
        payload={"items": [{"type": "reasoning", "encrypted_content": "opaque"}]},
    )

    result = await AgentRunner().run(make_run_spec(
        provider,
        initial_messages=[{"role": "user", "content": "continue"}],
        tools=tools,
        model="gpt-5.6",
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        provider_state=state,
    ))

    assert result.stop_reason == "error"
    assert result.provider_state is None


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
            usage=LLMUsage.reported(input_tokens=10, output_tokens=7),
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
async def test_runner_times_out_hung_max_iteration_finalization():
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock()
    calls = 0

    async def chat_with_retry(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return LLMResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        id="call_1",
                        name="probe",
                        arguments={},
                    )
                ],
                finish_reason="tool_calls",
            )
        await asyncio.Event().wait()

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(return_value="ok")

    result = await asyncio.wait_for(
        AgentRunner().run(make_run_spec(
            provider,
            initial_messages=[{"role": "user", "content": "run the probe"}],
            tools=tools,
            model="test-model",
            max_iterations=1,
            max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
            max_iterations_message="fallback after {max_iterations} iteration",
            llm_timeout_s=0.01,
        )),
        timeout=1.0,
    )

    assert calls == 2
    assert result.stop_reason == "max_iterations"
    assert result.error is None
    assert result.final_content == "fallback after 1 iteration"


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
                usage=None,
            )
        captured_second_call[:] = messages
        return LLMResponse(content="done", tool_calls=[], usage=None)

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
                usage=LLMUsage.reported(input_tokens=5, output_tokens=1),
            )
        return LLMResponse(
            content="final answer",
            tool_calls=[],
            usage=LLMUsage.reported(input_tokens=3, output_tokens=7),
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
    assert result.usage is not None
    assert result.usage.input_tokens == 13
    assert result.usage.output_tokens == 9


@pytest.mark.asyncio
@pytest.mark.parametrize("finish_reason", ["refusal", "content_filter"])
async def test_runner_does_not_retry_blank_policy_terminal(
    finish_reason: str,
) -> None:
    from nanobot.agent.runner import AgentRunner
    from nanobot.utils.runtime import EMPTY_FINAL_RESPONSE_MESSAGE

    provider = MagicMock(spec=LLMProvider)
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content=None,
        finish_reason=finish_reason,
    ))
    tools = MagicMock()
    tools.get_definitions.return_value = []

    result = await AgentRunner().run(make_run_spec(
        provider,
        initial_messages=[{"role": "user", "content": "do task"}],
        tools=tools,
        model="test-model",
        max_iterations=3,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    assert provider.chat_with_retry.await_count == 1
    assert result.final_content == EMPTY_FINAL_RESPONSE_MESSAGE
    assert result.stop_reason == "empty_final_response"


@pytest.mark.asyncio
@pytest.mark.parametrize("finish_reason", ["refusal", "content_filter"])
async def test_runner_does_not_auto_continue_goal_after_policy_terminal(
    finish_reason: str,
) -> None:
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content="Request blocked by provider policy.",
        finish_reason=finish_reason,
    ))
    tools = MagicMock()
    tools.get_definitions.return_value = []
    terminal_injection_callback = AsyncMock(return_value=[])

    result = await AgentRunner().run(make_run_spec(
        provider,
        initial_messages=[{"role": "user", "content": "do task"}],
        tools=tools,
        model="test-model",
        max_iterations=3,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        continuation_callback=lambda: "Continue working.",
        terminal_injection_callback=terminal_injection_callback,
    ))

    assert provider.chat_with_retry.await_count == 1
    terminal_injection_callback.assert_not_awaited()
    assert result.final_content == "Request blocked by provider policy."
    assert result.stop_reason == "completed"


@pytest.mark.asyncio
async def test_runner_uses_specific_message_after_empty_finalization_retry():
    """After silent retries + finalization all return empty, stop_reason is empty_final_response."""
    from nanobot.agent.runner import AgentRunner
    from nanobot.utils.runtime import EMPTY_FINAL_RESPONSE_MESSAGE

    provider = MagicMock(spec=LLMProvider)

    async def chat_with_retry(*, messages, **kwargs):
        return LLMResponse(content=None, tool_calls=[], usage=None)

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
async def test_empty_finalization_retry_discards_candidate_provider_state():
    from nanobot.agent.runner import AgentRunner

    candidate = ProviderConversationState(
        kind="openai_responses",
        provider="openai:test",
        model="test-model",
        version=1,
        payload={
            "items": [{
                "type": "function_call",
                "call_id": "call_1",
                "name": "exec",
                "arguments": "{}",
            }],
        },
    )
    provider = MagicMock(spec=LLMProvider)
    provider.can_resume_conversation_state.return_value = True
    provider.chat_with_retry = AsyncMock(side_effect=[
        LLMResponse(content=None, tool_calls=[], usage=None),
        LLMResponse(content=None, tool_calls=[], usage=None),
        LLMResponse(
            content="finalized without tools",
            tool_calls=[ToolCallRequest(id="call_1", name="exec", arguments={})],
            finish_reason="stop",
            provider_state=candidate,
            usage=None,
        ),
    ])
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(return_value="must not run")

    runner = AgentRunner()
    result = await runner.run(make_run_spec(
        provider,
        initial_messages=[{"role": "user", "content": "do task"}],
        tools=tools,
        model="test-model",
        max_iterations=3,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    tools.execute.assert_not_awaited()
    assert result.final_content == "finalized without tools"
    assert result.provider_state is None


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
async def test_runner_length_recovery_preserves_prefix_at_max_iterations():
    """Budget exhaustion must not replace output already produced by recovery."""
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)
    provider.chat_with_retry = AsyncMock(
        return_value=LLMResponse(content="partial answer", finish_reason="length")
    )
    tools = MagicMock()
    tools.get_definitions.return_value = []

    runner = AgentRunner()
    result = await runner.run(make_run_spec(
        provider,
        initial_messages=[{"role": "user", "content": "give a long answer"}],
        tools=tools,
        model="test-model",
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        finalize_on_max_iterations=False,
        max_iterations_message="limit reached",
    ))

    assert result.stop_reason == "max_iterations"
    assert result.final_content == "partial answer\n\nlimit reached"
    assert result.pending_stream_content == "\n\nlimit reached"
    assert [
        message["content"]
        for message in result.messages
        if message.get("role") == "assistant"
    ] == ["partial answer", "limit reached"]


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
                usage=LLMUsage.reported(input_tokens=10, output_tokens=5),
            )
        if call_count == 2:
            return LLMResponse(content=None, tool_calls=[], usage=LLMUsage.reported(input_tokens=10, output_tokens=1))
        if call_count == 3:
            return LLMResponse(
                content=None,
                tool_calls=[ToolCallRequest(id="tc2", name="read_file", arguments={"path": "b.txt"})],
                usage=LLMUsage.reported(input_tokens=10, output_tokens=5),
            )
        return LLMResponse(
            content="Here are the results.",
            tool_calls=[],
            usage=LLMUsage.reported(input_tokens=10, output_tokens=10),
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
async def test_runner_accumulates_usage_and_preserves_cache_reads():
    """Runner accumulates usage across iterations, including cache reads."""
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)
    call_count = {"n": 0}

    async def chat_with_retry(*, messages, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return LLMResponse(
                content="thinking",
                tool_calls=[ToolCallRequest(id="call_1", name="read_file", arguments={"path": "x"})],
                usage=LLMUsage.reported(input_tokens=100, output_tokens=10, cache_read_tokens=80),
            )
        return LLMResponse(
            content="done",
            tool_calls=[],
            usage=LLMUsage.reported(input_tokens=200, output_tokens=20, cache_read_tokens=150),
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
    assert result.usage is not None
    assert result.usage.input_tokens == 300  # 100 + 200
    assert result.usage.output_tokens == 30  # 10 + 20
    assert result.usage.cache_read_tokens == 230  # 80 + 150
    assert result.usage.context_tokens == 200
    assert result.usage.request_count == 2


@pytest.mark.asyncio
async def test_runner_binds_on_retry_wait_callback():
    """Provider retry heartbeats use the explicitly supplied callback."""
    from nanobot.agent.runner import AgentRunner

    captured: dict = {}

    async def chat_with_retry(**kwargs):
        captured.update(kwargs)
        return LLMResponse(content="done", tool_calls=[], usage=None)

    provider = MagicMock(spec=LLMProvider)
    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []

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
        retry_wait_callback=retry_wait_cb,
    ))

    assert captured["on_retry_wait"] is retry_wait_cb


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
        return LLMResponse(content="done", tool_calls=[], usage=None)

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
        return LLMResponse(content="done", tool_calls=[], usage=None)

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
        return LLMResponse(content="done", tool_calls=[], usage=None)

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
