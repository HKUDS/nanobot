from unittest.mock import patch

import pytest

from nanobot.providers.anthropic_provider import AnthropicProvider
from nanobot.providers.azure_openai_provider import AzureOpenAIProvider
from nanobot.providers.bedrock_provider import BedrockProvider
from nanobot.providers.openai_compat_provider import OpenAICompatProvider


async def test_openai_compat_disables_sdk_retries_by_default() -> None:
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI") as mock_client:
        provider = OpenAICompatProvider(api_key="sk-test", default_model="gpt-4o")
        await provider._ensure_client()

    kwargs = mock_client.call_args.kwargs
    assert kwargs["max_retries"] == 0


def test_anthropic_disables_sdk_retries_by_default() -> None:
    with patch("anthropic.AsyncAnthropic") as mock_client:
        AnthropicProvider(api_key="sk-test", default_model="claude-sonnet-4-5")

    kwargs = mock_client.call_args.kwargs
    assert kwargs["max_retries"] == 0


def test_anthropic_normalizes_versioned_base_url() -> None:
    with patch("anthropic.AsyncAnthropic") as mock_client:
        AnthropicProvider(
            api_key="sk-test",
            api_base="https://api.minimax.io/anthropic/v1",
            default_model="MiniMax-M2.7-highspeed",
        )

    kwargs = mock_client.call_args.kwargs
    assert kwargs["base_url"] == "https://api.minimax.io/anthropic"


def test_azure_openai_disables_sdk_retries_by_default() -> None:
    with patch("nanobot.providers.azure_openai_provider.AsyncOpenAI") as mock_client:
        AzureOpenAIProvider(
            api_key="sk-test",
            api_base="https://example.openai.azure.com",
            default_model="gpt-4.1",
        )

    kwargs = mock_client.call_args.kwargs
    assert kwargs["max_retries"] == 0


def test_bedrock_disables_sdk_retries_even_with_environment_attempts(monkeypatch) -> None:
    pytest.importorskip("boto3")
    monkeypatch.setenv("AWS_MAX_ATTEMPTS", "10")
    with patch("boto3.Session") as session:
        BedrockProvider(api_base="http://127.0.0.1:1", region="us-east-1")

    config = session.return_value.client.call_args.kwargs["config"]
    assert config.retries["total_max_attempts"] == 1
