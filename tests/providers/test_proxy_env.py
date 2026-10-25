"""Tests for proxy environment variable handling in OpenAICompatProvider."""

from unittest.mock import MagicMock

import httpx
import pytest

import nanobot.providers.openai_compat_provider as openai_compat_provider
from nanobot.providers.openai_compat_provider import OpenAICompatProvider


def _make_spec(is_local: bool = False) -> MagicMock:
    spec = MagicMock()
    spec.is_local = is_local
    return spec


class TestLocalEndpointProxyDisabled:
    """Local endpoints must bypass proxy to avoid routing LAN traffic through it."""

    @pytest.mark.parametrize("api_base,is_local", [
        ("http://localhost:11434/v1", True),
        ("http://192.168.8.188:1234/v1", False),
    ])
    async def test_local_endpoint_bypasses_environment_proxy(self, monkeypatch, api_base, is_local):
        for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"):
            monkeypatch.delenv(name, raising=False)
            monkeypatch.delenv(name.lower(), raising=False)
        monkeypatch.setenv("ALL_PROXY", "http://proxy.example:8123")
        spec = _make_spec(is_local=is_local)
        spec.env_key = ""
        spec.default_api_base = api_base
        provider = OpenAICompatProvider(api_key="test", api_base=api_base, spec=spec)
        async with await provider._ensure_client() as sdk:
            client = sdk._client
            assert client._transport_for_url(httpx.URL(api_base)) is client._transport


class TestCloudEndpointProxyEnabled:
    """Cloud endpoints must respect proxy env vars for corporate/VPN proxies."""

    async def test_cloud_respects_trust_env(self):
        spec = _make_spec(is_local=False)
        spec.env_key = ""
        spec.default_api_base = "https://api.openai.com/v1"
        provider = OpenAICompatProvider(
            api_key="test", api_base=None, spec=spec,
        )
        await provider._ensure_client()
        client = provider._client._client
        # trust_env should be True so httpx reads HTTP_PROXY etc.
        assert client._trust_env is True

    async def test_explicit_provider_proxy_overrides_env(self, monkeypatch):
        spec = _make_spec(is_local=False)
        spec.env_key = ""
        spec.default_api_base = "https://api.openai.com/v1"
        proxy = "http://127.0.0.1:23458"
        monkeypatch.delenv("NANOBOT_OPENAI_COMPAT_TIMEOUT_S", raising=False)

        http_client = MagicMock()
        async_client = MagicMock(return_value=http_client)
        openai_client = MagicMock(return_value=object())
        monkeypatch.setattr(httpx, "AsyncClient", async_client)
        monkeypatch.setattr(openai_compat_provider, "AsyncOpenAI", openai_client)

        provider = OpenAICompatProvider(
            api_key="test",
            api_base=None,
            spec=spec,
            proxy=proxy,
        )
        provider._build_client()

        async_client.assert_called_once_with(
            timeout=120.0,
            proxy=proxy,
            trust_env=False,
            follow_redirects=True,
        )
        assert openai_client.call_args.kwargs["http_client"] is http_client
