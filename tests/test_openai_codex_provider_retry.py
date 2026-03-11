from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from nanobot.providers.openai_codex_provider import (
    OpenAICodexProvider,
    _build_timeout,
    _is_retryable_error,
)


def test_is_retryable_error_only_for_transient_failures() -> None:
    assert _is_retryable_error(httpx.ReadTimeout("timeout")) is True
    assert _is_retryable_error(httpx.TransportError("network")) is True
    assert _is_retryable_error(RuntimeError("HTTP 500: upstream")) is True
    assert _is_retryable_error(RuntimeError("HTTP 429: rate limit")) is False
    assert _is_retryable_error(RuntimeError("HTTP 400: bad request")) is False


def test_build_timeout_uses_read_timeout_and_clamped_connect_timeout() -> None:
    timeout = _build_timeout(180.0)
    assert timeout.read == 180.0
    assert timeout.connect == 10.0

    short_timeout = _build_timeout(3.0)
    assert short_timeout.read == 3.0
    assert short_timeout.connect == 3.0


@pytest.mark.asyncio
async def test_chat_retries_once_for_retryable_error() -> None:
    provider = OpenAICodexProvider(timeout_s=120, max_retries=1)
    token = SimpleNamespace(account_id="acct_123", access="token_abc")
    request_mock = AsyncMock(side_effect=[httpx.ReadTimeout(""), ("ok", [], "stop")])

    with patch("nanobot.providers.openai_codex_provider.get_codex_token", return_value=token), patch(
        "nanobot.providers.openai_codex_provider._request_codex", new=request_mock
    ), patch("nanobot.providers.openai_codex_provider.asyncio.sleep", new=AsyncMock()) as sleep_mock:
        result = await provider.chat([{"role": "user", "content": "hello"}])

    assert result.finish_reason == "stop"
    assert result.content == "ok"
    assert request_mock.await_count == 2
    sleep_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_chat_does_not_retry_non_retryable_error() -> None:
    provider = OpenAICodexProvider(timeout_s=120, max_retries=2)
    token = SimpleNamespace(account_id="acct_123", access="token_abc")
    request_mock = AsyncMock(side_effect=RuntimeError("HTTP 429: rate limit"))

    with patch("nanobot.providers.openai_codex_provider.get_codex_token", return_value=token), patch(
        "nanobot.providers.openai_codex_provider._request_codex", new=request_mock
    ):
        result = await provider.chat([{"role": "user", "content": "hello"}])

    assert result.finish_reason == "error"
    assert "HTTP 429" in result.content
    assert request_mock.await_count == 1


@pytest.mark.asyncio
async def test_chat_error_message_keeps_exception_type_for_empty_timeout_text() -> None:
    provider = OpenAICodexProvider(timeout_s=120, max_retries=0)
    token = SimpleNamespace(account_id="acct_123", access="token_abc")
    request_mock = AsyncMock(side_effect=httpx.ReadTimeout(""))

    with patch("nanobot.providers.openai_codex_provider.get_codex_token", return_value=token), patch(
        "nanobot.providers.openai_codex_provider._request_codex", new=request_mock
    ):
        result = await provider.chat([{"role": "user", "content": "hello"}])

    assert result.finish_reason == "error"
    assert "ReadTimeout" in result.content
