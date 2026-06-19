"""Tests for blackcat.security.network — SSRF protection and internal URL detection."""

from __future__ import annotations

import socket
from unittest.mock import patch

import pytest

from blackcat.security.network import (
    configure_ssrf_whitelist,
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
    with patch("blackcat.security.network.socket.getaddrinfo", _fake_resolve("evil.com", [ip])):
        ok, err = validate_url_target("http://evil.com/path")
        assert not ok, f"Should block {label} ({ip})"
        assert "private" in err.lower() or "blocked" in err.lower()


def test_blocks_ipv6_loopback():
    def _resolver(hostname, port, family=0, type_=0):
        return [(socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("::1", 0, 0, 0))]
    with patch("blackcat.security.network.socket.getaddrinfo", _resolver):
        ok, err = validate_url_target("http://evil.com/")
        assert not ok


# ---------------------------------------------------------------------------
# validate_url_target — IPv6-mapped IPv4 bypass prevention
# ---------------------------------------------------------------------------

def _fake_resolve_v6(host: str, results: list[str]):
    """Like _fake_resolve but returns AF_INET6 tuples for IPv6 addresses."""
    def _resolver(hostname, port, family=0, type_=0):
        if hostname == host:
            entries = []
            for ip in results:
                if ":" in ip:
                    entries.append((socket.AF_INET6, socket.SOCK_STREAM, 0, "", (ip, 0, 0, 0)))
                else:
                    entries.append((socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip, 0)))
            return entries
        raise socket.gaierror(f"cannot resolve {hostname}")
    return _resolver


def test_blocks_ipv6_mapped_loopback():
    """::ffff:127.0.0.1 must be blocked just like 127.0.0.1."""
    with patch("blackcat.security.network.socket.getaddrinfo", _fake_resolve_v6("evil.com", ["::ffff:127.0.0.1"])):
        ok, err = validate_url_target("http://evil.com/")
        assert not ok
        assert "blocked" in err.lower()


def test_blocks_ipv6_mapped_metadata():
    """::ffff:169.254.169.254 must be blocked just like 169.254.169.254."""
    with patch("blackcat.security.network.socket.getaddrinfo", _fake_resolve_v6("evil.com", ["::ffff:169.254.169.254"])):
        ok, err = validate_url_target("http://evil.com/")
        assert not ok


def test_blocks_ipv6_mapped_rfc1918():
    """::ffff:10.0.0.1 must be blocked just like 10.0.0.1."""
    with patch("blackcat.security.network.socket.getaddrinfo", _fake_resolve_v6("evil.com", ["::ffff:10.0.0.1"])):
        ok, err = validate_url_target("http://evil.com/")
        assert not ok


def test_allows_public_ipv6():
    """Public IPv6 addresses must still be allowed."""
    with patch("blackcat.security.network.socket.getaddrinfo", _fake_resolve_v6("example.com", ["2606:4700::6810:84e5"])):
        ok, err = validate_url_target("http://example.com/")
        assert ok, f"Should allow public IPv6, got: {err}"


# ---------------------------------------------------------------------------
# validate_url_target — allows public IPs
# ---------------------------------------------------------------------------

def test_allows_public_ip():
    with patch("blackcat.security.network.socket.getaddrinfo", _fake_resolve("example.com", ["93.184.216.34"])):
        ok, err = validate_url_target("http://example.com/page")
        assert ok, f"Should allow public IP, got: {err}"


def test_allows_normal_https():
    with patch("blackcat.security.network.socket.getaddrinfo", _fake_resolve("github.com", ["140.82.121.3"])):
        ok, err = validate_url_target("https://github.com/HKUDS/blackcat")
        assert ok


# ---------------------------------------------------------------------------
# contains_internal_url — shell command scanning
# ---------------------------------------------------------------------------

def test_detects_curl_metadata():
    with patch("blackcat.security.network.socket.getaddrinfo", _fake_resolve("169.254.169.254", ["169.254.169.254"])):
        assert contains_internal_url('curl -s http://169.254.169.254/computeMetadata/v1/')


