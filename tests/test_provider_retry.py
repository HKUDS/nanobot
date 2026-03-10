import asyncio

import httpx
import pytest

from nanobot.providers.base import LLMProvider, LLMResponse, ProviderRequestError


class ScriptedProvider(LLMProvider):
    def __init__(self, responses):
        super().__init__()
        self._responses = list(responses)
        self.calls = 0

    async def chat(self, *args, **kwargs) -> LLMResponse:
        self.calls += 1
        response = self._responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response

    def get_default_model(self) -> str:
        return "test-model"


@pytest.mark.asyncio
async def test_chat_with_retry_retries_structured_retryable_error(monkeypatch) -> None:
    provider = ScriptedProvider([
        LLMResponse(
            content="temporary upstream failure",
            finish_reason="error",
            error=ProviderRequestError(
                "temporary upstream failure",
                retryable=True,
                status_code=503,
            ),
        ),
        LLMResponse(content="ok"),
    ])
    delays: list[int] = []

    async def _fake_sleep(delay: int) -> None:
        delays.append(delay)

    monkeypatch.setattr("nanobot.providers.base.asyncio.sleep", _fake_sleep)

    response = await provider.chat_with_retry(messages=[{"role": "user", "content": "hello"}])

    assert response.finish_reason == "stop"
    assert response.content == "ok"
    assert provider.calls == 2
    assert delays == [1]


@pytest.mark.asyncio
async def test_chat_with_retry_does_not_retry_structured_non_retryable_error(monkeypatch) -> None:
    provider = ScriptedProvider([
        LLMResponse(
            content="bad request",
            finish_reason="error",
            error=ProviderRequestError("bad request", retryable=False, status_code=400),
        ),
    ])
    delays: list[int] = []

    async def _fake_sleep(delay: int) -> None:
        delays.append(delay)

    monkeypatch.setattr("nanobot.providers.base.asyncio.sleep", _fake_sleep)

    response = await provider.chat_with_retry(messages=[{"role": "user", "content": "hello"}])

    assert response.content == "bad request"
    assert provider.calls == 1
    assert delays == []


@pytest.mark.asyncio
async def test_chat_with_retry_keeps_legacy_string_matching(monkeypatch) -> None:
    provider = ScriptedProvider([
        httpx.ReadTimeout("timed out"),
        LLMResponse(content="recovered"),
    ])
    delays: list[int] = []

    async def _fake_sleep(delay: int) -> None:
        delays.append(delay)

    monkeypatch.setattr("nanobot.providers.base.asyncio.sleep", _fake_sleep)

    response = await provider.chat_with_retry(messages=[{"role": "user", "content": "hello"}])

    assert response.content == "recovered"
    assert provider.calls == 2
    assert delays == [1]


@pytest.mark.asyncio
async def test_chat_with_retry_preserves_cancelled_error() -> None:
    provider = ScriptedProvider([asyncio.CancelledError()])

    with pytest.raises(asyncio.CancelledError):
        await provider.chat_with_retry(messages=[{"role": "user", "content": "hello"}])
