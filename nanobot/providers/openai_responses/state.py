from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, cast

from loguru import logger

from nanobot.providers.base import LLMResponse, LLMUsage, ProviderConversationState
from nanobot.providers.openai_responses.converters import convert_messages
from nanobot.providers.openai_responses.errors import (
    COMPACTION_FEATURES,
    is_unsupported_feature_error,
    response_error_details,
)

RESPONSES_STATE_KIND = "openai_responses"
RESPONSES_STATE_VERSION = 1
REPLAYABLE_FINISH_REASONS = frozenset({"stop", "tool_calls", "function_call"})
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
    prior_items = (
        _state_items(state)
        if state is not None and responses_state_matches(state, provider=provider, model=model)
        else None
    )
    if prior_items is None:
        instructions, items = convert_messages(messages, preserve_reasoning=preserve_reasoning)
        return instructions, items, False

    instructions = ""
    for message in reversed(messages):
        if message.get("role") == "system":
            content = message.get("content")
            instructions = content if isinstance(content, str) else ""
            break
    assert state is not None
    _, delta_items = convert_messages(
        state.pending_messages,
        preserve_reasoning=preserve_reasoning,
    )
    logger.debug(
        "Replaying Responses state: prior_items={} pending_messages={}",
        len(prior_items),
        len(state.pending_messages),
    )
    replayed_items = _prepare_replayed_items(prior_items)
    return instructions, [*replayed_items, *delta_items], True


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


def attach_responses_state(
    result: LLMResponse,
    *,
    provider: str,
    model: str,
    input_items: list[dict[str, Any]],
    output_items: list[dict[str, Any]],
) -> None:
    """Advance replay and compaction state only after a completed usable response."""
    if result.finish_reason not in REPLAYABLE_FINISH_REASONS:
        return
    result.provider_state = build_responses_state(
        provider=provider, model=model, input_items=input_items,
        output_items=output_items, usage=result.usage,
    )
    result.provider_compaction_state = build_responses_compaction_state(
        provider=provider, model=model, output_items=output_items,
    )
    result.provider_compaction_applied = result.provider_compaction_state is not None
    if result.provider_compaction_applied:
        result.provider_compaction_scope = "current_request"


def build_responses_compaction_state(
    *,
    provider: str,
    model: str,
    output_items: list[dict[str, Any]],
) -> ProviderConversationState | None:
    """Return the state at the latest native compaction output boundary."""
    latest = None
    for index, item in enumerate(output_items):
        if item.get("type") in _COMPACTION_ITEM_TYPES:
            latest = index
    if latest is None:
        return None
    return ProviderConversationState(
        kind=RESPONSES_STATE_KIND,
        provider=provider,
        model=model,
        version=RESPONSES_STATE_VERSION,
        payload={_ITEMS_KEY: [deepcopy(output_items[latest])]},
    )


def responses_state_items(
    state: ProviderConversationState,
) -> list[dict[str, Any]] | None:
    """Return an isolated copy of canonical input items for tests/consumers."""
    items = _state_items(state)
    return deepcopy(items) if items is not None else None


def responses_state_before_input(
    state: ProviderConversationState | None,
    messages: list[dict[str, Any]],
    boundary: int,
) -> ProviderConversationState | None:
    """Recover native items strictly before the original user record at *boundary*.

    Walk from both origins, including the target as a witness but not in the
    result. Never search forward to resynchronize: repeated turns are legal.
    """
    if (
        state is None or state.kind != RESPONSES_STATE_KIND
        or state.version != RESPONSES_STATE_VERSION or state.pending_messages
        or not 0 < boundary < len(messages) or messages[boundary].get("role") != "user"
        or messages[0].get("role") != "user"
    ):
        return None
    items = _state_items(state)
    if not items or any(isinstance(kind := item.get("type"), str) and kind in _COMPACTION_ITEM_TYPES
                        for item in items):
        return None

    cursor = 0

    def take(*, assistant: bool = False) -> dict[str, Any]:
        nonlocal cursor
        while cursor < len(items):
            item = items[cursor]
            cursor += 1
            if item.get("status") not in (None, "completed"):
                break
            # Only an assistant record can anchor otherwise opaque reasoning.
            if not assistant or item.get("type") != "reasoning":
                return item
        return {}

    seen: set[str] = set()
    pending: set[str] = set()
    for index in range(boundary + 1):
        message = messages[index]
        role, content = message.get("role"), message.get("content")
        if pending and role != "tool":
            return None
        if role == "user":
            start = cursor
            if not _matches_text_item(take(), "user", content):
                return None
            if index == boundary:
                return ProviderConversationState(
                    kind=state.kind, version=state.version, provider=state.provider, model=state.model,
                    payload={_ITEMS_KEY: deepcopy(items[:start])},
                )
        elif role == "assistant":
            calls = message.get("tool_calls", [])
            if not isinstance(calls, list) or (content in (None, "") and not calls):
                return None
            if content not in (None, "") and not _matches_text_item(take(assistant=True), role, content):
                return None
            for call in cast(list[object], calls):
                full_id = _matched_call_id(call, take(assistant=True))
                if full_id is None or (call_id := full_id.partition("|")[0]) in seen:
                    return None
                seen.add(call_id)
                pending.add(full_id)
        elif role == "tool":
            full_id = message.get("tool_call_id")
            item = take()
            if (not isinstance(full_id, str) or full_id not in pending or not isinstance(content, str)
                    or item.get("type") != "function_call_output" or item.get("output") != content
                    or item.get("call_id") != full_id.partition("|")[0]):
                return None
            pending.remove(full_id)
        else:
            return None
    return None


