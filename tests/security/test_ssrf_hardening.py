"""SSRF hardening regression tests.

Covers the two guard surfaces that previously had no direct coverage:
``validate_resolved_url`` (the post-redirect check) and
``PinnedDNSAsyncTransport`` (the TOCTOU defense that re-validates and pins
DNS at request time), plus mixed/odd DNS resolution shapes that bypass
attempts rely on.
"""

from __future__ import annotations

import socket
from unittest.mock import patch

import httpx
import pytest

from nanobot.security.network import (
    PinnedDNSAsyncTransport,
    UnsafeURLRequestError,
    resolve_url_target,
    validate_resolved_url,
    validate_url_target,
)

_PROXY_ENV_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")


@pytest.fixture(autouse=True)
def _clear_proxy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (*_PROXY_ENV_VARS, "NO_PROXY", "no_proxy"):
        monkeypatch.delenv(name, raising=False)


def _fake_resolve(host: str, results: list[str]):
    """Return a getaddrinfo mock that maps the given host to fake IP results."""
    def _resolver(hostname, port, family=0, type_=0):
        if hostname == host:
            return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip, 0)) for ip in results]
        raise socket.gaierror(f"cannot resolve {hostname}")
    return _resolver


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


# ---------------------------------------------------------------------------
# validate_resolved_url — the check applied to each redirect target
# ---------------------------------------------------------------------------

def test_redirect_to_private_ip_literal_is_blocked():
    ok, err = validate_resolved_url("http://169.254.169.254/latest/meta-data/")
    assert not ok
    assert "private" in err.lower()


@pytest.mark.parametrize("ip", ["10.0.0.1", "192.168.1.1", "127.0.0.1", "100.64.0.1"])
def test_redirect_to_internal_ip_literals_are_blocked(ip: str):
    ok, _ = validate_resolved_url(f"http://{ip}/secret")
    assert not ok


def test_redirect_to_ipv6_mapped_loopback_is_blocked():
    ok, err = validate_resolved_url("http://[::ffff:127.0.0.1]/secret")
    assert not ok
    assert "private" in err.lower()


def test_redirect_to_public_ip_is_allowed():
    ok, err = validate_resolved_url("http://93.184.216.34/page")
    assert ok, err


def test_redirect_to_public_domain_resolving_private_is_blocked():
    """A redirect to a hostname must be re-resolved, not trusted."""
    with patch(
        "nanobot.security.network.socket.getaddrinfo",
        _fake_resolve("evil.com", ["192.168.0.10"]),
    ):
        ok, err = validate_resolved_url("http://evil.com/secret")
    assert not ok
    assert "private" in err.lower()


def test_redirect_to_public_domain_resolving_public_is_allowed():
    with patch(
        "nanobot.security.network.socket.getaddrinfo",
        _fake_resolve("example.com", ["93.184.216.34"]),
    ):
        ok, err = validate_resolved_url("http://example.com/page")
    assert ok, err


def test_redirect_unresolvable_hostname_fails_open():
    """Documented trade-off: an unresolvable redirect target cannot be checked
    locally, and the request is delegated to the network stack (and, when
    configured, the user's trusted proxy)."""
    with patch(
        "nanobot.security.network.socket.getaddrinfo",
        side_effect=socket.gaierror("local DNS unavailable"),
    ):
        ok, _ = validate_resolved_url("http://unresolvable.example/page")
    assert ok


def test_redirect_without_hostname_is_allowed():
    ok, _ = validate_resolved_url("not-a-url")
    assert ok


# ---------------------------------------------------------------------------
# resolve_url_target — mixed and unusual resolution shapes
# ---------------------------------------------------------------------------

def test_blocks_hostname_resolving_to_mixed_public_and_private():
    """One private address among public ones must fail closed."""
    with patch(
        "nanobot.security.network.socket.getaddrinfo",
        _fake_resolve("mixed.example", ["93.184.216.34", "10.0.0.5"]),
    ):
        ok, err = validate_url_target("http://mixed.example/")
    assert not ok
    assert "private" in err.lower() or "blocked" in err.lower()


@pytest.mark.parametrize("literal", ["2130706433", "0x7f000001", "127.1"])
def test_blocks_decimal_and_hex_ip_literals(literal: str):
    """http://2130706433/ spellings of 127.0.0.1 must not bypass the guard:
    they are not IP literals to urlparse, so the resolved address decides."""
    with patch(
        "nanobot.security.network.socket.getaddrinfo",
        _fake_resolve(literal, ["127.0.0.1"]),
    ):
        ok, err = validate_url_target(f"http://{literal}/secret")
    assert not ok
    assert "private" in err.lower() or "blocked" in err.lower()


