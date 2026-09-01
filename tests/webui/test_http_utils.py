"""Tests for shared embedded WebUI HTTP helpers."""

import gzip
import json

from nanobot.webui.http_utils import http_json_response


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
