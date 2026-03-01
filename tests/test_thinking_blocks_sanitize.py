"""Tests for thinking_blocks/reasoning_content sanitization in LiteLLM provider.

Regression test for issue #1344: non-Anthropic providers (e.g. Dashscope/Qwen)
should never receive thinking_blocks in their message payloads, as LiteLLM may
mangle the content field when it encounters unknown Anthropic-only keys, causing
provider errors like:
  "Invalid type for 'messages.[0].content': got an object instead of a string"
"""

from __future__ import annotations

from nanobot.providers.base import LLMProvider
from nanobot.providers.litellm_provider import (
    LiteLLMProvider,
    _ALLOWED_MSG_KEYS,
    _ANTHROPIC_EXTRA_KEYS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_messages_with_thinking_blocks() -> list[dict]:
    """Return a typical message list that includes thinking_blocks (from Anthropic)."""
    return [
        {"role": "system", "content": "You are a helpful assistant."},
        {
            "role": "assistant",
            "content": "Let me think about that.",
            "thinking_blocks": [
                {"type": "thinking", "thinking": "The user asked a question."},
            ],
        },
        {"role": "user", "content": "What is 2+2?"},
    ]


# ---------------------------------------------------------------------------
# _sanitize_messages tests
# ---------------------------------------------------------------------------

def test_thinking_blocks_stripped_by_default() -> None:
    """thinking_blocks must be removed when no extra_keys are passed."""
    messages = _make_messages_with_thinking_blocks()
    sanitized = LiteLLMProvider._sanitize_messages(messages)

    for msg in sanitized:
        assert "thinking_blocks" not in msg, (
            f"thinking_blocks leaked into sanitized message: {msg}"
        )


def test_thinking_blocks_preserved_for_anthropic() -> None:
    """thinking_blocks must be kept when _ANTHROPIC_EXTRA_KEYS are passed."""
    messages = _make_messages_with_thinking_blocks()
    sanitized = LiteLLMProvider._sanitize_messages(messages, extra_keys=_ANTHROPIC_EXTRA_KEYS)

    assistant_msgs = [m for m in sanitized if m.get("role") == "assistant"]
    assert len(assistant_msgs) == 1
    assert "thinking_blocks" in assistant_msgs[0], (
        "thinking_blocks should be preserved when extra_keys includes it"
    )


def test_standard_keys_always_preserved() -> None:
    """Core message keys (role, content, tool_calls, …) must survive sanitization."""
    messages = [
        {"role": "user", "content": "hello", "unknown_field": "ignored"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": "x", "type": "function", "function": {"name": "f", "arguments": "{}"}}],
            "arbitrary": "should be stripped",
        },
    ]
    sanitized = LiteLLMProvider._sanitize_messages(messages)

    assert sanitized[0] == {"role": "user", "content": "hello"}
    assert "tool_calls" in sanitized[1]
    assert "arbitrary" not in sanitized[1]


def test_assistant_content_none_added_when_missing() -> None:
    """Strict providers need content=None on assistant messages that only have tool_calls."""
    messages = [
        {
            "role": "assistant",
            "tool_calls": [{"id": "x", "type": "function", "function": {"name": "f", "arguments": "{}"}}],
        }
    ]
    sanitized = LiteLLMProvider._sanitize_messages(messages)
    assert sanitized[0].get("content") is None


# ---------------------------------------------------------------------------
# _sanitize_empty_content defensive dict handling
# ---------------------------------------------------------------------------

def test_dict_content_wrapped_in_list() -> None:
    """A bare dict as content must be wrapped in a list for API compatibility."""
    messages = [
        {"role": "user", "content": {"type": "text", "text": "hello"}},
    ]
    sanitized = LLMProvider._sanitize_empty_content(messages)
    assert isinstance(sanitized[0]["content"], list), (
        "dict content should be wrapped in a list"
    )
    assert sanitized[0]["content"] == [{"type": "text", "text": "hello"}]


def test_string_content_unchanged() -> None:
    """Normal string content should pass through _sanitize_empty_content unchanged."""
    messages = [{"role": "user", "content": "hello"}]
    sanitized = LLMProvider._sanitize_empty_content(messages)
    assert sanitized[0]["content"] == "hello"


def test_list_content_unchanged_when_non_empty() -> None:
    """Non-empty list content should pass through unchanged."""
    messages = [{"role": "user", "content": [{"type": "text", "text": "hello"}]}]
    sanitized = LLMProvider._sanitize_empty_content(messages)
    assert sanitized[0]["content"] == [{"type": "text", "text": "hello"}]
