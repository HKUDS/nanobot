"""Tests for compress_context(), summarize_and_compress(), and system prompt assembly."""

from __future__ import annotations

from nanobot.agent.compression import (
    compress_context,
    estimate_messages_tokens,
    estimate_tokens,
    summarize_and_compress,
)
from nanobot.providers.base import LLMResponse

# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------


class TestEstimateTokens:
    def test_empty(self):
        assert estimate_tokens("") == 1  # min 1

    def test_short_string(self):
        assert estimate_tokens("hello") > 0

    def test_proportional(self):
        short = estimate_tokens("hi")
        long = estimate_tokens("hi " * 100)
        assert long > short

    def test_messages_tokens(self):
        msgs = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello!"},
        ]
        total = estimate_messages_tokens(msgs)
        assert total > 0


# ---------------------------------------------------------------------------
# compress_context (synchronous)
# ---------------------------------------------------------------------------


class TestCompressContext:
    def test_empty_messages(self):
        result = compress_context([], 1000)
        assert result == []

    def test_under_budget_unchanged(self):
        msgs = [
            {"role": "system", "content": "short"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        result = compress_context(msgs, 100000)
        assert result == msgs

    def test_truncates_large_tool_results(self):
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "tool", "content": "x" * 5000, "name": "read_file", "tool_call_id": "1"},
            {"role": "assistant", "content": "ok"},
            # tail messages
            {"role": "user", "content": "next"},
            {"role": "assistant", "content": "reply"},
        ]
        # Budget that forces truncation but not dropping
        budget = estimate_messages_tokens(msgs) - 200
        result = compress_context(msgs, budget, preserve_recent=2)
        # Tool result should be truncated
        tool_msg = [m for m in result if m.get("role") == "tool"]
        if tool_msg:
            assert len(tool_msg[0]["content"]) < 5000

    def test_drops_tool_results_under_pressure(self):
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "tool", "content": "x" * 5000, "name": "t1", "tool_call_id": "1"},
            {"role": "tool", "content": "y" * 5000, "name": "t2", "tool_call_id": "2"},
            {"role": "user", "content": "next"},
            {"role": "assistant", "content": "reply"},
        ]
        # Very tight budget
        result = compress_context(msgs, 30, preserve_recent=2)
        tool_msgs = [m for m in result if m.get("role") == "tool"]
        # Tool results should be gone
        assert len(tool_msgs) == 0

    def test_preserves_system_and_tail(self):
        msgs = [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "old"},
            {"role": "assistant", "content": "old reply"},
            {"role": "user", "content": "recent"},
            {"role": "assistant", "content": "recent reply"},
        ]
        result = compress_context(msgs, 20, preserve_recent=2)
        assert result[0]["role"] == "system"
        assert result[-1]["content"] == "recent reply"


# ---------------------------------------------------------------------------
# summarize_and_compress (async, with mock provider)
# ---------------------------------------------------------------------------


class MockProvider:
    """Minimal provider for summarization tests."""

    def __init__(self, summary: str = "Summary of earlier conversation."):
        self._summary = summary
        self.called = False

    async def chat(self, *, messages, tools, model, temperature, max_tokens, metadata=None):
        self.called = True
        return LLMResponse(content=self._summary)


class TestSummarizeAndCompress:
    async def test_under_budget_no_summarization(self):
        provider = MockProvider()
        msgs = [
            {"role": "system", "content": "short"},
            {"role": "user", "content": "hi"},
        ]
        result = await summarize_and_compress(msgs, 100000, provider, "test-model")
        assert result == msgs
        assert not provider.called

    async def test_summarization_triggered_on_large_context(self):
        """When messages exceed budget and truncation isn't enough, LLM summary is used."""
        provider = MockProvider("Compressed summary of conversation.")
        msgs = [
            {"role": "system", "content": "system prompt"},
        ]
        # Add many large middle messages
        for i in range(20):
            msgs.append({"role": "user", "content": f"Long message {i} " * 200})
            msgs.append({"role": "assistant", "content": f"Long reply {i} " * 200})
        # Recent tail
        msgs.append({"role": "user", "content": "final question"})
        msgs.append({"role": "assistant", "content": "final answer"})

        # Very tight budget that forces summarization
        result = await summarize_and_compress(
            msgs,
            100,
            provider,
            "test-model",
            preserve_recent=2,
        )

        # Should contain system + summary + tail
        assert result[0]["role"] == "system"
        assert any("Compressed Summary" in str(m.get("content", "")) for m in result)
        assert provider.called

    async def test_summary_cached(self):
        """Second call with same messages uses cached summary."""
        provider = MockProvider("Cached summary.")
        msgs = [
            {"role": "system", "content": "sys"},
        ]
        for i in range(10):
            msgs.append({"role": "user", "content": f"msg {i} " * 200})
            msgs.append({"role": "assistant", "content": f"reply {i} " * 200})
        msgs.append({"role": "user", "content": "last"})

        # Clear cache for test isolation
        from nanobot.agent.compression import _summary_cache

        _summary_cache.clear()

        await summarize_and_compress(msgs, 50, provider, "m", preserve_recent=1)
        assert provider.called

        # Second call — reset provider tracking
        provider.called = False
        await summarize_and_compress(msgs, 50, provider, "m", preserve_recent=1)
        # Should not call provider again (cached)
        assert not provider.called

    async def test_fallback_on_provider_failure(self):
        """If LLM summary fails, falls back to dropping messages."""

        class FailingProvider:
            async def chat(self, **kwargs):
                raise RuntimeError("LLM down")

        msgs = [
            {"role": "system", "content": "sys"},
        ]
        for i in range(10):
            msgs.append({"role": "user", "content": f"msg {i} " * 200})
        msgs.append({"role": "user", "content": "last"})

        result = await summarize_and_compress(
            msgs,
            50,
            FailingProvider(),
            "m",
            preserve_recent=1,
        )
        # Should still return something valid (system + tail)
        assert result[0]["role"] == "system"
        assert result[-1]["content"] == "last"

    async def test_none_content_in_middle_messages(self):
        """Messages with content=None (e.g. assistant tool_calls) must not crash."""
        from nanobot.agent.compression import _summary_cache

        _summary_cache.clear()

        provider = MockProvider("Summary with none content.")
        msgs = [
            {"role": "system", "content": "sys"},
        ]
        for i in range(10):
            msgs.append({"role": "user", "content": f"msg {i} " * 200})
            # assistant messages with tool_calls often have content=None
            msgs.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": f"tc_{i}",
                            "type": "function",
                            "function": {"name": "some_tool", "arguments": "{}"},
                        }
                    ],
                }
            )
        msgs.append({"role": "user", "content": "last"})

        result = await summarize_and_compress(
            msgs,
            50,
            provider,
            "m",
            preserve_recent=1,
        )
        assert result[0]["role"] == "system"
        assert result[-1]["content"] == "last"
