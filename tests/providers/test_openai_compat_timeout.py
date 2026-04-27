from unittest.mock import patch, sentinel

from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.providers.registry import ProviderSpec


def _assert_openai_compat_timeout(timeout) -> None:
    assert timeout == 120.0


def test_openai_compat_provider_sets_sdk_timeout() -> None:
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI") as mock_async_openai:
        OpenAICompatProvider(api_key="test-key", api_base="https://example.com/v1")

    kwargs = mock_async_openai.call_args.kwargs
    _assert_openai_compat_timeout(kwargs["timeout"])
    assert kwargs["http_client"] is None


def test_openai_compat_provider_sets_timeout_on_local_http_client() -> None:
    spec = ProviderSpec(
        name="local",
        keywords=(),
        env_key="",
        is_local=True,
        default_api_base="http://127.0.0.1:11434/v1",
    )

    with (
        patch("nanobot.providers.openai_compat_provider.AsyncOpenAI") as mock_async_openai,
        patch(
            "nanobot.providers.openai_compat_provider.httpx.AsyncClient",
            return_value=sentinel.http_client,
        ) as mock_http_client,
    ):
        OpenAICompatProvider(spec=spec)

    client_kwargs = mock_http_client.call_args.kwargs
    _assert_openai_compat_timeout(client_kwargs["timeout"])
    assert client_kwargs["limits"].keepalive_expiry == 0

    openai_kwargs = mock_async_openai.call_args.kwargs
    _assert_openai_compat_timeout(openai_kwargs["timeout"])
    assert openai_kwargs["http_client"] is sentinel.http_client


def test_openai_compat_provider_timeout_can_be_overridden_by_env(monkeypatch) -> None:
    monkeypatch.setenv("NANOBOT_OPENAI_COMPAT_TIMEOUT_S", "45")

    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI") as mock_async_openai:
        OpenAICompatProvider(api_key="test-key", api_base="https://example.com/v1")

    assert mock_async_openai.call_args.kwargs["timeout"] == 45.0
