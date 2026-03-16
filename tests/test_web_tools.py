"""Tests for nanobot.agent.tools.web — WebSearchTool & WebFetchTool."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import nanobot.agent.tools.web as _web_mod
)
WebFetchTool = _web_mod.WebFetchTool
WebSearchTool = _web_mod.WebSearchTool
_normalize = _web_mod._normalize
_strip_tags = _web_mod._strip_tags
    _url_cache,
    _url_cache,
_validate_url = _web_mod._validate_url


# ---------------------------------------------------------------------------
# WebSearchTool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_web_search_uses_configured_api_key(monkeypatch) -> None:
    seen: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "web": {
                    "results": [
                        {
                            "title": "Result",
                            "url": "https://example.com",
                            "description": "Snippet",
                        }
                    ]
                }
            }

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, _url: str, *, params: dict, headers: dict, timeout: float):
            seen["params"] = params
            seen["headers"] = headers
            seen["timeout"] = timeout
            return FakeResponse()

    monkeypatch.setattr("nanobot.agent.tools.web.httpx.AsyncClient", lambda: FakeClient())

    tool = WebSearchTool(api_key="test-token")
    output = await tool.execute("nanobot", count=1)

    assert output.success
    assert "Results for: nanobot" in output.output
    assert seen["params"] == {"q": "nanobot", "count": 1}
    assert seen["headers"] == {
        "Accept": "application/json",
        "X-Subscription-Token": "test-token",
    }


@pytest.mark.asyncio
async def test_web_search_no_key_and_error(monkeypatch: pytest.MonkeyPatch) -> None:
    tool = WebSearchTool(api_key="")
    no_key = await tool.execute("nanobot")
    assert not no_key.success

    class _ErrClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, *args, **kwargs):
            raise RuntimeError("network")

    tool2 = WebSearchTool(api_key="token")
    monkeypatch.setattr("nanobot.agent.tools.web.httpx.AsyncClient", lambda: _ErrClient())
    err = await tool2.execute("nanobot")
    assert not err.success


@pytest.mark.asyncio
async def test_web_search_empty_results(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"web": {"results": []}}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, *args, **kwargs):
            return _Resp()

    monkeypatch.setattr("nanobot.agent.tools.web.httpx.AsyncClient", lambda: _Client())
    tool = WebSearchTool(api_key="token")
    out = await tool.execute("nanobot")
    assert out.success
    assert "No results" in out.output


# ---------------------------------------------------------------------------
# Web helper functions
# ---------------------------------------------------------------------------


def test_web_helpers() -> None:
    assert _strip_tags("<h1>x</h1><script>a=1</script>") == "x"
    assert _normalize("a   b\n\n\n\nc") == "a b\n\nc"
    assert _validate_url("https://example.com")[0]
    assert not _validate_url("ftp://x")[0]


# ---------------------------------------------------------------------------
# WebFetchTool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_web_fetch_invalid_url() -> None:
    tool = WebFetchTool()
    out = await tool.execute(url="ftp://invalid")
    assert not out.success
    payload = json.loads(out.output)
    assert "validation" in payload["error"].lower()


    _url_cache.clear()
    _url_cache.clear()
            self.headers = {"content-type": ctype}
        def __init__(self, ctype: str, text: str, payload: dict | None = None):
            self.headers = {"content-type": ctype}
            self.text = text
            self.url = "https://example.com/final"
            self.status_code = 200
            self._payload = payload or {}

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class _Client:
        def __init__(self, responses):
            self._responses = responses

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, *args, **kwargs):
            return self._responses.pop(0)

    responses = [
        _Resp("application/json", "", {"ok": True}),
        _Resp("text/plain", "hello raw"),
    ]
    monkeypatch.setattr(
        "nanobot.agent.tools.web.httpx.AsyncClient", lambda **kwargs: _Client(responses)
    )

    tool = WebFetchTool(max_chars=1000)
    json_out = await tool.execute(url="https://example.com/a")
    raw_out = await tool.execute(url="https://example.com/b")

    assert json_out.success and raw_out.success
    json_payload = json.loads(json_out.output)
    raw_payload = json.loads(raw_out.output)
    # Compact output may omit extractor; verify content instead
    assert "true" in json_payload["text"]  # pretty-printed JSON: {"ok": true}
    assert raw_payload["text"] == "hello raw"


@pytest.mark.asyncio
async def test_web_fetch_html_and_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Doc:
        def __init__(self, _html: str):
            pass

        def summary(self):
            return "<h1>T</h1><p>Hello</p>"

        def title(self):
            return "Title"

    class _Resp:
        headers = {"content-type": "text/html"}
        text = "<html><body>Hello</body></html>"
        url = "https://example.com/final"
        status_code = 200

        def raise_for_status(self):
            return None

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, *args, **kwargs):
            return _Resp()

    monkeypatch.setattr("nanobot.agent.tools.web.httpx.AsyncClient", lambda **kwargs: _Client())
    monkeypatch.setitem(__import__("sys").modules, "readability", SimpleNamespace(Document=_Doc))

    _url_cache.clear()
    _url_cache.clear()
    out = await tool.execute(url="https://example.com", extractMode="markdown")
    # Compact output for small responses may omit extractor; verify content present
    assert "text" in payload

    class _BadClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, *args, **kwargs):
            raise RuntimeError("boom")

    monkeypatch.setattr("nanobot.agent.tools.web.httpx.AsyncClient", lambda **kwargs: _BadClient())
    _web_mod._url_cache.clear()  # clear cached success for same URL
    fail = await tool.execute(url="https://example.com")
    assert not fail.success

    _url_cache.clear()  # clear cached success for same URL
# ---------------------------------------------------------------------------
# WebFetchTool: userAgent parameter & cacheable flag
# ---------------------------------------------------------------------------


def test_web_fetch_cache_without_summary() -> None:
    """WebFetchTool caches for retrieval but does not summarize away the data."""
    tool = WebFetchTool()
    assert tool.cacheable is True
    assert tool.summarize is False


@pytest.mark.asyncio
async def test_web_fetch_bot_user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    """When userAgent='bot', the request should use the bot UA string."""
    _url_cache.clear()
    _url_cache.clear()
    captured_headers: dict[str, str] = {}
        headers = {"content-type": "text/plain"}
    _url_cache.clear()
        url = "https://wttr.in/Montreal?format=3"
        def raise_for_status(self) -> None:
            return None

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url: str, **kwargs):
            captured_headers.update(kwargs.get("headers", {}))
            return _Resp()

    monkeypatch.setattr("nanobot.agent.tools.web.httpx.AsyncClient", lambda **kwargs: _Client())

    tool = WebFetchTool()
    result = await tool.execute(url="https://wttr.in/Montreal?format=3", userAgent="bot")
    assert result.success
    assert "nanobot/" in captured_headers["User-Agent"]

    # Verify content is passed through (not summarised)
    payload = json.loads(result.output)
    assert payload["text"] == "Montreal: +5°C"


@pytest.mark.asyncio
async def test_web_fetch_browser_user_agent_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default userAgent should use the browser UA string."""
    _url_cache.clear()

    captured_headers: dict[str, str] = {}
    _url_cache.clear()
    class _Resp:
        url = "https://example.com"
        status_code = 200

    _url_cache.clear()
            return None
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url: str, **kwargs):
            captured_headers.update(kwargs.get("headers", {}))
            return _Resp()

    monkeypatch.setattr("nanobot.agent.tools.web.httpx.AsyncClient", lambda **kwargs: _Client())

    tool = WebFetchTool()
    result = await tool.execute(url="https://example.com")
    assert result.success
    assert "Mozilla" in captured_headers["User-Agent"]
