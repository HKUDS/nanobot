"""Regression tests for PR #2026 — litellm_kwargs injection from ProviderSpec."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from nanobot.providers.litellm_provider import LiteLLMProvider


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


@pytest.mark.asyncio
async def test_openrouter_injects_litellm_kwargs() -> None:
    """OpenRouter gateway must inject custom_llm_provider into acompletion call."""
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
    assert call_kwargs.get("custom_llm_provider") == "openrouter", (
        "OpenRouter gateway should pass custom_llm_provider='openrouter' to acompletion"
    )
    assert call_kwargs["model"] == "anthropic/claude-sonnet-4-5", (
        "Model name must NOT get an 'openrouter/' prefix — routing is via custom_llm_provider"
    )


@pytest.mark.asyncio
async def test_non_gateway_provider_does_not_inject_litellm_kwargs() -> None:
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
    assert "custom_llm_provider" not in call_kwargs, (
        "AiHubMix gateway has no litellm_kwargs, should not add custom_llm_provider"
    )


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
    assert call_kwargs.get("custom_llm_provider") == "openrouter", (
        "Auto-detected OpenRouter (by sk-or- prefix) should still inject custom_llm_provider"
    )
    assert call_kwargs["model"] == "anthropic/claude-sonnet-4-5", (
        "Auto-detected OpenRouter must preserve native model name without openrouter/ prefix"
    )
