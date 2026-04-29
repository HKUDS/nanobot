"""Tests for GitHubCopilotProvider._trim_kwargs_body."""

from __future__ import annotations

import json

import pytest

from nanobot.providers.github_copilot_provider import (
    GitHubCopilotProvider,
    _MAX_REQUEST_BODY_BYTES,
)


def _make_messages(
    n_pairs: int,
    content_size: int = 100,
    system_content: str = "You are helpful.",
) -> list[dict[str, object]]:
    """Build a system message + n_pairs of (user, assistant) messages."""
    msgs: list[dict[str, object]] = [{"role": "system", "content": system_content}]
    for i in range(n_pairs):
        msgs.append({"role": "user", "content": f"msg-{i} " + "x" * content_size})
        msgs.append({"role": "assistant", "content": f"reply-{i} " + "y" * content_size})
    return msgs


def _make_tools(n: int = 5) -> list[dict[str, object]]:
    return [
        {
            "type": "function",
            "function": {"name": f"tool_{i}", "description": "desc", "parameters": {}},
        }
        for i in range(n)
    ]


def _make_kwargs(
    n_pairs: int = 10,
    content_size: int = 100,
    n_tools: int = 0,
) -> dict[str, object]:
    """Build a kwargs dict mimicking _build_kwargs output."""
    kwargs: dict[str, object] = {
        "model": "claude-sonnet-4.6",
        "messages": _make_messages(n_pairs, content_size),
        "temperature": 0.1,
        "max_tokens": 8192,
    }
    if n_tools:
        kwargs["tools"] = _make_tools(n_tools)
        kwargs["tool_choice"] = "auto"
    return kwargs


def _body_size(kwargs: dict[str, object]) -> int:
    return len(json.dumps(kwargs, ensure_ascii=False, default=str).encode())


class TestTrimKwargsBody:
    """Test suite for _trim_kwargs_body."""

    def test_no_trim_when_under_limit(self) -> None:
        """kwargs under the limit are returned unchanged."""
        kwargs = _make_kwargs(3, content_size=10)
        result = GitHubCopilotProvider._trim_kwargs_body(kwargs)
        assert result is kwargs

    def test_trims_when_over_limit(self) -> None:
        """kwargs over the limit have messages trimmed."""
        kwargs = _make_kwargs(200, content_size=3000, n_tools=12)
        result = GitHubCopilotProvider._trim_kwargs_body(kwargs)
        assert len(result["messages"]) < len(kwargs["messages"])

    def test_system_messages_preserved(self) -> None:
        """System messages are never dropped."""
        kwargs = _make_kwargs(200, content_size=3000)
        result = GitHubCopilotProvider._trim_kwargs_body(kwargs)
        system_msgs = [m for m in result["messages"] if m.get("role") == "system"]
        assert len(system_msgs) == 1
        assert system_msgs[0]["content"] == "You are helpful."

    def test_starts_with_user_after_system(self) -> None:
        """After trimming, conversation starts with a user message."""
        kwargs = _make_kwargs(200, content_size=3000)
        result = GitHubCopilotProvider._trim_kwargs_body(kwargs)
        non_system = [m for m in result["messages"] if m.get("role") != "system"]
        assert non_system[0]["role"] == "user"

    def test_result_under_body_limit(self) -> None:
        """Trimmed result body size stays within the byte limit."""
        kwargs = _make_kwargs(200, content_size=3000, n_tools=12)
        result = GitHubCopilotProvider._trim_kwargs_body(kwargs)
        assert _body_size(result) <= _MAX_REQUEST_BODY_BYTES

    def test_custom_byte_limit(self) -> None:
        """A custom max_body_bytes is respected."""
        kwargs = _make_kwargs(50, content_size=500, n_tools=3)
        limit = 10_000
        result = GitHubCopilotProvider._trim_kwargs_body(kwargs, max_body_bytes=limit)
        assert len(result["messages"]) < len(kwargs["messages"])
        assert _body_size(result) <= limit

    def test_no_tools(self) -> None:
        """Works correctly when tools is absent."""
        kwargs = _make_kwargs(200, content_size=3000)
        result = GitHubCopilotProvider._trim_kwargs_body(kwargs)
        assert len(result["messages"]) < len(kwargs["messages"])
        assert result["messages"][0]["role"] == "system"

    def test_orphan_tool_result_skipped(self) -> None:
        """Tool result messages at the trim boundary are skipped."""
        msgs: list[dict[str, object]] = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1", "tool_calls": [
                {"id": "tc1", "type": "function", "function": {"name": "f", "arguments": "{}"}}
            ]},
            {"role": "tool", "content": "result1", "tool_call_id": "tc1"},
            {"role": "assistant", "content": "done1"},
            {"role": "user", "content": "q2"},
            {"role": "assistant", "content": "a2"},
        ]
        kwargs: dict[str, object] = {"model": "test", "messages": msgs, "max_tokens": 100}
        result = GitHubCopilotProvider._trim_kwargs_body(kwargs, max_body_bytes=200)
        non_system = [m for m in result["messages"] if m.get("role") != "system"]
        if non_system:
            assert non_system[0]["role"] == "user"

    def test_empty_messages(self) -> None:
        """Empty message list is handled gracefully."""
        kwargs: dict[str, object] = {"model": "test", "messages": [], "max_tokens": 100}
        result = GitHubCopilotProvider._trim_kwargs_body(kwargs)
        assert result["messages"] == []

    def test_only_system_message(self) -> None:
        """A single system message is returned as-is."""
        kwargs: dict[str, object] = {
            "model": "test",
            "messages": [{"role": "system", "content": "hello"}],
            "max_tokens": 100,
        }
        result = GitHubCopilotProvider._trim_kwargs_body(kwargs)
        assert len(result["messages"]) == 1

    def test_non_message_fields_preserved(self) -> None:
        """Non-message kwargs fields (model, tools, temperature) are preserved."""
        kwargs = _make_kwargs(200, content_size=3000, n_tools=5)
        result = GitHubCopilotProvider._trim_kwargs_body(kwargs)
        assert result["model"] == "claude-sonnet-4.6"
        assert result["temperature"] == 0.1
        assert result["max_tokens"] == 8192
        assert result["tools"] == kwargs["tools"]

