from __future__ import annotations
from types import SimpleNamespace

import pytest

import nanobot.http_api.server as http_server_module
from nanobot.http_api.server import HttpApiServer


class _FakeRequest:
    def __init__(self, body, headers=None):
        self._body = body
        self.headers = headers or {}

    async def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class _FakeStreamResponse:
    def __init__(self, *args, **kwargs):
        self.status = kwargs.get("status", 200)
        self.headers = kwargs.get("headers", {})
        self.chunks: list[bytes] = []
        self.closed = False

    async def prepare(self, request):
        return self

    async def write(self, data: bytes):
        self.chunks.append(data)

    async def write_eof(self):
        self.closed = True


@pytest.mark.asyncio
async def test_chat_requires_bearer_token():
    agent = SimpleNamespace(process_direct=None)
    server = HttpApiServer(agent=agent, token="secret")

    resp = await server.handle_chat(_FakeRequest({"session_id": "u1", "message": "hi"}))

    assert resp.status == 401
    assert resp.text == '{"error": "unauthorized"}'


@pytest.mark.asyncio
async def test_chat_requires_session_and_message():
    agent = SimpleNamespace(process_direct=None)
    server = HttpApiServer(agent=agent)

    missing_session = await server.handle_chat(_FakeRequest({"message": "hi"}))
    missing_message = await server.handle_chat(_FakeRequest({"session_id": "u1"}))

    assert missing_session.status == 400
    assert missing_session.text == '{"error": "session_id_required"}'
    assert missing_message.status == 400
    assert missing_message.text == '{"error": "message_required"}'


@pytest.mark.asyncio
async def test_chat_uses_session_id_for_persistent_session_key():
    calls: list[dict] = []

    async def _process_direct(**kwargs):
        calls.append(kwargs)
        return "stored-reply"

    agent = SimpleNamespace(process_direct=_process_direct)
    server = HttpApiServer(agent=agent, token="secret")

    resp = await server.handle_chat(
        _FakeRequest(
            {"session_id": "user-1", "input": "remember this"},
            headers={"Authorization": "Bearer secret"},
        )
    )

    assert resp.status == 200
    assert resp.text == (
        '{"session_id": "user-1", "session_key": "http:user-1", "reply": "stored-reply"}'
    )
    assert calls == [
        {
            "content": "remember this",
            "session_key": "http:user-1",
            "channel": "http",
            "chat_id": "user-1",
        }
    ]


@pytest.mark.asyncio
async def test_chat_allows_explicit_channel_chat_id_and_session_key():
    calls: list[dict] = []

    async def _process_direct(**kwargs):
        calls.append(kwargs)
        return "ok"

    agent = SimpleNamespace(process_direct=_process_direct)
    server = HttpApiServer(agent=agent)

    resp = await server.handle_chat(
        _FakeRequest(
            {
                "session_id": "user-1",
                "message": "hi",
                "channel": "api",
                "chat_id": "chat-42",
                "session_key": "api:thread-9",
            }
        )
    )

    assert resp.status == 200
    assert calls == [
        {
            "content": "hi",
            "session_key": "api:thread-9",
            "channel": "api",
            "chat_id": "chat-42",
        }
    ]


@pytest.mark.asyncio
async def test_chat_with_stream_true_uses_sse(monkeypatch):
    async def _process_direct(**kwargs):
        await kwargs["on_progress"]("thinking")
        return "done"

    monkeypatch.setattr(http_server_module.web, "StreamResponse", _FakeStreamResponse)
    agent = SimpleNamespace(process_direct=_process_direct)
    server = HttpApiServer(agent=agent, token="secret")

    resp = await server.handle_chat(
        _FakeRequest(
            {"session_id": "user-1", "message": "hi", "stream": True},
            headers={"Authorization": "Bearer secret"},
        )
    )

    body = b"".join(resp.chunks).decode("utf-8")

    assert resp.status == 200
    assert "event: progress\ndata: {\"content\":\"thinking\",\"tool_hint\":false}" in body
    assert (
        "event: final\ndata: {\"session_id\":\"user-1\",\"session_key\":\"http:user-1\",\"reply\":\"done\"}" in body
    )
    assert "event: done\ndata: {}" in body


@pytest.mark.asyncio
async def test_chat_stream_emits_progress_and_final_events(monkeypatch):
    async def _process_direct(**kwargs):
        await kwargs["on_progress"]("thinking")
        await kwargs["on_progress"]("read_file(\"x\")", tool_hint=True)
        return "done"

    monkeypatch.setattr(http_server_module.web, "StreamResponse", _FakeStreamResponse)
    agent = SimpleNamespace(process_direct=_process_direct)
    server = HttpApiServer(agent=agent, token="secret")

    resp = await server.handle_chat_stream(
        _FakeRequest(
            {"session_id": "user-1", "message": "hi"},
            headers={"Authorization": "Bearer secret"},
        )
    )

    body = b"".join(resp.chunks).decode("utf-8")

    assert resp.status == 200
    assert "event: progress\ndata: {\"content\":\"thinking\",\"tool_hint\":false}" in body
    assert "event: progress\ndata: {\"content\":\"read_file(\\\"x\\\")\",\"tool_hint\":true}" in body
    assert (
        "event: final\ndata: {\"session_id\":\"user-1\",\"session_key\":\"http:user-1\",\"reply\":\"done\"}" in body
    )
    assert "event: done\ndata: {}" in body
    assert resp.closed is True


def test_format_sse_event_uses_compact_json():
    raw = HttpApiServer._format_sse_event("progress", {"content": "hi", "tool_hint": False})

    assert raw == b'event: progress\ndata: {"content":"hi","tool_hint":false}\n\n'
