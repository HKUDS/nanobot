"""Network security utilities — SSRF protection and internal URL detection."""

from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urlparse

from loguru import logger

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

# Networks that are ALWAYS blocked regardless of allowlist
_ALWAYS_BLOCKED = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fe80::/10"),
]

_allowed_subnets: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []

_URL_RE = re.compile(r"https?://[^\s\"'`;|<>]+", re.IGNORECASE)


def configure_allowed_subnets(subnets: list[str]) -> None:
    """Parse and validate CIDR allowlist for SSRF bypass.

    Raises ValueError for invalid CIDR strings.
    Silently skips subnets that overlap with always-blocked ranges (with warning).
    """
    global _allowed_subnets
    parsed: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for cidr in subnets:
        try:
            net = ipaddress.ip_network(cidr, strict=False)
        except ValueError as e:
            raise ValueError(
                f"Invalid CIDR in ssrfAllowedSubnets: {cidr!r}: {e}"
            ) from e
        if any(net.overlaps(blocked) for blocked in _ALWAYS_BLOCKED):
            logger.warning(
                "ssrfAllowedSubnets: ignoring {!r}"
                " — overlaps with always-blocked range",
                cidr,
            )
            continue
        parsed.append(net)
    _allowed_subnets = parsed


def _is_private(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    # Always block loopback and link-local
    if any(addr in net for net in _ALWAYS_BLOCKED):
        return True
    # Check allowlist
    if _allowed_subnets and any(addr in net for net in _allowed_subnets):
        return False
    return any(addr in net for net in _BLOCKED_NETWORKS)


def validate_url_target(url: str) -> tuple[bool, str]:
    """Validate a URL is safe to fetch: scheme, hostname, and resolved IPs.

    Returns (ok, error_message).  When ok is True, error_message is empty.
    """
    try:
        p = urlparse(url)
    except Exception as e:
        return False, str(e)

    if p.scheme not in ("http", "https"):
        return False, f"Only http/https allowed, got '{p.scheme or 'none'}'"
    if not p.netloc:
        return False, "Missing domain"

    hostname = p.hostname
    if not hostname:
        return False, "Missing hostname"

    try:
        infos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror:
        return False, f"Cannot resolve hostname: {hostname}"

    for info in infos:
        try:
            addr = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if _is_private(addr):
            return False, f"Blocked: {hostname} resolves to private/internal address {addr}"

    return True, ""


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


def contains_internal_url(command: str) -> bool:
    """Return True if the command string contains a URL targeting an internal/private address."""
    for m in _URL_RE.finditer(command):
        url = m.group(0)
        ok, _ = validate_url_target(url)
        if not ok:
            return True
    return False