def test_detects_wget_localhost():
    with patch("blackcat.security.network.socket.getaddrinfo", _fake_resolve("localhost", ["127.0.0.1"])):
        assert contains_internal_url("wget http://localhost:8080/secret")


def test_loopback_exception_allows_literal_localhost_only():
    with patch("blackcat.security.network.socket.getaddrinfo", _fake_resolve("localhost", ["127.0.0.1"])):
        assert not contains_internal_url("curl http://localhost:8765/", allow_loopback=True)


def test_loopback_exception_rejects_public_name_resolving_to_loopback():
    with patch("blackcat.security.network.socket.getaddrinfo", _fake_resolve("example.com", ["127.0.0.1"])):
        assert contains_internal_url("curl http://example.com:8765/", allow_loopback=True)


def test_loopback_exception_rejects_metadata():
    with patch("blackcat.security.network.socket.getaddrinfo", _fake_resolve("169.254.169.254", ["169.254.169.254"])):
        assert contains_internal_url("curl http://169.254.169.254/latest/meta-data/", allow_loopback=True)


def test_detects_ipv6_mapped_loopback():
    """contains_internal_url must catch IPv6-mapped loopback in shell commands."""
    with patch("blackcat.security.network.socket.getaddrinfo", _fake_resolve_v6("evil.com", ["::ffff:127.0.0.1"])):
        assert contains_internal_url("curl http://evil.com/secret")


def test_allows_normal_curl():
    with patch("blackcat.security.network.socket.getaddrinfo", _fake_resolve("example.com", ["93.184.216.34"])):
        assert not contains_internal_url("curl https://example.com/api/data")


def test_no_urls_returns_false():
    assert not contains_internal_url("echo hello && ls -la")


# ---------------------------------------------------------------------------
# SSRF whitelist — allow specific CIDR ranges (#2669)
# ---------------------------------------------------------------------------

def test_blocks_cgnat_by_default():
    """100.64.0.0/10 (CGNAT / Tailscale) is blocked by default."""
    with patch("blackcat.security.network.socket.getaddrinfo", _fake_resolve("ts.local", ["100.100.1.1"])):
        ok, _ = validate_url_target("http://ts.local/api")
        assert not ok


def test_whitelist_allows_cgnat():
    """Whitelisting 100.64.0.0/10 lets Tailscale addresses through."""
    configure_ssrf_whitelist(["100.64.0.0/10"])
    try:
        with patch("blackcat.security.network.socket.getaddrinfo", _fake_resolve("ts.local", ["100.100.1.1"])):
            ok, err = validate_url_target("http://ts.local/api")
            assert ok, f"Whitelisted CGNAT should be allowed, got: {err}"
    finally:
        configure_ssrf_whitelist([])


def test_whitelist_does_not_affect_other_blocked():
    """Whitelisting CGNAT must not unblock other private ranges."""
    configure_ssrf_whitelist(["100.64.0.0/10"])
    try:
        with patch("blackcat.security.network.socket.getaddrinfo", _fake_resolve("evil.com", ["10.0.0.1"])):
            ok, _ = validate_url_target("http://evil.com/secret")
            assert not ok
    finally:
        configure_ssrf_whitelist([])


def test_whitelist_invalid_cidr_ignored():
    """Invalid CIDR entries are silently skipped."""
    configure_ssrf_whitelist(["not-a-cidr", "100.64.0.0/10"])
    try:
        with patch("blackcat.security.network.socket.getaddrinfo", _fake_resolve("ts.local", ["100.100.1.1"])):
            ok, _ = validate_url_target("http://ts.local/api")
            assert ok
    finally:
        configure_ssrf_whitelist([])


def test_whitelist_allows_ipv6_mapped_cgnat():
    """Whitelist must work when DNS returns IPv6-mapped CGNAT address."""
    configure_ssrf_whitelist(["100.64.0.0/10"])
    try:
        with patch("blackcat.security.network.socket.getaddrinfo", _fake_resolve_v6("ts.local", ["::ffff:100.100.1.1"])):
            ok, err = validate_url_target("http://ts.local/api")
            assert ok, f"Whitelisted IPv6-mapped CGNAT should be allowed, got: {err}"
    finally:
        configure_ssrf_whitelist([])
