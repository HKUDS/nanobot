"""Unit tests for AgentLoop static/helper methods (_strip_think, _tool_hint)."""

from dataclasses import dataclass
from typing import Any

from blackcat.agent.progress_hook import AgentProgressHook

# ── _strip_think ──────────────────────────────────────────────────


def test_strip_think_removes_block():
    result = AgentProgressHook._strip_think("<think>internal reasoning</think>Hello!")
    assert result == "Hello!"


def test_strip_think_multiline():
    text = "<think>\nStep 1: think\nStep 2: reason\n</think>\nThe answer is 42."
    result = AgentProgressHook._strip_think(text)
    assert result == "The answer is 42."


def test_strip_think_multiple_blocks():
    text = "<think>first</think>A<think>second</think>B"
    result = AgentProgressHook._strip_think(text)
    assert result == "AB"


def test_strip_think_no_block():
    result = AgentProgressHook._strip_think("Just normal text")
    assert result == "Just normal text"


def test_strip_think_none():
    assert AgentProgressHook._strip_think(None) is None


def test_strip_think_empty():
    assert AgentProgressHook._strip_think("") is None


def test_strip_think_only_think_block():
    """If the entire content is a think block, return None."""
    result = AgentProgressHook._strip_think("<think>all thinking no output</think>")
    assert result is None


def test_strip_think_whitespace_only_after_strip():
    result = AgentProgressHook._strip_think("<think>stuff</think>   ")
    assert result is None


# ── _tool_hint ────────────────────────────────────────────────────


@dataclass
class FakeToolCall:
    name: str
    arguments: dict[str, Any] | list | None


def _make_hook():
    """Create an AgentProgressHook instance for testing instance methods."""
    return AgentProgressHook(on_progress=None, tool_hint_max_length=50)


def test_tool_hint_single():
    hook = _make_hook()
    calls = [FakeToolCall(name="web_search", arguments={"query": "python async"})]
    result = hook._tool_hint(calls)
    assert result == 'search "python async"'


def test_tool_hint_long_value_truncated():
    hook = _make_hook()
    long_val = "a" * 50
    calls = [FakeToolCall(name="read_file", arguments={"path": long_val})]
    result = hook._tool_hint(calls)
    # abbreviate_path keeps basename; for a flat string of 'a's, it returns as-is
    assert long_val in result


def test_tool_hint_multiple():
    hook = _make_hook()
    calls = [
        FakeToolCall(name="shell", arguments={"command": "ls"}),
        FakeToolCall(name="read_file", arguments={"path": "/tmp/x"}),
    ]
    result = hook._tool_hint(calls)
    assert "shell" in result
    assert "read" in result
    assert ", " in result


def test_tool_hint_no_string_arg():
    hook = _make_hook()
    """When first arg value isn't a string, just show tool name."""
    calls = [FakeToolCall(name="cron", arguments={"interval": 60})]
    result = hook._tool_hint(calls)
    assert result == "cron"


def test_tool_hint_empty_args():
    hook = _make_hook()
    calls = [FakeToolCall(name="list_jobs", arguments={})]
    result = hook._tool_hint(calls)
    assert result == "list_jobs"


def test_tool_hint_none_args():
    hook = _make_hook()
    calls = [FakeToolCall(name="noop", arguments=None)]
    result = hook._tool_hint(calls)
    assert result == "noop"


def test_tool_hint_list_args():
    hook = _make_hook()
    """Some models (Kimi K2.5) return args as a list instead of dict."""
    calls = [FakeToolCall(name="search", arguments=[{"query": "test"}])]
    result = hook._tool_hint(calls)
    assert result == 'search("test")'


def test_tool_hint_empty_list_args():
    hook = _make_hook()
    calls = [FakeToolCall(name="noop", arguments=[])]
    result = hook._tool_hint(calls)
    assert result == "noop"
