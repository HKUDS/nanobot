"""Tests for _is_local_endpoint detection and keepalive configuration."""

from unittest.mock import MagicMock

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

    def test_localhost(self):
        assert _is_local_endpoint(None, "http://localhost:1234/v1") is True

    def test_localhost_https(self):
        assert _is_local_endpoint(None, "https://localhost:8080/v1") is True

    def test_loopback_127(self):
        assert _is_local_endpoint(None, "http://127.0.0.1:11434/v1") is True

    def test_private_192_168(self):
        assert _is_local_endpoint(None, "http://192.168.8.188:1234/v1") is True

    def test_private_10(self):
        assert _is_local_endpoint(None, "http://10.0.0.5:8000/v1") is True

    def test_private_172_16(self):
        assert _is_local_endpoint(None, "http://172.16.0.1:1234/v1") is True

    def test_private_172_31(self):
        assert _is_local_endpoint(None, "http://172.31.255.255:1234/v1") is True

    def test_not_private_172_32(self):
        assert _is_local_endpoint(None, "http://172.32.0.1:1234/v1") is False

    def test_docker_internal(self):
        assert _is_local_endpoint(None, "http://host.docker.internal:11434/v1") is True

    def test_ipv6_loopback(self):
        assert _is_local_endpoint(None, "http://[::1]:1234/v1") is True

    def test_public_api(self):
        assert _is_local_endpoint(None, "https://api.openai.com/v1") is False

    def test_openrouter(self):
        assert _is_local_endpoint(None, "https://openrouter.ai/api/v1") is False

    def test_spec_overrides_public_url(self):
        """spec.is_local=True takes precedence even with a public-looking URL."""
        assert _is_local_endpoint(_make_spec(is_local=True), "https://api.example.com/v1") is True

    def test_case_insensitive(self):
        assert _is_local_endpoint(None, "http://LOCALHOST:1234/v1") is True

    def test_trailing_slash(self):
        assert _is_local_endpoint(None, "http://192.168.1.1:8080/v1/") is True

    def test_public_hostname_containing_localhost_is_not_local(self):
        assert _is_local_endpoint(None, "https://notlocalhost.example/v1") is False

    def test_public_hostname_containing_private_ip_prefix_is_not_local(self):
        assert _is_local_endpoint(None, "https://api10.example.com/v1") is False

    def test_url_without_scheme(self):
        assert _is_local_endpoint(None, "192.168.1.1:8080/v1") is True


class TestLocalKeepaliveConfig:
    """Verify that local endpoints get keepalive_expiry=0."""

    def test_local_spec_disables_keepalive(self):
        spec = _make_spec(is_local=True)
        spec.env_key = ""
        spec.default_api_base = "http://localhost:11434/v1"
        provider = OpenAICompatProvider(
            api_key="test", api_base="http://localhost:11434/v1", spec=spec,
        )
        pool = provider._client._client._transport._pool
        assert pool._keepalive_expiry == 0

    def test_lan_ip_disables_keepalive(self):
        """A generic 'openai' spec with a LAN IP should still disable keepalive."""
        spec = _make_spec(is_local=False)
        spec.env_key = ""
        spec.default_api_base = None
        provider = OpenAICompatProvider(
            api_key="test", api_base="http://192.168.8.188:1234/v1", spec=spec,
        )
        pool = provider._client._client._transport._pool
        assert pool._keepalive_expiry == 0

    def test_cloud_keeps_default_keepalive(self):
        spec = _make_spec(is_local=False)
        spec.env_key = ""
        spec.default_api_base = "https://api.openai.com/v1"
        provider = OpenAICompatProvider(
            api_key="test", api_base=None, spec=spec,
        )
        pool = provider._client._client._transport._pool
        # Default httpx keepalive is 5.0s
        assert pool._keepalive_expiry == 5.0
