from types import SimpleNamespace

from janniebot.providers.anthropic_provider import AnthropicProvider
from janniebot.providers.azure_openai_provider import AzureOpenAIProvider
from janniebot.providers.openai_compat_provider import OpenAICompatProvider


def test_openai_compat_error_captures_retry_after_from_headers() -> None:
    err = Exception("boom")
    err.doc = None
    err.response = SimpleNamespace(
        text='{"error":{"message":"Rate limit exceeded"}}',
        headers={"Retry-After": "20"},
    )

    response = OpenAICompatProvider._handle_error(err)

    assert response.retry_after == 20.0


def test_azure_openai_error_captures_retry_after_from_headers() -> None:
    err = Exception("boom")
    err.body = {"message": "Rate limit exceeded"}
    err.response = SimpleNamespace(
        text='{"error":{"message":"Rate limit exceeded"}}',
        headers={"Retry-After": "20"},
    )

    response = AzureOpenAIProvider._handle_error(err)

    assert response.retry_after == 20.0


def test_anthropic_error_captures_retry_after_from_headers() -> None:
    err = Exception("boom")
    err.response = SimpleNamespace(
        headers={"Retry-After": "20"},
    )

    response = AnthropicProvider._handle_error(err)

    assert response.retry_after == 20.0
