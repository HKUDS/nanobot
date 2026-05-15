"""Anthropic streaming idle timeout should follow the full SSE stream, not text only."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.providers.anthropic_provider import AnthropicProvider


def _final_message_stub(text: str = "Hi") -> SimpleNamespace:
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason="end_turn",
        usage=SimpleNamespace(
            input_tokens=3,
            output_tokens=2,
            cache_creation_input_tokens=None,
            cache_read_input_tokens=None,
        ),
    )


class _FakeAsyncStream:
    """Minimal async iterator + context manager mimicking AsyncMessageStream."""

    def __init__(self, chunks: list[SimpleNamespace]) -> None:
        self._chunks = chunks
        self._idx = 0
        self.get_final_message = AsyncMock(return_value=_final_message_stub())

    async def __anext__(self) -> SimpleNamespace:
        if self._idx >= len(self._chunks):
            raise StopAsyncIteration
        c = self._chunks[self._idx]
        self._idx += 1
        return c

    def __aiter__(self) -> _FakeAsyncStream:
        return self

    async def __aenter__(self) -> _FakeAsyncStream:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        pass


@pytest.mark.asyncio
async def test_chat_stream_calls_on_content_delta_only_for_text_delta() -> None:
    """Thinking deltas must be consumed without invoking on_content_delta."""
    provider = AnthropicProvider(api_key="sk-test")
    provider._client = MagicMock()

    chunks = [
        SimpleNamespace(
            type="content_block_delta",
            delta=SimpleNamespace(type="thinking_delta", thinking="think"),
        ),
        SimpleNamespace(
            type="content_block_delta",
            delta=SimpleNamespace(type="text_delta", text="Hi"),
        ),
    ]
    fake = _FakeAsyncStream(chunks)
    stream_cm = MagicMock()
    stream_cm.__aenter__ = AsyncMock(return_value=fake)
    stream_cm.__aexit__ = AsyncMock(return_value=None)
    provider._client.messages.stream = MagicMock(return_value=stream_cm)

    out: list[str] = []

    async def on_delta(s: str) -> None:
        out.append(s)

    await provider.chat_stream(
        messages=[{"role": "user", "content": "hello"}],
        on_content_delta=on_delta,
        on_thinking_delta=None,
    )

    assert out == ["Hi"]
    fake.get_final_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_chat_stream_invokes_on_thinking_delta_for_thinking_delta() -> None:
    provider = AnthropicProvider(api_key="sk-test")
    provider._client = MagicMock()

    chunks = [
        SimpleNamespace(
            type="content_block_delta",
            delta=SimpleNamespace(type="thinking_delta", thinking="a"),
        ),
        SimpleNamespace(
            type="content_block_delta",
            delta=SimpleNamespace(type="thinking_delta", thinking="b"),
        ),
        SimpleNamespace(
            type="content_block_delta",
            delta=SimpleNamespace(type="text_delta", text="X"),
        ),
    ]
    fake = _FakeAsyncStream(chunks)
    stream_cm = MagicMock()
    stream_cm.__aenter__ = AsyncMock(return_value=fake)
    stream_cm.__aexit__ = AsyncMock(return_value=None)
    provider._client.messages.stream = MagicMock(return_value=stream_cm)

    thinking_parts: list[str] = []
    text_parts: list[str] = []

    async def on_thinking(s: str) -> None:
        thinking_parts.append(s)

    async def on_text(s: str) -> None:
        text_parts.append(s)

    await provider.chat_stream(
        messages=[{"role": "user", "content": "hello"}],
        on_content_delta=on_text,
        on_thinking_delta=on_thinking,
    )

    assert thinking_parts == ["a", "b"]
    assert text_parts == ["X"]


@pytest.mark.asyncio
async def test_chat_stream_without_callback_still_finalizes() -> None:
    provider = AnthropicProvider(api_key="sk-test")
    provider._client = MagicMock()

    fake = _FakeAsyncStream([])
    fake.get_final_message = AsyncMock(return_value=_final_message_stub("ok"))
    stream_cm = MagicMock()
    stream_cm.__aenter__ = AsyncMock(return_value=fake)
    stream_cm.__aexit__ = AsyncMock(return_value=None)
    provider._client.messages.stream = MagicMock(return_value=stream_cm)

    res = await provider.chat_stream(
        messages=[{"role": "user", "content": "hello"}],
        on_content_delta=None,
    )
    assert res.content == "ok"
    fake.get_final_message.assert_awaited_once()
