"""Tests for proxy environment variable handling in OpenAICompatProvider."""

from unittest.mock import MagicMock

import httpx

from blackcat.providers.openai_compat_provider import OpenAICompatProvider


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
