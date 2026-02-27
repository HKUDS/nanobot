"""Tests for AgentLoop._tool_hint formatting of tool calls."""

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.providers.base import ToolCallRequest


def test_tool_hint_no_arguments():
    """Tool with no arguments shows name()."""
    calls = [ToolCallRequest(id="1", name="list_dir", arguments={})]
    assert AgentLoop._tool_hint(calls) == "list_dir()"


def test_tool_hint_single_argument():
    """Tool with one argument shows name(arg=value)."""
    calls = [
        ToolCallRequest(id="1", name="web_search", arguments={"query": "weather Berlin"})
    ]
    assert AgentLoop._tool_hint(calls) == 'web_search(query=weather Berlin)'


def test_tool_hint_multiple_arguments():
    """Tool with multiple arguments shows all (e.g. exec with command and working_dir)."""
    calls = [
        ToolCallRequest(
            id="1",
            name="exec",
            arguments={"command": "ls -la", "working_dir": "/tmp"},
        )
    ]
    hint = AgentLoop._tool_hint(calls)
    assert "exec(" in hint
    assert "command=ls -la" in hint
    assert "working_dir=/tmp" in hint


def test_tool_hint_long_value_truncated():
    """Long string values are truncated with ellipsis."""
    long_query = "x" * 50
    calls = [
        ToolCallRequest(id="1", name="web_search", arguments={"query": long_query})
    ]
    hint = AgentLoop._tool_hint(calls)
    assert "…" in hint
    assert len(hint) < 60


def test_tool_hint_multiple_calls():
    """Multiple tool calls are comma-separated."""
    calls = [
        ToolCallRequest(id="1", name="read_file", arguments={"path": "a.txt"}),
        ToolCallRequest(id="2", name="read_file", arguments={"path": "b.txt"}),
    ]
    hint = AgentLoop._tool_hint(calls)
    assert "read_file(path=a.txt)" in hint
    assert "read_file(path=b.txt)" in hint
    assert hint.count(", ") >= 1


def test_tool_hint_non_string_value():
    """Non-string argument values use repr (e.g. numbers, bool)."""
    calls = [
        ToolCallRequest(id="1", name="fake_tool", arguments={"count": 3, "flag": True})
    ]
    hint = AgentLoop._tool_hint(calls)
    assert "count=3" in hint or "3" in hint
    assert "flag=True" in hint or "True" in hint
