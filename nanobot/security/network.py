"""Network security utilities — SSRF protection and internal URL detection."""

from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urlparse

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


def _is_private(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
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


def contains_internal_url(command: str, allowed_hosts: list[str] | None = None) -> bool:
    """Return True if the command string contains a URL targeting an internal/private address.

    Args:
        command: The command string to check
        allowed_hosts: Optional list of allowed hostnames/IPs to bypass the check

    Returns:
        True if the command contains a blocked internal URL, False otherwise
    """
    allowed_hosts = allowed_hosts or []
    for m in _URL_RE.finditer(command):
        url = m.group(0)
        ok, error_msg = validate_url_target(url)
        if not ok:
            # Check if this URL is in the allowed hosts list
            try:
                from urllib.parse import urlparse
                parsed = urlparse(url)
                hostname = parsed.hostname
                if hostname and hostname in allowed_hosts:
                    continue  # Allow this URL
            except Exception:
                pass
            return True
    return False
