"""IT-20: Context compression — token budget enforcement.

Verifies that compress_context reduces token usage for long conversations
while preserving recent and system messages.

Does not require LLM API key.
"""

from __future__ import annotations

from typing import Any

import pytest

from nanobot.context.compression import compress_context, estimate_messages_tokens

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_long_conversation(num_turns: int = 30, msg_length: int = 250) -> list[dict[str, Any]]:
    """Build a conversation with a system message and many user/assistant turns.

    Each message body is 200-300 characters to create meaningful token pressure.
    """
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": "You are a helpful assistant. " * 5},
    ]
    for i in range(num_turns):
        filler = f"Turn {i}: " + ("x" * msg_length)
        messages.append({"role": "user", "content": filler})
        messages.append({"role": "assistant", "content": f"Response {i}: " + ("y" * msg_length)})
    return messages


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestTokenEstimation:
    def test_estimate_messages_tokens_positive(self) -> None:
        """estimate_messages_tokens returns a positive number for non-empty messages."""
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello, how are you?"},
        ]
        tokens = estimate_messages_tokens(messages)
        assert tokens > 0

    def test_estimate_scales_with_content(self) -> None:
        """Longer messages produce higher token estimates."""
        short = [{"role": "user", "content": "Hi"}]
        long = [{"role": "user", "content": "x" * 1000}]

        assert estimate_messages_tokens(long) > estimate_messages_tokens(short)

    def test_empty_messages_zero_tokens(self) -> None:
        """An empty message list estimates to zero tokens."""
        assert estimate_messages_tokens([]) == 0


class TestCompressionReducesTokens:
    def test_compression_reduces_token_count(self) -> None:
        """compress_context with a tight budget produces fewer tokens than the original."""
        messages = _build_long_conversation(num_turns=30, msg_length=250)
        original_tokens = estimate_messages_tokens(messages)

        # Set a budget well below the original
        budget = original_tokens // 3
        compressed = compress_context(messages, max_tokens=budget, preserve_recent=6)

        compressed_tokens = estimate_messages_tokens(compressed)
        assert compressed_tokens < original_tokens
        assert len(compressed) < len(messages)

    def test_no_compression_under_budget(self) -> None:
        """Messages under budget are returned unchanged."""
        messages = [
            {"role": "system", "content": "System prompt."},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]
        original_tokens = estimate_messages_tokens(messages)
        generous_budget = original_tokens * 10

        result = compress_context(messages, max_tokens=generous_budget, preserve_recent=6)

        assert result == messages


class TestPreservation:
    def test_system_message_preserved(self) -> None:
        """The system message (first message) survives compression."""
        messages = _build_long_conversation(num_turns=30, msg_length=250)
        original_tokens = estimate_messages_tokens(messages)
        budget = original_tokens // 4

        compressed = compress_context(messages, max_tokens=budget, preserve_recent=6)

        assert len(compressed) > 0
        assert compressed[0]["role"] == "system"
        assert compressed[0]["content"] == messages[0]["content"]

    def test_recent_messages_preserved(self) -> None:
        """The most recent messages (within preserve_recent) survive compression."""
        messages = _build_long_conversation(num_turns=30, msg_length=250)
        original_tokens = estimate_messages_tokens(messages)
        budget = original_tokens // 4
        preserve_recent = 6

        compressed = compress_context(messages, max_tokens=budget, preserve_recent=preserve_recent)

        # The last preserve_recent messages from original should appear at the end
        original_tail = messages[-preserve_recent:]
        compressed_tail = compressed[-preserve_recent:]

        for orig, comp in zip(original_tail, compressed_tail):
            assert orig["role"] == comp["role"]
            assert orig["content"] == comp["content"]

    def test_empty_input_returns_empty(self) -> None:
        """compress_context with empty input returns empty list."""
        result = compress_context([], max_tokens=1000, preserve_recent=6)
        assert result == []
