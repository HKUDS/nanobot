"""Tests for provider-owned conversation-state lifecycle coordination."""

from __future__ import annotations

from unittest.mock import MagicMock

from nanobot.providers.base import (
    LLMProvider,
    LLMResponse,
    ProviderConversationState,
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


def test_independent_request_only_exposes_native_compaction_context() -> None:
    provider = _provider(compact=True)
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
