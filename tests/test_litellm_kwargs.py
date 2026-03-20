"""Regression tests for PR #2026 — litellm_kwargs injection from ProviderSpec.

Validates that:
- OpenRouter uses litellm_prefix (NOT custom_llm_provider) to avoid LiteLLM double-prefixing.
- The litellm_kwargs mechanism works correctly for providers that declare it.
- Non-gateway providers are unaffected.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from nanobot.providers.litellm_provider import LiteLLMProvider
from nanobot.providers.registry import find_by_name


def _fake_response(content: str = "ok") -> SimpleNamespace:
    """Build a minimal acompletion-shaped response object."""
    message = SimpleNamespace(
        content=content,
        tool_calls=None,
        reasoning_content=None,
        thinking_blocks=None,
    )
    choice = SimpleNamespace(message=message, finish_reason="stop")
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    return SimpleNamespace(choices=[choice], usage=usage)


def test_openrouter_spec_uses_prefix_not_custom_llm_provider() -> None:
    """OpenRouter must rely on litellm_prefix, not custom_llm_provider kwarg.

    LiteLLM internally adds a provider/ prefix when custom_llm_provider is set,
    which double-prefixes models (openrouter/anthropic/model) and breaks the API.
    """
    spec = find_by_name("openrouter")
    assert spec is not None
    assert spec.litellm_prefix == "openrouter"
    assert "custom_llm_provider" not in spec.litellm_kwargs, (
        "custom_llm_provider causes LiteLLM to double-prefix the model name"
    )


@pytest.mark.asyncio
async def test_openrouter_prefixes_model_correctly() -> None:
    """OpenRouter should prefix model as openrouter/vendor/model for LiteLLM routing."""
    mock_acompletion = AsyncMock(return_value=_fake_response())

    with patch("nanobot.providers.litellm_provider.acompletion", mock_acompletion):
        provider = LiteLLMProvider(
            api_key="sk-or-test-key",
            api_base="https://openrouter.ai/api/v1",
            default_model="anthropic/claude-sonnet-4-5",
            provider_name="openrouter",
        )
        await provider.chat(
            messages=[{"role": "user", "content": "hello"}],
            model="anthropic/claude-sonnet-4-5",
        )

    call_kwargs = mock_acompletion.call_args.kwargs
    assert call_kwargs["model"] == "openrouter/anthropic/claude-sonnet-4-5", (
        "LiteLLM needs openrouter/ prefix to detect the provider and strip it before API call"
    )
    assert "custom_llm_provider" not in call_kwargs


@pytest.mark.asyncio
async def test_non_gateway_provider_no_extra_kwargs() -> None:
    """Standard (non-gateway) providers must NOT inject any litellm_kwargs."""
    mock_acompletion = AsyncMock(return_value=_fake_response())

    with patch("nanobot.providers.litellm_provider.acompletion", mock_acompletion):
        provider = LiteLLMProvider(
            api_key="sk-ant-test-key",
            default_model="claude-sonnet-4-5",
        )
        await provider.chat(
            messages=[{"role": "user", "content": "hello"}],
            model="claude-sonnet-4-5",
        )

    call_kwargs = mock_acompletion.call_args.kwargs
    assert "custom_llm_provider" not in call_kwargs, (
        "Standard Anthropic provider should NOT inject custom_llm_provider"
    )


@pytest.mark.asyncio
async def test_gateway_without_litellm_kwargs_injects_nothing_extra() -> None:
    """Gateways without litellm_kwargs (e.g. AiHubMix) must not add extra keys."""
    mock_acompletion = AsyncMock(return_value=_fake_response())

    with patch("nanobot.providers.litellm_provider.acompletion", mock_acompletion):
        provider = LiteLLMProvider(
            api_key="sk-aihub-test-key",
            api_base="https://aihubmix.com/v1",
            default_model="claude-sonnet-4-5",
            provider_name="aihubmix",
        )
        await provider.chat(
            messages=[{"role": "user", "content": "hello"}],
            model="claude-sonnet-4-5",
        )

    call_kwargs = mock_acompletion.call_args.kwargs
    assert "custom_llm_provider" not in call_kwargs


@pytest.mark.asyncio
async def test_openrouter_autodetect_by_key_prefix() -> None:
    """OpenRouter should be auto-detected by sk-or- key prefix even without explicit provider_name."""
    mock_acompletion = AsyncMock(return_value=_fake_response())

    with patch("nanobot.providers.litellm_provider.acompletion", mock_acompletion):
        provider = LiteLLMProvider(
            api_key="sk-or-auto-detect-key",
            default_model="anthropic/claude-sonnet-4-5",
        )
        await provider.chat(
            messages=[{"role": "user", "content": "hello"}],
            model="anthropic/claude-sonnet-4-5",
        )

    call_kwargs = mock_acompletion.call_args.kwargs
    assert call_kwargs["model"] == "openrouter/anthropic/claude-sonnet-4-5", (
        "Auto-detected OpenRouter should prefix model for LiteLLM routing"
    )


@pytest.mark.asyncio
async def test_openrouter_native_model_id_gets_double_prefixed() -> None:
    """Models like openrouter/free must be double-prefixed so LiteLLM strips one layer.

    openrouter/free is an actual OpenRouter model ID.  LiteLLM strips the first
    openrouter/ for routing, so we must send openrouter/openrouter/free to ensure
    the API receives openrouter/free.
    """
    mock_acompletion = AsyncMock(return_value=_fake_response())

    with patch("nanobot.providers.litellm_provider.acompletion", mock_acompletion):
        provider = LiteLLMProvider(
            api_key="sk-or-test-key",
            api_base="https://openrouter.ai/api/v1",
            default_model="openrouter/free",
            provider_name="openrouter",
        )
        await provider.chat(
            messages=[{"role": "user", "content": "hello"}],
            model="openrouter/free",
        )

    call_kwargs = mock_acompletion.call_args.kwargs
    assert call_kwargs["model"] == "openrouter/openrouter/free", (
        "openrouter/free must become openrouter/openrouter/free — "
        "LiteLLM strips one layer so the API receives openrouter/free"
    )


@pytest.mark.asyncio
async def test_user_field_passed_to_acompletion() -> None:
    """When user is set, it must be forwarded to acompletion for provider-side tracking."""
    mock_acompletion = AsyncMock(return_value=_fake_response())

    with patch("nanobot.providers.litellm_provider.acompletion", mock_acompletion):
        provider = LiteLLMProvider(
            api_key="sk-or-test-key",
            api_base="https://openrouter.ai/api/v1",
            default_model="anthropic/claude-sonnet-4-5",
            provider_name="openrouter",
            user="user_123",
        )
        await provider.chat(
            messages=[{"role": "user", "content": "hello"}],
            model="anthropic/claude-sonnet-4-5",
        )

    call_kwargs = mock_acompletion.call_args.kwargs
    assert call_kwargs["extra_body"]["user"] == "user_123", (
        "user field must be passed via extra_body for provider-side usage tracking"
    )


@pytest.mark.asyncio
async def test_user_field_omitted_when_not_set() -> None:
    """When user is not set, user key must not appear in acompletion kwargs."""
    mock_acompletion = AsyncMock(return_value=_fake_response())

    with patch("nanobot.providers.litellm_provider.acompletion", mock_acompletion):
        provider = LiteLLMProvider(
            api_key="sk-or-test-key",
            api_base="https://openrouter.ai/api/v1",
            default_model="anthropic/claude-sonnet-4-5",
            provider_name="openrouter",
        )
        await provider.chat(
            messages=[{"role": "user", "content": "hello"}],
            model="anthropic/claude-sonnet-4-5",
        )

    call_kwargs = mock_acompletion.call_args.kwargs
    assert "extra_body" not in call_kwargs or "user" not in call_kwargs.get("extra_body", {}), (
        "user key must not be sent when not configured"
    )