def _matches_text_item(item: dict[str, Any], role: str, text: Any) -> bool:
    if not isinstance(text, str) or item.get("role") != role or item.get("type", "message") != "message":
        return False
    content = item.get("content")
    if isinstance(content, str):
        return content == text
    if not isinstance(content, list):
        return False
    blocks = cast(list[object], content)
    if len(blocks) != 1 or not isinstance(blocks[0], dict):
        return False
    block = cast(dict[str, Any], blocks[0])
    return block.get("type") == ("input_text" if role == "user" else "output_text") and block.get("text") == text


def _matched_call_id(raw: object, item: dict[str, Any]) -> str | None:
    if not isinstance(raw, dict) or item.get("type") != "function_call":
        return None
    call = cast(dict[str, Any], raw)
    full_id, fn = call.get("id"), call.get("function")
    if not isinstance(full_id, str) or not isinstance(fn, dict) or call.get("type", "function") != "function":
        return None
    function = cast(dict[str, Any], fn)
    call_id, _, item_id = full_id.partition("|")
    name, arguments = function.get("name"), function.get("arguments")
    if (call_id and item.get("call_id") == call_id and (not item_id or item.get("id") in (None, item_id))
            and isinstance(name, str) and name and item.get("name") == name
            and isinstance(arguments, str) and _same_call_arguments(arguments, item.get("arguments"))):
        return full_id
    return None


def _same_call_arguments(chat: str, native: Any) -> bool:
    # Accept exact JSON or the two common JSON serializations. Requiring both
    # sides to round-trip avoids equating duplicate keys or repaired arguments.
    if not isinstance(native, str):
        return False
    try:
        value = json.loads(chat)
        if not isinstance(value, dict):
            return False
        if native == chat:
            return True
        forms = (json.dumps(value, ensure_ascii=False, allow_nan=False),
                 json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")))
        return chat in forms and native in forms
    except (ValueError, RecursionError):
        return False


def responses_state_context_tokens(state: ProviderConversationState) -> int:
    """Return the reported active size or a locally estimated compacted prefix size."""
    value = state.payload.get(_CONTEXT_TOKENS_KEY)
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return max(0, value)


def responses_compaction_items(result: LLMResponse) -> list[dict[str, Any]]:
    """Return replay items ending at a valid trigger-compaction boundary."""
    items = responses_state_items(result.provider_state) if result.provider_state is not None else None
    if not items or items[-1].get("type") not in _COMPACTION_ITEM_TYPES:
        raise RuntimeError("Responses compaction returned no compaction item")
    return items


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
    status, body = response_error_details(exc)
    return is_unsupported_feature_error(status, body, COMPACTION_FEATURES)


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


def _prepare_replayed_items(
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Copy provider state and remove output-only fields rejected on replay."""
    replayed_items = deepcopy(items)
    for item in replayed_items:
        if item.get("type") == "reasoning":
            item.pop("status", None)
    return replayed_items


def without_response_item_ids(
    request_body: dict[str, Any],
) -> dict[str, Any]:
    """Strip output item IDs for endpoints that replay stateless input without IDs."""
    if request_body.get("store") is True:
        return request_body
    raw_input = request_body.get("input")
    if not isinstance(raw_input, list):
        return request_body

    input_items: list[object] = cast(list[object], raw_input)
    sanitized_input: list[object] = []
    for raw_item in input_items:
        if not isinstance(raw_item, dict):
            sanitized_input.append(raw_item)
            continue
        item = cast(dict[str, Any], raw_item)
        sanitized_input.append({key: value for key, value in item.items() if key != "id"})

    body = dict(request_body)
    body["input"] = sanitized_input
    return body
