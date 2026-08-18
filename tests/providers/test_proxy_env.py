"""Tests for proxy environment variable handling in OpenAICompatProvider."""

from unittest.mock import MagicMock

import httpx

import nanobot.providers.openai_compat_provider as openai_compat_provider
from nanobot.providers.openai_compat_provider import OpenAICompatProvider


def _make_spec(is_local: bool = False) -> MagicMock:
    spec = MagicMock()
    spec.is_local = is_local
    return spec


class TestLocalEndpointProxyDisabled:
    """Local endpoints must bypass proxy to avoid routing LAN traffic through it."""

    async def test_local_disables_proxy(self):
        spec = _make_spec(is_local=True)
        spec.env_key = ""
        spec.default_api_base = "http://localhost:11434/v1"
        provider = OpenAICompatProvider(
            api_key="test", api_base="http://localhost:11434/v1", spec=spec,
        )
        await provider._ensure_client()
        transport = provider._client._client._transport
        # The transport should be an AsyncHTTPTransport with proxy=None
        assert isinstance(transport, httpx.AsyncHTTPTransport)

    async def test_lan_ip_disables_proxy(self):
        spec = _make_spec(is_local=False)
        spec.env_key = ""
        spec.default_api_base = None
        provider = OpenAICompatProvider(
            api_key="test", api_base="http://192.168.8.188:1234/v1", spec=spec,
        )
        await provider._ensure_client()
        transport = provider._client._client._transport
        assert isinstance(transport, httpx.AsyncHTTPTransport)


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

    async def test_explicit_provider_proxy_normalizes_socks_alias(self, monkeypatch):
        spec = _make_spec(is_local=False)
        spec.env_key = ""
        spec.default_api_base = "https://api.openai.com/v1"
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
            proxy="socks://127.0.0.1:7892",
        )
        provider._build_client()

        async_client.assert_called_once_with(
            timeout=120.0,
            proxy="socks5://127.0.0.1:7892",
            trust_env=False,
            follow_redirects=True,
        )


class TestLegacySocksProxyEnvAlias:
    """A legacy ``socks://`` alias in the process environment (commonly via
    ALL_PROXY) must not crash client construction, even when a valid
    scheme-specific proxy is also set for the target endpoint."""

    def _clear_proxy_env(self, monkeypatch):
        for name in (
            "HTTP_PROXY", "http_proxy",
            "HTTPS_PROXY", "https_proxy",
            "ALL_PROXY", "all_proxy",
            "NO_PROXY", "no_proxy",
        ):
            monkeypatch.delenv(name, raising=False)

    def _patch_clients(self, monkeypatch):
        http_client = MagicMock()
        async_client = MagicMock(return_value=http_client)
        openai_client = MagicMock(return_value=object())
        monkeypatch.setattr(httpx, "AsyncClient", async_client)
        monkeypatch.setattr(openai_compat_provider, "AsyncOpenAI", openai_client)
        monkeypatch.delenv("NANOBOT_OPENAI_COMPAT_TIMEOUT_S", raising=False)
        return async_client, openai_client

    def _make_provider(self) -> OpenAICompatProvider:
        spec = _make_spec(is_local=False)
        spec.env_key = ""
        spec.default_api_base = "https://api.openai.com/v1"
        return OpenAICompatProvider(api_key="test", api_base=None, spec=spec)

    def test_all_proxy_alias_normalized_when_no_scoped_proxy(self, monkeypatch):
        self._clear_proxy_env(monkeypatch)
        monkeypatch.setenv("ALL_PROXY", "socks://127.0.0.1:7892")
        async_client, _ = self._patch_clients(monkeypatch)

        self._make_provider()._build_client()

        async_client.assert_called_once_with(
            timeout=120.0,
            proxy="socks5://127.0.0.1:7892",
            trust_env=False,
            follow_redirects=True,
        )

    def test_scheme_specific_https_proxy_preferred_over_all_proxy_alias(self, monkeypatch):
        self._clear_proxy_env(monkeypatch)
        monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7893")
        monkeypatch.setenv("ALL_PROXY", "socks://127.0.0.1:7892")
        async_client, _ = self._patch_clients(monkeypatch)

        self._make_provider()._build_client()

        async_client.assert_called_once_with(
            timeout=120.0,
            proxy="http://127.0.0.1:7893",
            trust_env=False,
            follow_redirects=True,
        )

    def test_no_proxy_excludes_matching_host(self, monkeypatch):
        self._clear_proxy_env(monkeypatch)
        monkeypatch.setenv("ALL_PROXY", "socks://127.0.0.1:7892")
        monkeypatch.setenv("NO_PROXY", "api.openai.com")
        async_client, _ = self._patch_clients(monkeypatch)

        self._make_provider()._build_client()

        async_client.assert_called_once_with(
            timeout=120.0,
            proxy=None,
            trust_env=False,
            follow_redirects=True,
        )

    def test_no_legacy_alias_keeps_default_trust_env_behavior(self, monkeypatch):
        self._clear_proxy_env(monkeypatch)
        monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7893")
        async_client, openai_client = self._patch_clients(monkeypatch)

        self._make_provider()._build_client()

        async_client.assert_not_called()
        assert openai_client.call_args.kwargs["http_client"] is None
