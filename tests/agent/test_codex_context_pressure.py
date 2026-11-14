import asyncio
import json
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
from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import ModelPresetConfig
from nanobot.providers.base import (
    LLMProvider,
    LLMResponse,
    LLMUsage,
    ProviderCallContext,
    ToolCallRequest,
)
from nanobot.providers.compaction import ProviderStateCommitError
from nanobot.providers.conversation_state import ProviderConversationStateController
from nanobot.providers.fallback_provider import FallbackProvider
from nanobot.providers.openai_codex_provider import OpenAICodexProvider, _CodexHTTPError
from nanobot.providers.openai_responses import build_responses_state
from nanobot.session.manager import SessionManager
from nanobot.session.recovery import (
    RUNTIME_CHECKPOINT_KEY,
    restore_runtime_checkpoint,
    runtime_checkpoint_is_well_formed,
)


def _request_state(provider, *, prior_tokens=180_000, repetitions=12_000, checkpoint_callback=None):
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
    # The default delta pressures prior state but fits after compaction, even with
    # UTF-8 byte estimates while the fallback tokenizer is unavailable.
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
            checkpoint_callback=checkpoint_callback,
        ),
    )
    return state, raw, consolidate


@pytest.fixture
def transport(monkeypatch):
    bodies = []
    behavior = {"errors": [], "generation_errors": [], "compacted_content": "compacted state"}
    monkeypatch.setattr(
        "nanobot.providers.openai_codex_provider.get_codex_token",
        lambda **_kwargs: SimpleNamespace(account_id="acct", access="token"),
    )

    monkeypatch.setattr(
        "nanobot.providers.openai_responses.backend.ResponsesBackend.websocket_request",
        AsyncMock(return_value=None),
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
            if behavior["errors"]:
                raise behavior["errors"].pop(0)
            output = [{"type": "compaction", "encrypted_content": behavior["compacted_content"]}]
        else:
            if behavior["generation_errors"]:
                error = behavior["generation_errors"].pop(0)
                if isinstance(error, LLMResponse):
                    return error
                raise error
            tool_call = behavior.pop("tool_call", None)
            if tool_call is not None:
                return LLMResponse(
                    content=None, tool_calls=[tool_call], finish_reason="tool_calls",
                    provider_state=build_responses_state(
                        provider=OpenAICodexProvider._responses_state_provider(), model="gpt-5.6-sol",
                        input_items=body["input"], output_items=[{
                            "type": "function_call", "call_id": tool_call.id,
                            "name": tool_call.name, "arguments": json.dumps(tool_call.arguments),
                        }],
                        usage=LLMUsage.reported(input_tokens=180_000, output_tokens=10),
                    ),
                )
            if behavior.get("on_generation") is not None:
                await behavior["on_generation"]()
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


@pytest.mark.parametrize("prior_tokens, wrapped", [(160_000, False), (180_000, True)])
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

    before[-1]["_meta"] = {"provider_state_boundary": True}
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


@pytest.mark.parametrize("stream", [False, True])
async def test_successful_compaction_survives_generation_retry(transport, monkeypatch, stream):
    provider = OpenAICodexProvider()
    state, raw, _ = _request_state(provider)
    prepared, context = await ContextGovernor().prepare_request(
        state, raw, tool_definitions=[], transcript=raw,
    )
    transport[1]["generation_errors"] = [httpx.ConnectError("synthetic generation failure")]
    monkeypatch.setattr(provider, "_sleep_with_heartbeat", AsyncMock())
    call = provider.chat_stream_with_retry if stream else provider.chat_with_retry

    response = await call(
        prepared, model=state.config.model, max_tokens=8192, provider_context=context,
    )

    assert response.content == "done"
    assert response.provider_compaction_applied is True
    bodies, _ = transport
    assert [body["input"][-1].get("type") for body in bodies] == [
        "compaction_trigger", "function_call_output", "function_call_output",
    ]
    assert bodies[1]["input"] == bodies[2]["input"]
    assert [item for item in bodies[2]["input"] if item.get("type") == "function_call_output"] == [
        {"type": "function_call_output", "call_id": "read-1", "output": raw[-1]["content"]},
    ]
    await provider.aclose()


async def test_accepted_compaction_survives_terminal_generation_response(transport):
    provider = OpenAICodexProvider()
    state, raw, _ = _request_state(provider)
    prepared, context = await ContextGovernor().prepare_request(
        state, raw, tool_definitions=[], transcript=raw,
    )
    transport[1]["generation_errors"] = [LLMResponse(
        content="synthetic response.failed", finish_reason="error", error_should_retry=False,
    )]
    response = await provider.chat_with_retry(prepared, max_tokens=8192, provider_context=context)
    assert response.finish_reason == "error"
    state.conversation.observe_response(response, raw)
    prepared, context = await ContextGovernor().prepare_request(
        state, raw, tool_definitions=[], transcript=raw,
    )
    assert context.compaction_input_budget is None
    response = await provider.chat_with_retry(prepared, max_tokens=8192, provider_context=context)
    assert response.content == "done"
    assert transport[0][1]["input"] == transport[0][2]["input"]
    assert len(transport[0]) == 3
    await provider.aclose()


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
        provider._responses.native_compaction_available = False
    elif mode == "inline_only":
        monkeypatch.setattr(provider, "supports_pre_request_compaction", lambda _model: False)
    else:
        monkeypatch.setattr(provider, "can_resume_conversation_state", lambda *_args: False)
    state, raw, consolidate = _request_state(
        provider, repetitions=70_000 if mode == "incompatible_state" else 15_000,
    )
    if mode == "incompatible_state":
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
    transport[1]["errors"] = [error]
    response = await provider.chat(prepared, max_tokens=8192, provider_context=context)
    assert response.finish_reason == "error"
    assert len(transport[0]) == 1
    consolidate.assert_not_awaited()
    state.conversation.observe_response(response, raw)
    assert context.conversation_state is not None
    assert state.conversation.checkpoint(raw) == context.conversation_state
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
    assert context.conversation_state is not None
    saved = state.conversation.checkpoint(raw)
    assert saved.pending_messages == context.conversation_state.pending_messages
    assert any(item.get("type") == "compaction" for item in saved.payload["items"])
    assert "after native compaction" in response.content
    assert len(transport[0]) == 1
    consolidate.assert_not_awaited()


@pytest.mark.parametrize("mode", [
    "incompatible_state", "compaction_unavailable", "compatible", "smaller_window",
])
@pytest.mark.parametrize("failure_stage", ["compaction", "generation"])
async def test_fallback_cannot_discard_required_compaction(transport, mode, failure_stage):
    primary = OpenAICodexProvider()
    model = (
        "openai-codex/gpt-6-astra" if mode == "incompatible_state" else primary.default_model
    )
    fallback = OpenAICodexProvider(default_model=model)
    fallback._responses.native_compaction_available = mode != "compaction_unavailable"
    fallback.chat_with_context = AsyncMock(wraps=fallback.chat_with_context)
    fallback_window = 32_768 if mode == "smaller_window" else 200_000
    provider = FallbackProvider(
        primary=primary,
        fallback_presets=[ModelPresetConfig(
            model=model, provider="openai_codex",
            context_window_tokens=fallback_window, max_tokens=8192,
        )],
        provider_factory=lambda _preset: fallback,
    )
    state, raw, consolidate = _request_state(provider)
    prepared, context = await ContextGovernor().prepare_request(
        state, raw, tool_definitions=[], transcript=raw,
    )
    error_key = "errors" if failure_stage == "compaction" else "generation_errors"
    transport[1][error_key] = [_CodexHTTPError("unavailable", status_code=503)]
    response = await provider.chat_with_context(
        messages=prepared, max_tokens=8192, provider_context=context,
    )
    consolidate.assert_not_awaited()
    bodies, _ = transport
    if mode in {"compatible", "smaller_window"}:
        fallback.chat_with_context.assert_awaited_once()
        forwarded = fallback.chat_with_context.await_args.kwargs["provider_context"]
        if failure_stage == "compaction":
            assert forwarded.conversation_state == context.conversation_state
            assert bodies[1]["input"][-1] == {"type": "compaction_trigger"}
        else:
            assert any(item.get("type") == "compaction" for item in forwarded.conversation_state.payload["items"])
        assert forwarded.compaction_input_budget == context.compaction_input_budget
        assert forwarded.context_window_tokens == fallback_window
    else:
        fallback.chat_with_context.assert_not_awaited()
        assert len(bodies) == (1 if failure_stage == "compaction" else 2)
    if mode == "compatible":
        assert response.content == "done"
        assert response.provider_compaction_applied is True
        assert len(bodies) == 3
        assert bodies[-1]["input"][-1]["output"] == raw[-1]["content"]
    else:
        assert response.finish_reason == "error"
        if mode == "smaller_window":
            assert response.error_kind == "context_window_exceeded"
            assert response.error_should_retry is False
            assert len(bodies) == 2
        state.conversation.observe_response(response, raw)
        assert context.conversation_state is not None
        saved = state.conversation.checkpoint(raw)
        assert saved.pending_messages == context.conversation_state.pending_messages
        if mode == "smaller_window" or failure_stage == "generation":
            assert any(item.get("type") == "compaction" for item in saved.payload["items"])
        else:
            assert saved == context.conversation_state


async def test_persistent_fallback_retries_reuse_accepted_compaction(transport, monkeypatch):
    primary = OpenAICodexProvider()
    provider = FallbackProvider(
        primary=primary,
        fallback_presets=[ModelPresetConfig(
            model=primary.default_model, provider="openai_codex",
            context_window_tokens=200_000, max_tokens=8192,
        )],
        provider_factory=lambda _preset: OpenAICodexProvider(),
    )
    state, raw, _ = _request_state(provider)
    prepared, context = await ContextGovernor().prepare_request(
        state, raw, tool_definitions=[], transcript=raw,
    )
    attempts = 1 + len(LLMProvider._CHAT_RETRY_DELAYS)
    transport[1]["generation_errors"] = [httpx.ConnectError("synthetic failure")] * (attempts * 2)
    monkeypatch.setattr(LLMProvider, "_sleep_with_heartbeat", AsyncMock())
    response = await provider.chat_with_retry(
        prepared, model=state.config.model, max_tokens=8192,
        provider_context=context, retry_mode="persistent",
    )
    assert response.content == "done"
    assert response.provider_compaction_applied is True
    bodies = transport[0]
    assert len(bodies) == 2 + attempts * 2
    assert bodies[0]["input"][-1] == {"type": "compaction_trigger"}
    assert all(body["input"] == bodies[1]["input"] for body in bodies[2:])
    await provider.aclose()


@pytest.mark.parametrize("stream", [False, True])
async def test_compaction_checkpoint_failure_aborts_retry_and_fallback(transport, monkeypatch, stream):
    primary = OpenAICodexProvider()
    fallback = AsyncMock()
    provider = FallbackProvider(
        primary=primary,
        fallback_presets=[ModelPresetConfig(model=primary.default_model, provider="openai_codex")],
        provider_factory=fallback,
    )
    commit = AsyncMock(side_effect=OSError("synthetic checkpoint failure"))
    state, raw, _ = _request_state(provider, checkpoint_callback=commit)
    prepared, context = await ContextGovernor().prepare_request(
        state, raw, tool_definitions=[], transcript=raw,
    )
    monkeypatch.setattr(LLMProvider, "_sleep_with_heartbeat", AsyncMock())
    call = provider.chat_stream_with_retry if stream else provider.chat_with_retry
    with pytest.raises(ProviderStateCommitError):
        await call(prepared, max_tokens=8192, provider_context=context)
    commit.assert_awaited_once()
    fallback.assert_not_called()
    assert len(transport[0]) == 1
    assert state.conversation.checkpoint(raw) == context.conversation_state
    await provider.aclose()


@pytest.mark.parametrize("mode,cancel_at", [
    ("stop", "generation"), ("restart", "generation"),
    ("temporary", "generation"), ("stop", "checkpoint"),
])
async def test_compaction_survives_stop_and_session_restore(
    transport, tmp_path, monkeypatch, mode, cancel_at,
):
    provider = OpenAICodexProvider()
    if mode == "temporary":
        provider = FallbackProvider(
            primary=provider,
            fallback_presets=[ModelPresetConfig(
                model=provider.default_model, provider="openai_codex", context_window_tokens=200_000,
            )],
            provider_factory=lambda _preset: OpenAICodexProvider(),
        )
        monkeypatch.setattr(LLMProvider, "_sleep_with_heartbeat", AsyncMock())
    loop = AgentLoop(
        bus=MessageBus(), provider=provider, workspace=tmp_path,
        model=provider.get_default_model(), context_window_tokens=200_000,
    )
    key = "websocket:compaction-recovery"
    if mode == "temporary":
        await loop.sessions.state.register_transient(key)
    else:
        await loop.sessions.state.get(key)
    source = tmp_path / "source.py"
    source.write_text("synthetic source evidence\n" * 100, encoding="utf-8")
    tool = loop.tools.get("read_file")
    execute = AsyncMock(wraps=tool.execute)
    monkeypatch.setattr(tool, "execute", execute)
    transport[1]["tool_call"] = ToolCallRequest("read-1", "read_file", {"path": str(source)})
    entered = asyncio.Event()
    settle = asyncio.Event()
    failures_left = 1 + len(LLMProvider._CHAT_RETRY_DELAYS) if mode == "temporary" else 0

    async def generation():
        nonlocal failures_left
        if failures_left:
            failures_left -= 1
            raise httpx.ConnectError("synthetic primary failure before temporary-session fallback")
        entered.set()
        await asyncio.Event().wait()

    if cancel_at == "generation":
        transport[1]["on_generation"] = generation
    else:
        checkpoint = loop.sessions.state.checkpoint_view

        async def gated_checkpoint(session, payload):
            if payload["phase"] == "model_input":
                entered.set()
                await settle.wait()
            await checkpoint(session, payload)

        monkeypatch.setattr(loop.sessions.state, "checkpoint_view", gated_checkpoint)
    if mode == "restart":
        loop.preserve_inflight_turns_on_shutdown()
    request = InboundMessage(
        channel="websocket", sender_id="user", chat_id="compaction-recovery",
        content="Read source.py and explain it.",
    )
    task = asyncio.create_task(loop._dispatch_one(request, asyncio.Queue()))
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
    finally:
        task.cancel()
        settle.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    transport[1]["on_generation"] = None
    if mode == "restart":
        await loop.aclose()
        sessions = SessionManager(tmp_path)
        restored = await sessions.state.read(key)
        checkpoint = restored.metadata[RUNTIME_CHECKPOINT_KEY]
        assert checkpoint["phase"] == "model_input"
        assert runtime_checkpoint_is_well_formed(checkpoint)
        assert [row["role"] for row in checkpoint["preceding_messages"]] == ["assistant", "tool"]
        assert restore_runtime_checkpoint(restored)
        await sessions.state.finish_turn(restored)
        provider = OpenAICodexProvider()
        loop = AgentLoop(
            bus=MessageBus(), provider=provider, workspace=tmp_path, session_manager=sessions,
            model=provider.default_model, context_window_tokens=200_000,
        )
    try:
        restored = await loop.sessions.state.read(key)
        assert [row["role"] for row in restored.messages] == ["user", "assistant", "tool"]
        saved = restored.provider_state
        assert saved is not None
        assert [item.get("type") for item in saved.payload["items"]][-2:] == [
            "compaction", "function_call",
        ]
        assert [row["tool_call_id"] for row in saved.pending_messages if row["role"] == "tool"] == ["read-1"]
        if mode == "temporary":
            assert SessionManager(tmp_path).read_session_file(key) is None
        await loop._dispatch_one(InboundMessage(
            channel="websocket", sender_id="user", chat_id="compaction-recovery", content="Continue",
        ), asyncio.Queue())
        bodies = transport[0]
        assert sum(body["input"][-1].get("type") == "compaction_trigger" for body in bodies) == 1
        pending = [item for item in bodies[-1]["input"] if item.get("type") == "function_call_output"]
        assert len(pending) == 1 and pending[0]["call_id"] == "read-1"
        assert "synthetic source evidence" in pending[0]["output"]
        execute.assert_awaited_once()
        final = await loop.sessions.state.read(key)
        assert [row["role"] for row in final.messages] == ["user", "assistant", "tool", "user", "assistant"]
        assert final.provider_state is not None
        if mode == "temporary":
            assert loop.sessions.read_session_file(key) is None
            assert not (tmp_path / ".nanobot" / "tool-results").exists()
    finally:
        await loop.aclose()


@pytest.mark.parametrize("existing", [False, True])
async def test_sdk_temporary_compaction_does_not_commit_to_session_owner(transport, tmp_path, existing):
    from nanobot import Nanobot

    provider = OpenAICodexProvider()
    loop = AgentLoop(
        bus=MessageBus(), provider=provider, workspace=tmp_path,
        model=provider.default_model, context_window_tokens=200_000,
    )
    bot = Nanobot(loop)
    key = "sdk:compaction"
    durable_state = build_responses_state(
        provider=provider._responses_state_provider(), model="gpt-5.6-sol",
        input_items=[{"role": "user", "content": "durable question"}],
        output_items=[{"role": "assistant", "content": "durable answer"}],
        usage=LLMUsage.reported(input_tokens=100, output_tokens=10),
    )
    if existing:
        session = await loop.sessions.state.get(key)
        session.add_message("user", "durable question")
        session.add_message("assistant", "durable answer")
        session.provider_state = durable_state
        await loop.sessions.state.prepare_input(session)
    before = loop.sessions.read_session_file(key)
    source = tmp_path / "source.py"
    source.write_text("synthetic private source", encoding="utf-8")
    transport[1]["tool_call"] = ToolCallRequest("read-1", "read_file", {"path": str(source)})
    try:
        result = await bot.run("Read source.py", session_key=key, ephemeral=True)
        assert result.content == "done"
        assert len(transport[0]) == 4  # Tool call, compaction, generation, memory-only summary.
        assert transport[0][1]["input"][-1] == {"type": "compaction_trigger"}
        assert transport[0][3]["input"][0]["type"] == "compaction"
        assert loop.sessions.read_session_file(key) == before
        current = await loop.sessions.state.read(key)
        if existing:
            assert current is not None and current.provider_state == durable_state
        else:
            assert current is None
    finally:
        await bot.aclose()


async def test_finalization_compaction_commit_failure_preserves_previous_checkpoint(
    transport, tmp_path, monkeypatch,
):
    provider = OpenAICodexProvider()
    loop = AgentLoop(
        bus=MessageBus(), provider=provider, workspace=tmp_path, max_iterations=1,
        model=provider.default_model, context_window_tokens=200_000,
    )
    source = tmp_path / "source.py"
    source.write_text("synthetic source", encoding="utf-8")
    transport[1]["tool_call"] = ToolCallRequest("read-1", "read_file", {"path": str(source)})
    checkpoint = loop.sessions.state.checkpoint_view
    drafts = []

    async def fail_compaction_commit(session, payload):
        if payload["phase"] == "model_input":
            drafts.append(session)
            raise OSError("synthetic checkpoint failure")
        await checkpoint(session, payload)

    monkeypatch.setattr(loop.sessions.state, "checkpoint_view", fail_compaction_commit)
    try:
        with pytest.raises(ProviderStateCommitError):
            await loop.process_direct("Read source.py", session_key="cli:commit-failure")
        assert len(transport[0]) == 2
        assert transport[0][-1]["input"][-1] == {"type": "compaction_trigger"}
        saved = await loop.sessions.state.read("cli:commit-failure")
        assert saved.metadata[RUNTIME_CHECKPOINT_KEY]["phase"] == "tools_completed"
        assert saved.provider_state.payload["context_tokens"] == 180_010
        assert len(drafts) == 1
        assert drafts[0].provider_state == saved.provider_state
        assert drafts[0].metadata[RUNTIME_CHECKPOINT_KEY] == saved.metadata[RUNTIME_CHECKPOINT_KEY]
    finally:
        await loop.aclose()
