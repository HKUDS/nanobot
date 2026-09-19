"""Reported input survives appends, but not route or transcript changes."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from providers.test_input_usage import chat_stream, provider_client

from agent.runner_helpers import make_run_spec
from nanobot.agent.context import TranscriptInput
from nanobot.agent.context_governance import ContextWindowExceededError, ModelRequestState
from nanobot.agent.runner import AgentRunner
from nanobot.providers.base import LLMResponse, LLMUsage
from nanobot.providers.input_usage import InputSnapshot, InputUsage
from nanobot.session.manager import SessionManager


def build_transcript(transcript):
    return [
        {"role": "system", "content": (
            transcript.session_summary["text"] if transcript.session_summary else "system"
        )},
        *transcript.history,
        *([{"role": "user", "content": transcript.current_message}]
          if transcript.current_message is not None else []),
    ]


def spec_for(provider, **kwargs):
    tools = MagicMock()
    tools.get_definitions.return_value = [{"type": "function", "function": {
        "name": "lookup", "parameters": {"type": "object", "properties": {}},
    }}]
    tools.execute = AsyncMock(return_value="saved lookup receipt")
    return make_run_spec(
        provider, model=provider.default_model, tools=tools, max_iterations=3,
        max_tool_result_chars=10000, context_window_tokens=8192, max_tokens=1000,
        initial_messages=None, **kwargs,
    )


@pytest.fixture
def underestimate(monkeypatch):
    monkeypatch.setattr(
        "nanobot.agent.context_governance.estimate_prompt_tokens_chain",
        lambda *_args, **_kwargs: (100, "deliberate underestimate"),
    )


async def test_tool_append_compacts_before_second_dispatch(monkeypatch, underestimate):
    provider, create, _ = provider_client(monkeypatch, responses=[
        chat_stream(9000, tool=True), chat_stream(100),
    ])
    consolidate = AsyncMock(return_value="compact summary")
    result = await AgentRunner().run(spec_for(
        provider, transcript_input=TranscriptInput(history=[], current_message="original input"),
        transcript_builder=build_transcript, consolidate_history=consolidate,
    ))
    consolidate.assert_awaited_once()
    assert create.await_count == 2
    before, after = [call.kwargs["messages"] for call in create.await_args_list]
    assert before[0]["content"] == "system"
    assert after[0]["content"] == "compact summary"
    assert after[-1]["content"] == "saved lookup receipt"
    assert any(row.get("content") == "original input" for row in result.messages)
    assert result.summary_checkpoint is not None
    assert result.input_usage.input_tokens == 100


async def test_measurement_can_cross_fresh_runner_turns(monkeypatch, underestimate):
    provider, create, _ = provider_client(monkeypatch, responses=[chat_stream(9000), chat_stream(100)])
    first = await AgentRunner().run(spec_for(
        provider, transcript_input=TranscriptInput(history=[], current_message="first input"),
        transcript_builder=build_transcript, consolidate_history=AsyncMock(return_value="unused"),
    ))
    consolidate = AsyncMock(return_value="new turn summary")
    second = await AgentRunner().run(spec_for(
        provider, input_usage=first.input_usage,
        transcript_input=TranscriptInput(history=first.messages[1:], current_message="second input"),
        transcript_builder=build_transcript, consolidate_history=consolidate,
    ))
    consolidate.assert_awaited_once()
    request = create.await_args_list[-1].kwargs["messages"]
    assert request[0]["content"] == "new turn summary"
    assert request[-1]["content"] == "second input"
    assert second.input_usage.input_tokens == 100


async def test_no_compactor_does_not_resend_known_overbudget_input(monkeypatch, underestimate):
    provider, create, _ = provider_client(monkeypatch, responses=[chat_stream(9000, tool=True)])
    spec = spec_for(provider)
    spec.initial_messages = [{"role": "user", "content": "work"}]
    with pytest.raises(ContextWindowExceededError, match="unchanged measured input"):
        await AgentRunner().run(spec)
    assert create.await_count == 1


async def test_noop_summary_cannot_discard_known_input_pressure(monkeypatch, underestimate):
    provider, create, _ = provider_client(monkeypatch, responses=[chat_stream(9000, tool=True)])
    # With a system-only prefix, a summary that repeats it leaves the measured
    # input in place. Calling the compactor is not evidence that fitting worked.
    spec = spec_for(
        provider, transcript_input=TranscriptInput(history=[], current_message=None),
        transcript_builder=build_transcript,
        consolidate_history=AsyncMock(return_value="system"),
    )
    with pytest.raises(ContextWindowExceededError, match="unchanged measured input"):
        await AgentRunner().run(spec)
    assert create.await_count == 1


@pytest.mark.parametrize("case", ["missing", "estimated", "aggregate", "native", "error"])
def test_invalid_measurements_never_establish_a_floor(monkeypatch, case):
    provider, _, _ = provider_client(monkeypatch)
    spec = spec_for(provider)
    messages = [{"role": "user", "content": "hello"}]
    snapshot = InputSnapshot.from_chat_request("test", {"messages": messages})
    usage = LLMUsage.reported(input_tokens=9000, output_tokens=2)
    response = LLMResponse(content="ok", usage=usage, input_snapshot=snapshot)
    if case == "missing":
        response.input_snapshot = None
    elif case == "estimated":
        response.usage = LLMUsage.estimated(input_tokens=9000, output_tokens=2)
    elif case == "aggregate":
        response.usage = usage + usage
    elif case == "native":
        response.provider_compaction_applied = True
    elif case == "error":
        response.finish_reason = "error"
    state = MagicMock(spec=ModelRequestState)
    state.messages, state.tool_definitions = messages, []
    AgentRunner()._record_request_usage(spec, state, response)
    assert state.input_usage is None


def test_measurement_is_not_canonical_or_display_metadata(tmp_path):
    manager = SessionManager(tmp_path)
    session = manager.get_or_create("cli:input-usage")
    snapshot = InputSnapshot.from_chat_request("private-scope", {
        "messages": [{"role": "user", "content": "not retained"}],
    })
    session.input_usage = InputUsage(snapshot, 9000)
    session.add_message("user", "saved input")
    manager.save(session)
    reloaded = SessionManager(tmp_path).get_or_create(session.key)
    assert reloaded.messages == session.messages
    assert reloaded.input_usage is None
    assert "input_usage" not in reloaded.metadata
    assert "private-scope" not in repr(session)
