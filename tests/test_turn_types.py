"""Tests for turn_types dataclasses."""

from __future__ import annotations

import pytest

from nanobot.agent.turn_types import ToolAttempt


class TestToolAttempt:
    """Tests for the ToolAttempt frozen dataclass."""

    def test_creation(self) -> None:
        attempt = ToolAttempt(
            tool_name="read_file",
            arguments={"path": "/tmp/test.txt"},
            success=True,
            output_empty=False,
            output_snippet="file contents here",
            iteration=3,
        )
        assert attempt.tool_name == "read_file"
        assert attempt.arguments == {"path": "/tmp/test.txt"}
        assert attempt.success is True
        assert attempt.output_empty is False
        assert attempt.output_snippet == "file contents here"
        assert attempt.iteration == 3

    def test_frozen(self) -> None:
        attempt = ToolAttempt(
            tool_name="exec",
            arguments={"command": "ls"},
            success=False,
            output_empty=True,
            output_snippet="",
            iteration=0,
        )
        with pytest.raises(AttributeError):
            attempt.tool_name = "other"  # type: ignore[misc]
        with pytest.raises(AttributeError):
            attempt.success = True  # type: ignore[misc]

    def test_output_snippet_stores_as_given(self) -> None:
        long_snippet = "x" * 500
        attempt = ToolAttempt(
            tool_name="web_fetch",
            arguments={"url": "https://example.com"},
            success=True,
            output_empty=False,
            output_snippet=long_snippet,
            iteration=1,
        )
        assert attempt.output_snippet == long_snippet
        assert len(attempt.output_snippet) == 500