def test_trailing_dot_hostname_resolving_loopback_is_blocked():
    with patch(
        "nanobot.security.network.socket.getaddrinfo",
        _fake_resolve("evil.com.", ["127.0.0.1"]),
    ):
        ok, err = validate_url_target("http://evil.com./secret")
    assert not ok
    assert "blocked" in err.lower() or "private" in err.lower()


def test_allow_loopback_still_blocks_mixed_loopback_resolution():
    """allow_loopback only permits hosts where EVERY resolved address is
    loopback; a mix of loopback and private must stay blocked."""
    with patch(
        "nanobot.security.network.socket.getaddrinfo",
        _fake_resolve("mixed.example", ["127.0.0.1", "169.254.169.254"]),
    ):
        ok, _, _ = resolve_url_target("http://mixed.example/", allow_loopback=True)
    assert not ok


def test_allow_loopback_accepts_all_loopback_resolution():
    """localhost may resolve to several loopback addresses; allow_loopback
    requires every one of them to be loopback."""
    with patch(
        "nanobot.security.network.socket.getaddrinfo",
        _fake_resolve_v6("localhost", ["127.0.0.1", "::1"]),
    ):
        ok, _, resolved = resolve_url_target(
            "http://localhost/", allow_loopback=True
        )
    assert ok
    assert set(resolved) == {"127.0.0.1", "::1"}


def test_no_addresses_resolved_fails_closed_for_loopback_exception():
    """A hostname that resolves to nothing cannot prove it is loopback-only."""
    with patch(
        "nanobot.security.network.socket.getaddrinfo",
        _fake_resolve("empty.example", []),
    ):
        ok, _, _ = resolve_url_target("http://empty.example/", allow_loopback=True)
    assert not ok


# ---------------------------------------------------------------------------
# PinnedDNSAsyncTransport — the TOCTOU defense at request time
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_transport_rejects_url_resolving_to_private_target():
    transport = PinnedDNSAsyncTransport()
    request = httpx.Request("GET", "http://evil.example/secret")
    with patch(
        "nanobot.security.network.socket.getaddrinfo",
        _fake_resolve("evil.example", ["10.0.0.7"]),
    ):
        with pytest.raises(UnsafeURLRequestError):
            await transport.handle_async_request(request)
    await transport.aclose()


@pytest.mark.asyncio
async def test_transport_pins_dns_against_second_resolution_rebind():
    """After validating, the transport pins DNS so a re-binding resolver that
    returns a private address at request time cannot take effect."""

    class _RecordingTransport(httpx.AsyncBaseTransport):
        def __init__(self) -> None:
            self.resolved_during_request: list[str] | None = None
            self.requested_url: str | None = None

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            self.requested_url = str(request.url)
            infos = socket.getaddrinfo(
                "example.com", 80, socket.AF_UNSPEC, socket.SOCK_STREAM
            )
            self.resolved_during_request = [info[4][0] for info in infos]
            return httpx.Response(200)

    inner = _RecordingTransport()
    transport = PinnedDNSAsyncTransport(inner=inner)
    request = httpx.Request("GET", "http://example.com/page")

    resolutions = {"count": 0}

    def _hostile_after_first_resolver(hostname, port, family=0, type_=0):
        """Answers with the validated IP once, then rebinds to a blocked
        target — what an attacker wants after the check has passed."""
        if hostname == "example.com":
            resolutions["count"] += 1
            if resolutions["count"] == 1:
                return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 0))]
            return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("169.254.169.254", 0))]
        raise socket.gaierror(f"cannot resolve {hostname}")

    with patch(
        "nanobot.security.network.socket.getaddrinfo", _hostile_after_first_resolver
    ):
        response = await transport.handle_async_request(request)

    assert response.status_code == 200
    assert inner.requested_url == "http://example.com/page"
    # The hostile second resolution never won: the request saw the IP that
    # was validated, because the transport pinned DNS around the inner call.
    assert resolutions["count"] == 1
    assert inner.resolved_during_request == ["93.184.216.34"]
    await transport.aclose()


@pytest.mark.asyncio
async def test_transport_propagates_inner_response_without_validation_skip():
    """A URL that validates must still flow through the pinned inner transport,
    and errors from it surface to the caller."""
    transport = PinnedDNSAsyncTransport(
        inner=httpx.MockTransport(lambda request: httpx.Response(404))
    )
    with patch(
        "nanobot.security.network.socket.getaddrinfo",
        _fake_resolve("example.com", ["93.184.216.34"]),
    ):
        response = await transport.handle_async_request(
            httpx.Request("GET", "http://example.com/missing")
        )
    assert response.status_code == 404
    await transport.aclose()
