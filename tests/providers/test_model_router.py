from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest

from nanobot.config.schema import FailoverConfig
from nanobot.providers.base import LLMProvider, LLMResponse
from nanobot.providers.failover import ModelCandidate, ModelRouter


class ScriptedProvider(LLMProvider):
    def __init__(
        self,
        model: str,
        responses: list[LLMResponse],
        *,
        stream_chunks: list[list[str]] | None = None,
    ) -> None:
        super().__init__()
        self.model = model
        self.responses = list(responses)
        self.stream_chunks = list(stream_chunks or [])
        self.calls: list[tuple[str | None, str]] = []

    def get_default_model(self) -> str:
        return self.model

    async def chat(self, **kwargs) -> LLMResponse:
        raise AssertionError("ModelRouter should use provider-local chat_with_retry")

    async def chat_with_retry(self, *, model: str | None = None, **kwargs) -> LLMResponse:
        self.calls.append((model, "chat"))
        return self.responses.pop(0)

    async def chat_stream_with_retry(
        self,
        *,
        model: str | None = None,
        on_content_delta: Callable[[str], Awaitable[None]] | None = None,
        **kwargs,
    ) -> LLMResponse:
        self.calls.append((model, "stream"))
        chunks = self.stream_chunks.pop(0) if self.stream_chunks else []
        if on_content_delta:
            for chunk in chunks:
                await on_content_delta(chunk)
        return self.responses.pop(0)


def _router(
    primary: ScriptedProvider,
    fallback: ScriptedProvider | None = None,
    *,
    failover: FailoverConfig | None = None,
) -> ModelRouter:
    fallback_candidates = []
    if fallback is not None:
        fallback_candidates.append(
            ModelCandidate(
                model=fallback.model,
                provider_name="fallback",
                provider_factory=lambda: fallback,
            )
        )
    return ModelRouter(
        primary_provider=primary,
        primary_model=primary.model,
        primary_provider_name="primary",
        fallback_candidates=fallback_candidates,
        failover=failover or FailoverConfig(cooldown_seconds=0),
    )


@pytest.mark.asyncio
async def test_no_fallback_delegates_exactly_once() -> None:
    primary = ScriptedProvider("primary-model", [LLMResponse(content="ok")])
    router = _router(primary)

    response = await router.chat_with_retry(messages=[{"role": "user", "content": "hi"}])

    assert response.content == "ok"
    assert primary.calls == [("primary-model", "chat")]


@pytest.mark.asyncio
async def test_transient_failure_routes_to_fallback() -> None:
    primary = ScriptedProvider(
        "primary-model",
        [LLMResponse(content="timeout", finish_reason="error", error_kind="timeout")],
    )
    fallback = ScriptedProvider("fallback-model", [LLMResponse(content="fallback ok")])
    router = _router(primary, fallback)

    response = await router.chat_with_retry(messages=[{"role": "user", "content": "hi"}])

    assert response.content == "fallback ok"
    assert primary.calls == [("primary-model", "chat")]
    assert fallback.calls == [("fallback-model", "chat")]


@pytest.mark.asyncio
async def test_non_transient_error_does_not_route() -> None:
    primary = ScriptedProvider(
        "primary-model",
        [
            LLMResponse(
                content="401 unauthorized",
                finish_reason="error",
                error_status_code=401,
            )
        ],
    )
    fallback = ScriptedProvider("fallback-model", [LLMResponse(content="fallback ok")])
    router = _router(primary, fallback)

    response = await router.chat_with_retry(messages=[{"role": "user", "content": "hi"}])

    assert response.content == "401 unauthorized"
    assert fallback.calls == []


@pytest.mark.asyncio
async def test_quota_error_does_not_route_by_default() -> None:
    primary = ScriptedProvider(
        "primary-model",
        [
            LLMResponse(
                content="insufficient quota",
                finish_reason="error",
                error_status_code=429,
                error_code="insufficient_quota",
            )
        ],
    )
    fallback = ScriptedProvider("fallback-model", [LLMResponse(content="fallback ok")])
    router = _router(primary, fallback)

    response = await router.chat_with_retry(messages=[{"role": "user", "content": "hi"}])

    assert response.content == "insufficient quota"
    assert fallback.calls == []


@pytest.mark.asyncio
async def test_all_candidates_fail_returns_final_error() -> None:
    primary = ScriptedProvider(
        "primary-model",
        [LLMResponse(content="primary down", finish_reason="error", error_status_code=503)],
    )
    fallback = ScriptedProvider(
        "fallback-model",
        [LLMResponse(content="fallback down", finish_reason="error", error_status_code=500)],
    )
    router = _router(primary, fallback)

    response = await router.chat_with_retry(messages=[{"role": "user", "content": "hi"}])

    assert response.content == "fallback down"
    assert fallback.calls == [("fallback-model", "chat")]


@pytest.mark.asyncio
async def test_cooldown_skips_failed_candidate_on_next_call() -> None:
    primary = ScriptedProvider(
        "primary-model",
        [
            LLMResponse(content="primary down", finish_reason="error", error_status_code=503),
            LLMResponse(content="primary down again", finish_reason="error", error_status_code=503),
        ],
    )
    fallback = ScriptedProvider(
        "fallback-model",
        [
            LLMResponse(content="fallback down", finish_reason="error", error_status_code=500),
        ],
    )
    router = _router(primary, fallback, failover=FailoverConfig(cooldown_seconds=60))

    first = await router.chat_with_retry(messages=[{"role": "user", "content": "hi"}])
    second = await router.chat_with_retry(messages=[{"role": "user", "content": "hi"}])

    assert first.content == "fallback down"
    assert second.content == "primary down again"
    assert fallback.calls == [("fallback-model", "chat")]


@pytest.mark.asyncio
async def test_streaming_discards_failed_candidate_buffer_and_flushes_success() -> None:
    primary = ScriptedProvider(
        "primary-model",
        [LLMResponse(content="primary failed", finish_reason="error", error_status_code=503)],
        stream_chunks=[["bad ", "partial"]],
    )
    fallback = ScriptedProvider(
        "fallback-model",
        [LLMResponse(content="good final")],
        stream_chunks=[["good ", "stream"]],
    )
    router = _router(primary, fallback)
    deltas: list[str] = []

    async def on_delta(delta: str) -> None:
        deltas.append(delta)

    response = await router.chat_stream_with_retry(
        messages=[{"role": "user", "content": "hi"}],
        on_content_delta=on_delta,
    )

    assert response.content == "good final"
    assert deltas == ["good ", "stream"]


@pytest.mark.asyncio
async def test_streaming_flushes_primary_success_buffer() -> None:
    primary = ScriptedProvider(
        "primary-model",
        [LLMResponse(content="primary final")],
        stream_chunks=[["hello", " world"]],
    )
    fallback = ScriptedProvider("fallback-model", [LLMResponse(content="fallback ok")])
    router = _router(primary, fallback)
    deltas: list[str] = []

    async def on_delta(delta: str) -> None:
        deltas.append(delta)

    response = await router.chat_stream_with_retry(
        messages=[{"role": "user", "content": "hi"}],
        on_content_delta=on_delta,
    )

    assert response.content == "primary final"
    assert deltas == ["hello", " world"]
    assert fallback.calls == []
