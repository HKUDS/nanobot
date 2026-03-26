"""Tests for nanobot.tools.builtin.web — WebSearchTool & WebFetchTool."""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest

from nanobot.tools.builtin.web import (
    WebFetchTool,
    WebSearchTool,
    _check_ssrf_host,
    _normalize,
    _strip_tags,
    _url_cache,
    _validate_url,
)

# Module reference for resetting module-level state (_http_client) in fixtures.
_web_mod = sys.modules["nanobot.tools.builtin.web"]


@pytest.fixture(autouse=True)
def _reset_web_module_state():
    """Reset module-level shared state between tests to prevent cross-test pollution."""
    _url_cache.clear()
    _web_mod._http_client = None
    yield
    _url_cache.clear()
    _web_mod._http_client = None


# ---------------------------------------------------------------------------
# WebSearchTool
# ---------------------------------------------------------------------------


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

    monkeypatch.setattr("nanobot.tools.builtin.web.httpx.AsyncClient", lambda: FakeClient())

    tool = WebSearchTool(api_key="test-token")
    output = await tool.execute(query="nanobot", count=1)

    assert output.success
    assert "Results for: nanobot" in output.output
    assert seen["params"] == {"q": "nanobot", "count": 1}
    assert seen["headers"] == {
        "Accept": "application/json",
        "X-Subscription-Token": "test-token",
    }


async def test_web_search_no_key_and_error(monkeypatch: pytest.MonkeyPatch) -> None:
    tool = WebSearchTool(api_key="")
    no_key = await tool.execute(query="nanobot")
    assert not no_key.success

    class _ErrClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, *args, **kwargs):
            raise RuntimeError("network")

    tool2 = WebSearchTool(api_key="token")
    monkeypatch.setattr("nanobot.tools.builtin.web.httpx.AsyncClient", lambda: _ErrClient())
    err = await tool2.execute(query="nanobot")
    assert not err.success


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

    monkeypatch.setattr("nanobot.tools.builtin.web.httpx.AsyncClient", lambda: _Client())
    tool = WebSearchTool(api_key="token")
    out = await tool.execute(query="nanobot")
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
# SSRF protection tests (SEC-02, T-C1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://127.0.0.1:8080/secret",
        "http://0.0.0.0/",
        "http://10.0.0.1/",
        "http://10.255.255.255/",
        "http://172.16.0.1/",
        "http://172.31.255.255/",
        "http://192.168.1.1/",
        "http://169.254.169.254/",  # AWS/GCP/Azure IMDS
        "http://169.254.169.254/latest/meta-data/iam/security-credentials/",
        "http://169.254.0.1/",
        "http://[::1]/",  # IPv6 loopback
        "http://[fc00::1]/",  # IPv6 ULA (private)
    ],
)
def test_validate_url_blocks_private_ips(url: str) -> None:
    """_validate_url must reject IP literals that are private/loopback/link-local (SEC-02)."""
    valid, err = _validate_url(url)
    assert not valid, f"Expected {url!r} to be blocked, but was allowed"
    assert "private" in err.lower() or "not permitted" in err.lower() or "metadata" in err.lower()


@pytest.mark.parametrize(
    "url",
    [
        "http://metadata.google.internal/",
        "http://metadata.azure.com/",
        "http://100.100.100.200/",  # Alibaba Cloud metadata
    ],
)
def test_validate_url_blocks_cloud_metadata_hosts(url: str) -> None:
    """_validate_url must block known cloud metadata service hostnames (SEC-02)."""
    valid, err = _validate_url(url)
    assert not valid, f"Expected {url!r} to be blocked"
    assert "not permitted" in err.lower() or "metadata" in err.lower()


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/",
        "https://api.github.com/",
        "http://httpbin.org/get",
    ],
)
def test_validate_url_allows_public_urls(url: str) -> None:
    """_validate_url must allow legitimate public URLs."""
    valid, _ = _validate_url(url)
    assert valid, f"Expected {url!r} to be allowed"


