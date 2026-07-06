"""Shared HTTP helpers for the embedded WebUI gateway."""

from __future__ import annotations

import email.utils
import hmac
import http
import ipaddress
import json
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

from websockets.datastructures import Headers
from websockets.http11 import Response

QueryParams = dict[str, list[str]]


def strip_trailing_slash(path: str) -> str:
    if len(path) > 1 and path.endswith("/"):
        return path.rstrip("/")
    return path or "/"


def normalize_config_path(path: str) -> str:
    return strip_trailing_slash(path)


def case_insensitive_header(headers: Any, key: str) -> str:
    """Read a header from websockets/http test stubs without assuming casing."""
    try:
        value = headers.get(key)
    except Exception:
        value = None
    if value is None:
        try:
            value = headers.get(key.lower())
        except Exception:
            value = None
    return str(value or "").strip()


def safe_host_header(value: str) -> str:
    """Return a safe Host header value, or empty when it should not be echoed."""
    value = value.strip()
    if not value:
        return ""
    if re.fullmatch(r"\[[0-9A-Fa-f:.]+\](?::\d{1,5})?", value):
        return value
    if re.fullmatch(r"[A-Za-z0-9.-]+(?::\d{1,5})?", value):
        return value
    return ""


def host_for_url(host: str, port: int) -> str:
    host = host.strip()
    if host in ("0.0.0.0", "::"):
        host = "127.0.0.1"
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"{host}:{port}"


def http_json_response(data: dict[str, Any], *, status: int = 200) -> Response:
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    headers = Headers(
        [
            ("Date", email.utils.formatdate(usegmt=True)),
            ("Connection", "close"),
            ("Content-Length", str(len(body))),
            ("Content-Type", "application/json; charset=utf-8"),
        ]
    )
    reason = http.HTTPStatus(status).phrase
    return Response(status, reason, headers, body)


def http_response(
    body: bytes,
    *,
    status: int = 200,
    content_type: str = "text/plain; charset=utf-8",
    extra_headers: list[tuple[str, str]] | None = None,
) -> Response:
    headers = [
        ("Date", email.utils.formatdate(usegmt=True)),
        ("Connection", "close"),
        ("Content-Length", str(len(body))),
        ("Content-Type", content_type),
    ]
    if extra_headers:
        headers.extend(extra_headers)
    reason = http.HTTPStatus(status).phrase
    return Response(status, reason, Headers(headers), body)


def http_error(status: int, message: str | None = None) -> Response:
    body = (message or http.HTTPStatus(status).phrase).encode("utf-8")
    return http_response(body, status=status)


def parse_request_path(path_with_query: str) -> tuple[str, QueryParams]:
    """Parse normalized path and query parameters in one pass."""
    parsed = urlparse("ws://x" + path_with_query)
    path = strip_trailing_slash(parsed.path or "/")
    return path, parse_qs(parsed.query, keep_blank_values=True)


def normalize_http_path(path_with_query: str) -> str:
    return parse_request_path(path_with_query)[0]


def parse_query(path_with_query: str) -> QueryParams:
    return parse_request_path(path_with_query)[1]


def query_first(query: QueryParams, key: str) -> str | None:
    values = query.get(key)
    return values[0] if values else None


def is_localhost(connection: Any) -> bool:
    addr = getattr(connection, "remote_address", None)
    if not addr:
        return False
    host = addr[0] if isinstance(addr, tuple) else addr
    if not isinstance(host, str):
        return False
    if host.startswith("::ffff:"):
        host = host[7:]
    return host in {"127.0.0.1", "::1", "localhost"}


def _host_without_port(value: str) -> str:
    value = value.strip().strip('"').strip("'")
    if not value:
        return ""
    if value.startswith("["):
        end = value.find("]")
        return value[1:end] if end > 0 else value
    if value.count(":") == 1:
        host, port = value.rsplit(":", 1)
        if port.isdigit():
            return host
    return value


def is_loopback_host(value: str) -> bool:
    host = _host_without_port(value)
    if host.startswith("::ffff:"):
        host = host[7:]
    host = host.rstrip(".").lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _split_comma_header(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _forwarded_header_values(value: str, key: str) -> list[str]:
    values: list[str] = []
    for entry in _split_comma_header(value):
        for part in entry.split(";"):
            name, sep, raw = part.partition("=")
            if sep and name.strip().lower() == key:
                cleaned = raw.strip().strip('"')
                if cleaned:
                    values.append(cleaned)
    return values


def _all_forwarded_values_are_loopback(headers: Any) -> bool:
    checks: list[str] = []
    checks.extend(_split_comma_header(case_insensitive_header(headers, "X-Forwarded-For")))
    checks.extend(_split_comma_header(case_insensitive_header(headers, "X-Real-IP")))
    checks.extend(_split_comma_header(case_insensitive_header(headers, "X-Forwarded-Host")))
    forwarded = case_insensitive_header(headers, "Forwarded")
    checks.extend(_forwarded_header_values(forwarded, "for"))
    checks.extend(_forwarded_header_values(forwarded, "host"))
    return all(is_loopback_host(value) for value in checks)


def is_local_browser_request(connection: Any, headers: Any) -> bool:
    """Return True only for a local TCP peer presenting a local browser origin."""
    if not is_localhost(connection):
        return False
    host = case_insensitive_header(headers, "Host")
    if not is_loopback_host(host):
        return False
    return _all_forwarded_values_are_loopback(headers)


def bearer_token(headers: Any) -> str | None:
    auth = headers.get("Authorization") or headers.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return None


def issue_route_secret_matches(headers: Any, configured_secret: str) -> bool:
    if not configured_secret:
        return True
    authorization = headers.get("Authorization") or headers.get("authorization")
    if authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
        return hmac.compare_digest(supplied, configured_secret)
    header_token = headers.get("X-Nanobot-Auth") or headers.get("x-nanobot-auth")
    if not header_token:
        return False
    return hmac.compare_digest(header_token.strip(), configured_secret)
