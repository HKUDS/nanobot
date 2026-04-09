"""Tests for <thought> block handling helpers and build_assistant_message."""

from __future__ import annotations

import pytest

from nanobot.utils.helpers import (
    strip_think,
    extract_thought_blocks,
    extract_think_blocks,
    has_thought_content,
    build_assistant_message,
)


# ---------------------------------------------------------------------------
# strip_think
# ---------------------------------------------------------------------------

class TestStripThink:
    def test_removes_thought_blocks(self):
        text = "Hello<thought>internal reasoning</thought>World"
        assert strip_think(text) == "HelloWorld"

    def test_removes_multiple_thought_blocks(self):
        text = "<thought>a</thought>mid<thought>b</thought>"
        assert strip_think(text) == "mid"

    def test_removes_unclosed_trailing_thought(self):
        text = "visible<thought>unclosed"
        assert strip_think(text) == "visible"

    def test_removes_think_blocks(self):
        text = "before<think>secret</think>after"
        assert strip_think(text) == "beforeafter"

    def test_removes_unclosed_trailing_think(self):
        text = "ok<think>partial"
        assert strip_think(text) == "ok"

    def test_strips_result(self):
        text = "  <thought>x</thought>  hello  "
        assert strip_think(text) == "hello"

    def test_no_change_when_no_tags(self):
        assert strip_think("just plain text") == "just plain text"


# ---------------------------------------------------------------------------
# extract_thought_blocks
# ---------------------------------------------------------------------------

class TestExtractThoughtBlocks:
    def test_single_block(self):
        text = "prefix<thought>reasoning here</thought>suffix"
        assert extract_thought_blocks(text) == ["reasoning here"]

    def test_multiple_blocks(self):
        text = "<thought>first</thought>gap<thought>second</thought>"
        assert extract_thought_blocks(text) == ["first", "second"]

    def test_multiline_block(self):
        text = "<thought>\nline1\nline2\n</thought>"
        assert extract_thought_blocks(text) == ["\nline1\nline2\n"]

    def test_unclosed_trailing_block(self):
        text = "visible<thought>unclosed tail"
        assert extract_thought_blocks(text) == ["unclosed tail"]

    def test_empty_block(self):
        assert extract_thought_blocks("<thought></thought>") == [""]

    def test_no_blocks_returns_empty(self):
        assert extract_thought_blocks("no tags here") == []


# ---------------------------------------------------------------------------
# extract_think_blocks
# ---------------------------------------------------------------------------

class TestExtractThinkBlocks:
    def test_single_block(self):
        text = "a<think>secret</think>b"
        assert extract_think_blocks(text) == ["secret"]

    def test_multiple_blocks(self):
        text = "<think>one</think>x<think>two</think>"
        assert extract_think_blocks(text) == ["one", "two"]

    def test_unclosed_trailing_block(self):
        text = "ok<think>partial"
        assert extract_think_blocks(text) == ["partial"]

    def test_no_blocks_returns_empty(self):
        assert extract_think_blocks("nothing") == []


# ---------------------------------------------------------------------------
# has_thought_content
# ---------------------------------------------------------------------------

class TestHasThoughtContent:
    def test_detects_thought_tag(self):
        assert has_thought_content("<thought>x</thought>") is True

    def test_detects_think_tag(self):
        assert has_thought_content("<think>y</think>") is True

    def test_false_when_no_tags(self):
        assert has_thought_content("plain text") is False

    def test_false_on_empty_string(self):
        assert has_thought_content("") is False


# ---------------------------------------------------------------------------
# build_assistant_message
# ---------------------------------------------------------------------------

class TestBuildAssistantMessage:
    def test_minimal_message(self):
        msg = build_assistant_message("hello")
        assert msg == {"role": "assistant", "content": "hello"}

    def test_none_content_becomes_empty_string(self):
        msg = build_assistant_message(None)
        assert msg["content"] == ""

    def test_with_tool_calls(self):
        tc = [{"id": "1", "type": "function"}]
        msg = build_assistant_message("ok", tool_calls=tc)
        assert msg["tool_calls"] == tc

    def test_with_reasoning_content(self):
        msg = build_assistant_message("hi", reasoning_content="thinking…")
        assert msg["reasoning_content"] == "thinking…"

    def test_with_thought_content(self):
        msg = build_assistant_message("hi", thought_content=["step 1", "step 2"])
        assert msg["thought_content"] == ["step 1", "step 2"]

    def test_with_thinking_blocks(self):
        blocks = [{"type": "thinking", "thinking": "deep"}]
        msg = build_assistant_message("hi", thinking_blocks=blocks)
        assert msg["thinking_blocks"] == blocks

    def test_all_optional_fields(self):
        msg = build_assistant_message(
            "answer",
            tool_calls=[{"id": "1"}],
            reasoning_content="r",
            thinking_blocks=[{"type": "x"}],
            thought_content=["t1"],
        )
        assert msg["role"] == "assistant"
        assert msg["content"] == "answer"
        assert msg["tool_calls"] == [{"id": "1"}]
        assert msg["reasoning_content"] == "r"
        assert msg["thinking_blocks"] == [{"type": "x"}]
        assert msg["thought_content"] == ["t1"]

    def test_reasoning_content_added_when_thought_content_present(self):
        """reasoning_content key is injected even when only thought_content is set."""
        msg = build_assistant_message("hi", thought_content=["x"])
        assert "reasoning_content" in msg
        assert msg["reasoning_content"] == ""
