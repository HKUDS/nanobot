from unittest.mock import AsyncMock, patch

import pytest

from nanobot.providers.litellm_provider import LiteLLMProvider


class _StopGateway(RuntimeError):
    pass


def _make_openrouter_provider(model: str) -> LiteLLMProvider:
    return LiteLLMProvider(
        default_model=model,
        provider_name="openrouter",
        api_key="sk-or-test",
    )


@pytest.mark.asyncio
async def test_openrouter_native_model_uses_custom_llm_provider_hint():
    provider = _make_openrouter_provider("openrouter/free")

    with patch("nanobot.providers.litellm_provider.acompletion", new=AsyncMock(side_effect=_StopGateway)) as mock_acompletion:
        response = await provider.chat([{"role": "user", "content": "hello"}], model="openrouter/free")

    assert "Error calling LLM" in response.content
    assert mock_acompletion.await_args.kwargs["model"] == "openrouter/free"
    assert mock_acompletion.await_args.kwargs["custom_llm_provider"] == "openrouter"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("model", "expected_model"),
    [
        ("openrouter/anthropic/claude-3", "openrouter/anthropic/claude-3"),
        ("moonshotai/kimi-k2.5:exacto", "openrouter/moonshotai/kimi-k2.5:exacto"),
    ],
)
async def test_openrouter_non_native_models_do_not_use_custom_llm_provider_hint(
    model: str,
    expected_model: str,
):
    provider = _make_openrouter_provider(model)

    with patch("nanobot.providers.litellm_provider.acompletion", new=AsyncMock(side_effect=_StopGateway)) as mock_acompletion:
        response = await provider.chat([{"role": "user", "content": "hello"}], model=model)

    assert "Error calling LLM" in response.content
    assert mock_acompletion.await_args.kwargs["model"] == expected_model
    assert "custom_llm_provider" not in mock_acompletion.await_args.kwargs
