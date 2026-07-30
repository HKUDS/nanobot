"""Opaque conversation state for Responses API item replay."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, cast

from nanobot.providers.base import ProviderConversationState
from nanobot.providers.openai_responses.converters import convert_messages

RESPONSES_STATE_KIND = "openai_responses"
RESPONSES_STATE_VERSION = 1
_ITEMS_KEY = "items"


def responses_state_matches(
    state: ProviderConversationState,
    *,
    provider: str,
    model: str,
) -> bool:
    """Return whether *state* belongs to this exact Responses endpoint/model."""
    return (
        state.kind == RESPONSES_STATE_KIND
        and state.version == RESPONSES_STATE_VERSION
        and state.provider == provider
        and state.model == model
        and _state_items(state) is not None
    )


def prepare_responses_input(
    messages: list[dict[str, Any]],
    *,
    state: ProviderConversationState | None,
    state_messages: list[dict[str, Any]] | None,
    provider: str,
    model: str,
) -> tuple[str, list[dict[str, Any]], bool]:
    """Build a request from exact prior items plus only newly appended messages.

    The full Chat transcript remains the source for the current instructions.
    When no compatible state exists, it is converted normally as a safe
    fallback.
    """
    instructions, fallback_items = convert_messages(messages)
    if state is None or not responses_state_matches(
        state,
        provider=provider,
        model=model,
    ):
        return instructions, fallback_items, False

    prior_items = _state_items(state)
    if prior_items is None:
        return instructions, fallback_items, False

    pending = [*state.pending_messages, *(state_messages or [])]
    _, delta_items = convert_messages(pending)
    return instructions, [*deepcopy(prior_items), *delta_items], True


def build_responses_state(
    *,
    provider: str,
    model: str,
    input_items: list[dict[str, Any]],
    output_items: list[dict[str, Any]],
) -> ProviderConversationState:
    """Create the canonical next state from request input and every output item."""
    return ProviderConversationState(
        kind=RESPONSES_STATE_KIND,
        provider=provider,
        model=model,
        version=RESPONSES_STATE_VERSION,
        payload={_ITEMS_KEY: deepcopy([*input_items, *output_items])},
    )


def responses_state_items(
    state: ProviderConversationState,
) -> list[dict[str, Any]] | None:
    """Return an isolated copy of canonical input items for tests/consumers."""
    items = _state_items(state)
    return deepcopy(items) if items is not None else None


def _state_items(
    state: ProviderConversationState,
) -> list[dict[str, Any]] | None:
    raw_items = state.payload.get(_ITEMS_KEY)
    if not isinstance(raw_items, list):
        return None
    items: list[dict[str, Any]] = []
    for raw in cast(list[object], raw_items):
        if not isinstance(raw, dict):
            return None
        items.append(cast(dict[str, Any], raw))
    return items