async def test_check_ssrf_host_blocks_private_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    """_check_ssrf_host must block hosts that DNS-resolve to private addresses (SEC-02)."""
    import asyncio

    async def _fake_getaddrinfo(host: str, port: object, **kwargs: object) -> list:  # type: ignore[override]
        return [(None, None, None, None, ("10.0.0.1", 0))]

    monkeypatch.setattr(asyncio.get_event_loop(), "getaddrinfo", _fake_getaddrinfo)
    result = await _check_ssrf_host("evil-internal.example.com")
    assert result is not None
    assert "private" in result.lower() or "10.0.0.1" in result


async def test_web_fetch_blocks_private_ip_url() -> None:
    """WebFetchTool.execute must reject private IP URLs before making any HTTP request (SEC-02)."""
    tool = WebFetchTool()
    result = await tool.execute(url="http://192.168.1.1/admin")
    assert not result.success
    payload = json.loads(result.output)
    assert "private" in payload["error"].lower() or "not permitted" in payload["error"].lower()


# ---------------------------------------------------------------------------
# WebFetchTool
# ---------------------------------------------------------------------------


async def test_web_fetch_invalid_url() -> None:
    tool = WebFetchTool()
    out = await tool.execute(url="ftp://invalid")
    assert not out.success
    payload = json.loads(out.output)
    assert "validation" in payload["error"].lower()


async def test_web_fetch_json_and_raw(monkeypatch: pytest.MonkeyPatch) -> None:
    _url_cache.clear()

    class _Resp:
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
        "nanobot.tools.builtin.web.httpx.AsyncClient", lambda **kwargs: _Client(responses)
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

    monkeypatch.setattr("nanobot.tools.builtin.web.httpx.AsyncClient", lambda **kwargs: _Client())
    monkeypatch.setitem(__import__("sys").modules, "readability", SimpleNamespace(Document=_Doc))

    tool = WebFetchTool(max_chars=20)
    out = await tool.execute(url="https://example.com", extractMode="markdown")
    assert out.success
    payload = json.loads(out.output)
    # Compact output for small responses may omit extractor; verify content present
    assert "text" in payload

    class _BadClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, *args, **kwargs):
            raise RuntimeError("boom")

    monkeypatch.setattr(
        "nanobot.tools.builtin.web.httpx.AsyncClient", lambda **kwargs: _BadClient()
    )
    _url_cache.clear()  # clear cached success for same URL
    _web_mod._http_client = None  # force _BadClient to be picked up
    fail = await tool.execute(url="https://example.com")
    assert not fail.success


# ---------------------------------------------------------------------------
# WebFetchTool: userAgent parameter & cacheable flag
# ---------------------------------------------------------------------------


def test_web_fetch_cache_without_summary() -> None:
    """WebFetchTool caches for retrieval but does not summarize away the data."""
    tool = WebFetchTool()
    assert tool.cacheable is True
    assert tool.summarize is False


async def test_web_fetch_bot_user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    """When userAgent='bot', the request should use the bot UA string."""
    _url_cache.clear()

    captured_headers: dict[str, str] = {}

    class _Resp:
        headers = {"content-type": "text/plain"}
        text = "Montreal: +5°C"
        url = "https://wttr.in/Montreal?format=3"
        status_code = 200

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

    monkeypatch.setattr("nanobot.tools.builtin.web.httpx.AsyncClient", lambda **kwargs: _Client())

    tool = WebFetchTool()
    result = await tool.execute(url="https://wttr.in/Montreal?format=3", userAgent="bot")
    assert result.success
    assert "nanobot/" in captured_headers["User-Agent"]

    # Verify content is passed through (not summarised)
    payload = json.loads(result.output)
    assert payload["text"] == "Montreal: +5°C"


async def test_web_fetch_browser_user_agent_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default userAgent should use the browser UA string."""
    _url_cache.clear()

    captured_headers: dict[str, str] = {}

    class _Resp:
        headers = {"content-type": "text/plain"}
        text = "hello"
        url = "https://example.com"
        status_code = 200

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

    monkeypatch.setattr("nanobot.tools.builtin.web.httpx.AsyncClient", lambda **kwargs: _Client())

    tool = WebFetchTool()
    result = await tool.execute(url="https://example.com")
    assert result.success
    assert "Mozilla" in captured_headers["User-Agent"]
