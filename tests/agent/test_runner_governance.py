"""Tests for AgentRunner context governance, repair, and compaction."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.runner_helpers import make_run_spec
from nanobot.agent.context import TranscriptInput
from nanobot.agent.context_governance import (
    BACKFILL_CONTENT,
    ContextCompactionState,
    ContextGovernanceConfig,
    ContextGovernor,
    ContextWindowExceededError,
    ModelRequestState,
)
from nanobot.agent.runner import AgentRunner, AgentRunSpec
from nanobot.config.schema import AgentDefaults
from nanobot.events import ContextCompactionEvent, EventSink
from nanobot.providers.base import (
    LLMProvider,
    LLMResponse,
    LLMUsage,
    ProviderConversationState,
    ToolCallRequest,
)
from nanobot.providers.conversation_state import ProviderConversationStateController
from nanobot.session.summary import SUMMARY_CONTINUATION_TEXT

_MAX_TOOL_RESULT_CHARS = AgentDefaults().max_tool_result_chars


def _build_transcript(transcript: TranscriptInput) -> list[dict]:
    system = (
        transcript.session_summary["text"]
        if transcript.session_summary is not None
        else "system"
    )
    messages = [{"role": "system", "content": system}, *transcript.history]
    if transcript.current_message is not None:
        messages.append({"role": transcript.current_role, "content": transcript.current_message})
    return messages


def _governance_config(
    provider,
    tools,
    spec: AgentRunSpec,
) -> ContextGovernanceConfig:
    return ContextGovernanceConfig(
        provider=provider,
        model=spec.runtime.model,
        tools=tools,
        workspace=spec.workspace,
        session_key=spec.session_key,
        max_tool_result_chars=spec.max_tool_result_chars,
        context_window_tokens=spec.runtime.context_window_tokens,
        max_tokens=spec.runtime.generation.max_tokens,
    )


def _compaction_state(spec: AgentRunSpec) -> ContextCompactionState:
    assert spec.initial_messages is not None
    return ContextCompactionState.from_messages(
        spec.initial_messages,
        spec.consolidate_history,
        spec.consolidate_provider_compaction,
    )


def _make_loop(tmp_path):
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    with patch("nanobot.agent.loop.ContextBuilder"), \
         patch("nanobot.agent.loop.SessionManager"), \
         patch("nanobot.agent.loop.SubagentManager") as mock_sub_mgr:
        mock_sub_mgr.return_value.cancel_by_session = AsyncMock(return_value=0)
        loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path)
    return loop


async def test_provider_can_emit_without_an_event_specific_runner_callback():
    from nanobot.events import AgentEvent

    event = AgentEvent()
    received = []

    async def observe(value):
        received.append(value)

    async def request(*, provider_context, **kwargs):
        await provider_context.events.emit(event)
        return LLMResponse(content="done")

    provider = MagicMock(spec=LLMProvider)
    provider.chat_stream_with_retry = request
    tools = MagicMock()
    tools.get_definitions.return_value = []
    await AgentRunner().run(make_run_spec(
        provider, model="test-model", tools=tools, max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        initial_messages=[{"role": "user", "content": "hello"}],
        events=EventSink(observe),
    ))
    assert received == [event]


async def test_runner_propagates_context_governance_failure():
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock()
    provider.chat_stream_with_retry = AsyncMock()
    tools = MagicMock()
    tools.get_definitions.return_value = []
    initial_messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "hello"},
    ]

    runner = AgentRunner()
    runner.context_governor.prepare_for_model = MagicMock(  # type: ignore[method-assign]
        side_effect=RuntimeError("boom")
    )
    with pytest.raises(RuntimeError, match="boom"):
        await runner.run(make_run_spec(provider,
            initial_messages=initial_messages,
            tools=tools,
            model="test-model",
            max_iterations=1,
            max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        ))

    provider.chat_stream_with_retry.assert_not_awaited()


async def test_runner_summarizes_history_and_preserves_current_input(monkeypatch):
    provider = MagicMock(spec=LLMProvider)
    provider.can_resume_conversation_state.return_value = True
    prior_state = ProviderConversationState(
        kind="openai_responses",
        provider="openai:test",
        model="test-model",
        version=1,
        payload={"items": [{"type": "message", "role": "assistant"}]},
    )
    candidate_state = ProviderConversationState(
        kind="openai_responses",
        provider="openai:test",
        model="test-model",
        version=1,
        payload={"items": [{"type": "message", "role": "assistant", "fresh": True}]},
    )
    requests: list[tuple[list[dict], object]] = []

    async def request(*, messages, provider_context, **_kwargs):
        requests.append((messages, provider_context))
        return LLMResponse(content="done", provider_state=candidate_state)

    provider.chat_stream_with_retry = request
    tools = MagicMock()
    tools.get_definitions.return_value = []
    old_answer = "old answer " * 2_000
    monkeypatch.setattr(
        "nanobot.agent.context_governance.estimate_prompt_tokens_chain",
        lambda _provider, _model, messages, _tools: (
            (600, "test-counter")
            if any(message.get("content") == old_answer for message in messages)
            else (100, "test-counter")
        ),
    )
    consolidate = AsyncMock(return_value="fresh checkpoint")
    previous = {"text": "existing checkpoint", "last_active": "2026-08-30T00:00:00"}

    result = await AgentRunner().run(make_run_spec(
        provider,
        initial_messages=None,
        transcript_input=TranscriptInput(
            history=[
                {"role": "user", "content": "old question"},
                {"role": "assistant", "content": old_answer},
            ],
            current_message="continue the current task",
            session_summary=previous,
        ),
        transcript_builder=_build_transcript,
        consolidate_history=consolidate,
        provider_state=prior_state,
        tools=tools,
        model="test-model",
        context_window_tokens=1_624,
        max_tokens=100,
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    consolidate.assert_awaited_once_with(
        [
            {"role": "system", "content": "existing checkpoint"},
            {"role": "user", "content": "old question"},
            {"role": "assistant", "content": old_answer},
        ],
        "existing checkpoint",
    )
    assert requests[0][0] == [
        {"role": "system", "content": "fresh checkpoint"},
        {"role": "user", "content": "continue the current task"},
    ]
    assert requests[0][1].conversation_state is None
    assert result.provider_state == candidate_state
    assert result.summary_checkpoint is not None
    assert result.summary_checkpoint.summary == "fresh checkpoint"
    assert result.summary_checkpoint.transcript_boundary == 3
    assert any(message.get("content") == old_answer for message in result.messages)


async def test_runner_rejects_oversized_delta_without_summarizable_history(monkeypatch):
    provider = MagicMock(spec=LLMProvider)
    provider.chat_stream_with_retry = AsyncMock()
    tools = MagicMock()
    tools.get_definitions.return_value = []
    monkeypatch.setattr(
        "nanobot.agent.context_governance.estimate_prompt_tokens_chain",
        lambda *_args, **_kwargs: (600, "test-counter"),
    )
    consolidate = AsyncMock(return_value=None)

    with pytest.raises(ContextWindowExceededError):
        await AgentRunner().run(make_run_spec(
            provider,
            initial_messages=None,
            transcript_input=TranscriptInput(
                history=[],
                current_message="current input is the entire oversized delta",
            ),
            transcript_builder=_build_transcript,
            consolidate_history=consolidate,
            tools=tools,
            model="test-model",
            context_window_tokens=1_624,
            max_tokens=100,
            max_iterations=1,
            max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        ))

    consolidate.assert_awaited_once_with(
        [{"role": "system", "content": "system"}],
        None,
    )
    provider.chat_stream_with_retry.assert_not_awaited()


async def test_runner_governs_history_before_summarizing_it(monkeypatch):
    provider = MagicMock(spec=LLMProvider)
    provider.can_resume_conversation_state.return_value = False
    provider.chat_stream_with_retry = AsyncMock(return_value=LLMResponse(content="done"))
    tools = MagicMock()
    tools.get_definitions.return_value = []
    monkeypatch.setattr(
        "nanobot.agent.context_governance.estimate_prompt_tokens_chain",
        lambda _provider, _model, messages, _tools: (
            (100, "test-counter")
            if messages[0].get("content") == "fresh checkpoint"
            else (600, "test-counter")
        ),
    )
    consolidate = AsyncMock(return_value="fresh checkpoint")

    await AgentRunner().run(make_run_spec(
        provider,
        initial_messages=None,
        transcript_input=TranscriptInput(
            history=[
                {"role": "user", "content": "inspect"},
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{
                        "id": "call-missing",
                        "type": "function",
                        "function": {"name": "inspect", "arguments": "{}"},
                    }],
                },
            ],
            current_message="continue",
        ),
        transcript_builder=_build_transcript,
        consolidate_history=consolidate,
        tools=tools,
        model="test-model",
        context_window_tokens=1_624,
        max_tokens=100,
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    summarized = consolidate.await_args.args[0]
    assert [message["role"] for message in summarized] == [
        "system", "user", "assistant", "tool",
    ]
    assert summarized[-1]["tool_call_id"] == "call-missing"
    assert summarized[-1]["content"] == BACKFILL_CONTENT


@pytest.mark.parametrize(
    ("scope", "expected_contents", "expected_boundary"),
    [
        ("prior_context", ["system", "accepted question", "accepted answer"], 3),
        (
            "current_request",
            ["system", "accepted question", "accepted answer", "inspect the project"],
            4,
        ),
    ],
)
async def test_native_compaction_uses_provider_request_boundary(
    monkeypatch,
    scope,
    expected_contents,
    expected_boundary,
):
    provider = MagicMock(spec=LLMProvider)
    provider.can_resume_conversation_state.return_value = False
    compacted_state = ProviderConversationState(
        kind="openai_responses",
        provider="openai:test",
        model="test-model",
        version=1,
        payload={"items": [{"type": "compaction", "encrypted_content": "opaque"}]},
    )
    provider.chat_stream_with_retry = AsyncMock(side_effect=[
        LLMResponse(
            content=None,
            tool_calls=[ToolCallRequest(id="call-1", name="inspect", arguments={})],
            provider_compaction_applied=True,
            provider_compaction_state=compacted_state,
            provider_compaction_scope=scope,
        ),
        LLMResponse(content="done"),
    ])
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(return_value="complete tool result")
    monkeypatch.setattr(
        "nanobot.agent.context_governance.estimate_prompt_tokens_chain",
        lambda *_args: (100, "test-counter"),
    )
    consolidate = AsyncMock(return_value="portable checkpoint")
    consolidate_native = AsyncMock(
        return_value="portable checkpoint"
    )
    compaction_events: list[ContextCompactionEvent] = []

    async def observe_compaction(event: ContextCompactionEvent) -> None:
        compaction_events.append(event)

    result = await AgentRunner().run(make_run_spec(
        provider,
        initial_messages=None,
        transcript_input=TranscriptInput(
            history=[
                {"role": "user", "content": "accepted question"},
                {"role": "assistant", "content": "accepted answer"},
            ],
            current_message="inspect the project",
        ),
        transcript_builder=_build_transcript,
        consolidate_history=consolidate,
        consolidate_provider_compaction=consolidate_native,
        tools=tools,
        model="test-model",
        context_window_tokens=1_624,
        max_tokens=100,
        max_iterations=2,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        events=EventSink(observe_compaction),
    ))

    consolidate.assert_not_awaited()
    consolidate_native.assert_awaited_once()
    assert consolidate_native.await_args.args[0] == compacted_state
    assert [
        message["content"] for message in consolidate_native.await_args.args[1]
    ] == expected_contents
    assert consolidate_native.await_args.args[2] is None
    assert result.summary_checkpoint is not None
    assert result.summary_checkpoint.transcript_boundary == expected_boundary
    assert result.provider_compaction_applied is True
    assert any(message.get("content") == "inspect the project" for message in result.messages)
    assert any(message.get("content") == "complete tool result" for message in result.messages)
    assert [event.phase for event in compaction_events] == ["started", "succeeded"]
    assert {event.compaction_id for event in compaction_events} == {
        compaction_events[0].compaction_id
    }


async def test_runner_keeps_current_tool_exchange_outside_summary(monkeypatch):
    provider = MagicMock(spec=LLMProvider)
    provider.can_resume_conversation_state.return_value = False
    responses = [
        LLMResponse(
            content=None,
            tool_calls=[ToolCallRequest(id="call-1", name="inspect", arguments={})],
        ),
        LLMResponse(content="done"),
    ]
    requests: list[list[dict]] = []

    async def request(*, messages, **_kwargs):
        requests.append(messages)
        return responses.pop(0)

    provider.chat_stream_with_retry = request
    tools = MagicMock()
    tools.get_definitions.return_value = []
    full_result = "tool-result:" + ("x" * 4_000)
    tools.execute = AsyncMock(return_value=full_result)

    def estimate(_provider, _model, messages, _tools):
        has_tool_result = any(message.get("role") == "tool" for message in messages)
        has_old_system = any(
            message.get("role") == "system" and message.get("content") == "system"
            for message in messages
        )
        return (600 if has_tool_result and has_old_system else 100, "test-counter")

    monkeypatch.setattr(
        "nanobot.agent.context_governance.estimate_prompt_tokens_chain",
        estimate,
    )
    consolidate = AsyncMock(return_value="fresh checkpoint")

    result = await AgentRunner().run(make_run_spec(
        provider,
        initial_messages=None,
        transcript_input=TranscriptInput(history=[], current_message="inspect the project"),
        transcript_builder=_build_transcript,
        consolidate_history=consolidate,
        tools=tools,
        model="test-model",
        context_window_tokens=1_624,
        max_tokens=100,
        max_iterations=2,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    consolidate.assert_awaited_once_with(
        [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "inspect the project"},
        ],
        None,
    )
    assert [message["role"] for message in requests[1]] == [
        "system", "user", "assistant", "tool",
    ]
    assert requests[1][1]["content"] == SUMMARY_CONTINUATION_TEXT
    assert requests[1][-1]["content"] == full_result
    assert result.summary_checkpoint is not None
    assert result.summary_checkpoint.transcript_boundary == 2
    assert any(message.get("content") == full_result for message in result.messages)


async def test_repeated_pressure_advances_summary_boundary(monkeypatch):
    provider = MagicMock(spec=LLMProvider)
    provider.can_resume_conversation_state.return_value = False
    provider.chat_stream_with_retry = AsyncMock(side_effect=[
        LLMResponse(
            content=None,
            tool_calls=[ToolCallRequest(id="call-1", name="inspect", arguments={})],
        ),
        LLMResponse(
            content=None,
            tool_calls=[ToolCallRequest(id="call-2", name="inspect", arguments={})],
        ),
        LLMResponse(content="done"),
    ])
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(side_effect=["result-1", "result-2"])

    def estimate(_provider, _model, messages, _tools):
        system = messages[0].get("content")
        contents = {message.get("content") for message in messages}
        if "result-2" in contents:
            return (100 if system == "checkpoint-2" else 600, "test-counter")
        if "result-1" in contents:
            return (100 if system == "checkpoint-1" else 600, "test-counter")
        return 100, "test-counter"

    monkeypatch.setattr(
        "nanobot.agent.context_governance.estimate_prompt_tokens_chain",
        estimate,
    )
    consolidate = AsyncMock(side_effect=[
        "checkpoint-1",
        "checkpoint-2",
    ])
    compaction_events: list[ContextCompactionEvent] = []

    async def observe_compaction(event: ContextCompactionEvent) -> None:
        compaction_events.append(event)

    result = await AgentRunner().run(make_run_spec(
        provider,
        initial_messages=None,
        transcript_input=TranscriptInput(history=[], current_message="inspect"),
        transcript_builder=_build_transcript,
        consolidate_history=consolidate,
        tools=tools,
        model="test-model",
        context_window_tokens=1_624,
        max_tokens=100,
        max_iterations=3,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        events=EventSink(observe_compaction),
    ))

    assert consolidate.await_count == 2
    assert consolidate.await_args_list[0].args[1] is None
    assert consolidate.await_args_list[1].args[1] == "checkpoint-1"
    second_prefix = consolidate.await_args_list[1].args[0]
    assert second_prefix[0]["content"] == "checkpoint-1"
    assert any(message.get("content") == "result-1" for message in second_prefix)
    assert result.final_content == "done"
    assert result.summary_checkpoint is not None
    assert result.summary_checkpoint.summary == "checkpoint-2"
    assert result.summary_checkpoint.transcript_boundary == 4
    assert [event.phase for event in compaction_events] == [
        "started", "succeeded", "started", "succeeded",
    ]
    first_id, second_id = compaction_events[0].compaction_id, compaction_events[2].compaction_id
    assert first_id == compaction_events[1].compaction_id
    assert second_id == compaction_events[3].compaction_id
    assert first_id != second_id


async def test_runner_refuses_checkpoint_that_cannot_fit_with_delta(monkeypatch):
    provider = MagicMock(spec=LLMProvider)
    provider.chat_stream_with_retry = AsyncMock(return_value=LLMResponse(content="unexpected"))
    tools = MagicMock()
    tools.get_definitions.return_value = []
    old_answer = "old answer"
    current_input = "current input must remain intact"

    def estimate(_provider, _model, messages, _tools):
        contents = {message.get("content") for message in messages}
        if old_answer in contents or current_input in contents:
            return 600, "test-counter"
        return 100, "test-counter"

    monkeypatch.setattr(
        "nanobot.agent.context_governance.estimate_prompt_tokens_chain",
        estimate,
    )
    consolidate = AsyncMock(return_value="small checkpoint")

    with pytest.raises(ContextWindowExceededError):
        await AgentRunner().run(make_run_spec(
            provider,
            initial_messages=None,
            transcript_input=TranscriptInput(
                history=[{"role": "assistant", "content": old_answer}],
                current_message=current_input,
            ),
            transcript_builder=_build_transcript,
            consolidate_history=consolidate,
            tools=tools,
            model="test-model",
            context_window_tokens=1_624,
            max_tokens=100,
            max_iterations=1,
            max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        ))

    summarized = consolidate.await_args.args[0]
    assert all(message.get("content") != current_input for message in summarized)
    provider.chat_stream_with_retry.assert_not_awaited()


@pytest.mark.parametrize("context_window, omitted_count", [(200_000, 1), (100_000, 2)])
async def test_runner_recovers_oversized_file_read_delta(
    tmp_path, monkeypatch, context_window, omitted_count,
):
    from nanobot.agent.tools.filesystem import ReadFileTool
    from nanobot.agent.tools.registry import ToolRegistry

    # A cold/offline tokenizer must exercise the same conservative count as #5879.
    monkeypatch.setattr(
        "nanobot.utils.helpers._get_token_encoding",
        MagicMock(side_effect=RuntimeError("tokenizer unavailable")),
    )
    paths = [tmp_path / f"result-{index}.json" for index in range(3)]
    for path in paths:
        path.write_text("record, " * 10_000, encoding="utf-8")
    tools = ToolRegistry()
    tools.register(ReadFileTool(workspace=tmp_path, allowed_dir=tmp_path))
    provider = MagicMock(spec=LLMProvider)
    provider.can_resume_conversation_state.return_value = True
    provider_state = ProviderConversationState(
        kind="openai_responses", provider="openai:test", model="test-model",
        version=1, payload={"items": []},
    )
    calls = [
        ToolCallRequest(id=f"read-{index}", name="read_file", arguments={
            "path": str(path), "limit": 20,
        })
        for index, path in enumerate(paths)
    ]
    # Retrying the omitted file alone must return its content, not "unchanged".
    provider.chat_stream_with_retry = AsyncMock(side_effect=[
        LLMResponse(content=None, tool_calls=calls, provider_state=provider_state),
        LLMResponse(content=None, tool_calls=[ToolCallRequest(
            id="reread", name="read_file", arguments=calls[0].arguments,
        )], provider_state=provider_state),
        LLMResponse(content="done"),
    ])
    consolidate = AsyncMock(return_value="small checkpoint")
    phases = []

    async def observe(event):
        if isinstance(event, ContextCompactionEvent):
            phases.append(event.phase)

    result = await AgentRunner().run(make_run_spec(
        provider, tools=tools, model="test-model", workspace=tmp_path,
        initial_messages=None,
        transcript_input=TranscriptInput(history=[], current_message="inspect the files"),
        transcript_builder=_build_transcript,
        consolidate_history=consolidate,
        context_window_tokens=context_window, max_tokens=8192, max_iterations=3,
        max_tool_result_chars=16_000, concurrent_tools=True,
        events=EventSink(observe),
    ))

    assert result.final_content == "done"
    requests = provider.chat_stream_with_retry.await_args_list
    delivered = [m for m in requests[1].kwargs["messages"] if m["role"] == "tool"]
    assert all("read_file result was not sent" in m["content"] for m in delivered[:omitted_count])
    assert "offset" in delivered[0]["content"] and "JSON" in delivered[0]["content"]
    assert all("record, " * 10_000 in m["content"] for m in delivered[omitted_count:])
    assert all(r.kwargs["provider_context"].conversation_state is None for r in requests[1:])
    assert "record, " * 10_000 in requests[2].kwargs["messages"][-1]["content"]
    assert all("record, " * 10_000 in m["content"] for m in result.messages if m["role"] == "tool")
    assert phases == ["started", "succeeded", "started", "succeeded"]
    assert consolidate.await_count == 2
    assert not any(m["role"] == "tool" for m in consolidate.await_args_list[0].args[0])
    assert all(path.read_text(encoding="utf-8") == "record, " * 10_000 for path in paths)
    assert not (tmp_path / ".nanobot" / "tool-results").exists()


@pytest.mark.asyncio
async def test_runner_governs_messages_added_by_before_iteration_hook(monkeypatch):
    from nanobot.agent.hook import AgentHook, AgentHookContext
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)
    provider.chat_stream_with_retry = AsyncMock(return_value=LLMResponse(content="unexpected"))
    tools = MagicMock()
    tools.get_definitions.return_value = []
    oversized = "hook-added-oversized-message"

    monkeypatch.setattr(
        "nanobot.agent.context_governance.estimate_prompt_tokens_chain",
        lambda _provider, _model, messages, _tools: (
            (2_000, "test-counter")
            if any(oversized in str(message.get("content")) for message in messages)
            else (100, "test-counter")
        ),
    )

    class MutatingHook(AgentHook):
        async def before_iteration(self, context: AgentHookContext) -> None:
            context.messages.append({"role": "user", "content": oversized})

    with pytest.raises(ContextWindowExceededError):
        await AgentRunner().run(make_run_spec(
            provider,
            initial_messages=[{"role": "user", "content": "hello"}],
            tools=tools,
            model="local-model",
            context_window_tokens=1_624,
            max_tokens=100,
            max_iterations=1,
            max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
            hook=MutatingHook(),
        ))

    provider.chat_stream_with_retry.assert_not_awaited()


@pytest.mark.parametrize(
    ("input_tokens", "expected_pressure"),
    [(500, True), (100, False)],
)
async def test_matching_reported_provider_usage_avoids_local_estimate(
    monkeypatch,
    input_tokens,
    expected_pressure,
):
    provider = MagicMock(spec=LLMProvider)
    tools = MagicMock()
    tools.get_definitions.return_value = []
    spec = make_run_spec(
        provider,
        initial_messages=[{"role": "user", "content": "hello"}],
        tools=tools,
        model="local-model",
        context_window_tokens=1_624,
        max_tokens=100,
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    )
    monkeypatch.setattr(
        "nanobot.agent.context_governance.estimate_prompt_tokens_chain",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("matching provider usage must be authoritative")
        ),
    )

    governor = ContextGovernor()
    state = ModelRequestState(
        config=_governance_config(provider, tools, spec),
        conversation=ProviderConversationStateController(
            provider=provider, model=spec.runtime.model, messages=spec.initial_messages,
        ),
        compaction=_compaction_state(spec),
        usage=LLMUsage.reported(input_tokens=input_tokens, output_tokens=10),
        messages=spec.initial_messages,
        tool_definitions=[],
    )
    if expected_pressure:
        with pytest.raises(ContextWindowExceededError):
            await governor.prepare_request(
                state,
                spec.initial_messages,
                tool_definitions=tools.get_definitions(),
            )
    else:
        messages, _context = await governor.prepare_request(
            state,
            spec.initial_messages,
            tool_definitions=tools.get_definitions(),
        )
        assert messages == spec.initial_messages


async def test_changed_messages_use_local_estimate_after_reported_usage(monkeypatch):
    provider = MagicMock(spec=LLMProvider)
    tools = MagicMock()
    tools.get_definitions.return_value = []
    spec = make_run_spec(
        provider,
        initial_messages=[{"role": "user", "content": "new tool output"}],
        tools=tools,
        model="local-model",
        context_window_tokens=1_624,
        max_tokens=100,
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    )
    estimate = MagicMock(return_value=(600, "test-counter"))
    monkeypatch.setattr(
        "nanobot.agent.context_governance.estimate_prompt_tokens_chain",
        estimate,
    )

    governor = ContextGovernor()
    state = ModelRequestState(
        config=_governance_config(provider, tools, spec),
        conversation=ProviderConversationStateController(
            provider=provider, model=spec.runtime.model, messages=spec.initial_messages,
        ),
        compaction=_compaction_state(spec),
        usage=LLMUsage.reported(input_tokens=900, output_tokens=10),
        messages=[{"role": "user", "content": "previous request"}],
        tool_definitions=[],
    )
    with pytest.raises(ContextWindowExceededError):
        await governor.prepare_request(
            state,
            spec.initial_messages,
            tool_definitions=tools.get_definitions(),
        )
    estimate.assert_called_once()


def test_resumed_provider_context_avoids_full_transcript_estimate(monkeypatch):
    provider = MagicMock(spec=LLMProvider)
    tools = MagicMock()
    tools.get_definitions.return_value = []
    spec = make_run_spec(
        provider,
        initial_messages=[{"role": "user", "content": "pending delta"}],
        tools=tools,
        model="local-model",
        context_window_tokens=1_624,
        max_tokens=100,
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    )
    monkeypatch.setattr(
        "nanobot.agent.context_governance.estimate_prompt_tokens_chain",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("resumed provider context must be authoritative")
        ),
    )

    pressure = ContextGovernor().request_pressure(
        _governance_config(provider, tools, spec),
        spec.initial_messages,
        LLMUsage.reported(input_tokens=900, output_tokens=10),
        usage_matches_messages=False,
        tool_definitions=tools.get_definitions(),
        request_context_tokens=100,
    )

    assert pressure is None


@pytest.mark.asyncio
async def test_runner_refuses_oversized_resumed_state_without_compactor(monkeypatch):
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)
    provider.can_resume_conversation_state.return_value = True
    captured_contexts = []

    async def chat_stream_with_retry(*, provider_context=None, **_kwargs):
        captured_contexts.append(provider_context)
        return LLMResponse(
            content="done",
            usage=LLMUsage.reported(input_tokens=100, output_tokens=10),
        )

    provider.chat_stream_with_retry = chat_stream_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []
    current_message = {"role": "user", "content": "new delta"}
    saved_state = ProviderConversationState(
        kind="openai_responses",
        provider="openai:test",
        model="local-model",
        version=1,
        payload={
            "items": [{"type": "reasoning", "encrypted_content": "opaque"}],
            "context_tokens": 450,
        },
        pending_messages=[current_message],
    )
    monkeypatch.setattr(
        "nanobot.agent.context_governance.estimate_prompt_tokens_chain",
        lambda *_args, **_kwargs: (100, "test-counter"),
    )
    monkeypatch.setattr(
        "nanobot.providers.conversation_state.estimate_prompt_tokens_chain",
        lambda *_args, **_kwargs: (100, "test-counter"),
    )

    with pytest.raises(ContextWindowExceededError) as exc_info:
        await AgentRunner().run(make_run_spec(
            provider,
            initial_messages=[current_message],
            tools=tools,
            model="local-model",
            context_window_tokens=1_624,
            max_tokens=100,
            max_iterations=1,
            max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
            provider_state=saved_state,
        ))

    assert exc_info.value.estimated_tokens == 550
    assert exc_info.value.source == "resumed provider state plus pending messages"
    assert captured_contexts == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("context_window_tokens", "expected_budget"),
    [(1_624, 500), (1_000, 0)],
)
async def test_runner_refuses_oversized_request_without_compactor(
    monkeypatch,
    context_window_tokens,
    expected_budget,
):
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)
    provider.chat_stream_with_retry = AsyncMock(return_value=LLMResponse(content="unexpected"))
    tools = MagicMock()
    tools.get_definitions.return_value = []
    monkeypatch.setattr(
        "nanobot.agent.context_governance.estimate_prompt_tokens_chain",
        lambda *_args, **_kwargs: (2_000, "test-counter"),
    )

    with pytest.raises(ContextWindowExceededError) as exc_info:
        await AgentRunner().run(make_run_spec(
            provider,
            initial_messages=[
                {"role": "system", "content": "oversized system"},
                {"role": "user", "content": "oversized user"},
            ],
            tools=tools,
            model="local-model",
            context_window_tokens=context_window_tokens,
            max_tokens=100,
            max_iterations=1,
            max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        ))

    assert exc_info.value.estimated_tokens == 2_000
    assert exc_info.value.input_budget == expected_budget
    provider.chat_stream_with_retry.assert_not_awaited()


async def test_backfill_missing_tool_results_inserts_error():
    """Orphaned tool_use (no matching tool_result) should get a synthetic error."""

    messages = [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call_a", "type": "function", "function": {"name": "exec", "arguments": "{}"}},
                {"id": "call_b", "type": "function", "function": {"name": "read_file", "arguments": "{}"}},
            ],
        },
        {"role": "tool", "tool_call_id": "call_a", "name": "exec", "content": "ok"},
    ]
    result = ContextGovernor.backfill_missing_tool_results(messages)
    tool_msgs = [m for m in result if m.get("role") == "tool"]
    assert len(tool_msgs) == 2
    backfilled = [m for m in tool_msgs if m.get("tool_call_id") == "call_b"]
    assert len(backfilled) == 1
    assert backfilled[0]["content"] == BACKFILL_CONTENT
    assert backfilled[0]["name"] == "read_file"


def test_drop_orphan_tool_results_removes_unmatched_tool_messages():
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "old user"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call_ok", "type": "function", "function": {"name": "read_file", "arguments": "{}"}},
            ],
        },
        {"role": "tool", "tool_call_id": "call_ok", "name": "read_file", "content": "ok"},
        {"role": "tool", "tool_call_id": "call_orphan", "name": "exec", "content": "stale"},
        {"role": "assistant", "content": "after tool"},
    ]

    cleaned = ContextGovernor.drop_orphan_tool_results(messages)

    assert cleaned == [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "old user"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call_ok", "type": "function", "function": {"name": "read_file", "arguments": "{}"}},
            ],
        },
        {"role": "tool", "tool_call_id": "call_ok", "name": "read_file", "content": "ok"},
        {"role": "assistant", "content": "after tool"},
    ]


@pytest.mark.asyncio
async def test_backfill_noop_when_complete():
    """Complete message chains should not be modified."""
    messages = [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call_x", "type": "function", "function": {"name": "exec", "arguments": "{}"}},
            ],
        },
        {"role": "tool", "tool_call_id": "call_x", "name": "exec", "content": "done"},
        {"role": "assistant", "content": "all good"},
    ]
    result = ContextGovernor.backfill_missing_tool_results(messages)
    assert result is messages  # same object — no copy


@pytest.mark.asyncio
async def test_runner_drops_orphan_tool_results_before_model_request():
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock()
    captured_messages: list[dict] = []

    async def chat_stream_with_retry(*, messages, **kwargs):
        captured_messages[:] = messages
        return LLMResponse(content="done", tool_calls=[], usage=None)

    provider.chat_stream_with_retry = chat_stream_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
        initial_messages=[
            {"role": "system", "content": "system"},
            {"role": "user", "content": "old user"},
            {"role": "tool", "tool_call_id": "call_orphan", "name": "exec", "content": "stale"},
            {"role": "assistant", "content": "after orphan"},
            {"role": "user", "content": "new prompt"},
        ],
        tools=tools,
        model="test-model",
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    assert all(
        message.get("tool_call_id") != "call_orphan"
        for message in captured_messages
        if message.get("role") == "tool"
    )
    assert result.messages[2]["tool_call_id"] == "call_orphan"
    assert result.final_content == "done"


@pytest.mark.asyncio
async def test_backfill_repairs_model_context_without_shifting_save_turn_boundary(tmp_path):
    """Historical backfill should not duplicate old tail messages on persist."""
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.events import InboundMessage
    from nanobot.bus.queue import MessageBus

    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    response = LLMResponse(content="new answer", tool_calls=[], usage=None)
    provider.chat_stream_with_retry = AsyncMock(return_value=response)

    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
    )
    loop.tools.get_definitions = MagicMock(return_value=[])

    session = loop.sessions.get_or_create("cli:test")
    session.messages = [
        {"role": "user", "content": "old user", "timestamp": "2026-01-01T00:00:00"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_missing",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": "{}"},
                }
            ],
            "timestamp": "2026-01-01T00:00:01",
        },
        {"role": "assistant", "content": "old tail", "timestamp": "2026-01-01T00:00:02"},
    ]
    loop.sessions.save(session)

    result = await loop._process_message(
        InboundMessage(channel="cli", sender_id="user", chat_id="test", content="new prompt")
    )

    assert result is not None
    assert result.content == "new answer"

    request_messages = provider.chat_stream_with_retry.await_args.kwargs["messages"]
    synthetic = [
        message
        for message in request_messages
        if message.get("role") == "tool" and message.get("tool_call_id") == "call_missing"
    ]
    assert len(synthetic) == 1
    assert synthetic[0]["content"] == BACKFILL_CONTENT

    session_after = loop.sessions.get_or_create("cli:test")
    assert [
        {
            key: value
            for key, value in message.items()
            if key in {"role", "content", "tool_call_id", "name", "tool_calls"}
        }
        for message in session_after.messages
    ] == [
        {"role": "user", "content": "old user"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_missing",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": "{}"},
                }
            ],
        },
        {"role": "assistant", "content": "old tail"},
        {"role": "user", "content": "new prompt"},
        {"role": "assistant", "content": "new answer"},
    ]


@pytest.mark.asyncio
async def test_runner_backfill_only_mutates_model_context_not_returned_messages():
    """Runner should repair orphaned tool calls for the model without rewriting result.messages."""
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock()
    captured_messages: list[dict] = []

    async def chat_stream_with_retry(*, messages, **kwargs):
        captured_messages[:] = messages
        return LLMResponse(content="done", tool_calls=[], usage=None)

    provider.chat_stream_with_retry = chat_stream_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []

    initial_messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "old user"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_missing",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": "{}"},
                }
            ],
        },
        {"role": "assistant", "content": "old tail"},
        {"role": "user", "content": "new prompt"},
    ]

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
        initial_messages=initial_messages,
        tools=tools,
        model="test-model",
        max_iterations=3,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    synthetic = [
        message
        for message in captured_messages
        if message.get("role") == "tool" and message.get("tool_call_id") == "call_missing"
    ]
    assert len(synthetic) == 1
    assert synthetic[0]["content"] == BACKFILL_CONTENT

    assert [
        {
            key: value
            for key, value in message.items()
            if key in {"role", "content", "tool_call_id", "name", "tool_calls"}
        }
        for message in result.messages
    ] == [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "old user"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_missing",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": "{}"},
                }
            ],
        },
        {"role": "assistant", "content": "old tail"},
        {"role": "user", "content": "new prompt"},
        {"role": "assistant", "content": "done"},
    ]


def test_governance_repairs_orphans_after_history_rewrite():
    """A rewritten history drops tool results whose calls are no longer present."""
    rewritten = [
        {"role": "system", "content": "system"},
        {"role": "tool", "tool_call_id": "tc_old", "name": "search",
         "content": "old result"},
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": "new msg"},
    ]

    cleaned = ContextGovernor.drop_orphan_tool_results(rewritten)
    # The orphan tool result should be removed.
    assert not any(
        m.get("role") == "tool" and m.get("tool_call_id") == "tc_old"
        for m in cleaned
    )


def test_governance_fallback_still_repairs_orphans():
    """When full governance fails, the fallback must still repair orphans."""
    # Messages with an orphan tool result (no matching assistant tool_call).
    messages = [
        {"role": "user", "content": "hello"},
        {"role": "tool", "tool_call_id": "orphan_tc", "name": "read",
         "content": "stale"},
        {"role": "assistant", "content": "hi"},
    ]

    repaired = ContextGovernor.drop_orphan_tool_results(messages)
    repaired = ContextGovernor.backfill_missing_tool_results(repaired)
    # Orphan tool result should be gone.
    assert not any(m.get("tool_call_id") == "orphan_tc" for m in repaired)


# ---------------------------------------------------------------------------
# Malformed tool_call name guard (missing/non-string name wedges the session
# upstream: messages.content.N.tool_use.name: Input should be a valid string)
# ---------------------------------------------------------------------------


def test_drop_malformed_tool_calls_trims_response():
    """LLM response tool_calls with a missing/empty name are dropped in place."""
    from nanobot.agent.runner import AgentRunner

    candidate_state = ProviderConversationState(
        kind="openai_responses",
        provider="openai:test",
        model="gpt-5.6",
        version=1,
        payload={"items": [{"type": "function_call", "name": None}]},
    )
    response = LLMResponse(
        content=None,
        tool_calls=[
            ToolCallRequest(id="1", name=None, arguments={}),
            ToolCallRequest(id="2", name="", arguments={}),
            ToolCallRequest(id="3", name={"unexpected": "object"}, arguments={}),
            ToolCallRequest(id="4", name="read_file", arguments={}),
        ],
        finish_reason="tool_calls",
        provider_state=candidate_state,
    )
    dropped, all_dropped, orig = AgentRunner._drop_malformed_tool_calls(response)
    assert [tc.name for tc in response.tool_calls] == ["read_file"]
    assert response.provider_state is None
    assert response.finish_reason == "tool_calls"
    assert response.should_execute_tools is True
    assert dropped == 3
    assert all_dropped is False
    assert orig == "tool_calls"


def test_drop_malformed_tool_calls_all_bad_disables_execution():
    """If every tool call is malformed, execution is disabled (no empty exec)."""
    from nanobot.agent.runner import AgentRunner

    response = LLMResponse(
        content="some text",
        tool_calls=[ToolCallRequest(id="1", name=None, arguments={})],
        finish_reason="tool_calls",
    )
    dropped, all_dropped, orig = AgentRunner._drop_malformed_tool_calls(response)
    assert response.tool_calls == []
    assert response.finish_reason == "stop"
    assert response.should_execute_tools is False
    assert dropped == 1
    assert all_dropped is True
    assert orig == "tool_calls"


def test_drop_malformed_returns_tuple_no_calls():
    """No tool calls returns (0, False, current_finish_reason)."""
    from nanobot.agent.runner import AgentRunner

    response = LLMResponse(content="hi", finish_reason="stop")
    dropped, all_dropped, orig = AgentRunner._drop_malformed_tool_calls(response)
    assert dropped == 0
    assert all_dropped is False
    assert orig == "stop"


def test_strip_malformed_tool_calls_keeps_valid_calls_in_history():
    """A mixed assistant turn keeps only its valid tool_calls."""
    messages = [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "bad", "type": "function", "function": {"name": None, "arguments": "{}"}},
                {"id": "ok", "type": "function", "function": {"name": "exec", "arguments": "{}"}},
            ],
        },
        {"role": "tool", "tool_call_id": "ok", "name": "exec", "content": "done"},
    ]
    result = ContextGovernor.strip_malformed_tool_calls(messages)
    assert result is not messages  # copied, original untouched
    assert len(messages[1]["tool_calls"]) == 2  # original preserved
    kept = result[1]["tool_calls"]
    assert [tc["function"]["name"] for tc in kept] == ["exec"]


def test_strip_malformed_tool_calls_drops_empty_assistant_turn():
    """An assistant turn that is only a malformed call is removed entirely;
    the existing orphan-result cleanup then drops its dangling tool result,
    so a polluted session self-heals."""
    messages = [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "bad", "type": "function", "function": {"name": None, "arguments": "{}"}},
            ],
        },
        {"role": "tool", "tool_call_id": "bad", "name": "", "content": "r"},
    ]
    stripped = ContextGovernor.strip_malformed_tool_calls(messages)
    assert [m["role"] for m in stripped] == ["user", "tool"]
    healed = ContextGovernor.drop_orphan_tool_results(stripped)
    assert [m["role"] for m in healed] == ["user"]


def test_strip_malformed_tool_calls_noop_when_clean():
    """Clean history is returned unchanged (same object)."""
    messages = [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "ok", "type": "function", "function": {"name": "exec", "arguments": "{}"}},
            ],
        },
        {"role": "tool", "tool_call_id": "ok", "name": "exec", "content": "done"},
    ]
    assert ContextGovernor.strip_malformed_tool_calls(messages) is messages


def test_strip_placeholder_assistant_messages_removes_omitted():
    """Placeholder assistant messages are removed; real messages kept."""
    messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "real response"},
        {"role": "user", "content": "ok"},
        {"role": "assistant", "content": "[Previous assistant message omitted.]"},
        {"role": "user", "content": "?"},
        {"role": "assistant", "content": "[Previous assistant message omitted.]"},
        {"role": "user", "content": "hello"},
    ]
    result = ContextGovernor.strip_placeholder_assistant_messages(messages)
    assert [m["role"] for m in result] == [
        "user", "assistant", "user", "user", "user",
    ]
    assert result[1]["content"] == "real response"


def test_strip_placeholder_noop_when_clean():
    """Clean history is returned unchanged (same object)."""
    messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello back"},
    ]
    assert ContextGovernor.strip_placeholder_assistant_messages(messages) is messages


def test_strip_placeholder_keeps_assistant_with_tool_calls():
    """A placeholder assistant that also carries tool_calls is kept."""
    messages = [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": "[Previous assistant message omitted.]",
            "tool_calls": [
                {"id": "1", "type": "function", "function": {"name": "exec", "arguments": "{}"}},
            ],
        },
        {"role": "tool", "tool_call_id": "1", "name": "exec", "content": "done"},
    ]
    result = ContextGovernor.strip_placeholder_assistant_messages(messages)
    assert result is messages
