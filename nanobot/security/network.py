"""Network security utilities — SSRF protection and internal URL detection."""

from __future__ import annotations

import ipaddress
import re
import socket
from contextlib import contextmanager, suppress
from urllib.parse import urlparse

import httpx

_BLOCKED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),   # carrier-grade NAT
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),   # link-local / cloud metadata
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),          # unique local
    ipaddress.ip_network("fe80::/10"),         # link-local v6
]

_URL_RE = re.compile(r"https?://[^\s\"'`;|<>]+", re.IGNORECASE)

_allowed_networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []


def configure_ssrf_whitelist(cidrs: list[str]) -> None:
    """Allow specific CIDR ranges to bypass SSRF blocking (e.g. Tailscale's 100.64.0.0/10)."""
    global _allowed_networks
    nets = []
    for cidr in cidrs:
        with suppress(ValueError):
            nets.append(ipaddress.ip_network(cidr, strict=False))
    _allowed_networks = nets


def _normalize_addr(
    addr: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    """Normalize IPv6-mapped IPv4 addresses to their IPv4 form.

    ``::ffff:127.0.0.1`` is semantically identical to ``127.0.0.1`` but
    Python's ipaddress treats it as an IPv6Address that matches neither
    ``127.0.0.0/8`` nor ``::1/128``.  Converting it to IPv4 ensures
    blocklist/allowlist checks work correctly.
    """
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        return addr.ipv4_mapped
    return addr


def _is_private(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    normalized = _normalize_addr(addr)
    if _allowed_networks and any(normalized in net for net in _allowed_networks):
        return False
    return any(normalized in net for net in _BLOCKED_NETWORKS)


def resolve_url_target(url: str, *, allow_loopback: bool = False) -> tuple[bool, str, tuple[str, ...]]:
    """Validate a URL is safe to fetch: scheme, hostname, and resolved IPs.

    ``allow_loopback`` is intentionally narrow: it only permits literal
    loopback hosts (localhost, 127.0.0.0/8, ::1) when every resolved address is
    loopback. It does not allow RFC1918, link-local, metadata, or public DNS
    names that happen to resolve to loopback.

    Returns (ok, error_message, resolved_ips).  When ok is True,
    resolved_ips contains the public IPs that were validated for this URL.
    """
    try:
        p = urlparse(url)
    except Exception as e:
        return False, str(e), ()

    if p.scheme not in ("http", "https"):
        return False, f"Only http/https allowed, got '{p.scheme or 'none'}'", ()
    if not p.netloc:
        return False, "Missing domain", ()

    hostname = p.hostname
    if not hostname:
        return False, "Missing hostname", ()

    try:
        infos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror:
        return False, f"Cannot resolve hostname: {hostname}", ()

    addrs: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for info in infos:
        try:
            addr = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        addrs.append(addr)
    if allow_loopback and _is_allowed_loopback_target(hostname, addrs):
        return True, "", tuple(dict.fromkeys(str(_normalize_addr(addr)) for addr in addrs))
    for addr in addrs:
        if _is_private(addr):
            return False, f"Blocked: {hostname} resolves to private/internal address {addr}", ()

    return True, "", tuple(dict.fromkeys(str(_normalize_addr(addr)) for addr in addrs))


def validate_url_target(url: str, *, allow_loopback: bool = False) -> tuple[bool, str]:
    """Validate a URL is safe to fetch: scheme, hostname, and resolved IPs."""
    ok, error, _ = resolve_url_target(url, allow_loopback=allow_loopback)
    return ok, error


@contextmanager
def pin_resolved_url_dns(url: str, resolved_ips: tuple[str, ...]):
    """Pin DNS lookups for the URL hostname to previously validated IPs."""
    try:
        hostname = urlparse(url).hostname
    except Exception:
        hostname = None
    if not hostname or not resolved_ips:
        yield
        return

    pinned_host = hostname.rstrip(".").lower()
    original_getaddrinfo = socket.getaddrinfo

    def _getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):  # noqa: A002
        if str(host).rstrip(".").lower() != pinned_host:
            return original_getaddrinfo(host, port, family, type, proto, flags)
        infos = []
        for ip in resolved_ips:
            addr = ipaddress.ip_address(ip)
            addr_family = socket.AF_INET6 if addr.version == 6 else socket.AF_INET
            if family not in (0, socket.AF_UNSPEC, addr_family):
                continue
            sockaddr = (ip, port or 0, 0, 0) if addr_family == socket.AF_INET6 else (ip, port or 0)
            infos.append((addr_family, type or socket.SOCK_STREAM, proto, "", sockaddr))
        return infos

    socket.getaddrinfo = _getaddrinfo
    try:
        yield
    finally:
        socket.getaddrinfo = original_getaddrinfo


class PinnedDNSAsyncTransport(httpx.AsyncBaseTransport):
    """HTTPX transport that pins each request to the IPs validated for its URL."""

    def __init__(self, *, allow_loopback: bool = False) -> None:
        self._allow_loopback = allow_loopback
        self._inner = httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        ok, error, resolved_ips = resolve_url_target(url, allow_loopback=self._allow_loopback)
        if not ok:
            raise httpx.RequestError(error, request=request)
        with pin_resolved_url_dns(url, resolved_ips):
            return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self._inner.aclose()


def validate_resolved_url(url: str) -> tuple[bool, str]:
    """Validate an already-fetched URL (e.g. after redirect). Only checks the IP, skips DNS."""
    try:
        p = urlparse(url)
    except Exception:
        return True, ""

    hostname = p.hostname
    if not hostname:
        return True, ""

    try:
        addr = ipaddress.ip_address(hostname)
        if _is_private(addr):
            return False, f"Redirect target is a private address: {addr}"
    except ValueError:
        # hostname is a domain name, resolve it
        try:
            infos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        except socket.gaierror:
            return True, ""
        for info in infos:
            try:
                addr = ipaddress.ip_address(info[4][0])
            except ValueError:
                continue
            if _is_private(addr):
                return False, f"Redirect target {hostname} resolves to private address {addr}"

    return True, ""


def contains_internal_url(command: str, *, allow_loopback: bool = False) -> bool:
    """Return True if the command string contains a URL targeting an internal/private address."""
    for m in _URL_RE.finditer(command):
        url = m.group(0)
        ok, _ = validate_url_target(url, allow_loopback=allow_loopback)
        if not ok:
            return True
    return False


def _is_allowed_loopback_target(
    hostname: str,
    addrs: list[ipaddress.IPv4Address | ipaddress.IPv6Address],
) -> bool:
    if not addrs or not all(_normalize_addr(addr).is_loopback for addr in addrs):
        return False
    normalized = hostname.rstrip(".").lower()
    if normalized == "localhost":
        return True
    with suppress(ValueError):
        return ipaddress.ip_address(hostname).is_loopback
    return False
