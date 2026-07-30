"""Provider-owned conversation-state lifecycle coordination."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, cast

from nanobot.providers.base import (
    LLMProvider,
    LLMResponse,
    ProviderConversationState,
)

_PROVIDER_STATE_OUTPUT_META = "provider_state_output"
_PROVIDER_STATE_BOUNDARY_META = "provider_state_boundary"


def allows_conversation_message_merge(message: dict[str, Any]) -> bool:
    """Return whether new same-role input may merge into *message*."""
    internal_meta = cast(object, message.get("_meta"))
    return not (
        isinstance(internal_meta, dict)
        and cast(dict[str, Any], internal_meta).get(
            _PROVIDER_STATE_BOUNDARY_META
        ) is True
    )


class ProviderConversationStateController:
    """Keep provider conversation-state semantics outside the agent runner.

    The runner owns the tool loop and reports lifecycle events here. This
    controller owns capability checks, transcript deltas, response projections,
    retry transitions, and durable snapshots for provider-private state.
    """

    def __init__(
        self,
        *,
        provider: LLMProvider,
        model: str | None,
        messages: list[dict[str, Any]],
        state: ProviderConversationState | None = None,
        initial_state_messages: list[dict[str, Any]] | None = None,
    ) -> None:
        self._provider = provider
        self._model = model
        self._state = (
            state
            if state is not None
            and provider.can_resume_conversation_state(state, model)
            else None
        )
        self._boundary = len(messages)
        self._initial_state_messages = (
            deepcopy(initial_state_messages or [])
            if self._state is not None
            else None
        )
        self._request_messages: list[dict[str, Any]] = []

    def independent_request_options(
        self,
        *,
        context_window_tokens: int | None,
    ) -> dict[str, Any]:
        """Return provider options for a request that does not resume state."""
        if not self._provider.supports_native_compaction(self._model):
            return {}
        return {"context_window_tokens": context_window_tokens}

    def prepare_request(
        self,
        messages: list[dict[str, Any]],
        *,
        context_window_tokens: int | None,
        supplemental_messages: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Build options for the next request and remember its durable delta."""
        options = self.independent_request_options(
            context_window_tokens=context_window_tokens,
        )
        if self._state is None:
            self._initial_state_messages = None
            self._request_messages = []
            return options
        if not self._provider.can_resume_conversation_state(
            self._state,
            self._model,
        ):
            self._state = None
            self._initial_state_messages = None
            self._request_messages = []
            return options

        request_messages = (
            deepcopy(self._initial_state_messages)
            if self._initial_state_messages is not None
            else self._messages_after_boundary(messages)
        )
        self._initial_state_messages = None
        self._request_messages = deepcopy(request_messages)
        options["provider_state"] = self._state
        options["provider_state_messages"] = [
            *request_messages,
            *deepcopy(supplemental_messages or []),
        ]
        return options

    def observe_response(
        self,
        response: LLMResponse,
        messages: list[dict[str, Any]],
    ) -> None:
        """Advance, preserve, or discard state after one provider response."""
        candidate = response.provider_state
        if (
            candidate is not None
            and self._provider.can_resume_conversation_state(
                candidate,
                self._model,
            )
        ):
            self._state = candidate
            self._boundary = len(messages)
            self._seal_boundary(messages)
        elif (
            response.finish_reason == "error"
            and LLMProvider.is_transient_response(response)
        ):
            if self._state is not None and self._request_messages:
                self._state = self._state.with_pending_messages([
                    *self._state.pending_messages,
                    *self._request_messages,
                ])
            self._boundary = len(messages)
        else:
            self._state = None
            self._boundary = len(messages)
        self._request_messages = []

    @staticmethod
    def project_response_message(
        message: dict[str, Any],
        response: LLMResponse,
    ) -> dict[str, Any]:
        """Mark a Chat projection already represented by provider output."""
        if response.provider_state is None:
            return message
        internal_meta = dict(message.get("_meta") or {})
        internal_meta[_PROVIDER_STATE_OUTPUT_META] = True
        message["_meta"] = internal_meta
        return message

    def checkpoint(
        self,
        messages: list[dict[str, Any]],
    ) -> ProviderConversationState | None:
        """Return a durable state snapshot without changing live state."""
        if self._state is None:
            return None
        return self._state.with_pending_messages([
            *self._state.pending_messages,
            *self._messages_after_boundary(messages),
        ])

    def finish(
        self,
        messages: list[dict[str, Any]],
    ) -> ProviderConversationState | None:
        """Return the final durable state after all runner messages are known."""
        self._state = self.checkpoint(messages)
        return self._state

    def _messages_after_boundary(
        self,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        pending: list[dict[str, Any]] = []
        for message in messages[self._boundary:]:
            internal_meta = cast(object, message.get("_meta"))
            if (
                isinstance(internal_meta, dict)
                and cast(dict[str, Any], internal_meta).get(
                    _PROVIDER_STATE_OUTPUT_META
                ) is True
            ):
                continue
            pending.append(deepcopy(message))
        return pending

    @staticmethod
    def _seal_boundary(messages: list[dict[str, Any]]) -> None:
        """Prevent later same-role injection merging across a state boundary."""
        if not messages:
            return
        internal_meta = dict(messages[-1].get("_meta") or {})
        internal_meta[_PROVIDER_STATE_BOUNDARY_META] = True
        messages[-1]["_meta"] = internal_meta
