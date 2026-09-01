"""Opaque conversation state for Responses API item replay."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, cast

from loguru import logger

from nanobot.providers.base import LLMUsage, ProviderConversationState
from nanobot.providers.openai_responses.converters import convert_messages

RESPONSES_STATE_KIND = "openai_responses"
RESPONSES_STATE_VERSION = 1
_ITEMS_KEY = "items"
_CONTEXT_TOKENS_KEY = "context_tokens"
_COMPACTION_ITEM_TYPES = frozenset({
    "compaction",
    "compaction_summary",
    "context_compaction",
})


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
    provider: str,
    model: str,
    preserve_reasoning: bool = False,
) -> tuple[str, list[dict[str, Any]], bool]:
    """Build a request from exact prior items plus only newly appended messages.

    The full Chat transcript remains the source for the current instructions.
    When no compatible state exists, it is converted normally as a safe
    fallback.
    """
    instructions, fallback_items = convert_messages(
        messages,
        preserve_reasoning=preserve_reasoning,
    )
    if state is None or not responses_state_matches(
        state,
        provider=provider,
        model=model,
    ):
        return instructions, fallback_items, False

    prior_items = _state_items(state)
    if prior_items is None:
        return instructions, fallback_items, False

    _, delta_items = convert_messages(
        state.pending_messages,
        preserve_reasoning=preserve_reasoning,
    )
    logger.debug(
        "Replaying Responses state: prior_items={} pending_messages={}",
        len(prior_items),
        len(state.pending_messages),
    )
    return instructions, [*deepcopy(prior_items), *delta_items], True


def build_responses_state(
    *,
    provider: str,
    model: str,
    input_items: list[dict[str, Any]],
    output_items: list[dict[str, Any]],
    usage: LLMUsage | None = None,
) -> ProviderConversationState:
    """Create the canonical next state from request input and every output item."""
    unpruned_items = [*input_items, *output_items]
    items = _prune_before_latest_output_compaction(input_items, output_items)
    if len(items) < len(unpruned_items):
        logger.info(
            "Installed Responses compaction: dropped_items={} retained_items={}",
            len(unpruned_items) - len(items),
            len(items),
        )
    payload: dict[str, Any] = {_ITEMS_KEY: deepcopy(items)}
    context_tokens = _context_tokens_from_usage(usage)
    if context_tokens > 0:
        payload[_CONTEXT_TOKENS_KEY] = context_tokens
    return ProviderConversationState(
        kind=RESPONSES_STATE_KIND,
        provider=provider,
        model=model,
        version=RESPONSES_STATE_VERSION,
        payload=payload,
    )


def responses_state_items(
    state: ProviderConversationState,
) -> list[dict[str, Any]] | None:
    """Return an isolated copy of canonical input items for tests/consumers."""
    items = _state_items(state)
    return deepcopy(items) if items is not None else None


def responses_state_context_tokens(state: ProviderConversationState) -> int:
    """Return the last server-reported active context size."""
    value = state.payload.get(_CONTEXT_TOKENS_KEY)
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return max(0, value)


def resolve_compact_threshold(
    context_window_tokens: int | None,
    max_output_tokens: int,
) -> int | None:
    """Derive Codex-compatible 90% compaction headroom for a model window."""
    if context_window_tokens is None or context_window_tokens <= 0:
        return None
    ninety_percent = max(1, context_window_tokens * 9 // 10)
    output_headroom = max(1, context_window_tokens - max(1, max_output_tokens))
    return min(ninety_percent, output_headroom)


def is_compaction_compatibility_error(exc: Exception) -> bool:
    """Recognize endpoints that reject native Responses compaction fields."""
    if getattr(exc, "compaction_unsupported", False) is True:
        return True
    response = getattr(exc, "response", None)
    status_code = getattr(exc, "status_code", None)
    if status_code is None and response is not None:
        status_code = getattr(response, "status_code", None)
    body = (
        getattr(exc, "body", None)
        or getattr(exc, "doc", None)
        or getattr(response, "text", None)
        or str(exc)
    )
    text = str(body).lower()
    has_compaction_marker = any(
        marker in text
        for marker in ("context_management", "compact_threshold", "compaction_trigger")
    )
    if not has_compaction_marker:
        return False
    return isinstance(exc, TypeError) or status_code in {400, 404, 422}


def _prune_before_latest_output_compaction(
    input_items: list[dict[str, Any]],
    output_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Drop old input only when this response emits a new compaction item.

    A canonical compacted input may intentionally retain messages before its
    compaction item. Those messages must survive ordinary subsequent responses.
    """
    latest = None
    for index, item in enumerate(output_items):
        if item.get("type") in _COMPACTION_ITEM_TYPES:
            latest = index
    if latest is None:
        return [*input_items, *output_items]
    return output_items[latest:]


def _context_tokens_from_usage(usage: LLMUsage | None) -> int:
    return usage.total_tokens if usage is not None else 0


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
