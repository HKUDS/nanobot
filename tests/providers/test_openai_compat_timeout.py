from unittest.mock import patch, sentinel

from blackcat.providers.openai_compat_provider import OpenAICompatProvider
from blackcat.providers.registry import ProviderSpec


def _assert_openai_compat_timeout(timeout) -> None:
    assert timeout == 120.0


async def test_openai_compat_provider_defers_sdk_client_until_first_use() -> None:
    with patch("blackcat.providers.openai_compat_provider.AsyncOpenAI") as mock_async_openai:
        provider = OpenAICompatProvider(api_key="test-key", api_base="https://example.com/v1")
        mock_async_openai.assert_not_called()
        await provider._ensure_client()

    kwargs = mock_async_openai.call_args.kwargs
    _assert_openai_compat_timeout(kwargs["timeout"])
    # Cloud endpoints pass http_client=None so the SDK creates its own
    # DefaultAsyncHttpxClient, which already handles proxy env vars,
    # connection limits, and redirects correctly.
    assert kwargs["http_client"] is None


async def test_openai_compat_provider_sets_timeout_on_local_http_client() -> None:
    spec = ProviderSpec(
        name="local",
        keywords=(),
        env_key="",
        is_local=True,
        default_api_base="http://127.0.0.1:11434/v1",
    )

    with (
        patch("blackcat.providers.openai_compat_provider.AsyncOpenAI") as mock_async_openai,
        patch(
            "httpx.AsyncClient",
            return_value=sentinel.http_client,
        ) as mock_http_client,
    ):
        provider = OpenAICompatProvider(spec=spec)
        mock_async_openai.assert_not_called()
        await provider._ensure_client()

    client_kwargs = mock_http_client.call_args.kwargs
    _assert_openai_compat_timeout(client_kwargs["timeout"])
    assert client_kwargs["limits"].keepalive_expiry == 0

    openai_kwargs = mock_async_openai.call_args.kwargs
    _assert_openai_compat_timeout(openai_kwargs["timeout"])
    assert openai_kwargs["http_client"] is sentinel.http_client


async def test_openai_compat_provider_timeout_can_be_overridden_by_env(monkeypatch) -> None:
    monkeypatch.setenv("BLACKCAT_OPENAI_COMPAT_TIMEOUT_S", "45")

    with patch("blackcat.providers.openai_compat_provider.AsyncOpenAI") as mock_async_openai:
        provider = OpenAICompatProvider(api_key="test-key", api_base="https://example.com/v1")
        await provider._ensure_client()

    assert mock_async_openai.call_args.kwargs["timeout"] == 45.0
