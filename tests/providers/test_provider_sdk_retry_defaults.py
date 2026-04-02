from unittest.mock import patch

from nanobot.providers.anthropic_provider import AnthropicProvider
from nanobot.providers.openai_compat_provider import OpenAICompatProvider


def test_openai_compat_disables_sdk_retries_by_default() -> None:
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI") as mock_client:
        OpenAICompatProvider(api_key="sk-test", default_model="gpt-4o")

    kwargs = mock_client.call_args.kwargs
    assert kwargs["max_retries"] == 0


def test_anthropic_disables_sdk_retries_by_default() -> None:
    with patch("anthropic.AsyncAnthropic") as mock_client:
        AnthropicProvider(api_key="sk-test", default_model="claude-sonnet-4-5")

    kwargs = mock_client.call_args.kwargs
    assert kwargs["max_retries"] == 0
