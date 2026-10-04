"""Tests for _is_local_endpoint detection and keepalive configuration."""

from unittest.mock import MagicMock

import pytest

from nanobot.providers.openai_compat_provider import (
    OpenAICompatProvider,
    _is_local_endpoint,
)


def _make_spec(is_local: bool = False) -> MagicMock:
    spec = MagicMock()
    spec.is_local = is_local
    return spec


class TestIsLocalEndpoint:
    """Test the _is_local_endpoint helper."""

    def test_spec_is_local_true(self):
        assert _is_local_endpoint(_make_spec(is_local=True), None) is True

    def test_spec_is_local_false_no_base(self):
        assert _is_local_endpoint(_make_spec(is_local=False), None) is False

    def test_no_spec_no_base(self):
        assert _is_local_endpoint(None, None) is False

    @pytest.mark.parametrize(
        "expected, api_base",
        [
            pytest.param(True, "http://localhost:1234/v1", id="localhost"),
            pytest.param(True, "https://localhost:8080/v1", id="localhost_https"),
            pytest.param(True, "http://127.0.0.1:11434/v1", id="loopback_127"),
            pytest.param(True, "http://192.168.8.188:1234/v1", id="private_192_168"),
            pytest.param(True, "http://10.0.0.5:8000/v1", id="private_10"),
            pytest.param(True, "http://172.16.0.1:1234/v1", id="private_172_16"),
            pytest.param(True, "http://172.31.255.255:1234/v1", id="private_172_31"),
            pytest.param(False, "http://172.32.0.1:1234/v1", id="not_private_172_32"),
            pytest.param(True, "http://host.docker.internal:11434/v1", id="docker_internal"),
            pytest.param(True, "http://[::1]:1234/v1", id="ipv6_loopback"),
            pytest.param(False, "https://api.openai.com/v1", id="public_api"),
            pytest.param(False, "https://openrouter.ai/api/v1", id="openrouter"),
            pytest.param(True, "http://LOCALHOST:1234/v1", id="case_insensitive"),
            pytest.param(True, "http://192.168.1.1:8080/v1/", id="trailing_slash"),
            pytest.param(
                False,
                "https://notlocalhost.example/v1",
                id="public_hostname_containing_localhost_is_not_local",
            ),
            pytest.param(
                False,
                "https://api10.example.com/v1",
                id="public_hostname_containing_private_ip_prefix_is_not_local",
            ),
            pytest.param(True, "192.168.1.1:8080/v1", id="url_without_scheme"),
        ],
    )
    def test_endpoint_locality(self, expected, api_base):
        assert _is_local_endpoint(None, api_base) is expected

    def test_spec_overrides_public_url(self):
        """spec.is_local=True takes precedence even with a public-looking URL."""
        assert _is_local_endpoint(_make_spec(is_local=True), "https://api.example.com/v1") is True

class TestLocalKeepaliveConfig:
    """Verify that local endpoints get keepalive_expiry=0."""

    async def test_local_spec_disables_keepalive(self):
        spec = _make_spec(is_local=True)
        spec.env_key = ""
        spec.default_api_base = "http://localhost:11434/v1"
        provider = OpenAICompatProvider(
            api_key="test", api_base="http://localhost:11434/v1", spec=spec,
        )
        await provider._ensure_client()
        pool = provider._client._client._transport._pool
        assert pool._keepalive_expiry == 0

    async def test_lan_ip_disables_keepalive(self):
        """A generic 'openai' spec with a LAN IP should still disable keepalive."""
        spec = _make_spec(is_local=False)
        spec.env_key = ""
        spec.default_api_base = None
        provider = OpenAICompatProvider(
            api_key="test", api_base="http://192.168.8.188:1234/v1", spec=spec,
        )
        await provider._ensure_client()
        pool = provider._client._client._transport._pool
        assert pool._keepalive_expiry == 0

    async def test_cloud_keeps_default_keepalive(self):
        spec = _make_spec(is_local=False)
        spec.env_key = ""
        spec.default_api_base = "https://api.openai.com/v1"
        provider = OpenAICompatProvider(
            api_key="test", api_base=None, spec=spec,
        )
        await provider._ensure_client()
        pool = provider._client._client._transport._pool
        # Default httpx keepalive is 5.0s
        assert pool._keepalive_expiry == 5.0
