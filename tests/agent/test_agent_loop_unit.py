"""Unit tests for AgentLoop static/helper methods (_strip_think, _tool_hint)."""

from dataclasses import dataclass
from typing import Any

from blackcat.agent.loop import AgentLoop

# ── _strip_think ──────────────────────────────────────────────────


def test_strip_think_removes_block():
    result = AgentLoop._strip_think("<think>internal reasoning</think>Hello!")
    assert result == "Hello!"


def test_strip_think_multiline():
    text = "<think>\nStep 1: think\nStep 2: reason\n</think>\nThe answer is 42."
    result = AgentLoop._strip_think(text)
    assert result == "The answer is 42."


def test_strip_think_multiple_blocks():
    text = "<think>first</think>A<think>second</think>B"
    result = AgentLoop._strip_think(text)
    assert result == "AB"


def test_strip_think_no_block():
    result = AgentLoop._strip_think("Just normal text")
    assert result == "Just normal text"


def test_strip_think_none():
    assert AgentLoop._strip_think(None) is None


def test_strip_think_empty():
    assert AgentLoop._strip_think("") is None


def test_strip_think_only_think_block():
    """If the entire content is a think block, return None."""
    result = AgentLoop._strip_think("<think>all thinking no output</think>")
    assert result is None


def test_strip_think_whitespace_only_after_strip():
    result = AgentLoop._strip_think("<think>stuff</think>   ")
    assert result is None


# ── _tool_hint ────────────────────────────────────────────────────


@dataclass
class FakeToolCall:
    name: str
    arguments: dict[str, Any] | list | None


def test_tool_hint_single():
    calls = [FakeToolCall(name="web_search", arguments={"query": "python async"})]
    result = AgentLoop._tool_hint(calls)
    assert result == 'search "python async"'


def test_tool_hint_long_value_truncated():
    long_val = "a" * 50
    calls = [FakeToolCall(name="read_file", arguments={"path": long_val})]
    result = AgentLoop._tool_hint(calls)
    assert "…" in result
    assert len(result) < 60


def test_tool_hint_multiple():
    calls = [
        FakeToolCall(name="shell", arguments={"command": "ls"}),
        FakeToolCall(name="read_file", arguments={"path": "/tmp/x"}),
    ]
    result = AgentLoop._tool_hint(calls)
    assert "shell" in result
    assert "read" in result
    assert ", " in result


def test_tool_hint_no_string_arg():
    """When first arg value isn't a string, just show tool name."""
    calls = [FakeToolCall(name="cron", arguments={"interval": 60})]
    result = AgentLoop._tool_hint(calls)
    assert result == "cron"


def test_tool_hint_empty_args():
    calls = [FakeToolCall(name="list_jobs", arguments={})]
    result = AgentLoop._tool_hint(calls)
    assert result == "list_jobs"


def test_tool_hint_none_args():
    calls = [FakeToolCall(name="noop", arguments=None)]
    result = AgentLoop._tool_hint(calls)
    assert result == "noop"


def test_tool_hint_list_args():
    """Some models (Kimi K2.5) return args as a list instead of dict."""
    calls = [FakeToolCall(name="search", arguments=[{"query": "test"}])]
    result = AgentLoop._tool_hint(calls)
    assert result == 'search("test")'


def test_tool_hint_empty_list_args():
    calls = [FakeToolCall(name="noop", arguments=[])]
    result = AgentLoop._tool_hint(calls)
    assert result == "noop"
