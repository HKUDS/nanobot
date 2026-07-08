"""Tests for repeated tool-result hints."""

from __future__ import annotations

from nanobot.utils.runtime import (
    repeated_external_lookup_error,
    repeated_tool_result_hint,
)


def test_repeated_tool_result_hints_after_two_identical_results():
    counts: dict[str, int] = {}

    assert repeated_tool_result_hint("grep", "same result", counts) is None
    assert repeated_tool_result_hint("grep", "same result", counts) is None
    third = repeated_tool_result_hint("grep", "same result", counts)

    assert third is not None
    assert "Repeated grep result" in third


def test_repeated_tool_result_ignores_different_results():
    counts: dict[str, int] = {}

    assert repeated_tool_result_hint("grep", "first", counts) is None
    assert repeated_tool_result_hint("grep", "second", counts) is None
    assert repeated_tool_result_hint("grep", "third", counts) is None


def test_repeated_tool_result_is_per_tool():
    counts: dict[str, int] = {}

    repeated_tool_result_hint("grep", "same", counts)
    repeated_tool_result_hint("grep", "same", counts)

    assert repeated_tool_result_hint("read_file", "same", counts) is None


def test_repeated_tool_result_handles_text_blocks():
    counts: dict[str, int] = {}
    result = [{"type": "text", "text": "same result"}]

    repeated_tool_result_hint("mcp", result, counts)
    repeated_tool_result_hint("mcp", result, counts)
    third = repeated_tool_result_hint("mcp", result, counts)

    assert third is not None
    assert "Repeated mcp result" in third


def test_repeated_external_lookup_still_blocks_after_two_attempts():
    counts: dict[str, int] = {}
    arguments = {"url": "https://example.com"}

    repeated_external_lookup_error("web_fetch", arguments, counts)
    repeated_external_lookup_error("web_fetch", arguments, counts)
    third = repeated_external_lookup_error("web_fetch", arguments, counts)

    assert third is not None
    assert "repeated external lookup blocked" in third
