from __future__ import annotations

import asyncio
from collections.abc import Iterator
from types import SimpleNamespace

import pytest

from nanobot.llm_usage.context import llm_usage_source
from nanobot.llm_usage.models import LLMCallRecord
from nanobot.providers.base import LLMProvider, LLMResponse, LLMUsage
from nanobot.providers.fallback_provider import FallbackProvider


class _SequenceProvider(LLMProvider):
    _CHAT_RETRY_DELAYS = (0,)

    def __init__(self, responses: Iterator[LLMResponse]) -> None:
        super().__init__(provider_name="test-provider")
        self._responses = responses

    async def chat(self, **_kwargs: object) -> LLMResponse:
        return next(self._responses)

    def get_default_model(self) -> str:
        return "test-model"


class _NoRetryProvider(_SequenceProvider):
    _CHAT_RETRY_DELAYS = ()


class _BlockingProvider(LLMProvider):
    async def chat(self, **_kwargs: object) -> LLMResponse:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    async def chat_stream(self, **_kwargs: object) -> LLMResponse:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    def get_default_model(self) -> str:
        return "test-model"


class _StreamingProvider(LLMProvider):
    async def chat(self, **_kwargs: object) -> LLMResponse:
        raise AssertionError("streaming path expected")

    async def chat_stream(self, **kwargs: object) -> LLMResponse:
        on_thinking_delta = kwargs.get("on_thinking_delta")
        if callable(on_thinking_delta):
            await on_thinking_delta("thinking")
        on_content_delta = kwargs.get("on_content_delta")
        if callable(on_content_delta):
            await on_content_delta("ok")
        return LLMResponse(
            content="ok",
            usage=LLMUsage.reported(input_tokens=12, output_tokens=2),
        )

    def get_default_model(self) -> str:
        return "test-model"


@pytest.mark.asyncio
async def test_observer_receives_every_retry_attempt() -> None:
    provider = _SequenceProvider(
        iter(
            [
                LLMResponse(
                    content="temporary failure",
                    finish_reason="error",
                    error_kind="timeout",
                ),
                LLMResponse(
                    content="ok",
                    usage=LLMUsage.reported(
                        input_tokens=100,
                        output_tokens=20,
                        cache_read_tokens=60,
                    ),
                ),
            ]
        )
    )
    events: list[LLMCallRecord] = []
    provider.set_llm_call_observer(events.append)

    with llm_usage_source("api"):
        response = await provider.chat_with_retry(
            messages=[{"role": "user", "content": "hello"}],
            model="selected-model",
        )

    assert response.finish_reason == "stop"
    assert len(events) == 2
    assert [event.finish_reason for event in events] == ["error", "stop"]
    assert all(event.provider == "test-provider" for event in events)
    assert all(event.model == "selected-model" for event in events)
    assert all(event.source == "api" for event in events)
    assert events[1].usage is not None
    assert events[1].usage.cache_read_tokens == 60


@pytest.mark.asyncio
async def test_observer_estimates_missing_success_usage_without_storing_content() -> None:
    provider = _SequenceProvider(iter([LLMResponse(content="hello")]))
    events: list[LLMCallRecord] = []
    provider.set_llm_call_observer(events.append)

    response = await provider.chat_with_retry(
        messages=[{"role": "user", "content": "hello"}],
    )

    assert response.usage is not None
    assert response.usage.source == "estimated"
    assert events[0].usage == response.usage
    assert "content" not in LLMCallRecord.__dataclass_fields__


@pytest.mark.asyncio
async def test_observer_failure_never_breaks_provider_call() -> None:
    provider = _SequenceProvider(iter([LLMResponse(content="ok")]))

    def _fail(_event: LLMCallRecord) -> None:
        raise RuntimeError("disk unavailable")

    provider.set_llm_call_observer(_fail)
    response = await provider.chat_with_retry(
        messages=[{"role": "user", "content": "hello"}],
    )

    assert response.content == "ok"


@pytest.mark.asyncio
async def test_stream_observer_records_physical_attempt_timing(monkeypatch) -> None:
    provider = _StreamingProvider(provider_name="streaming-provider")
    events: list[LLMCallRecord] = []
    provider.set_llm_call_observer(events.append)
    monotonic_values = iter(
        [
            1_000_000_000,
            1_005_000_000,
            1_012_000_000,
            1_013_000_000,
        ]
    )
    monkeypatch.setattr(
        "nanobot.providers.base.time.monotonic_ns",
        lambda: next(monotonic_values),
    )

    response = await provider.chat_stream_with_retry(
        messages=[{"role": "user", "content": "hello"}],
        on_content_delta=lambda _delta: asyncio.sleep(0),
        on_thinking_delta=lambda _delta: asyncio.sleep(0),
    )

    assert len(events) == 1
    usage = events[0].usage
    assert usage is not None
    assert usage.ttft_ms == 5
    assert usage.generation_ms == 7
    assert usage.timed_requests == 1
    assert usage.measured_output_tokens == 2
    assert response.usage == usage


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_observer_records_cancelled_provider_attempt(stream: bool) -> None:
    provider = _BlockingProvider(provider_name="blocking-provider")
    events: list[LLMCallRecord] = []
    provider.set_llm_call_observer(events.append)
    call = provider.chat_stream_with_retry if stream else provider.chat_with_retry

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(
            call(messages=[{"role": "user", "content": "hello"}]),
            timeout=0.01,
        )

    assert len(events) == 1
    assert events[0].finish_reason == "cancelled"
    assert events[0].error_kind == "cancelled"
    assert events[0].usage is None


@pytest.mark.asyncio
async def test_fallback_provider_propagates_observer_to_every_leaf() -> None:
    primary = _NoRetryProvider(
        iter(
            [
                LLMResponse(
                    content="primary unavailable",
                    finish_reason="error",
                    error_kind="timeout",
                )
            ]
        )
    )
    fallback = _SequenceProvider(
        iter(
            [
                LLMResponse(
                    content="fallback ok",
                    usage=LLMUsage.reported(input_tokens=12, output_tokens=3),
                )
            ]
        )
    )
    preset = SimpleNamespace(
        model="fallback-model",
        max_tokens=256,
        temperature=0.2,
        reasoning_effort=None,
        context_window_tokens=4_096,
    )
    provider = FallbackProvider(primary, [preset], lambda _preset: fallback)
    events: list[LLMCallRecord] = []
    provider.set_llm_call_observer(events.append)

    response = await provider.chat_with_retry(
        messages=[{"role": "user", "content": "hello"}],
        model="primary-model",
    )

    assert response.content == "fallback ok"
    assert [(event.model, event.finish_reason) for event in events] == [
        ("primary-model", "error"),
        ("fallback-model", "stop"),
    ]
