"""Tests for nanobot.security.network — SSRF protection and internal URL detection."""

from __future__ import annotations

import socket
from unittest.mock import patch

import pytest

from nanobot.security.network import contains_internal_url, validate_resolved_url, validate_url_target


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
# allowed_hosts — validate_url_target allowlist
# ---------------------------------------------------------------------------

def test_allowlist_bypasses_private_ip_block():
    """Hosts in allowed_hosts must not be blocked even when resolving to private IPs."""
    allowed = frozenset(["gitlab.gleezy.cn"])
    with patch("nanobot.security.network.socket.getaddrinfo", _fake_resolve("gitlab.gleezy.cn", ["172.16.1.10"])):
        ok, err = validate_url_target("https://gitlab.gleezy.cn/api", allowed_hosts=allowed)
    assert ok, f"Expected allowlisted host to pass, got: {err}"


def test_non_allowlisted_host_still_blocked():
    """Hosts NOT in allowed_hosts must still be blocked for private IPs."""
    allowed = frozenset(["gitlab.gleezy.cn"])
    with patch("nanobot.security.network.socket.getaddrinfo", _fake_resolve("evil.internal", ["172.16.1.10"])):
        ok, err = validate_url_target("https://evil.internal/", allowed_hosts=allowed)
    assert not ok


def test_allowlist_case_insensitive():
    """allowed_hosts matching must be case-insensitive."""
    allowed = frozenset(["gitlab.gleezy.cn"])
    with patch("nanobot.security.network.socket.getaddrinfo", _fake_resolve("GITLAB.GLEEZY.CN", ["172.16.1.10"])):
        ok, _ = validate_url_target("https://GITLAB.GLEEZY.CN/repo", allowed_hosts=allowed)
    assert ok


# ---------------------------------------------------------------------------
# allowed_hosts — contains_internal_url allowlist
# ---------------------------------------------------------------------------

def test_contains_internal_url_respects_allowlist():
    """git push to allowlisted host must not be flagged as internal URL."""
    allowed = frozenset(["gitlab.gleezy.cn"])
    cmd = "git push https://user:token@gitlab.gleezy.cn/org/repo.git main"
    with patch("nanobot.security.network.socket.getaddrinfo", _fake_resolve("gitlab.gleezy.cn", ["172.16.1.10"])):
        assert not contains_internal_url(cmd, allowed_hosts=allowed)


def test_contains_internal_url_blocks_non_allowlisted():
    """Non-allowlisted private hosts must still be caught."""
    allowed = frozenset(["gitlab.gleezy.cn"])
    cmd = "curl http://192.168.0.1/secret"
    with patch("nanobot.security.network.socket.getaddrinfo", _fake_resolve("192.168.0.1", ["192.168.0.1"])):
        assert contains_internal_url(cmd, allowed_hosts=allowed)


# ---------------------------------------------------------------------------
# allowed_hosts — validate_resolved_url allowlist
# ---------------------------------------------------------------------------

def test_validate_resolved_url_blocks_private_redirect():
    """Without allowlist, redirect to private IP must be blocked."""
    with patch("nanobot.security.network.socket.getaddrinfo", _fake_resolve("internal.host", ["10.0.0.5"])):
        ok, err = validate_resolved_url("http://internal.host/path")
    assert not ok
    assert "private" in err.lower() or "redirect" in err.lower()


def test_validate_resolved_url_allows_allowlisted_redirect():
    """Allowlisted host must pass even when it redirects to a private IP."""
    allowed = frozenset(["gitlab.gleezy.cn"])
    with patch("nanobot.security.network.socket.getaddrinfo", _fake_resolve("gitlab.gleezy.cn", ["172.16.1.10"])):
        ok, err = validate_resolved_url("https://gitlab.gleezy.cn/api", allowed_hosts=allowed)
    assert ok, f"Expected allowlisted redirect host to pass, got: {err}"
