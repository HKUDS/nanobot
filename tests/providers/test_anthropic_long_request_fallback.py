"""Regression test for #2709: Anthropic non-stream long-request fallback.

When ``messages.create`` raises the Anthropic SDK's client-side
``ValueError("Streaming is required for operations that may take longer
than 10 minutes...")``, ``AnthropicProvider.chat`` should transparently
retry via ``chat_stream`` instead of surfacing the error.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.providers.anthropic_provider import AnthropicProvider
from nanobot.providers.base import LLMResponse

_LONG_REQUEST_MESSAGE = (
    "Streaming is required for operations that may take longer than 10 minutes. "
    "See https://github.com/anthropics/anthropic-sdk-python#long-requests for more details"
)


def _make_provider() -> AnthropicProvider:
    provider = AnthropicProvider(api_key="test-key")
    provider._client = MagicMock()
    return provider


def test_is_streaming_required_error_matches_value_error() -> None:
    assert AnthropicProvider._is_streaming_required_error(
        ValueError(_LONG_REQUEST_MESSAGE)
    ) is True


def test_is_streaming_required_error_ignores_other_value_errors() -> None:
    assert AnthropicProvider._is_streaming_required_error(
        ValueError("something else went wrong")
    ) is False


def test_is_streaming_required_error_ignores_other_exception_types() -> None:
    assert AnthropicProvider._is_streaming_required_error(
        RuntimeError(_LONG_REQUEST_MESSAGE)
    ) is False


@pytest.mark.asyncio
async def test_chat_falls_back_to_stream_on_long_request_error() -> None:
    provider = _make_provider()
    provider._client.messages.create = AsyncMock(
        side_effect=ValueError(_LONG_REQUEST_MESSAGE)
    )

    expected = LLMResponse(content="streamed result", finish_reason="stop")
    captured: dict[str, Any] = {}

    async def _fake_chat_stream(**kwargs: Any) -> LLMResponse:
        captured.update(kwargs)
        return expected

    provider.chat_stream = _fake_chat_stream  # type: ignore[method-assign]

    result = await provider.chat(
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=64_000,
        temperature=0.5,
        reasoning_effort="high",
        tool_choice="auto",
    )

    assert result is expected
    assert captured["messages"] == [{"role": "user", "content": "hi"}]
    assert captured["max_tokens"] == 64_000
    assert captured["temperature"] == 0.5
    assert captured["reasoning_effort"] == "high"
    assert captured["tool_choice"] == "auto"
    # The fallback must NOT pass an on_content_delta — chat() callers don't
    # expect streaming side-effects.
    assert "on_content_delta" not in captured


@pytest.mark.asyncio
async def test_chat_does_not_fall_back_on_unrelated_value_error() -> None:
    provider = _make_provider()
    provider._client.messages.create = AsyncMock(
        side_effect=ValueError("some other validation failure")
    )

    called = False

    async def _should_not_be_called(**_kwargs: Any) -> LLMResponse:
        nonlocal called
        called = True
        return LLMResponse(content="x", finish_reason="stop")

    provider.chat_stream = _should_not_be_called  # type: ignore[method-assign]

    result = await provider.chat(messages=[{"role": "user", "content": "hi"}])

    assert called is False
    # Generic ValueError flows through _handle_error and surfaces as an error response.
    assert result.finish_reason == "error" or "Error" in (result.content or "")
