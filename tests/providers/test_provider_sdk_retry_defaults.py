from unittest.mock import patch

from janniebot.providers.anthropic_provider import AnthropicProvider
from janniebot.providers.azure_openai_provider import AzureOpenAIProvider
from janniebot.providers.openai_compat_provider import OpenAICompatProvider


def test_openai_compat_disables_sdk_retries_by_default() -> None:
    with patch("janniebot.providers.openai_compat_provider.AsyncOpenAI") as mock_client:
        OpenAICompatProvider(api_key="sk-test", default_model="gpt-4o")

    kwargs = mock_client.call_args.kwargs
    assert kwargs["max_retries"] == 0


def test_anthropic_disables_sdk_retries_by_default() -> None:
    with patch("anthropic.AsyncAnthropic") as mock_client:
        AnthropicProvider(api_key="sk-test", default_model="claude-sonnet-4-5")

    kwargs = mock_client.call_args.kwargs
    assert kwargs["max_retries"] == 0


def test_azure_openai_disables_sdk_retries_by_default() -> None:
    with patch("janniebot.providers.azure_openai_provider.AsyncOpenAI") as mock_client:
        AzureOpenAIProvider(
            api_key="sk-test",
            api_base="https://example.openai.azure.com",
            default_model="gpt-4.1",
        )

    kwargs = mock_client.call_args.kwargs
    assert kwargs["max_retries"] == 0
