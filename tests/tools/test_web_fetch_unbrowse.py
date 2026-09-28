"""Tests for the optional Unbrowse backend of web_fetch."""

from __future__ import annotations

import json

import pytest

from nanobot.agent.tools import web as web_module
from nanobot.agent.tools.web import WebFetchConfig, WebFetchTool


def _scrape_result(**data) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"content": [{"type": "text", "text": json.dumps(data)}]},
    }


class _FakeResponse:
    def __init__(self, body: dict, status_code: int = 200):
        self._body = body
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._body


def _patch_client(monkeypatch, response: _FakeResponse) -> list[dict]:
    calls: list[dict] = []

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json=None, headers=None, **kwargs):
            calls.append({"url": url, "json": json, "headers": headers})
            return response

    monkeypatch.setattr("nanobot.agent.tools.web.httpx.AsyncClient", FakeClient)
    return calls


def _tool() -> WebFetchTool:
    return WebFetchTool(config=WebFetchConfig(unbrowse_api_key="ub-test-key"))


async def test_unbrowse_fetch_returns_markdown(monkeypatch) -> None:
    calls = _patch_client(
        monkeypatch,
        _FakeResponse(
            _scrape_result(
                url="https://example.com/page",
                finalUrl="https://example.com/page/",
                metadata={"title": "Example"},
                markdown="Hello from a rendered page.",
            )
        ),
    )

    result = await _tool()._fetch_unbrowse("https://example.com/page#section", 50000)

    data = json.loads(result)
    assert data["extractor"] == "unbrowse"
    assert data["finalUrl"] == "https://example.com/page/"
    assert data["untrusted"] is True
    assert "# Example\n\nHello from a rendered page." in data["text"]
    assert calls[0]["url"] == "https://unbrowse.ai/api/mcp"
    assert calls[0]["headers"]["Authorization"] == "Bearer ub-test-key"
    assert calls[0]["json"]["method"] == "tools/call"
    assert calls[0]["json"]["params"]["name"] == "unbrowse.scrape"
    # The fragment is client-side only and never forwarded.
    assert calls[0]["json"]["params"]["arguments"]["url"] == "https://example.com/page"


async def test_unbrowse_fetch_truncates(monkeypatch) -> None:
    _patch_client(monkeypatch, _FakeResponse(_scrape_result(markdown="x" * 500)))

    data = json.loads(await _tool()._fetch_unbrowse("https://example.com/", 100))

    assert data["truncated"] is True
    assert data["text"].endswith("x" * 100)


@pytest.mark.parametrize(
    "response",
    [
        _FakeResponse({"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "x"}}),
        _FakeResponse({"error": "invalid_token"}, status_code=401),
        _FakeResponse({"jsonrpc": "2.0", "id": 1, "result": {"isError": True, "content": []}}),
        _FakeResponse(_scrape_result(markdown="")),
    ],
)
async def test_unbrowse_failures_return_none(monkeypatch, response) -> None:
    _patch_client(monkeypatch, response)

    assert await _tool()._fetch_unbrowse("https://example.com/", 50000) is None


async def test_unbrowse_skips_credential_urls(monkeypatch) -> None:
    calls = _patch_client(monkeypatch, _FakeResponse(_scrape_result(markdown="body")))

    assert await _tool()._fetch_unbrowse("https://example.com/f?token=secret", 50000) is None
    assert calls == []


def _patch_preflight(monkeypatch, *, carries_credentials: bool = False) -> None:
    class _Html:
        headers = {"content-type": "text/html"}

    async def fake_stream(client, url, headers=None):
        return _Html(), None, None, carries_credentials

    monkeypatch.setattr(web_module, "_stream_with_safe_redirects", fake_stream)
    monkeypatch.setattr(web_module, "_validate_url_safe", lambda url: (True, ""))


def _record_backends(monkeypatch, tool: WebFetchTool, unbrowse_result: str | None) -> list[str]:
    used: list[str] = []

    async def fake_unbrowse(url, max_chars):
        used.append("unbrowse")
        return unbrowse_result

    async def fake_jina(url, max_chars):
        used.append("jina")
        return "jina-result"

    async def fake_readability(url, extract_mode, max_chars):
        used.append("readability")
        return "readability-result"

    monkeypatch.setattr(tool, "_fetch_unbrowse", fake_unbrowse)
    monkeypatch.setattr(tool, "_fetch_jina", fake_jina)
    monkeypatch.setattr(tool, "_fetch_readability", fake_readability)
    return used


async def test_execute_prefers_unbrowse_when_key_configured(monkeypatch) -> None:
    tool = _tool()
    _patch_preflight(monkeypatch)
    used = _record_backends(monkeypatch, tool, "unbrowse-result")

    assert await tool.execute(url="https://example.com/") == "unbrowse-result"
    assert used == ["unbrowse"]


async def test_execute_falls_back_when_unbrowse_fails(monkeypatch) -> None:
    tool = _tool()
    _patch_preflight(monkeypatch)
    used = _record_backends(monkeypatch, tool, None)

    assert await tool.execute(url="https://example.com/") == "jina-result"
    assert used == ["unbrowse", "jina"]


async def test_execute_skips_unbrowse_without_key(monkeypatch) -> None:
    tool = WebFetchTool()
    _patch_preflight(monkeypatch)
    used = _record_backends(monkeypatch, tool, "unbrowse-result")

    assert await tool.execute(url="https://example.com/") == "jina-result"
    assert used == ["jina"]


async def test_execute_keeps_credential_redirects_local(monkeypatch) -> None:
    tool = _tool()
    _patch_preflight(monkeypatch, carries_credentials=True)
    used = _record_backends(monkeypatch, tool, "unbrowse-result")

    assert await tool.execute(url="https://example.com/") == "readability-result"
    assert used == ["readability"]
