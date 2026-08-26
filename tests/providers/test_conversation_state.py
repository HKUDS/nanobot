"""Tests for provider-owned conversation-state lifecycle coordination."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nanobot.providers.base import (
    LLMProvider,
    LLMResponse,
    ProviderCallContext,
    ProviderConversationState,
    ToolCallRequest,
)
from nanobot.providers.conversation_state import (
    ProviderConversationStateController,
    allows_conversation_message_merge,
)


def _provider(*, resumable: bool = True, compact: bool = False) -> MagicMock:
    provider = MagicMock(spec=LLMProvider)
    provider.can_resume_conversation_state.return_value = resumable
    provider.supports_native_compaction.return_value = compact
    return provider


def _state(label: str, *, pending: list[dict] | None = None) -> ProviderConversationState:
    return ProviderConversationState(
        kind="openai_responses",
        provider="openai:test",
        model="gpt-5.6",
        version=1,
        payload={"items": [{"type": "reasoning", "encrypted_content": label}]},
        pending_messages=pending or [],
    )


def test_controller_replays_only_messages_after_provider_output() -> None:
    provider = _provider()
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "run a tool"},
    ]
    controller = ProviderConversationStateController(
        provider=provider,
        model="gpt-5.6",
        messages=messages,
    )
    state = _state("first")

    controller.prepare_request(messages, context_window_tokens=200_000)
    response = LLMResponse(content=None, provider_state=state)
    controller.observe_response(response, messages)
    assert allows_conversation_message_merge(messages[-1]) is False

    messages.append(controller.project_response_message(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": "call_1", "type": "function"}],
        },
        response,
    ))
    tool_message = {
        "role": "tool",
        "tool_call_id": "call_1",
        "content": "tool result",
    }
    messages.append(tool_message)

    provider_context = controller.prepare_request(
        messages,
        context_window_tokens=200_000,
    )

    assert provider_context is not None
    assert provider_context.conversation_state is not None
    assert provider_context.conversation_state.payload == state.payload
    assert provider_context.conversation_state.pending_messages == [tool_message]
    assert controller.checkpoint(messages).pending_messages == [tool_message]


def test_controller_uses_governed_messages_for_provider_state_delta() -> None:
    provider = _provider()
    messages = [
        {"role": "user", "content": "run a tool"},
    ]
    controller = ProviderConversationStateController(
        provider=provider,
        model="gpt-5.6",
        messages=messages,
    )
    state = _state("first")

    controller.prepare_request(messages, context_window_tokens=200_000)
    response = LLMResponse(content=None, provider_state=state)
    controller.observe_response(response, messages)
    messages.extend([
        controller.project_response_message(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "call_1", "type": "function"}],
            },
            response,
        ),
        {
            "role": "tool",
            "tool_call_id": "call_1",
            "content": "raw oversized result",
        },
    ])
    governed_messages = [
        messages[0],
        messages[1],
        {
            "role": "tool",
            "tool_call_id": "call_1",
            "content": "compacted result",
        },
    ]

    provider_context = controller.prepare_request(
        messages,
        context_window_tokens=200_000,
        model_messages=governed_messages,
    )

    assert provider_context is not None
    assert provider_context.conversation_state is not None
    assert provider_context.conversation_state.pending_messages == [{
        "role": "tool",
        "tool_call_id": "call_1",
        "content": "compacted result",
    }]
    assert controller.checkpoint(messages).pending_messages[-1]["content"] == (
        "raw oversized result"
    )
    governed_checkpoint = controller.checkpoint(
        messages,
        model_messages=governed_messages,
    )
    assert governed_checkpoint is not None
    assert governed_checkpoint.pending_messages[-1]["content"] == "compacted result"


def test_transient_response_preserves_only_durable_request_messages() -> None:
    provider = _provider()
    current_message = {"role": "user", "content": "continue"}
    supplemental = {"role": "user", "content": "internal finalization retry"}
    messages = [{"role": "system", "content": "system"}, current_message]
    controller = ProviderConversationStateController(
        provider=provider,
        model="gpt-5.6",
        messages=messages,
        state=_state("saved", pending=[
            {"role": "tool", "content": "prior"},
            current_message,
        ]),
    )

    provider_context = controller.prepare_request(
        messages,
        context_window_tokens=200_000,
        supplemental_messages=[supplemental],
    )
    assert provider_context is not None
    assert provider_context.conversation_state is not None
    assert provider_context.conversation_state.pending_messages == [
        {"role": "tool", "content": "prior"},
        current_message,
        supplemental,
    ]

    controller.observe_response(
        LLMResponse(
            content="temporary failure",
            finish_reason="error",
            error_kind="timeout",
        ),
        messages,
    )
    placeholder = {"role": "assistant", "content": "model error"}
    messages.append(placeholder)

    state = controller.finish(messages)
    assert state is not None
    assert state.pending_messages == [
        {"role": "tool", "content": "prior"},
        current_message,
        placeholder,
    ]


def test_non_retryable_response_discards_saved_state() -> None:
    provider = _provider()
    messages = [{"role": "user", "content": "continue"}]
    controller = ProviderConversationStateController(
        provider=provider,
        model="gpt-5.6",
        messages=messages,
        state=_state("saved"),
    )

    controller.prepare_request(messages, context_window_tokens=200_000)
    controller.observe_response(
        LLMResponse(
            content="invalid request",
            finish_reason="error",
            error_status_code=400,
            error_should_retry=False,
        ),
        messages,
    )

    assert controller.finish(messages) is None


@pytest.mark.parametrize(
    ("finish_reason", "exposes_tool_call"),
    [
        ("length", False),
        ("length", True),
        ("refusal", True),
        ("content_filter", True),
    ],
)
def test_terminal_response_discards_candidate_state(
    finish_reason: str,
    exposes_tool_call: bool,
) -> None:
    provider = _provider()
    messages = [{"role": "user", "content": "continue"}]
    controller = ProviderConversationStateController(
        provider=provider,
        model="gpt-5.6",
        messages=messages,
        state=_state("saved"),
    )

    controller.prepare_request(messages, context_window_tokens=200_000)
    candidate = ProviderConversationState(
        kind="openai_responses",
        provider="openai:test",
        model="gpt-5.6",
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
    response = LLMResponse(
        content="terminal response",
        tool_calls=(
            [ToolCallRequest(id="call_1", name="exec", arguments={})]
            if exposes_tool_call
            else []
        ),
        finish_reason=finish_reason,
        provider_state=candidate,
    )
    assert response.has_tool_calls is exposes_tool_call
    assert response.should_execute_tools is False

    controller.observe_response(response, messages)

    assert controller.finish(messages) is None


def test_independent_request_exposes_context_without_capability_check() -> None:
    provider = _provider(compact=False)
    messages = [{"role": "user", "content": "hello"}]
    controller = ProviderConversationStateController(
        provider=provider,
        model="gpt-5.6",
        messages=messages,
        state=_state("saved"),
    )

    provider_context = controller.independent_request_context(
        context_window_tokens=200_000,
    )
    assert provider_context is not None
    assert provider_context.conversation_state is None
    assert provider_context.context_window_tokens == 200_000
    provider.supports_native_compaction.assert_not_called()


def test_independent_request_exposes_session_id_without_token_budget() -> None:
    provider = _provider(compact=False)
    messages = [{"role": "user", "content": "hello"}]
    controller = ProviderConversationStateController(
        provider=provider,
        model="gpt-5.6",
        messages=messages,
        session_id="webui:cache-test",
    )

    provider_context = controller.prepare_request(
        messages,
        context_window_tokens=None,
    )

    assert provider_context == ProviderCallContext(
        session_id="webui:cache-test",
    )
