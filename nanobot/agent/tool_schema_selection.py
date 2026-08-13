"""Build a bounded model-visible view of registered MCP tool schemas."""

from __future__ import annotations

import json
import re
from typing import Any, cast

from nanobot.session.history_visibility import is_hidden_history_message

_WORD_RE = re.compile(r"[a-zA-Z0-9]+")
_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_STOP_WORDS = frozenset({
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "can",
    "do",
    "for",
    "from",
    "i",
    "in",
    "is",
    "it",
    "me",
    "mcp",
    "of",
    "on",
    "or",
    "please",
    "the",
    "this",
    "to",
    "tool",
    "tools",
    "use",
    "with",
    "you",
})


def _tool_name(schema: dict[str, Any]) -> str:
    function = schema.get("function")
    if isinstance(function, dict):
        name = cast(dict[str, Any], function).get("name")
        if isinstance(name, str):
            return name
    name = schema.get("name")
    return name if isinstance(name, str) else ""


def _terms(text: str) -> frozenset[str]:
    expanded = _CAMEL_BOUNDARY_RE.sub(" ", text)
    return frozenset(
        token
        for token in (match.group(0).lower() for match in _WORD_RE.finditer(expanded))
        if len(token) > 1 and token not in _STOP_WORDS
    )


def _text_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in cast(list[Any], content):
        if not isinstance(item, dict):
            continue
        block = cast(dict[str, Any], item)
        if block.get("type") == "text" and isinstance(block.get("text"), str):
            parts.append(cast(str, block["text"]))
    return "\n".join(parts)


def _latest_user_terms(messages: list[dict[str, Any]]) -> frozenset[str]:
    for message in reversed(messages):
        if message.get("role") != "user" or is_hidden_history_message(message):
            continue
        return _terms(_text_content(message.get("content")))
    return frozenset()


def schema_size_bytes(schema: dict[str, Any]) -> int:
    """Return the deterministic compact-JSON UTF-8 size of one tool schema."""
    payload = json.dumps(
        schema,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return len(payload.encode("utf-8"))


def schema_list_size_bytes(schemas: list[dict[str, Any]]) -> int:
    """Return the compact-JSON UTF-8 size of a list of tool schemas."""
    if not schemas:
        return 2  # []
    return 2 + sum(schema_size_bytes(schema) for schema in schemas) + len(schemas) - 1


def _relevance(schema: dict[str, Any], query_terms: frozenset[str]) -> tuple[int, bool]:
    name = _tool_name(schema)
    name_terms = _terms(name)
    name_overlap = query_terms & name_terms

    function = schema.get("function")
    definition = cast(dict[str, Any], function) if isinstance(function, dict) else schema
    description = definition.get("description")
    description_terms: frozenset[str] = (
        _terms(description) if isinstance(description, str) else frozenset()
    )
    description_overlap = query_terms & description_terms

    # Require two independent intent terms. A server name or generic action on
    # its own is not enough evidence to silently hide other MCP capabilities.
    clear = len(name_overlap | description_overlap) >= 2
    score = 100 * len(name_overlap) + 10 * len(description_overlap)
    return score, clear


def select_model_visible_tools(
    definitions: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    mcp_schema_budget_bytes: int,
) -> list[dict[str, Any]]:
    """Return built-ins plus a deterministic, budgeted MCP subset.

    A non-positive budget disables selection. Selection also fails open when
    user intent has no clear lexical match or when the best match cannot fit.
    The registry and executable tool set remain unchanged.
    """
    if mcp_schema_budget_bytes <= 0:
        return definitions

    builtins: list[dict[str, Any]] = []
    mcp_tools: list[dict[str, Any]] = []
    for schema in definitions:
        target = mcp_tools if _tool_name(schema).startswith("mcp_") else builtins
        target.append(schema)

    try:
        sizes = {id(schema): schema_size_bytes(schema) for schema in mcp_tools}
    except (TypeError, ValueError):
        return definitions
    if 2 + sum(sizes.values()) + max(0, len(mcp_tools) - 1) <= mcp_schema_budget_bytes:
        return definitions

    query_terms = _latest_user_terms(messages)
    if not query_terms:
        return definitions

    ranked: list[tuple[int, str, dict[str, Any]]] = []
    for schema in mcp_tools:
        score, clear = _relevance(schema, query_terms)
        if clear:
            ranked.append((score, _tool_name(schema), schema))
    if not ranked:
        return definitions

    ranked.sort(key=lambda item: (-item[0], item[1]))
    if sizes[id(ranked[0][2])] + 2 > mcp_schema_budget_bytes:
        return definitions

    selected: list[dict[str, Any]] = []
    used = 2  # JSON list brackets
    for _score, _name, schema in ranked:
        size = sizes[id(schema)]
        separator_size = 1 if selected else 0
        if used + separator_size + size <= mcp_schema_budget_bytes:
            selected.append(schema)
            used += separator_size + size

    selected.sort(key=_tool_name)
    return builtins + selected
