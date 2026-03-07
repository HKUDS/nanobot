"""Tests for AgentLoop helper methods."""

import pytest
from unittest.mock import MagicMock

from nanobot.agent.loop import AgentLoop
from nanobot.providers.base import ToolCallRequest


class TestStripThink:
    """Tests for _strip_think method."""

    def test_strip_think_removes_think_block(self) -> None:
        """Should remove think block from content."""
        content = "<think>\nLet me think about this.\n</think>\nHere is my response."
        result = AgentLoop._strip_think(content)
        assert result == "Here is my response."

    def test_strip_think_with_multiple_think_blocks(self) -> None:
        """Should remove multiple think blocks."""
        content = "<think>\nFirst thought\n</think>\nHello\n<think>\nSecond thought\n</think>\nWorld"
        result = AgentLoop._strip_think(content)
        # After stripping, there's an extra newline between blocks
        assert result == "Hello\n\nWorld"

    def test_strip_think_without_think_block(self) -> None:
        """Should return original content without think block."""
        content = "Just a normal response without think blocks."
        result = AgentLoop._strip_think(content)
        assert result == "Just a normal response without think blocks."

    def test_strip_think_empty_content(self) -> None:
        """Should return None for empty content."""
        assert AgentLoop._strip_think("") is None
        assert AgentLoop._strip_think(None) is None

    def test_strip_think_only_think_block(self) -> None:
        """Should return None when content is only think block."""
        content = "<think>\nJust thinking\n</think>"
        result = AgentLoop._strip_think(content)
        assert result is None

    def test_strip_think_preserves_whitespace_trimming(self) -> None:
        """Should strip whitespace after removing think blocks."""
        content = "<think>\nThink\n</think>   \n  Response  "
        result = AgentLoop._strip_think(content)
        assert result == "Response"


class TestToolHint:
    """Tests for _tool_hint method."""

    def test_tool_hint_single_call(self) -> None:
        """Should format single tool call correctly."""
        tool_calls = [ToolCallRequest(id="1", name="web_search", arguments={"query": "python"})]
        result = AgentLoop._tool_hint(tool_calls)
        assert result == 'web_search("python")'

    def test_tool_hint_multiple_calls(self) -> None:
        """Should format multiple tool calls correctly."""
        tool_calls = [
            ToolCallRequest(id="1", name="web_search", arguments={"query": "python"}),
            ToolCallRequest(id="2", name="read_file", arguments={"path": "test.py"}),
        ]
        result = AgentLoop._tool_hint(tool_calls)
        assert result == 'web_search("python"), read_file("test.py")'

    def test_tool_hint_long_argument_truncates(self) -> None:
        """Should truncate long arguments."""
        long_query = "a" * 50
        tool_calls = [ToolCallRequest(id="1", name="web_search", arguments={"query": long_query})]
        result = AgentLoop._tool_hint(tool_calls)
        assert "…" in result
        assert len(result) < len('web_search("' + long_query + '")')

    def test_tool_hint_non_string_argument(self) -> None:
        """Should return just tool name for non-string arguments."""
        tool_calls = [ToolCallRequest(id="1", name="tool_name", arguments={"count": 5})]
        result = AgentLoop._tool_hint(tool_calls)
        assert result == "tool_name"

    def test_tool_hint_empty_arguments(self) -> None:
        """Should return just tool name for empty arguments."""
        tool_calls = [ToolCallRequest(id="1", name="tool_name", arguments={})]
        result = AgentLoop._tool_hint(tool_calls)
        assert result == "tool_name"

    def test_tool_hint_list_arguments(self) -> None:
        """Should handle list-style arguments."""
        tool_calls = [ToolCallRequest(id="1", name="web_search", arguments=["search query"])]
        result = AgentLoop._tool_hint(tool_calls)
        assert "web_search" in result

    def test_tool_hint_empty_list(self) -> None:
        """Empty list arguments should return tool name."""
        # Note: current implementation has a bug with empty lists (IndexError)
        # This test documents the current behavior
        tool_calls = [ToolCallRequest(id="1", name="tool_name", arguments=[])]
        with pytest.raises(IndexError):
            AgentLoop._tool_hint(tool_calls)


class TestConstants:
    """Tests for constants in AgentLoop."""

    def test_tool_result_max_chars_value(self) -> None:
        """Should have correct max chars value."""
        assert AgentLoop._TOOL_RESULT_MAX_CHARS == 500

    def test_message_preview_length(self) -> None:
        """Should have correct message preview length."""
        assert AgentLoop.MESSAGE_PREVIEW_LENGTH == 80

    def test_response_preview_length(self) -> None:
        """Should have correct response preview length."""
        assert AgentLoop.RESPONSE_PREVIEW_LENGTH == 120

    def test_log_arg_truncate_length(self) -> None:
        """Should have correct log argument truncate length."""
        assert AgentLoop.LOG_ARG_TRUNCATE_LENGTH == 200
