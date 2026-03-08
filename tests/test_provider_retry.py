import httpx
import pytest

from nanobot.config.schema import LLMRetryConfig
from nanobot.providers.base import LLMProvider, LLMResponse, ProviderRequestError


class DummyProvider(LLMProvider):
    def __init__(self, outcomes, retry_config: LLMRetryConfig | None = None):
        super().__init__(retry_config=retry_config)
        self._outcomes = list(outcomes)
        self.calls = 0

    async def _chat_once(
        self,
        messages,
        tools=None,
        model=None,
        max_tokens=4096,
        temperature=0.7,
        reasoning_effort=None,
    ) -> LLMResponse:
        self.calls += 1
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def get_default_model(self) -> str:
        return "dummy"


def _retry_config(max_attempts: int = 3) -> LLMRetryConfig:
    return LLMRetryConfig(
        enabled=True,
        max_attempts=max_attempts,
        initial_delay_ms=0,
        max_delay_ms=0,
        backoff_multiplier=1.0,
        jitter_ratio=0.0,
    )


@pytest.mark.asyncio
async def test_provider_retries_retryable_error_until_success():
    provider = DummyProvider(
        [
            ProviderRequestError("temporary upstream failure", retryable=True, status_code=503),
            LLMResponse(content="ok"),
        ],
        retry_config=_retry_config(max_attempts=2),
    )

    result = await provider.chat(messages=[{"role": "user", "content": "hello"}])

    assert result.content == "ok"
    assert provider.calls == 2


@pytest.mark.asyncio
async def test_provider_does_not_retry_non_retryable_error():
    provider = DummyProvider(
        [
            ProviderRequestError("bad request", retryable=False, status_code=400),
            LLMResponse(content="unreachable"),
        ],
        retry_config=_retry_config(max_attempts=3),
    )

    result = await provider.chat(messages=[{"role": "user", "content": "hello"}])

    assert result.finish_reason == "error"
    assert result.content == "bad request"
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_provider_retries_generic_timeout_exception():
    provider = DummyProvider(
        [
            httpx.ReadTimeout("timed out"),
            LLMResponse(content="recovered"),
        ],
        retry_config=_retry_config(max_attempts=2),
    )

    result = await provider.chat(messages=[{"role": "user", "content": "hello"}])

    assert result.content == "recovered"
    assert provider.calls == 2
