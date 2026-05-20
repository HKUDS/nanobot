"""Tests for emergency tool result truncation in _snip_history.

When tool results accumulated within a single agent loop iteration exceed the
context window budget, _snip_history should truncate tool result contents as a
last resort instead of letting the provider return a 400 error.

See: https://github.com/HKUDS/nanobot/issues/2343
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from nanobot.agent.runner import AgentRunner


@dataclass
class FakeToolSet:
    """Minimal stand-in for the tools spec."""

    def get_definitions(self) -> list[dict[str, Any]]:
        return []

    def get(self, name: str) -> Any:
        return None


@dataclass
class FakeSpec:
    """Minimal AgentRunSpec stand-in with the fields _snip_history reads."""

    context_window_tokens: int = 32768
    max_tokens: int = 8192
    context_block_limit: int | None = None
    model: str = "test-model"
    tools: FakeToolSet = field(default_factory=FakeToolSet)
    max_tool_result_chars: int = 80000


def _make_runner() -> AgentRunner:
    """Create a minimal AgentRunner with a mock provider."""
    provider = MagicMock()
    provider.generation = MagicMock(max_tokens=4096)
    return AgentRunner(provider=provider)


def _char_based_token_estimate(provider, model, messages, tools=None):
    """Simple char-based token estimator for testing (~4 chars per token)."""
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total += len(content) // 4 + 4
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    total += len(str(part)) // 4 + 4
        tc = msg.get("tool_calls")
        if tc:
            total += len(str(tc)) // 4 + 4
    return total, "test"


def _char_based_msg_tokens(message):
    """Simple char-based message token estimator for testing."""
    content = message.get("content", "")
    if isinstance(content, str):
        return len(content) // 4 + 4
    return 4


@patch("nanobot.agent.runner.estimate_prompt_tokens_chain", side_effect=_char_based_token_estimate)
@patch("nanobot.agent.runner.estimate_message_tokens", side_effect=_char_based_msg_tokens)
class TestSnipHistoryEmergencyTruncation:
    """Verify that oversized tool results get truncated when history snip alone
    can't bring messages under the context budget."""

    def test_oversized_tool_results_truncated(self, mock_msg_tokens, mock_chain):
        """Tool results exceeding the budget should be truncated."""
        runner = _make_runner()
        spec = FakeSpec(context_window_tokens=16384, max_tokens=8192)

        # Budget ~ 16384 - 8192 - 1024 = 7168 tokens ~ 28672 chars
        # 4 tool results of 10000 chars each = 40000 chars ~ 10000 tokens >> 7168
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Search for generals"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "tc_1", "type": "function", "function": {"name": "web_search", "arguments": "{}"}},
                {"id": "tc_2", "type": "function", "function": {"name": "web_search", "arguments": "{}"}},
                {"id": "tc_3", "type": "function", "function": {"name": "web_search", "arguments": "{}"}},
                {"id": "tc_4", "type": "function", "function": {"name": "web_search", "arguments": "{}"}},
            ]},
            {"role": "tool", "tool_call_id": "tc_1", "content": "x" * 10000},
            {"role": "tool", "tool_call_id": "tc_2", "content": "x" * 10000},
            {"role": "tool", "tool_call_id": "tc_3", "content": "x" * 10000},
            {"role": "tool", "tool_call_id": "tc_4", "content": "x" * 10000},
        ]

        result = runner._snip_history(spec, messages)

        # All tool messages should still exist (pairing preserved)
        tool_msgs = [m for m in result if m.get("role") == "tool"]
        assert len(tool_msgs) == 4

        # But their content should be truncated from 10000 chars
        for msg in tool_msgs:
            assert len(msg["content"]) < 10000, (
                f"Tool result should have been truncated but is {len(msg['content'])} chars"
            )

    def test_within_budget_not_truncated(self, mock_msg_tokens, mock_chain):
        """Messages within budget should not be modified."""
        runner = _make_runner()
        # Large context window so nothing needs truncating
        spec = FakeSpec(context_window_tokens=131072, max_tokens=4096)

        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
            {"role": "user", "content": "What time is it?"},
        ]

        result = runner._snip_history(spec, messages)
        assert result == messages

    def test_tool_pairing_preserved(self, mock_msg_tokens, mock_chain):
        """Emergency truncation should keep assistant→tool message pairs intact."""
        runner = _make_runner()
        spec = FakeSpec(context_window_tokens=16384, max_tokens=8192)

        messages = [
            {"role": "system", "content": "System prompt."},
            {"role": "user", "content": "Do research"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "tc_1", "type": "function", "function": {"name": "search", "arguments": "{}"}},
            ]},
            {"role": "tool", "tool_call_id": "tc_1", "content": "y" * 50000},
        ]

        result = runner._snip_history(spec, messages)

        roles = [m["role"] for m in result]
        # Should have system, user, assistant, tool in order
        assert "assistant" in roles
        assert "tool" in roles
        # Tool should follow assistant
        asst_idx = roles.index("assistant")
        tool_idx = roles.index("tool")
        assert tool_idx == asst_idx + 1
        # Tool content should be truncated
        tool_msg = [m for m in result if m["role"] == "tool"][0]
        assert len(tool_msg["content"]) < 50000
