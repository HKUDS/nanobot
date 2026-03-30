"""Tests for OpenAI-compatible provider message sanitization."""

import pytest
from nanobot.providers.openai_compat_provider import OpenAICompatProvider


def test_sanitize_messages_strips_reasoning_content_by_default():
    """reasoning_content must be stripped unless provider spec explicitly allows it."""
    provider = OpenAICompatProvider.__new__(OpenAICompatProvider)
    provider._spec = None  # No spec = default behavior (strip non-standard keys)

    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi", "reasoning_content": "thinking..."},
        {"role": "user", "content": "Tell me more"},
        {"role": "assistant", "content": "Sure", "thinking_blocks": [{"type": "thinking", "thinking": "hmm"}]},
    ]

    result = provider._sanitize_messages(messages)

    for msg in result:
        assert "reasoning_content" not in msg, f"reasoning_content leaked into {msg['role']} message"
        assert "thinking_blocks" not in msg, f"thinking_blocks leaked into {msg['role']} message"
        assert "extra_content" not in msg, f"extra_content leaked into {msg['role']} message"


def test_sanitize_messages_keeps_standard_keys():
    """Standard OpenAI keys must always be preserved."""
    provider = OpenAICompatProvider.__new__(OpenAICompatProvider)
    provider._spec = None

    messages = [
        {"role": "assistant", "content": None, "tool_calls": [{"id": "tc_1", "type": "function", "function": {"name": "test", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "tc_1", "name": "test", "content": "ok"},
    ]

    result = provider._sanitize_messages(messages)

    assert "tool_calls" in result[0]
    assert result[0]["content"] is None
    assert "tool_call_id" in result[1]
    assert "name" in result[1]


def test_sanitize_messages_strips_timestamp():
    """timestamp is a nanobot-internal field and must never reach the provider."""
    provider = OpenAICompatProvider.__new__(OpenAICompatProvider)
    provider._spec = None

    messages = [
        {"role": "user", "content": "Hi", "timestamp": "2026-03-30T21:00:00"},
    ]

    result = provider._sanitize_messages(messages)

    assert "timestamp" not in result[0]


def test_sanitize_messages_preserves_reasoning_when_spec_allows():
    """reasoning_content must be preserved when spec.supports_reasoning is True."""
    from types import SimpleNamespace

    provider = OpenAICompatProvider.__new__(OpenAICompatProvider)
    provider._spec = SimpleNamespace(supports_reasoning=True)

    messages = [
        {"role": "assistant", "content": "Hi", "reasoning_content": "thinking..."},
    ]

    result = provider._sanitize_messages(messages)

    assert "reasoning_content" in result[0]
    assert result[0]["reasoning_content"] == "thinking..."
