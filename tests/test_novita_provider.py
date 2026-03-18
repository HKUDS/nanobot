"""Tests for the Novita AI provider integration.

Validates that:
- The ProviderSpec is registered correctly with expected metadata.
- Model names are prefixed correctly for LiteLLM routing via OpenAI-compatible API.
- Auto-detection by api_base keyword works.
- Default model (deepseek/deepseek-v3.2) and multi-model IDs route correctly.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from nanobot.providers.litellm_provider import LiteLLMProvider
from nanobot.providers.registry import find_by_name, find_gateway


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


def test_novita_spec_exists() -> None:
    """Novita AI must be registered in the provider registry."""
    spec = find_by_name("novita")
    assert spec is not None
    assert spec.display_name == "Novita AI"
    assert spec.env_key == "NOVITA_API_KEY"
    assert spec.is_gateway is True
    assert spec.default_api_base == "https://api.novita.ai/openai"
    assert spec.litellm_prefix == "openai"


def test_novita_detected_by_base_keyword() -> None:
    """Novita should be auto-detected when api_base contains 'novita'."""
    spec = find_gateway(api_base="https://api.novita.ai/openai")
    assert spec is not None
    assert spec.name == "novita"


@pytest.mark.asyncio
async def test_novita_prefixes_default_model() -> None:
    """Default model deepseek/deepseek-v3.2 should get openai/ prefix for LiteLLM."""
    mock_acompletion = AsyncMock(return_value=_fake_response())

    with patch("nanobot.providers.litellm_provider.acompletion", mock_acompletion):
        provider = LiteLLMProvider(
            api_key="novita-test-key",
            api_base="https://api.novita.ai/openai",
            default_model="deepseek/deepseek-v3.2",
            provider_name="novita",
        )
        await provider.chat(
            messages=[{"role": "user", "content": "hello"}],
            model="deepseek/deepseek-v3.2",
        )

    call_kwargs = mock_acompletion.call_args.kwargs
    assert call_kwargs["model"] == "openai/deepseek/deepseek-v3.2", (
        "Novita models need openai/ prefix for LiteLLM OpenAI-compatible routing"
    )


@pytest.mark.asyncio
async def test_novita_prefixes_glm_model() -> None:
    """Multi-model: zai-org/glm-5 should also get openai/ prefix."""
    mock_acompletion = AsyncMock(return_value=_fake_response())

    with patch("nanobot.providers.litellm_provider.acompletion", mock_acompletion):
        provider = LiteLLMProvider(
            api_key="novita-test-key",
            api_base="https://api.novita.ai/openai",
            default_model="zai-org/glm-5",
            provider_name="novita",
        )
        await provider.chat(
            messages=[{"role": "user", "content": "hello"}],
            model="zai-org/glm-5",
        )

    call_kwargs = mock_acompletion.call_args.kwargs
    assert call_kwargs["model"] == "openai/zai-org/glm-5"


@pytest.mark.asyncio
async def test_novita_prefixes_minimax_model() -> None:
    """Multi-model: minimax/minimax-m2.5 should also get openai/ prefix."""
    mock_acompletion = AsyncMock(return_value=_fake_response())

    with patch("nanobot.providers.litellm_provider.acompletion", mock_acompletion):
        provider = LiteLLMProvider(
            api_key="novita-test-key",
            api_base="https://api.novita.ai/openai",
            default_model="minimax/minimax-m2.5",
            provider_name="novita",
        )
        await provider.chat(
            messages=[{"role": "user", "content": "hello"}],
            model="minimax/minimax-m2.5",
        )

    call_kwargs = mock_acompletion.call_args.kwargs
    assert call_kwargs["model"] == "openai/minimax/minimax-m2.5"
