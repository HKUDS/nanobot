"""Opaque conversation state for Responses API item replay."""

from __future__ import annotations

import hashlib
import json
import re
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
_EVIDENCE_LEDGER_PREFIX = "nanobot.retrieval_evidence.v1"
_EVIDENCE_LEDGER_CHAR_BUDGET = 16_000
_RETRIEVAL_TOOL_NAMES = frozenset({"grep", "read_file"})


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
    retained = output_items[latest:]
    ledger, entry_count = _build_retrieval_evidence_ledger(input_items)
    if ledger is not None:
        logger.info(
            "Preserved retrieval evidence across Responses compaction: entries={}",
            entry_count,
        )
        return [ledger, *retained]
    return retained


def _build_retrieval_evidence_ledger(
    input_items: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, int]:
    """Build a bounded locator ledger without retaining retrieved content."""
    existing_entries: list[dict[str, Any]] = []
    outputs: dict[str, object] = {}
    for item in input_items:
        if is_retrieval_evidence_item(item):
            existing_entries.extend(_retrieval_ledger_entries(item))
        if item.get("type") == "function_call_output":
            call_id = item.get("call_id")
            if isinstance(call_id, str):
                outputs[call_id] = item.get("output")

    new_entries: list[dict[str, Any]] = []
    for item in input_items:
        if item.get("type") != "function_call" or item.get("name") not in _RETRIEVAL_TOOL_NAMES:
            continue
        call_id = item.get("call_id")
        if not isinstance(call_id, str) or call_id not in outputs:
            continue
        arguments = _json_arguments(item.get("arguments"))
        output_text = _tool_output_text(outputs[call_id])
        entry = _retrieval_evidence_entry(str(item["name"]), arguments, output_text)
        new_entries.append(entry)

    candidates = [*existing_entries, *new_entries]
    if not candidates:
        return None, 0

    selected_reversed: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in reversed(candidates):
        key = json.dumps(entry, ensure_ascii=False, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        proposed = [entry, *reversed(selected_reversed)]
        text = _render_retrieval_ledger(proposed)
        if len(text) > _EVIDENCE_LEDGER_CHAR_BUDGET:
            continue
        selected_reversed.append(entry)
    selected = list(reversed(selected_reversed))
    if not selected:
        return None, 0
    text = _render_retrieval_ledger(selected)
    return ({
        "type": "message",
        "role": "developer",
        "content": [{"type": "input_text", "text": text}],
    }, len(selected))


def _retrieval_evidence_entry(
    tool_name: str,
    arguments: dict[str, Any],
    output: str,
) -> dict[str, Any]:
    request_keys = (
        (
            "pattern",
            "path",
            "glob",
            "type",
            "pages",
            "case_insensitive",
            "fixed_strings",
            "offset",
        )
        if tool_name == "grep"
        else ("path", "offset", "limit", "pages")
    )
    request = {
        key: _bounded_value(arguments[key])
        for key in request_keys
        if key in arguments
    }
    entry: dict[str, Any] = {
        "tool": tool_name,
        "request": request,
        "result_sha256": hashlib.sha256(output.encode("utf-8")).hexdigest()[:16],
    }
    if tool_name == "grep":
        hits = _grep_hit_locators(output, arguments.get("output_mode"))
        if hits:
            entry["hits"] = hits
    return entry


def _grep_hit_locators(output: str, output_mode: object) -> list[str]:
    hits: list[str] = []
    content_mode = output_mode in {None, "content"}
    for line in output.splitlines():
        if len(hits) >= 8:
            break
        stripped = line.strip()
        if not stripped or stripped.startswith("("):
            continue
        if content_mode:
            if not re.fullmatch(r".+:\d+(?: \[.+\])?", stripped):
                continue
        elif output_mode == "count":
            match = re.fullmatch(r"(.+): \d+", stripped)
            if match is None:
                continue
            stripped = match.group(1)
        hits.append(stripped[:500])
    return hits


def _json_arguments(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return cast(dict[str, Any], value)
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return cast(dict[str, Any], parsed) if isinstance(parsed, dict) else {}


def _tool_output_text(value: object) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _bounded_value(value: object) -> object:
    if isinstance(value, str):
        return value[:1000]
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return str(value)[:1000]


def _render_retrieval_ledger(entries: list[dict[str, Any]]) -> str:
    payload = json.dumps({"entries": entries}, ensure_ascii=False, separators=(",", ":"))
    return (
        f"{_EVIDENCE_LEDGER_PREFIX}\n{payload}\n"
        "These are compact references to retrievals completed before compaction. "
        "Use the recorded locators and ranges; retrieve content again only when needed."
    )


def is_retrieval_evidence_item(item: dict[str, Any]) -> bool:
    """Return whether a Responses input item is nanobot's compact ledger."""
    return _message_text(item).startswith(_EVIDENCE_LEDGER_PREFIX + "\n")


def _retrieval_ledger_entries(item: dict[str, Any]) -> list[dict[str, Any]]:
    text = _message_text(item)
    first_line, separator, remainder = text.partition("\n")
    if first_line != _EVIDENCE_LEDGER_PREFIX or not separator:
        return []
    payload_text, _, _ = remainder.partition("\n")
    try:
        payload = json.loads(payload_text)
    except (TypeError, ValueError):
        return []
    if not isinstance(payload, dict):
        return []
    payload_object = cast(dict[str, object], payload)
    raw_entries = payload_object.get("entries")
    if not isinstance(raw_entries, list):
        return []
    return [
        cast(dict[str, Any], entry)
        for entry in cast(list[object], raw_entries)
        if isinstance(entry, dict)
    ]


def _message_text(item: dict[str, Any]) -> str:
    content = item.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for raw_part in cast(list[object], content):
        if not isinstance(raw_part, dict):
            continue
        part = cast(dict[str, object], raw_part)
        text = part.get("text")
        if isinstance(text, str):
            parts.append(text)
    return "\n".join(parts)


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
