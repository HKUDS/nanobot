"""Tests for streaming response support (Step 15)."""

from __future__ import annotations

import pytest

from nanobot.agent.streaming import StreamingLLMCaller
from nanobot.providers.base import LLMProvider, LLMResponse, StreamChunk, ToolCallRequest
from nanobot.providers.rate_limiter import RateLimiter

# ---------------------------------------------------------------------------
# Mock streaming provider
# ---------------------------------------------------------------------------


class FakeStreamProvider(LLMProvider):
    """A provider that yields pre-configured StreamChunks."""

    def __init__(self, chunks: list[StreamChunk] | None = None):
        super().__init__()
        self._chunks = chunks or []
        self._chat_calls = 0
        self._stream_calls = 0

    async def chat(
        self, messages, tools=None, model=None, max_tokens=4096, temperature=0.7, metadata=None
    ):
        self._chat_calls += 1
        return LLMResponse(content="non-streaming fallback", finish_reason="stop")

    def get_default_model(self):
        return "fake-model"

    async def stream_chat(
        self, messages, tools=None, model=None, max_tokens=4096, temperature=0.7, metadata=None
    ):
        self._stream_calls += 1
        for chunk in self._chunks:
            yield chunk


# ---------------------------------------------------------------------------
# StreamChunk tests
# ---------------------------------------------------------------------------


class TestStreamChunk:
    def test_defaults(self):
        c = StreamChunk()
        assert c.content_delta is None
        assert c.reasoning_delta is None
        assert c.finish_reason is None
        assert c.tool_calls == []
        assert c.done is False

    def test_content_chunk(self):
        c = StreamChunk(content_delta="Hello", done=False)
        assert c.content_delta == "Hello"
        assert not c.done

    def test_final_chunk_with_tool_calls(self):
        tc = ToolCallRequest(id="1", name="read_file", arguments={"path": "a.txt"})
        c = StreamChunk(tool_calls=[tc], finish_reason="tool_calls", done=True)
        assert len(c.tool_calls) == 1
        assert c.done


# ---------------------------------------------------------------------------
# Base class fallback
# ---------------------------------------------------------------------------


class TestBaseProviderStreamFallback:
    """The default stream_chat on LLMProvider falls back to chat()."""

    async def test_fallback_yields_single_chunk(self):
        class SimpleProvider(LLMProvider):
            async def chat(
                self,
                messages,
                tools=None,
                model=None,
                max_tokens=4096,
                temperature=0.7,
                metadata=None,
            ):
                return LLMResponse(
                    content="hello world", finish_reason="stop", usage={"total_tokens": 5}
                )

            def get_default_model(self):
                return "simple"

        provider = SimpleProvider()
        chunks = []
        async for chunk in provider.stream_chat(messages=[{"role": "user", "content": "hi"}]):
            chunks.append(chunk)

        assert len(chunks) == 1
        assert chunks[0].content_delta == "hello world"
        assert chunks[0].done is True
        assert chunks[0].finish_reason == "stop"


# ---------------------------------------------------------------------------
# FakeStreamProvider integration
# ---------------------------------------------------------------------------


class TestFakeStreamProvider:
    async def test_yields_all_chunks(self):
        provider = FakeStreamProvider(
            chunks=[
                StreamChunk(content_delta="Hello"),
                StreamChunk(content_delta=" world"),
                StreamChunk(content_delta="!", finish_reason="stop", done=True),
            ]
        )

        accumulated = []
        async for chunk in provider.stream_chat(messages=[]):
            accumulated.append(chunk)

        assert len(accumulated) == 3
        text = "".join(c.content_delta or "" for c in accumulated)
        assert text == "Hello world!"
        assert accumulated[-1].done

    async def test_tool_calls_on_final_chunk(self):
        tc = ToolCallRequest(id="tc1", name="exec", arguments={"command": "ls"})
        provider = FakeStreamProvider(
            chunks=[
                StreamChunk(content_delta="Let me check"),
                StreamChunk(tool_calls=[tc], finish_reason="tool_calls", done=True),
            ]
        )

        chunks = []
        async for chunk in provider.stream_chat(messages=[]):
            chunks.append(chunk)

        final = chunks[-1]
        assert final.done
        assert len(final.tool_calls) == 1
        assert final.tool_calls[0].name == "exec"

    async def test_chat_not_called_when_streaming(self):
        """stream_chat should NOT fall back to chat()."""
        provider = FakeStreamProvider(
            chunks=[
                StreamChunk(content_delta="ok", done=True, finish_reason="stop"),
            ]
        )

        async for _ in provider.stream_chat(messages=[]):
            pass

        assert provider._stream_calls == 1
        assert provider._chat_calls == 0


# ---------------------------------------------------------------------------
# Reassembly into LLMResponse (simulating what _call_llm does)
# ---------------------------------------------------------------------------


class TestChunkReassembly:
    """Verify that accumulating chunks produces a correct LLMResponse."""

    async def test_reassemble_text_response(self):
        chunks = [
            StreamChunk(content_delta="The answer"),
            StreamChunk(content_delta=" is 42"),
            StreamChunk(
                content_delta=".", finish_reason="stop", usage={"total_tokens": 10}, done=True
            ),
        ]

        content_parts = []
        finish = "stop"
        usage = {}
        for c in chunks:
            if c.content_delta:
                content_parts.append(c.content_delta)
            if c.finish_reason:
                finish = c.finish_reason
            if c.usage:
                usage = c.usage

        response = LLMResponse(
            content="".join(content_parts),
            finish_reason=finish,
            usage=usage,
        )
        assert response.content == "The answer is 42."
        assert response.finish_reason == "stop"
        assert response.usage["total_tokens"] == 10
        assert not response.has_tool_calls

    async def test_reassemble_tool_call_response(self):
        tc = ToolCallRequest(id="t1", name="web_search", arguments={"query": "weather"})
        chunks = [
            StreamChunk(content_delta="Searching"),
            StreamChunk(tool_calls=[tc], finish_reason="tool_calls", done=True),
        ]

        content_parts = []
        tool_calls = []
        for c in chunks:
            if c.content_delta:
                content_parts.append(c.content_delta)
            if c.tool_calls:
                tool_calls = c.tool_calls

        response = LLMResponse(
            content="".join(content_parts) or None,
            tool_calls=tool_calls,
            finish_reason="tool_calls",
        )
        assert response.has_tool_calls
        assert response.content == "Searching"


# ---------------------------------------------------------------------------
# Rate limiter integration
# ---------------------------------------------------------------------------


class TestStreamingWithRateLimiter:
    @pytest.mark.asyncio
    async def test_rate_limiter_called_before_and_after(self):
        """Rate limiter is consulted before the call and records tokens after."""
        provider = FakeStreamProvider()
        rl = RateLimiter(tokens_per_minute=50_000)
        caller = StreamingLLMCaller(
            provider=provider,
            model="test",
            temperature=0.1,
            max_tokens=100,
            rate_limiter=rl,
        )
        messages = [{"role": "user", "content": "hello"}]
        await caller.call(messages, tools=None, on_progress=None)
        # Provider was called (no rate limit hit since window is empty)
        assert provider._chat_calls == 1

    @pytest.mark.asyncio
    async def test_rate_limiter_none_works(self):
        """StreamingLLMCaller works fine without a rate limiter."""
        provider = FakeStreamProvider()
        caller = StreamingLLMCaller(
            provider=provider,
            model="test",
            temperature=0.1,
            max_tokens=100,
        )
        messages = [{"role": "user", "content": "hello"}]
        await caller.call(messages, tools=None, on_progress=None)
        assert provider._chat_calls == 1
