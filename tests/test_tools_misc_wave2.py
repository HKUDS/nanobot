from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from nanobot.agent.tools.cron import CronTool
from nanobot.agent.tools.message import MessageTool
from nanobot.agent.tools.web import (
    WebFetchTool,
    WebSearchTool,
    _normalize,
    _strip_tags,
    _validate_url,
)


class _FakeCron:
    def __init__(self) -> None:
        self.jobs: dict[str, SimpleNamespace] = {}

    def add_job(self, **kwargs):
        job = SimpleNamespace(id="job-1", name=kwargs["name"], schedule=kwargs["schedule"])
        self.jobs[job.id] = job
        return job

    def list_jobs(self):
        return list(self.jobs.values())

    def remove_job(self, job_id: str) -> bool:
        return self.jobs.pop(job_id, None) is not None


def test_cron_tool_invalid_and_remove_paths() -> None:
    tool = CronTool(_FakeCron())

    bad_msg = tool._add_job(message="", every_seconds=1, cron_expr=None, tz=None, at=None)
    assert not bad_msg.success

    tool.set_context("telegram", "123")
    bad_tz = tool._add_job(message="hello", every_seconds=None, cron_expr=None, tz="UTC", at=None)
    assert not bad_tz.success

    missing_schedule = tool._add_job(
        message="hello", every_seconds=None, cron_expr=None, tz=None, at=None
    )
    assert not missing_schedule.success

    assert not tool._remove_job(None).success
    assert not tool._remove_job("missing").success


def test_cron_tool_add_list_remove_success() -> None:
    tool = CronTool(_FakeCron())
    tool.set_context("telegram", "123")

    created = tool._add_job("hello", every_seconds=10, cron_expr=None, tz=None, at=None)
    assert created.success

    listed = tool._list_jobs()
    assert listed.success
    assert "Scheduled jobs" in listed.output

    removed = tool._remove_job("job-1")
    assert removed.success


@pytest.mark.asyncio
async def test_cron_tool_execute_dispatch() -> None:
    tool = CronTool(_FakeCron())
    tool.set_context("telegram", "123")

    out = await tool.execute(action="add", message="ping", every_seconds=1)
    assert out.success

    listed = await tool.execute(action="list")
    assert listed.success

    rm = await tool.execute(action="remove", job_id="job-1")
    assert rm.success

    unknown = await tool.execute(action="wat")
    assert not unknown.success


@pytest.mark.asyncio
async def test_message_tool_paths() -> None:
    tool = MessageTool()

    missing_target = await tool.execute(content="hello")
    assert not missing_target.success

    tool.set_context("telegram", "123")
    no_callback = await tool.execute(content="hello")
    assert not no_callback.success

    sent: list[object] = []

    async def _send(msg):
        sent.append(msg)

    tool.set_send_callback(_send)
    tool.start_turn()
    ok = await tool.execute(content="hello", media=["a.png"])
    assert ok.success
    assert "attachments" in ok.output
    assert len(sent) == 1


@pytest.mark.asyncio
async def test_message_tool_send_error() -> None:
    async def _bad(_msg):
        raise RuntimeError("boom")

    tool = MessageTool(send_callback=_bad, default_channel="telegram", default_chat_id="123")
    out = await tool.execute(content="hello")
    assert not out.success
    assert "Error sending message" in out.output


def test_web_helpers() -> None:
    assert _strip_tags("<h1>x</h1><script>a=1</script>") == "x"
    assert _normalize("a   b\n\n\n\nc") == "a b\n\nc"
    assert _validate_url("https://example.com")[0]
    assert not _validate_url("ftp://x")[0]


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


@pytest.mark.asyncio
async def test_web_fetch_invalid_url() -> None:
    tool = WebFetchTool()
    out = await tool.execute(url="ftp://invalid")
    assert not out.success
    payload = json.loads(out.output)
    assert "validation" in payload["error"].lower()


@pytest.mark.asyncio
async def test_web_fetch_json_and_raw(monkeypatch: pytest.MonkeyPatch) -> None:
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
        "nanobot.agent.tools.web.httpx.AsyncClient", lambda **kwargs: _Client(responses)
    )

    tool = WebFetchTool(max_chars=1000)
    json_out = await tool.execute(url="https://example.com/a")
    raw_out = await tool.execute(url="https://example.com/b")

    assert json_out.success and raw_out.success
    assert json.loads(json_out.output)["extractor"] == "json"
    assert json.loads(raw_out.output)["extractor"] == "raw"


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

    tool = WebFetchTool(max_chars=20)
    out = await tool.execute(url="https://example.com", extractMode="markdown")
    assert out.success
    payload = json.loads(out.output)
    assert payload["extractor"] == "readability"

    class _BadClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, *args, **kwargs):
            raise RuntimeError("boom")

    monkeypatch.setattr("nanobot.agent.tools.web.httpx.AsyncClient", lambda **kwargs: _BadClient())
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


@pytest.mark.asyncio
async def test_web_fetch_bot_user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    """When userAgent='bot', the request should use the bot UA string."""
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

    monkeypatch.setattr("nanobot.agent.tools.web.httpx.AsyncClient", lambda **kwargs: _Client())

    tool = WebFetchTool()
    result = await tool.execute(url="https://example.com")
    assert result.success
    assert "Mozilla" in captured_headers["User-Agent"]
