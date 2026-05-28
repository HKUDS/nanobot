"""Tests for the text-format tool-call fallback parser."""

import logging
import re

from loguru import logger as loguru_logger

from nanobot.providers.base import LLMResponse, ToolCallRequest
from nanobot.providers.text_tool_calls import (
    _ALNUM,
    _short_tool_id,
    maybe_inject_text_tool_calls,
    parse_text_tool_calls,
)

_MIMO_BLOCK = (
    "<tool_call>\n"
    "<function=read_file>\n"
    "<parameter=path>/etc/hosts</parameter>\n"
    "<parameter=encoding>utf-8</parameter>\n"
    "</function>\n"
    "</tool_call>"
)


def test_short_tool_id_is_9_char_alphanumeric():
    """Mistral and other strict providers require short alphanumeric IDs."""
    tool_id = _short_tool_id()
    assert len(tool_id) == 9
    assert all(ch in _ALNUM for ch in tool_id)


def test_parse_extracts_function_and_parameters():
    cleaned, calls = parse_text_tool_calls(_MIMO_BLOCK)
    assert cleaned == ""
    assert len(calls) == 1
    call = calls[0]
    assert isinstance(call, ToolCallRequest)
    assert call.name == "read_file"
    assert call.arguments == {"path": "/etc/hosts", "encoding": "utf-8"}


def test_parse_strips_blocks_from_mixed_content():
    """After stripping tool-call XML the surrounding prose must remain clean."""
    content = (
        "Sure, I'll read that file for you.\n\n"
        f"{_MIMO_BLOCK}\n\n"
        "Let me know if you want me to do anything else."
    )
    cleaned, calls = parse_text_tool_calls(content)
    assert len(calls) == 1
    assert "<tool_call>" not in cleaned
    assert "</tool_call>" not in cleaned
    assert "I'll read that file" in cleaned
    assert "Let me know" in cleaned
    # No leading/trailing whitespace artifacts from the strip.
    assert cleaned == cleaned.strip()


def test_parse_handles_multiple_blocks():
    content = (
        f"{_MIMO_BLOCK}\n"
        "<tool_call>\n"
        "<function=list_dir>\n"
        "<parameter=path>/tmp</parameter>\n"
        "</function>\n"
        "</tool_call>"
    )
    cleaned, calls = parse_text_tool_calls(content)
    assert cleaned == ""
    assert [c.name for c in calls] == ["read_file", "list_dir"]
    assert calls[1].arguments == {"path": "/tmp"}


def test_parse_no_blocks_is_noop():
    cleaned, calls = parse_text_tool_calls("just plain text, no tools here")
    assert cleaned == "just plain text, no tools here"
    assert calls == []


def test_parse_empty_content_is_noop():
    assert parse_text_tool_calls("") == ("", [])
    assert parse_text_tool_calls(None) == (None, [])


def test_parse_malformed_block_emits_warning(caplog):
    """Missing <function=...> inside <tool_call> should warn, not silently drop."""
    bad = "<tool_call>\n<parameter=x>1</parameter>\n</tool_call>"
    handler_id = loguru_logger.add(caplog.handler, format="{message}", level="WARNING")
    try:
        with caplog.at_level(logging.WARNING):
            cleaned, calls = parse_text_tool_calls(bad)
    finally:
        loguru_logger.remove(handler_id)
    assert calls == []
    assert cleaned == bad  # malformed -> unchanged content
    assert any(
        "Malformed <tool_call> block" in r.getMessage() for r in caplog.records
    )


def test_parse_empty_function_name_emits_warning(caplog):
    bad = "<tool_call>\n<function=>\n</function>\n</tool_call>"
    handler_id = loguru_logger.add(caplog.handler, format="{message}", level="WARNING")
    try:
        with caplog.at_level(logging.WARNING):
            cleaned, calls = parse_text_tool_calls(bad)
    finally:
        loguru_logger.remove(handler_id)
    # Regex requires at least one char inside function=...; either no match
    # (warns about missing function tag) or empty name (warns about empty name).
    assert calls == []
    assert any("Malformed <tool_call> block" in r.getMessage() for r in caplog.records)


