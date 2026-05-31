"""Tests for XmlToolCallSanitizer streaming content cleaner."""

from __future__ import annotations

import pytest

from nanobot.providers.openai_compat_provider import XmlToolCallSanitizer


class TestXmlToolCallSanitizerNormal:
    """Cases where deltas contain complete <function=…> blocks."""

    def test_no_xml_passes_through(self) -> None:
        s = XmlToolCallSanitizer()
        assert s.feed("hello world") == "hello world"

    def test_complete_function_block_stripped(self) -> None:
        s = XmlToolCallSanitizer()
        result = s.feed("<function=read_file><parameter=path>/tmp/x</parameter></function>")
        assert result == ""

    def test_text_before_and_after_block(self) -> None:
        s = XmlToolCallSanitizer()
        result = s.feed(
            "Sure!<function=read_file><parameter=path>/tmp</parameter></function>Done."
        )
        assert result == "Sure!Done."

    def test_tool_call_marker_stripped(self) -> None:
        s = XmlToolCallSanitizer()
        assert s.feed("<tool_call_none/>") == ""

    def test_closing_tool_call_stripped(self) -> None:
        s = XmlToolCallSanitizer()
        assert s.feed("</tool_call_none>") == ""

    def test_buffered_incomplete_function(self) -> None:
        s = XmlToolCallSanitizer()
        # First delta: partial opening tag
        assert s.feed("Hello <function") == "Hello "
        # Second delta completes the block
        assert s.feed("=exec><parameter=cmd>ls</parameter></function>") == ""


class TestXmlToolCallSanitizerOrphan:
    """Cases where leading '<' was emitted in reasoning delta."""

    def test_orphan_function_block_stripped(self) -> None:
        """Complete orphan block (function=…>…</function> without leading '<')."""
        s = XmlToolCallSanitizer()
        result = s.feed("function=exec><parameter=cmd>ls</parameter></function>")
        assert result == ""

    def test_orphan_block_with_surrounding_text(self) -> None:
        s = XmlToolCallSanitizer()
        result = s.feed(
            "Prefix function=exec><parameter=cmd>ls</parameter></function> Suffix"
        )
        assert result == "Prefix  Suffix"

    def test_orphan_block_multi_param(self) -> None:
        s = XmlToolCallSanitizer()
        result = s.feed(
            "function=read_file>"
            "<parameter=path>/etc/hosts</parameter>"
            "<parameter=offset>10</parameter>"
            "</function>"
        )
        assert result == ""

    def test_orphan_fragment_buffered_until_complete(self) -> None:
        """Orphan opening tag arrives alone; parameter tags in later deltas."""
        s = XmlToolCallSanitizer()
        # Delta 1: orphan opening (no '<')
        assert s.feed("function=exec>") == ""
        # Delta 2: parameter opening
        assert s.feed("<parameter=command") == ""
        # Delta 3: parameter value and close
        assert s.feed(">ls -la /tmp</parameter>") == ""
        # Delta 4: closing function tag
        assert s.feed("</function>") == ""

    def test_orphan_reproduces_reasoning_content_split(self) -> None:
        """Exact delta sequence from WebSocket trace: '<' was in reasoning."""
        deltas = [
            "function=exec>",
            "<parameter=command",
            ">ls -la",
            "/tmp",
            "</parameter>",
            "</function>",
        ]
        s = XmlToolCallSanitizer()
        for d in deltas:
            result = s.feed(d)
            assert result == "", f"Leaked at delta {d!r}: got {result!r}"
        assert s.flush() == ""


class TestXmlToolCallSanitizerFlush:
    """Flush behaviour for incomplete buffers."""

    def test_flush_strips_incomplete_function_prefix(self) -> None:
        s = XmlToolCallSanitizer()
        s.feed("<function=read_file><parameter=path>/tmp")
        remaining = s.flush()
        assert remaining == ""

    def test_flush_preserves_plain_function_equals(self) -> None:
        """Plain text 'function=main is important' must NOT be stripped."""
        s = XmlToolCallSanitizer()
        s.feed("the function=main is important")
        remaining = s.flush()
        assert "function=main is important" in remaining

    def test_flush_strips_xml_like_function_equals(self) -> None:
        """'function=exec>' looks like XML and should be stripped."""
        s = XmlToolCallSanitizer()
        s.feed("function=exec>")
        remaining = s.flush()
        assert remaining == ""

    def test_flush_orphan_block_in_final_deltas(self) -> None:
        """Complete orphan block sitting in buffer at flush time."""
        s = XmlToolCallSanitizer()
        # Feed enough to buffer the orphan opening
        s.feed("function=exec><parameter=cmd>ls</parameter>")
        # Don't feed closing tag — simulates it arriving at the very end
        # Actually feed it through flush by not closing
        assert s.flush() == ""


class TestXmlToolCallSanitizerParameter:
    """Cases with <parameter=…> tags."""

    def test_parameter_tag_buffered(self) -> None:
        s = XmlToolCallSanitizer()
        assert s.feed("<parameter=path") == ""
        assert s.feed(">/tmp</parameter>") == ""

    def test_parameter_inside_function_stripped(self) -> None:
        s = XmlToolCallSanitizer()
        result = s.feed(
            "<function=exec><parameter=cmd>ls</parameter></function>"
        )
        assert result == ""
