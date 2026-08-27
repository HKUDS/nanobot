"""Tests for explicit OpenAI Responses and Chat Completions attempts."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from nanobot.providers.base import (
    GenerationSettings,
    LLMResponse,
    ProviderAttempt,
    ProviderCallContext,
)
from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.providers.registry import find_by_name


@pytest.mark.asyncio
async def test_responses_compatibility_fallback_becomes_a_new_chat_attempt() -> None:
    provider = OpenAICompatProvider(
        api_key="test",
        default_model="gpt-5",
        spec=find_by_name("openai"),
    )
    source_context = ProviderCallContext(
        context_window_tokens=128_000,
        session_id="webui:test",
    )
    route = provider.create_attempt_route(
        model="gpt-5",
        generation=GenerationSettings(reasoning_effort="medium"),
        context_window_tokens=128_000,
        provider_context=source_context,
        retry_mode="standard",
    )

    responses_attempt = await route.start()
    assert isinstance(responses_attempt, ProviderAttempt)
    assert responses_attempt.transport == "responses"
    assert responses_attempt.native_compaction is True
    assert responses_attempt.provider_context == source_context

    compatibility_error = LLMResponse(
        content="Error: unsupported Responses API parameter",
        finish_reason="error",
        error_status_code=400,
        error_kind="invalid_request",
    )
    chat_attempt = await route.advance(compatibility_error, streamed=False)

    assert isinstance(chat_attempt, ProviderAttempt)
    assert chat_attempt is not responses_attempt
    assert chat_attempt.transport == "chat_completions"
    assert chat_attempt.native_compaction is False
    assert chat_attempt.continuation == "rebuild"
    assert chat_attempt.provider_context == ProviderCallContext(session_id="webui:test")


@pytest.mark.asyncio
async def test_attempt_transport_is_forced_at_execution() -> None:
    provider = OpenAICompatProvider(
        api_key="test",
        default_model="gpt-5",
        spec=find_by_name("openai"),
    )
    route = provider.create_attempt_route(
        model="gpt-5",
        generation=GenerationSettings(reasoning_effort="medium"),
        context_window_tokens=128_000,
        provider_context=None,
        retry_mode="standard",
    )
    attempt = await route.start()
    assert isinstance(attempt, ProviderAttempt)

    with patch.object(
        provider,
        "chat",
        new_callable=AsyncMock,
        return_value=LLMResponse(content="ok"),
    ) as chat:
        response = await provider.chat_attempt(
            attempt=attempt,
            provider_context=attempt.provider_context,
            messages=[{"role": "user", "content": "hello"}],
        )

    assert response.content == "ok"
    assert chat.await_args.kwargs["_attempt_transport"] == "responses"


@pytest.mark.asyncio
async def test_native_compaction_fallback_becomes_a_new_responses_attempt() -> None:
    provider = OpenAICompatProvider(
        api_key="test",
        default_model="gpt-5",
        spec=find_by_name("openai"),
    )
    route = provider.create_attempt_route(
        model="gpt-5",
        generation=GenerationSettings(reasoning_effort="medium"),
        context_window_tokens=128_000,
        provider_context=ProviderCallContext(context_window_tokens=128_000),
        retry_mode="standard",
    )
    native_attempt = await route.start()
    assert isinstance(native_attempt, ProviderAttempt)

    local_fit_attempt = await route.advance(
        LLMResponse(
            content="Error: unknown parameter context_management",
            finish_reason="error",
            error_status_code=400,
            error_kind="native_compaction_fallback",
        ),
        streamed=False,
    )

    assert isinstance(local_fit_attempt, ProviderAttempt)
    assert local_fit_attempt is not native_attempt
    assert local_fit_attempt.transport == "responses"
    assert local_fit_attempt.native_compaction is False
    assert local_fit_attempt.provider_context == ProviderCallContext()
    assert provider.supports_native_compaction("gpt-5") is False


@pytest.mark.asyncio
async def test_transport_fallback_bypasses_leaf_image_retry() -> None:
    class CompatibilityError(Exception):
        status_code = 400
        body = {"error": "unknown parameter previous_response_id"}

    provider = OpenAICompatProvider(
        api_key="test",
        default_model="gpt-5",
        spec=find_by_name("openai"),
    )
    create_response = AsyncMock(side_effect=CompatibilityError())
    provider._client = SimpleNamespace(
        responses=SimpleNamespace(create=create_response),
    )
    route = provider.create_attempt_route(
        model="gpt-5",
        generation=GenerationSettings(reasoning_effort="medium"),
        context_window_tokens=None,
        provider_context=None,
        retry_mode="standard",
    )
    attempt = await route.start()
    assert isinstance(attempt, ProviderAttempt)

    response = await provider.chat_with_retry(
        messages=[{
            "role": "user",
            "content": [{
                "type": "image_url",
                "image_url": {"url": "data:image/png;base64,AAAA"},
            }],
        }],
        model="gpt-5",
        reasoning_effort="medium",
        _provider_attempt=attempt,
    )

    assert response.error_kind == "route_fallback"
    assert create_response.await_count == 1


@pytest.mark.asyncio
async def test_native_compaction_error_bypasses_hidden_provider_retry() -> None:
    class CompatibilityError(Exception):
        status_code = 400
        body = {"error": "unknown parameter context_management"}

    provider = OpenAICompatProvider(
        api_key="test",
        default_model="gpt-5",
        spec=find_by_name("openai"),
    )
    create_response = AsyncMock(side_effect=CompatibilityError())
    provider._client = SimpleNamespace(
        responses=SimpleNamespace(create=create_response),
    )
    provider_context = ProviderCallContext(context_window_tokens=128_000)
    route = provider.create_attempt_route(
        model="gpt-5",
        generation=GenerationSettings(reasoning_effort="medium"),
        context_window_tokens=128_000,
        provider_context=provider_context,
        retry_mode="standard",
    )
    attempt = await route.start()
    assert isinstance(attempt, ProviderAttempt)

    response = await provider.chat_with_retry(
        messages=[{"role": "user", "content": "hello"}],
        model="gpt-5",
        reasoning_effort="medium",
        provider_context=attempt.provider_context,
        _provider_attempt=attempt,
    )

    assert response.error_kind == "native_compaction_fallback"
    assert create_response.await_count == 1