# ---------- integration: maybe_inject_text_tool_calls ----------


def test_inject_lifts_calls_and_flips_finish_reason():
    """The reviewer-requested integration test: text tool_calls get lifted into
    the structured field and finish_reason is flipped from "stop" to "tool_calls"."""
    response = LLMResponse(
        content=f"Reading the file now.\n{_MIMO_BLOCK}",
        tool_calls=[],
        finish_reason="stop",
    )
    out = maybe_inject_text_tool_calls(response)

    # Same object, mutated in place.
    assert out is response
    # tool_calls populated.
    assert len(out.tool_calls) == 1
    assert out.tool_calls[0].name == "read_file"
    assert out.tool_calls[0].arguments == {"path": "/etc/hosts", "encoding": "utf-8"}
    # ID format matches the rest of the provider (9 alphanumeric chars).
    assert re.fullmatch(r"[A-Za-z0-9]{9}", out.tool_calls[0].id)
    # finish_reason flipped so AgentRunner dispatches the call.
    assert out.finish_reason == "tool_calls"
    # Surrounding prose preserved, XML stripped.
    assert out.content == "Reading the file now."


def test_inject_noop_when_tool_calls_already_present():
    """Providers returning structured tool_calls must not be touched."""
    existing = ToolCallRequest(id="abc123def", name="foo", arguments={"x": 1})
    response = LLMResponse(
        content=_MIMO_BLOCK,  # would parse if asked, but we shouldn't
        tool_calls=[existing],
        finish_reason="tool_calls",
    )
    out = maybe_inject_text_tool_calls(response)
    assert out.tool_calls == [existing]
    assert out.content == _MIMO_BLOCK  # untouched
    assert out.finish_reason == "tool_calls"


def test_inject_noop_when_content_empty():
    response = LLMResponse(content=None, tool_calls=[], finish_reason="stop")
    out = maybe_inject_text_tool_calls(response)
    assert out.tool_calls == []
    assert out.content is None
    assert out.finish_reason == "stop"


def test_inject_noop_on_error_envelope():
    """Error responses must not have their finish_reason mutated."""
    response = LLMResponse(
        content=_MIMO_BLOCK,
        tool_calls=[],
        finish_reason="error",
        error_kind="timeout",
    )
    out = maybe_inject_text_tool_calls(response)
    assert out.tool_calls == []
    assert out.finish_reason == "error"
    assert out.content == _MIMO_BLOCK


def test_inject_noop_when_content_has_no_blocks():
    response = LLMResponse(
        content="Just a plain response, no tool calls.",
        tool_calls=[],
        finish_reason="stop",
    )
    out = maybe_inject_text_tool_calls(response)
    assert out.tool_calls == []
    assert out.finish_reason == "stop"
    assert out.content == "Just a plain response, no tool calls."


def test_inject_content_becomes_none_when_only_tool_block():
    """If the message was ONLY a tool call, content should drop to None
    (not an empty string), matching native tool-call responses."""
    response = LLMResponse(
        content=_MIMO_BLOCK,
        tool_calls=[],
        finish_reason="stop",
    )
    out = maybe_inject_text_tool_calls(response)
    assert out.tool_calls and out.tool_calls[0].name == "read_file"
    assert out.content is None
    assert out.finish_reason == "tool_calls"


def test_inject_preserves_non_stop_finish_reason():
    """If finish_reason is something other than "stop" (e.g. "length"),
    we still lift the calls but leave the finish_reason alone — the reason
    why generation ended is preserved."""
    response = LLMResponse(
        content=_MIMO_BLOCK,
        tool_calls=[],
        finish_reason="length",
    )
    out = maybe_inject_text_tool_calls(response)
    assert len(out.tool_calls) == 1
    assert out.finish_reason == "length"
