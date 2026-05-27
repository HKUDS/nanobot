from unittest.mock import patch, sentinel

from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.providers.registry import ProviderSpec


def _assert_openai_compat_timeout(timeout) -> None:
    assert timeout == 120.0


async def test_openai_compat_provider_defers_sdk_client_until_first_use() -> None:
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI") as mock_async_openai:
        provider = OpenAICompatProvider(api_key="test-key", api_base="https://example.com/v1")
        mock_async_openai.assert_not_called()
        await provider._ensure_client()

    kwargs = mock_async_openai.call_args.kwargs
    _assert_openai_compat_timeout(kwargs["timeout"])
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
        patch("nanobot.providers.openai_compat_provider.AsyncOpenAI") as mock_async_openai,
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
    monkeypatch.setenv("NANOBOT_OPENAI_COMPAT_TIMEOUT_S", "45")

    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI") as mock_async_openai:
        provider = OpenAICompatProvider(api_key="test-key", api_base="https://example.com/v1")
        await provider._ensure_client()

    assert mock_async_openai.call_args.kwargs["timeout"] == 45.0


# ---------------------------------------------------------------------------
# Stream-idle timeout — config field, env-var fallback, local-default bump.
# Regression tests for nanobot#4013.
# ---------------------------------------------------------------------------


from nanobot.providers.base import (  # noqa: E402  — co-located with timeout tests
    DEFAULT_LOCAL_STREAM_IDLE_TIMEOUT_S,
    DEFAULT_STREAM_IDLE_TIMEOUT_S,
    resolve_stream_idle_timeout_s,
)


def test_stream_idle_config_override_wins_over_env(monkeypatch) -> None:
    monkeypatch.setenv("NANOBOT_STREAM_IDLE_TIMEOUT_S", "120")
    provider = OpenAICompatProvider(
        api_key="test-key",
        api_base="https://example.com/v1",
        stream_idle_timeout_s=600,
    )
    resolved = resolve_stream_idle_timeout_s(
        config_override=provider._stream_idle_timeout_s_override,
        is_local=provider._is_local,
    )
    assert resolved == 600


def test_stream_idle_local_provider_bumps_default(monkeypatch) -> None:
    """A local provider (Ollama at 127.0.0.1) gets the 300s default, not 90s."""
    monkeypatch.delenv("NANOBOT_STREAM_IDLE_TIMEOUT_S", raising=False)
    spec = ProviderSpec(
        name="ollama",
        keywords=("ollama",),
        env_key="",
        is_local=True,
        default_api_base="http://127.0.0.1:11434/v1",
    )
    provider = OpenAICompatProvider(spec=spec)
    assert provider._is_local is True
    resolved = resolve_stream_idle_timeout_s(
        config_override=provider._stream_idle_timeout_s_override,
        is_local=provider._is_local,
    )
    assert resolved == DEFAULT_LOCAL_STREAM_IDLE_TIMEOUT_S


def test_stream_idle_cloud_provider_keeps_90s_default(monkeypatch) -> None:
    monkeypatch.delenv("NANOBOT_STREAM_IDLE_TIMEOUT_S", raising=False)
    provider = OpenAICompatProvider(
        api_key="test-key",
        api_base="https://api.openai.com/v1",
    )
    assert provider._is_local is False
    resolved = resolve_stream_idle_timeout_s(
        config_override=provider._stream_idle_timeout_s_override,
        is_local=provider._is_local,
    )
    assert resolved == DEFAULT_STREAM_IDLE_TIMEOUT_S


def test_stream_idle_lm_studio_localhost_api_base(monkeypatch) -> None:
    """LM Studio configured via api_base alone (no is_local spec) still gets 300s."""
    monkeypatch.delenv("NANOBOT_STREAM_IDLE_TIMEOUT_S", raising=False)
    provider = OpenAICompatProvider(
        api_key="lm-studio",
        api_base="http://localhost:1234/v1",
    )
    assert provider._is_local is True
    resolved = resolve_stream_idle_timeout_s(
        config_override=provider._stream_idle_timeout_s_override,
        is_local=provider._is_local,
    )
    assert resolved == DEFAULT_LOCAL_STREAM_IDLE_TIMEOUT_S
