"""Exercise request governance through the Codex transport boundary."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from nanobot.agent.context_governance import (
    ContextCompactionState,
    ContextGovernanceConfig,
    ContextGovernor,
    ModelRequestState,
)
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.config.schema import ModelPresetConfig
from nanobot.providers.base import LLMResponse, LLMUsage, ProviderCallContext
from nanobot.providers.conversation_state import ProviderConversationStateController
from nanobot.providers.fallback_provider import FallbackProvider
from nanobot.providers.openai_codex_provider import OpenAICodexProvider, _CodexHTTPError
from nanobot.providers.openai_responses import build_responses_state


def _request_state(provider, *, prior_tokens=180_000, repetitions=15_000):
    model = "openai-codex/gpt-5.6-sol"
    accepted = [
        {"role": "system", "content": "Continue the coding task."},
        {"role": "user", "content": "Inspect the source."},
        {"role": "assistant", "content": None, "tool_calls": [{
            "id": "read-1", "type": "function",
            "function": {"name": "read_file", "arguments": '{"path":"source.py"}'},
        }]},
    ]
    saved = build_responses_state(
        provider=OpenAICodexProvider._responses_state_provider(), model="gpt-5.6-sol",
        input_items=[{"role": "user", "content": "Inspect the source."}],
        output_items=[
            {"type": "reasoning", "encrypted_content": "prior opaque state"},
            {"type": "function_call", "call_id": "read-1", "name": "read_file",
             "arguments": '{"path":"source.py"}'},
        ],
        usage=LLMUsage.reported(input_tokens=prior_tokens, output_tokens=10),
    )
    delta = {"role": "tool", "name": "read_file", "tool_call_id": "read-1",
             "content": "source_line\n" * repetitions}
    raw = [*deepcopy(accepted), delta]
    consolidate = AsyncMock(return_value="Implement the recorded fix.")
    compaction = ContextCompactionState.from_messages(accepted, consolidate, None)
    compaction.raw_messages = raw
    config = ContextGovernanceConfig(
        provider=provider, model=model, tools=ToolRegistry(), workspace=None,
        session_key="pressure-test", max_tool_result_chars=16_000,
        context_window_tokens=200_000, max_tokens=8192,
    )
    state = ModelRequestState(
        config=config, compaction=compaction,
        conversation=ProviderConversationStateController(
            provider=provider, model=model, messages=accepted, state=saved,
        ),
    )
    return state, raw, consolidate


@pytest.fixture
def transport(monkeypatch):
    bodies = []
    behavior = {"error": None, "compacted_content": "compacted state"}
    monkeypatch.setattr(
        "nanobot.providers.openai_codex_provider.get_codex_token",
        lambda **_kwargs: SimpleNamespace(account_id="acct", access="token"),
    )

    async def request(_url, _headers, body, **_kwargs):
        bodies.append(deepcopy(body))
        calls = {i["call_id"] for i in body["input"] if i.get("type") == "function_call"}
        outputs = {i["call_id"] for i in body["input"] if i.get("type") == "function_call_output"}
        if calls != outputs:
            raise _CodexHTTPError(
                "Function calls and outputs must be paired", status_code=400,
            )
        if body["input"][-1].get("type") == "compaction_trigger":
            if behavior["error"] is not None:
                raise behavior["error"]
            output = [{"type": "compaction", "encrypted_content": behavior["compacted_content"]}]
        else:
            output = [{"role": "assistant", "content": "done"}]
        return LLMResponse(
            content="done",
            provider_state=build_responses_state(
                provider=OpenAICodexProvider._responses_state_provider(), model="gpt-5.6-sol",
                input_items=body["input"], output_items=output,
                usage=LLMUsage.reported(input_tokens=100, output_tokens=10),
            ),
        )

    monkeypatch.setattr("nanobot.providers.openai_codex_provider._request_codex", request)
    return bodies, behavior


@pytest.mark.parametrize("prior_tokens", [160_000, 180_000])
@pytest.mark.parametrize("wrapped", [False, True])
async def test_pressure_compacts_resumable_state_before_sending_tool_result(
    transport, prior_tokens, wrapped,
):
    leaf = OpenAICodexProvider()
    provider = FallbackProvider(
        primary=leaf, fallback_presets=[], provider_factory=lambda _preset: leaf,
    ) if wrapped else leaf
    state, raw, consolidate = _request_state(provider, prior_tokens=prior_tokens)
    before = deepcopy(raw)

    prepared, context = await ContextGovernor().prepare_request(
        state, raw, tool_definitions=[], transcript=raw,
    )
    consolidate.assert_not_awaited()
    assert context.compaction_input_budget == 190_784
    assert context.conversation_state is not None
    response = await provider.chat_with_context(
        messages=prepared, model=state.config.model, max_tokens=8192, provider_context=context,
    )

    consolidate.assert_not_awaited()
    assert raw == before
    assert response.content == "done"
    assert response.provider_compaction_applied is True
    assert response.provider_compaction_scope == "prior_context"
    bodies, _ = transport
    assert len(bodies) == 2
    assert bodies[0]["input"][-1] == {"type": "compaction_trigger"}
    assert any(item.get("encrypted_content") == "prior opaque state" for item in bodies[0]["input"])
    assert not any(item.get("type") == "function_call_output" for item in bodies[0]["input"])
    pending = [item for item in bodies[1]["input"] if item.get("type") == "function_call_output"]
    assert len(pending) == 1
    assert pending[0]["call_id"] == "read-1"
    assert pending[0]["output"] == raw[-1]["content"]
    assert [i.get("type") for i in bodies[1]["input"][-3:]] == [
        "compaction", "function_call", "function_call_output",
    ]
    assert not any(item.get("type") == "reasoning" for item in bodies[1]["input"])


async def test_unpressured_request_preserves_normal_provider_behavior(transport):
    provider = OpenAICodexProvider()
    state, raw, consolidate = _request_state(provider, prior_tokens=160_000, repetitions=10)
    prepared, context = await ContextGovernor().prepare_request(
        state, raw, tool_definitions=[], transcript=raw,
    )
    assert context.compaction_input_budget is None
    response = await provider.chat(
        prepared, max_tokens=8192, provider_context=context,
    )
    assert response.content == "done"
    consolidate.assert_not_awaited()
    assert len(transport[0]) == 1


async def test_compaction_preserves_parallel_calls_with_reordered_pending_outputs(transport):
    provider = OpenAICodexProvider()
    completed_exchange = [
        {"type": "function_call", "call_id": "completed", "name": "read_file", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "completed", "output": "old source"},
    ]
    pending_calls = [
        {"type": "function_call", "call_id": call_id, "name": "read_file", "arguments": "{}"}
        for call_id in ("read-a", "read-b")
    ]
    saved = build_responses_state(
        provider=provider._responses_state_provider(), model="gpt-5.6-sol",
        input_items=[{"role": "user", "content": "read files"}, *completed_exchange],
        output_items=[{"type": "reasoning", "encrypted_content": "opaque"}, *pending_calls],
        usage=LLMUsage.reported(input_tokens=180_000, output_tokens=10),
    ).with_pending_messages([
        {"role": "tool", "tool_call_id": "read-b", "content": "source B"},
        {"role": "tool", "tool_call_id": "read-a", "content": "source A"},
    ])
    response = await provider.chat(
        [{"role": "user", "content": "read files"}], max_tokens=8192,
        provider_context=ProviderCallContext(
            conversation_state=saved, context_window_tokens=200_000,
            compaction_input_budget=190_784,
        ),
    )
    assert response.content == "done"
    compact, generation = transport[0]
    assert [i for i in compact["input"] if i.get("call_id")] == completed_exchange
    assert [i for i in generation["input"] if i.get("type") == "function_call"] == pending_calls
    assert [i for i in generation["input"] if i.get("type") == "function_call_output"] == [
        {"type": "function_call_output", "call_id": "read-b", "output": "source B"},
        {"type": "function_call_output", "call_id": "read-a", "output": "source A"},
    ]


@pytest.mark.parametrize("mode", ["disabled", "inline_only", "incompatible_state"])
async def test_without_pre_request_compaction_pressure_uses_local_summary(monkeypatch, mode):
    provider = OpenAICodexProvider()
    if mode == "disabled":
        provider._native_compaction_available = False
    elif mode == "inline_only":
        monkeypatch.setattr(provider, "supports_pre_request_compaction", lambda _model: False)
    else:
        monkeypatch.setattr(provider, "can_resume_conversation_state", lambda *_args: False)
        # With no replayable state, pressure must come from the actual transcript.
    state, raw, consolidate = _request_state(
        provider, repetitions=70_000 if mode == "incompatible_state" else 15_000,
    )
    if mode == "incompatible_state":
        # Put the large content in accepted history so its replacement can fit.
        state.compaction.accepted_messages = deepcopy(raw)
        state.compaction.raw_accepted_boundary = len(raw)
    _, context = await ContextGovernor().prepare_request(
        state, raw, tool_definitions=[], transcript=raw,
    )
    consolidate.assert_awaited_once()
    assert context.conversation_state is None
    assert context.compaction_input_budget is None


@pytest.mark.parametrize("error", [
    _CodexHTTPError("unsupported", status_code=400, compaction_unsupported=True),
    httpx.ReadTimeout("compaction timed out"),
])
async def test_failed_required_compaction_does_not_send_oversized_generation(transport, error):
    provider = OpenAICodexProvider()
    state, raw, consolidate = _request_state(provider)
    prepared, context = await ContextGovernor().prepare_request(
        state, raw, tool_definitions=[], transcript=raw,
    )
    transport[1]["error"] = error
    response = await provider.chat(prepared, max_tokens=8192, provider_context=context)
    assert response.finish_reason == "error"
    assert len(transport[0]) == 1
    consolidate.assert_not_awaited()
    state.conversation.observe_response(response, raw)
    assert state.conversation.checkpoint(raw) is not None
    if isinstance(error, httpx.ReadTimeout):
        assert response.error_should_retry is True
        assert provider.supports_pre_request_compaction() is True
    else:
        assert provider.supports_pre_request_compaction() is False
        await ContextGovernor().prepare_request(state, raw, tool_definitions=[], transcript=raw)
        consolidate.assert_awaited_once()


@pytest.mark.parametrize("oversized", ["delta", "compaction"])
async def test_compaction_that_still_exceeds_budget_stops_before_generation(transport, oversized):
    provider = OpenAICodexProvider()
    state, raw, consolidate = _request_state(
        provider, repetitions=70_000 if oversized == "delta" else 15_000,
    )
    if oversized == "compaction":
        transport[1]["compacted_content"] = "compacted content " * 100_000
    prepared, context = await ContextGovernor().prepare_request(
        state, raw, tool_definitions=[], transcript=raw,
    )
    response = await provider.chat(prepared, max_tokens=8192, provider_context=context)
    assert response.finish_reason == "error"
    assert response.error_kind == "context_window_exceeded"
    assert response.error_should_retry is False
    state.conversation.observe_response(response, raw)
    assert state.conversation.checkpoint(raw) is not None
    assert "after native compaction" in response.content
    assert len(transport[0]) == 1
    consolidate.assert_not_awaited()


@pytest.mark.parametrize("compatible", [False, True])
async def test_fallback_cannot_discard_required_compaction(transport, compatible):
    primary = OpenAICodexProvider()
    model = "openai-codex/gpt-5.6-sol" if compatible else "openai-codex/gpt-6-astra"
    fallback = OpenAICodexProvider(default_model=model)
    fallback.chat_with_context = AsyncMock(return_value=LLMResponse(content="fallback done"))
    provider = FallbackProvider(
        primary=primary,
        fallback_presets=[ModelPresetConfig(model=model, provider="openai_codex")],
        provider_factory=lambda _preset: fallback,
    )
    state, raw, _ = _request_state(provider)
    prepared, context = await ContextGovernor().prepare_request(
        state, raw, tool_definitions=[], transcript=raw,
    )
    transport[1]["error"] = _CodexHTTPError("unavailable", status_code=503)
    response = await provider.chat_with_context(
        messages=prepared, max_tokens=8192, provider_context=context,
    )
    if compatible:
        assert response.content == "fallback done"
        fallback.chat_with_context.assert_awaited_once()
        forwarded = fallback.chat_with_context.await_args.kwargs["provider_context"]
        assert forwarded.conversation_state is not None
        assert forwarded.compaction_input_budget == context.compaction_input_budget
    else:
        assert response.finish_reason == "error"
        fallback.chat_with_context.assert_not_awaited()
        state.conversation.observe_response(response, raw)
        assert state.conversation.checkpoint(raw) is not None
