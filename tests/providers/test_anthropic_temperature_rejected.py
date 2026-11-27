"""Models that refuse ``temperature`` should not fail every turn.

New Claude releases can drop sampling parameters before the version tables in
``anthropic_provider`` know about them. The provider retries once without
``temperature`` and stops sending it for that model.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import anthropic
import httpx
import pytest

from nanobot.providers.anthropic_provider import AnthropicProvider
from nanobot.providers.base import LLMResponse

_MODEL = "claude-newmodel-9"


def _bad_request(message: str) -> anthropic.BadRequestError:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    body = {"type": "error", "error": {"type": "invalid_request_error", "message": message}}
    return anthropic.BadRequestError(
        message,
        response=httpx.Response(400, request=request, json=body),
        body=body,
    )


def _make_provider() -> AnthropicProvider:
    provider = AnthropicProvider(api_key="test-key", default_model=_MODEL)
    provider._client = MagicMock()
    provider._parse_response = lambda response: LLMResponse(  # type: ignore[method-assign]
        content="ok",
        finish_reason="stop",
    )
    return provider


def _build(provider: AnthropicProvider) -> dict[str, Any]:
    return provider._build_kwargs(
        [{"role": "user", "content": "hi"}],
        None,
        None,
        1024,
        0.7,
        None,
        None,
    )


@pytest.mark.asyncio
async def test_chat_retries_without_temperature_and_remembers_model() -> None:
    provider = _make_provider()
    provider._client.messages.create = AsyncMock(
        side_effect=[_bad_request("`temperature` is deprecated for this model."), MagicMock()],
    )

    result = await provider.chat(messages=[{"role": "user", "content": "hi"}], temperature=0.3)

    assert result.content == "ok"
    first, second = provider._client.messages.create.await_args_list
    assert first.kwargs["temperature"] == 0.3
    assert "temperature" not in second.kwargs
    assert "temperature" not in _build(provider)


@pytest.mark.asyncio
async def test_chat_does_not_retry_unrelated_bad_request() -> None:
    provider = _make_provider()
    provider._client.messages.create = AsyncMock(
        side_effect=_bad_request("max_tokens: must be greater than 0"),
    )

    result = await provider.chat(messages=[{"role": "user", "content": "hi"}])

    assert result.finish_reason == "error"
    assert provider._client.messages.create.await_count == 1
    assert _build(provider)["temperature"] == 0.7


@pytest.mark.asyncio
async def test_chat_retries_only_once() -> None:
    provider = _make_provider()
    provider._client.messages.create = AsyncMock(
        side_effect=_bad_request("`temperature` is deprecated for this model."),
    )

    result = await provider.chat(messages=[{"role": "user", "content": "hi"}])

    assert result.finish_reason == "error"
    assert provider._client.messages.create.await_count == 2


class _EmptyStream:
    def __init__(self) -> None:
        self.get_final_message = AsyncMock(return_value=MagicMock(stop_reason="end_turn"))

    async def __aenter__(self) -> _EmptyStream:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def __aiter__(self) -> _EmptyStream:
        return self

    async def __anext__(self) -> Any:
        raise StopAsyncIteration


@pytest.mark.asyncio
async def test_chat_stream_retries_without_temperature() -> None:
    provider = _make_provider()
    provider._client.messages.stream = MagicMock(
        side_effect=[
            _bad_request("`temperature` is not supported for this model."),
            _EmptyStream(),
        ],
    )

    result = await provider.chat_stream(messages=[{"role": "user", "content": "hi"}])

    assert result.content == "ok"
    first, second = provider._client.messages.stream.call_args_list
    assert "temperature" in first.kwargs
    assert "temperature" not in second.kwargs
