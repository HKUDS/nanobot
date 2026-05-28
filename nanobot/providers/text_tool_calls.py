"""Fallback parser for text-format tool calls in openai-compatible responses.

Some openai-compatible providers occasionally emit tool calls as plain text
inside the assistant message ``content`` instead of populating the structured
``tool_calls`` field of the OpenAI Chat Completions response. Observed in
practice with Xiaomi MiMo (``xiaomi_mimo`` provider); the exact format is:

    <tool_call>
    <function=tool_name>
    <parameter=key1>value1</parameter>
    <parameter=key2>value2</parameter>
    </function>
    </tool_call>

The agent runner only dispatches ``LLMResponse.tool_calls`` — any text in
``content`` is shown to the user verbatim, which breaks tool-using flows on
those providers (the user sees the raw XML markup instead of the tool result).

``maybe_inject_text_tool_calls`` post-processes an ``LLMResponse``: when the
structured ``tool_calls`` field is empty and the content contains one or more
``<tool_call>`` blocks, it parses them into ``ToolCallRequest`` objects, strips
the markup from content, and flips ``finish_reason`` from ``"stop"`` to
``"tool_calls"`` so the runner dispatches them like native calls.

The helper is a no-op when the provider already returned structured tool calls,
the content is empty, or the response is an error envelope — so providers that
behave correctly (GPT, Claude via openai-compat, etc.) are unaffected.
"""

from __future__ import annotations

import re
import secrets
import string

from loguru import logger

from nanobot.providers.base import LLMResponse, ToolCallRequest

_TOOL_CALL_BLOCK_RE = re.compile(
    r"<tool_call>\s*(.*?)\s*</tool_call>",
    re.DOTALL,
)
_FUNCTION_RE = re.compile(
    r"<function=([^>]+)>\s*(.*?)\s*</function>",
    re.DOTALL,
)
_PARAMETER_RE = re.compile(
    r"<parameter=([^>]+)>(.*?)</parameter>",
    re.DOTALL,
)

_ALNUM = string.ascii_letters + string.digits


def _short_tool_id() -> str:
    """9-char alphanumeric ID compatible with all providers (incl. Mistral)."""
    return "".join(secrets.choice(_ALNUM) for _ in range(9))


def parse_text_tool_calls(content: str) -> tuple[str, list[ToolCallRequest]]:
    """Extract ``<tool_call>`` blocks (text-format) from *content*.

    Returns ``(cleaned_content, tool_calls)``. When no blocks are found,
    returns ``(content, [])`` unchanged. Parameter values are kept as
    strings — the tool registry's ``cast_params`` handles type coercion
    against the tool's JSON schema downstream.
    """
    if not content or "<tool_call>" not in content:
        return content, []

    tool_calls: list[ToolCallRequest] = []
    for block_match in _TOOL_CALL_BLOCK_RE.finditer(content):
        body = block_match.group(1)
        func_match = _FUNCTION_RE.search(body)
        if not func_match:
            logger.warning("Malformed <tool_call> block: missing <function=...> tag")
            continue
        name = func_match.group(1).strip()
        params_body = func_match.group(2)
        args: dict[str, str] = {}
        for param_match in _PARAMETER_RE.finditer(params_body):
            key = param_match.group(1).strip()
            value = param_match.group(2)
            args[key] = value
        if not name:
            logger.warning("Malformed <tool_call> block: empty function name")
            continue
        tool_calls.append(ToolCallRequest(
            id=_short_tool_id(),
            name=name,
            arguments=args,
        ))

    if not tool_calls:
        return content, []

    cleaned = _TOOL_CALL_BLOCK_RE.sub("", content).strip()
    return cleaned, tool_calls


def maybe_inject_text_tool_calls(response: LLMResponse) -> LLMResponse:
    """Lift any text-format tool calls into ``response.tool_calls``.

    No-op when the provider already returned structured tool calls, when
    content is empty, or when the response is an error envelope. Mutates
    and returns the same ``response`` for convenience.
    """
    if response.tool_calls or not response.content:
        return response
    if response.finish_reason == "error":
        return response

    cleaned, parsed = parse_text_tool_calls(response.content)
    if not parsed:
        return response

    response.content = cleaned or None
    response.tool_calls = parsed
    if response.finish_reason == "stop":
        response.finish_reason = "tool_calls"
    return response
