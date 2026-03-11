import asyncio

import pytest

from nanobot.providers.base import GenerationSettings, LLMProvider, LLMResponse


class ScriptedProvider(LLMProvider):
    def __init__(self, responses):
        super().__init__()
        self._responses = list(responses)
        self.calls = 0
        self.last_kwargs: dict = {}

    async def chat(self, *args, **kwargs) -> LLMResponse:
        self.calls += 1
        self.last_kwargs = kwargs
        response = self._responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response

    def get_default_model(self) -> str:
        return "test-model"


@pytest.mark.asyncio
async def test_chat_with_retry_retries_transient_error_then_succeeds(monkeypatch) -> None:
    provider = ScriptedProvider([
        LLMResponse(content="429 rate limit", finish_reason="error"),
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
async def test_chat_with_retry_does_not_retry_non_transient_error(monkeypatch) -> None:
    provider = ScriptedProvider([
        LLMResponse(content="401 unauthorized", finish_reason="error"),
    ])
    delays: list[int] = []

    async def _fake_sleep(delay: int) -> None:
        delays.append(delay)

    monkeypatch.setattr("nanobot.providers.base.asyncio.sleep", _fake_sleep)

    response = await provider.chat_with_retry(messages=[{"role": "user", "content": "hello"}])

    assert response.content == "401 unauthorized"
    assert provider.calls == 1
    assert delays == []


@pytest.mark.asyncio
async def test_chat_with_retry_returns_final_error_after_retries(monkeypatch) -> None:
    provider = ScriptedProvider([
        LLMResponse(content="429 rate limit a", finish_reason="error"),
        LLMResponse(content="429 rate limit b", finish_reason="error"),
        LLMResponse(content="429 rate limit c", finish_reason="error"),
        LLMResponse(content="503 final server error", finish_reason="error"),
    ])
    delays: list[int] = []

    async def _fake_sleep(delay: int) -> None:
        delays.append(delay)

    monkeypatch.setattr("nanobot.providers.base.asyncio.sleep", _fake_sleep)

    response = await provider.chat_with_retry(messages=[{"role": "user", "content": "hello"}])

    assert response.content == "503 final server error"
    assert provider.calls == 4
    assert delays == [1, 2, 4]


@pytest.mark.asyncio
async def test_chat_with_retry_preserves_cancelled_error() -> None:
    provider = ScriptedProvider([asyncio.CancelledError()])

    with pytest.raises(asyncio.CancelledError):
        await provider.chat_with_retry(messages=[{"role": "user", "content": "hello"}])


@pytest.mark.asyncio
async def test_chat_with_retry_uses_provider_generation_defaults() -> None:
    """When callers omit generation params, provider.generation defaults are used."""
    provider = ScriptedProvider([LLMResponse(content="ok")])
    provider.generation = GenerationSettings(temperature=0.2, max_tokens=321, reasoning_effort="high")

    await provider.chat_with_retry(messages=[{"role": "user", "content": "hello"}])

    assert provider.last_kwargs["temperature"] == 0.2
    assert provider.last_kwargs["max_tokens"] == 321
    assert provider.last_kwargs["reasoning_effort"] == "high"


@pytest.mark.asyncio
async def test_chat_with_retry_explicit_override_beats_defaults() -> None:
    """Explicit kwargs should override provider.generation defaults."""
    provider = ScriptedProvider([LLMResponse(content="ok")])
    provider.generation = GenerationSettings(temperature=0.2, max_tokens=321, reasoning_effort="high")

    await provider.chat_with_retry(
        messages=[{"role": "user", "content": "hello"}],
        temperature=0.9,
        max_tokens=9999,
        reasoning_effort="low",
    )

    assert provider.last_kwargs["temperature"] == 0.9
    assert provider.last_kwargs["max_tokens"] == 9999
    assert provider.last_kwargs["reasoning_effort"] == "low"
