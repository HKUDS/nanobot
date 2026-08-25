"""Tests for shared embedded WebUI HTTP helpers."""

import gzip
import json
import time
from types import SimpleNamespace

from nanobot.webui.http_utils import http_json_response
from nanobot.webui.ws_http import GatewayHTTPHandler


def test_http_json_response_compresses_large_payload_when_gzip_is_accepted() -> None:
    payload = {"message": "响应内容" * 2_000}

    response = http_json_response(payload, accept_encoding="br, gzip; q=0.5")

    assert response.headers["Content-Encoding"] == "gzip"
    assert response.headers["Vary"] == "Accept-Encoding"
    assert int(response.headers["Content-Length"]) == len(response.body)
    assert json.loads(gzip.decompress(response.body)) == payload


def test_http_json_response_preserves_identity_when_gzip_is_rejected() -> None:
    payload = {"message": "x" * 8_000}

    response = http_json_response(payload, accept_encoding="gzip;q=0, br")

    assert "Content-Encoding" not in response.headers
    assert response.headers["Vary"] == "Accept-Encoding"
    assert int(response.headers["Content-Length"]) == len(response.body)
    assert json.loads(response.body) == payload


def test_http_json_response_does_not_compress_small_payload() -> None:
    payload = {"ok": True}

    response = http_json_response(payload, accept_encoding="gzip")

    assert "Content-Encoding" not in response.headers
    assert response.headers["Vary"] == "Accept-Encoding"
    assert json.loads(response.body) == payload


def test_slow_http_log_records_route_scale_without_user_path_content() -> None:
    records: list[str] = []

    class _Logger:
        def warning(self, message: str, *args: object) -> None:
            records.append(message.format(*args))

    handler = SimpleNamespace(_log=_Logger())
    secret = "private-session-token"

    GatewayHTTPHandler._log_slow_http(
        handler,
        f"/api/sessions/{secret}?query={secret}",
        SimpleNamespace(status_code=200),
        time.perf_counter() - 2,
        input_chars=80,
    )

    assert len(records) == 1
    assert "operation=/api/sessions" in records[0]
    assert "status=200" in records[0]
    assert "input_chars=80" in records[0]
    assert "duration_ms=" in records[0]
    assert secret not in records[0]
