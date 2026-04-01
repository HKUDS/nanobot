"""Tests for nanobot.security.network — SSRF protection and internal URL detection."""

from __future__ import annotations

import socket
from unittest.mock import patch

import pytest

from nanobot.security.network import (
    configure_allowed_subnets,
    contains_internal_url,
    validate_url_target,
)


def _fake_resolve(host: str, results: list[str]):
    """Return a getaddrinfo mock that maps the given host to fake IP results."""
    def _resolver(hostname, port, family=0, type_=0):
        if hostname == host:
            return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip, 0)) for ip in results]
        raise socket.gaierror(f"cannot resolve {hostname}")
    return _resolver


# ---------------------------------------------------------------------------
# validate_url_target — scheme / domain basics
# ---------------------------------------------------------------------------

def test_rejects_non_http_scheme():
    ok, err = validate_url_target("ftp://example.com/file")
    assert not ok
    assert "http" in err.lower()


def test_rejects_missing_domain():
    ok, err = validate_url_target("http://")
    assert not ok


# ---------------------------------------------------------------------------
# validate_url_target — blocked private/internal IPs
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ip,label", [
    ("127.0.0.1", "loopback"),
    ("127.0.0.2", "loopback_alt"),
    ("10.0.0.1", "rfc1918_10"),
    ("172.16.5.1", "rfc1918_172"),
    ("192.168.1.1", "rfc1918_192"),
    ("169.254.169.254", "metadata"),
    ("0.0.0.0", "zero"),
])
def test_blocks_private_ipv4(ip: str, label: str):
    with patch("nanobot.security.network.socket.getaddrinfo", _fake_resolve("evil.com", [ip])):
        ok, err = validate_url_target(f"http://evil.com/path")
        assert not ok, f"Should block {label} ({ip})"
        assert "private" in err.lower() or "blocked" in err.lower()


def test_blocks_ipv6_loopback():
    def _resolver(hostname, port, family=0, type_=0):
        return [(socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("::1", 0, 0, 0))]
    with patch("nanobot.security.network.socket.getaddrinfo", _resolver):
        ok, err = validate_url_target("http://evil.com/")
        assert not ok


# ---------------------------------------------------------------------------
# validate_url_target — allows public IPs
# ---------------------------------------------------------------------------

def test_allows_public_ip():
    with patch("nanobot.security.network.socket.getaddrinfo", _fake_resolve("example.com", ["93.184.216.34"])):
        ok, err = validate_url_target("http://example.com/page")
        assert ok, f"Should allow public IP, got: {err}"


def test_allows_normal_https():
    with patch("nanobot.security.network.socket.getaddrinfo", _fake_resolve("github.com", ["140.82.121.3"])):
        ok, err = validate_url_target("https://github.com/HKUDS/nanobot")
        assert ok


# ---------------------------------------------------------------------------
# contains_internal_url — shell command scanning
# ---------------------------------------------------------------------------

def test_detects_curl_metadata():
    with patch("nanobot.security.network.socket.getaddrinfo", _fake_resolve("169.254.169.254", ["169.254.169.254"])):
        assert contains_internal_url('curl -s http://169.254.169.254/computeMetadata/v1/')


def test_detects_wget_localhost():
    with patch("nanobot.security.network.socket.getaddrinfo", _fake_resolve("localhost", ["127.0.0.1"])):
        assert contains_internal_url("wget http://localhost:8080/secret")


def test_allows_normal_curl():
    with patch("nanobot.security.network.socket.getaddrinfo", _fake_resolve("example.com", ["93.184.216.34"])):
        assert not contains_internal_url("curl https://example.com/api/data")


def test_no_urls_returns_false():
    assert not contains_internal_url("echo hello && ls -la")


# ---------------------------------------------------------------------------
# ssrfAllowedSubnets — subnet-based allowlist
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_allowed_subnets():
    """Reset SSRF allowlist between tests."""
    yield
    configure_allowed_subnets([])


def test_allowed_subnet_bypasses_private_block():
    configure_allowed_subnets(["172.16.0.0/12"])
    with patch(
        "nanobot.security.network.socket.getaddrinfo",
        _fake_resolve("internal.corp", ["172.16.5.1"]),
    ):
        ok, err = validate_url_target("http://internal.corp/api")
        assert ok, f"172.16.5.1 should be allowed, got: {err}"


def test_private_ip_not_in_allowlist_still_blocked():
    configure_allowed_subnets(["172.16.0.0/12"])
    with patch(
        "nanobot.security.network.socket.getaddrinfo",
        _fake_resolve("evil.com", ["10.0.0.1"]),
    ):
        ok, err = validate_url_target("http://evil.com/path")
        assert not ok, "10.0.0.1 should still be blocked"


def test_empty_allowlist_blocks_all_private():
    configure_allowed_subnets([])
    for ip in ["10.0.0.1", "172.16.5.1", "192.168.1.1"]:
        with patch(
            "nanobot.security.network.socket.getaddrinfo",
            _fake_resolve("evil.com", [ip]),
        ):
            ok, _ = validate_url_target("http://evil.com/path")
            assert not ok, f"{ip} should be blocked with empty allowlist"


def test_invalid_cidr_raises_error():
    with pytest.raises(ValueError, match="Invalid CIDR"):
        configure_allowed_subnets(["not-a-cidr"])


def test_loopback_blocked_even_if_allowlisted():
    configure_allowed_subnets(["127.0.0.0/8"])
    with patch(
        "nanobot.security.network.socket.getaddrinfo",
        _fake_resolve("evil.com", ["127.0.0.1"]),
    ):
        ok, _ = validate_url_target("http://evil.com/path")
        assert not ok, "127.0.0.1 must always be blocked"


def test_multiple_subnets_configured():
    configure_allowed_subnets(["10.0.0.0/8", "172.16.0.0/12"])
    for ip in ["10.0.0.1", "172.16.5.1"]:
        with patch(
            "nanobot.security.network.socket.getaddrinfo",
            _fake_resolve("internal.corp", [ip]),
        ):
            ok, err = validate_url_target("http://internal.corp/api")
            assert ok, f"{ip} should be allowed, got: {err}"


def test_link_local_blocked_even_if_allowlisted():
    configure_allowed_subnets(["169.254.0.0/16"])
    with patch(
        "nanobot.security.network.socket.getaddrinfo",
        _fake_resolve("evil.com", ["169.254.169.254"]),
    ):
        ok, _ = validate_url_target("http://evil.com/path")
        assert not ok, "169.254.169.254 must always be blocked"
