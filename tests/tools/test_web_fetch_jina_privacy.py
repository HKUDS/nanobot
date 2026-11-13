from __future__ import annotations

import json
import socket
from unittest.mock import patch

import httpx
import pytest

from nanobot.agent.tools import web as web_module
from nanobot.agent.tools.web import (
    WebFetchTool,
    _redact_url_for_log,
    _url_carries_credentials,
)


def _fake_resolve_public(hostname, port, family=0, type_=0):
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 0))]


class _RecordingJinaClient:
    """Fake httpx.AsyncClient that records every requested URL."""

    requested: list[str] = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url, **kwargs):
        _RecordingJinaClient.requested.append(url)

        class _Response:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"data": {"title": "T", "content": "body", "url": url}}

        return _Response()


@pytest.fixture
def jina_client():
    _RecordingJinaClient.requested = []
    with patch("nanobot.agent.tools.web.httpx.AsyncClient", _RecordingJinaClient):
        yield _RecordingJinaClient


@pytest.mark.parametrize(
    "url",
    [
        "https://user:secret@example.com/report",
        "https://user@example.com/report",
        "https://example.com/download?token=abc123",
        "https://example.com/download?access_token=abc123",
        "https://example.com/doc?Signature=xyz&Expires=1700000000",
        "https://bucket.s3.amazonaws.com/key?X-Amz-Signature=deadbeef",
        "https://storage.googleapis.com/o/file?X-Goog-Signature=deadbeef",
        "https://example.com/blob?sig=sas-token-material",
        "https://maps.example.com/api?key=AIzaFixture",
        "https://example.com/callback?code=oauth-code",
        "https://example.com/download?API-KEY=secret",
        "https://example.com/download?file=report;token=secret",
    ],
)
def test_credential_urls_are_detected(url: str) -> None:
    assert _url_carries_credentials(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/",
        "https://example.com/watch?v=abc123",
        "https://example.com/search?q=token+design&page=2",
        "https://example.com/page#section-3",
    ],
)
def test_plain_urls_are_not_detected(url: str) -> None:
    assert _url_carries_credentials(url) is False


def test_log_label_excludes_every_credential_bearing_component() -> None:
    url = "https://user:secret@example.com:8443/private/webhook-token?token=abc#secret"
    assert _redact_url_for_log(url) == "https://example.com:8443"


def test_log_label_preserves_ipv6_origin_without_credentials() -> None:
    url = "https://user:secret@[2001:db8::1]:8443/private?token=abc"
    assert _redact_url_for_log(url) == "https://[2001:db8::1]:8443"


async def test_jina_skip_log_does_not_contain_url_credentials(
    jina_client, monkeypatch
) -> None:
    logged: list[tuple[object, ...]] = []
    monkeypatch.setattr(web_module.logger, "debug", lambda *args: logged.append(args))

    result = await WebFetchTool()._fetch_jina(
        ("https://user:secret@example.com/private/webhook-token?token=abc",),
        max_chars=1000,
    )

    assert result is None
    assert jina_client.requested == []
    rendered_log_arguments = " ".join(str(item) for call in logged for item in call)
    assert "secret" not in rendered_log_arguments
    assert "webhook-token" not in rendered_log_arguments
    assert "token=abc" not in rendered_log_arguments


async def test_jina_still_used_for_plain_urls(jina_client) -> None:
    tool = WebFetchTool()
    result = await tool._fetch_jina(("https://example.com/watch?v=abc123",), max_chars=1000)
    assert result is not None
    assert json.loads(result)["extractor"] == "jina"
    assert jina_client.requested == [
        "https://r.jina.ai/https://example.com/watch?v=abc123"
    ]


async def test_fragment_is_never_forwarded(jina_client) -> None:
    tool = WebFetchTool()
    result = await tool._fetch_jina(
        ("https://example.com/page?q=1#access_token=leaked",), max_chars=1000
    )
    assert result is not None
    assert jina_client.requested == ["https://r.jina.ai/https://example.com/page?q=1"]


@pytest.mark.parametrize("scenario", ["direct", "userinfo", "final-hop", "middle-hop", "failed-preflight"])
async def test_execute_keeps_unverified_or_credentialed_urls_local(monkeypatch, scenario: str) -> None:
    tool = WebFetchTool()
    requested: list[str] = []
    short_url = "https://example.com/short"
    signed_url = "https://cdn.example.com/file?token=secret"
    public_url = "https://cdn.example.com/result"
    chains = {
        "direct": [signed_url],
        "userinfo": ["https://user:secret@example.com/report"],
        "final-hop": [short_url, signed_url],
        "middle-hop": [short_url, signed_url, public_url],
        "failed-preflight": [short_url, public_url],
    }
    chain = chains[scenario]
    redirects = dict(zip(chain, chain[1:]))

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        requested.append(url)
        if scenario == "failed-preflight" and len(requested) == len(chain):
            raise httpx.ReadError("preflight interrupted", request=request)
        if url in redirects:
            return httpx.Response(302, headers={"location": redirects[url]})
        assert url == chain[-1]
        return httpx.Response(
            200, headers={"content-type": "text/html"}, text="<html><body>ok</body></html>",
        )

    async def unexpected_jina(*args, **kwargs):
        pytest.fail("No HTTP request to Jina is allowed for this chain")

    monkeypatch.setattr(httpx.AsyncClient, "get", unexpected_jina)
    monkeypatch.setattr(tool, "_extract_readable_html", lambda html, mode: "ok")
    monkeypatch.setattr(web_module, "PinnedDNSAsyncTransport", lambda: httpx.MockTransport(handler))
    monkeypatch.setattr("nanobot.security.network.getproxies", lambda: {})

    with patch("nanobot.security.network.socket.getaddrinfo", _fake_resolve_public):
        result = await tool.execute(url=chain[0])

    data = json.loads(result)
    assert data["extractor"] == "readability"
    assert requested == chain * 2
