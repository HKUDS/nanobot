"""Provider-owned conversation-state lifecycle coordination."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, cast

from nanobot.providers.base import (
    LLMProvider,
    LLMResponse,
    ProviderCallContext,
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
        session_id: str | None = None,
    ) -> None:
        self._provider = provider
        self._model = model
        self._session_id = session_id
        self._state = (
            state
            if state is not None
            and provider.can_resume_conversation_state(state, model)
            else None
        )
        self._boundary = len(messages)
        self._request_messages: list[dict[str, Any]] = []

    def independent_request_context(
        self,
        *,
        context_window_tokens: int | None,
    ) -> ProviderCallContext | None:
        """Return typed provider context for a request that does not resume state."""
        if context_window_tokens is None and self._session_id is None:
            return None
        return ProviderCallContext(
            context_window_tokens=context_window_tokens,
            session_id=self._session_id,
        )

    def prepare_request(
        self,
        messages: list[dict[str, Any]],
        *,
        context_window_tokens: int | None,
        model_messages: list[dict[str, Any]] | None = None,
        supplemental_messages: list[dict[str, Any]] | None = None,
    ) -> ProviderCallContext | None:
        """Build typed context for the next request and remember its durable delta."""
        independent_context = self.independent_request_context(
            context_window_tokens=context_window_tokens,
        )
        if self._state is None:
            self._request_messages = []
            return independent_context
        if not self._provider.can_resume_conversation_state(
            self._state,
            self._model,
        ):
            self._state = None
            self._request_messages = []
            return independent_context

        durable_messages = self._messages_after_boundary(messages)
        governed_messages = (
            self._model_messages_after_boundary(model_messages)
            if model_messages is not None and durable_messages
            else None
        )
        request_messages = (
            governed_messages
            if governed_messages is not None
            else durable_messages
        )
        supplemental = deepcopy(supplemental_messages or [])
        self._request_messages = deepcopy(request_messages)
        request_state = self._state.with_pending_messages([
            *self._state.pending_messages,
            *request_messages,
            *supplemental,
        ])
        return ProviderCallContext(
            conversation_state=request_state,
            context_window_tokens=(
                independent_context.context_window_tokens
                if independent_context is not None
                else None
            ),
            session_id=self._session_id,
        )

    def observe_response(
        self,
        response: LLMResponse,
        messages: list[dict[str, Any]],
        *,
        adopt_candidate_state: bool = True,
    ) -> None:
        """Advance, preserve, or discard state after one provider response."""
        candidate = response.provider_state if adopt_candidate_state else None
        candidate_is_replayable = response.finish_reason in {
            "stop",
            "tool_calls",
            "function_call",
        }
        if (
            candidate is not None
            and candidate_is_replayable
            and self._provider.can_resume_conversation_state(
                candidate,
                self._model,
            )
        ):
            self._state = candidate
            self._boundary = len(messages)
            self._seal_boundary(messages)
        elif response.finish_reason == "error" and (
            response.preserve_provider_state_on_error is True
            or (
                response.preserve_provider_state_on_error is None
                and LLMProvider.is_transient_response(response)
            )
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
        *,
        model_messages: list[dict[str, Any]] | None = None,
    ) -> ProviderConversationState | None:
        """Return a durable state snapshot without changing live state."""
        if self._state is None:
            return None
        durable_messages = self._messages_after_boundary(messages)
        governed_messages = (
            self._model_messages_after_boundary(model_messages)
            if model_messages is not None and durable_messages
            else None
        )
        pending_messages = (
            governed_messages
            if governed_messages is not None
            else durable_messages
        )
        return self._state.with_pending_messages([
            *self._state.pending_messages,
            *pending_messages,
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
    def _model_messages_after_boundary(
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]] | None:
        """Return the governed delta after the latest provider-owned boundary."""
        boundary = None
        for idx in range(len(messages) - 1, -1, -1):
            internal_meta = cast(object, messages[idx].get("_meta"))
            if (
                isinstance(internal_meta, dict)
                and cast(dict[str, Any], internal_meta).get(
                    _PROVIDER_STATE_BOUNDARY_META
                ) is True
            ):
                boundary = idx
                break
        if boundary is None:
            return None

        pending: list[dict[str, Any]] = []
        for message in messages[boundary + 1:]:
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
