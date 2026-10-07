"""Exercise the Codex provider against local Responses WebSocket and SSE peers."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest
from aiohttp import web
from pypdf import PdfWriter

from nanobot.agent.loop import AgentLoop
from nanobot.agent.model_runtime import ModelRuntimeResolver
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMResponse, ProviderCallContext
from nanobot.providers.factory import ProviderSnapshot
from nanobot.providers.openai_codex_provider import OpenAICodexProvider
from nanobot.utils.llm_runtime import LLMRuntime


@dataclass
class _Peer:
    socket: web.WebSocketResponse
    headers: dict[str, str]
    requests: list[dict[str, Any]] = field(default_factory=list)
    closed: asyncio.Event = field(default_factory=asyncio.Event)


def _events(response_id: str, output: list[dict[str, Any]] | None = None):
    if output is None:
        output = [{
            "type": "message", "id": f"msg_{response_id}", "role": "assistant",
            "content": [{"type": "output_text", "text": "answer"}],
        }]
    events = []
    for index, item in enumerate(output):
        if item["type"] == "message":
            for block in item["content"]:
                events.append({"type": "response.output_text.delta", "delta": block["text"]})
        events.append({"type": "response.output_item.done", "output_index": index, "item": item})
    events.append({"type": "response.completed", "response": {
        "id": response_id, "status": "completed", "output": output,
        "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
    }})
    return events


async def _complete(peer: _Peer, response_id: str, output=None):
    for event in _events(response_id, output):
        await peer.socket.send_json(event)


class _ResponsesServer:
    def __init__(self):
        self.peers: list[_Peer] = []
        self.requests: list[tuple[_Peer, dict[str, Any]]] = []
        self.http_requests: list[dict[str, Any]] = []
        self.upgrade_attempts = 0
        self.reject_upgrade = False
        self.upgrade_status = 426
        self.upgrade_headers = []
        self.respond = self._respond

    async def _respond(self, peer, _body):
        await _complete(peer, f"resp_{len(self.requests)}")

    async def handle(self, request):
        if request.method == "POST":
            body = await request.json()
            self.http_requests.append(body)
            data = "".join(f"data: {json.dumps(event)}\n\n" for event in _events("resp_http"))
            return web.Response(text=data, content_type="text/event-stream")
        self.upgrade_attempts += 1
        if self.reject_upgrade:
            return web.json_response(
                {"error": {"code": "token_revoked", "message": "PRIVATE INPUT"}},
                status=self.upgrade_status, headers=self.upgrade_headers,
            )
        socket = web.WebSocketResponse(max_msg_size=0)
        await socket.prepare(request)
        peer = _Peer(socket, dict(request.headers))
        self.peers.append(peer)
        try:
            async for message in socket:
                if message.type != web.WSMsgType.TEXT:
                    continue
                body = json.loads(message.data)
                peer.requests.append(body)
                self.requests.append((peer, body))
                await self.respond(peer, body)
        finally:
            peer.closed.set()
        return socket


@pytest.fixture
async def codex_peer(monkeypatch):
    server = _ResponsesServer()
    app = web.Application()
    app.router.add_route("*", "/responses", server.handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    url = f"http://127.0.0.1:{runner.addresses[0][1]}/responses"
    monkeypatch.setattr("nanobot.providers.openai_codex_provider.DEFAULT_CODEX_URL", url)
    token = SimpleNamespace(account_id="acct", access="test-token")
    monkeypatch.setattr("nanobot.providers.openai_codex_provider.get_codex_token", lambda **_: token)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    provider = OpenAICodexProvider(default_model="gpt-6-astra")
    try:
        yield provider, server, token
    finally:
        await provider.aclose()
        await runner.cleanup()


def _messages(text="hello", instructions="You are nanobot."):
    return [{"role": "system", "content": instructions}, {"role": "user", "content": text}]


def _context(result: LLMResponse | None = None, pending=None, session="session-a", **kwargs):
    if result is None:
        state = None
    else:
        assert result.provider_state is not None
        state = result.provider_state.with_pending_messages(
            pending if pending is not None else [{"role": "user", "content": "next"}],
        )
    return ProviderCallContext(session_id=session, conversation_state=state, **kwargs)


async def test_gateway_continues_image_then_pdf_attachment_turn(codex_peer, tmp_path):
    provider, server, _ = codex_peer
    image = tmp_path / "image.png"
    image.write_bytes(base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aP1kAAAAASUVORK5CYII="
    ))
    pdf = tmp_path / "report.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(pdf)
    agent = AgentLoop(
        bus=MessageBus(), provider=provider, workspace=tmp_path,
        model=provider.get_default_model(), context_window_tokens=128_000,
    )
    try:
        first = await agent.process_direct(
            "Describe this image.", session_key="websocket:attachments",
            channel="websocket", chat_id="attachments", media=[str(image)],
        )
        second = await agent.process_direct(
            "Summarize this PDF.", session_key="websocket:attachments",
            channel="websocket", chat_id="attachments", media=[str(pdf)],
        )
        assert first.content == second.content == "answer"
        assert len(server.peers) == 1
        assert len(server.requests) == 2
        initial, continued = [body for _, body in server.requests]
        assert "input_image" in json.dumps(initial["input"])
        assert continued["previous_response_id"] == "resp_1"
        assert "input_image" not in json.dumps(continued["input"])
        assert f"[Attachment: {pdf}]" in continued["input"][0]["content"][0]["text"]
        assert not server.http_requests
    finally:
        await agent.aclose()
    await asyncio.wait_for(server.peers[0].closed.wait(), 2)


async def test_codex_continues_attachment_and_tool_turns_without_replaying_history(codex_peer):
    provider, server, _ = codex_peer
    reasoning = {
        "type": "reasoning", "id": "rs_1", "status": "completed",
        "encrypted_content": "opaque-reasoning", "summary": [{"type": "summary_text", "text": "thinking"}],
    }
    call = {"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": "read_file", "arguments": '{"path":"report.pdf"}'}

    async def respond(peer, _body):
        if len(server.requests) == 1:
            await _complete(peer, "resp_1", [reasoning, call])
        else:
            await _complete(peer, f"resp_{len(server.requests)}")

    server.respond = respond
    image = "data:image/png;base64," + "A" * 100_000
    messages = _messages([{"type": "image_url", "image_url": {"url": image}}, {"type": "text", "text": "Read this image."}])
    thinking = []
    tool_progress = []

    async def on_thinking(delta):
        thinking.append(delta)

    async def on_tool(delta):
        tool_progress.append(delta)

    first = await provider.chat_stream(
        messages, provider_context=_context(), on_thinking_delta=on_thinking,
        on_tool_call_delta=on_tool,
    )
    assert first.finish_reason == "stop"
    assert first.tool_calls[0].id == "call_1|fc_1"
    assert thinking == ["thinking"]
    assert tool_progress[0]["call_id"] == "call_1"
    assert first.usage.total_tokens == 15
    tool_output = [{"role": "tool", "tool_call_id": first.tool_calls[0].id, "content": "PDF extracted text"}]
    second = await provider.chat(_messages(), provider_context=_context(first, tool_output))
    third = await provider.chat(
        _messages("Summarize [Attachment: /workspace/report.pdf]"),
        provider_context=_context(second, [{"role": "user", "content": "Summarize [Attachment: /workspace/report.pdf]"}]),
    )
    assert third.content == "answer"
    assert len(server.peers) == 1
    bodies = [body for _, body in server.requests]
    assert bodies[0]["type"] == "response.create"
    assert bodies[0]["store"] is False
    assert "stream" not in bodies[0]
    assert image in json.dumps(bodies[0])
    assert bodies[1]["previous_response_id"] == "resp_1"
    assert bodies[1]["input"] == [{"type": "function_call_output", "call_id": "call_1", "output": "PDF extracted text"}]
    assert bodies[2]["previous_response_id"] == "resp_2"
    assert len(bodies[2]["input"]) == 1
    assert image not in json.dumps(bodies[1:])
    assert "opaque-reasoning" not in json.dumps(bodies[1:])
    assert image in json.dumps(third.provider_state.to_private_record())
    assert "opaque-reasoning" in json.dumps(third.provider_state.to_private_record())
    assert "previous_response_id" not in json.dumps(third.provider_state.to_private_record())
    headers = server.peers[0].headers
    assert headers["OpenAI-Beta"] == "responses_websockets=2026-02-06"
    assert headers["Authorization"] == "Bearer test-token"
    assert headers["chatgpt-account-id"] == "acct"
    assert headers["session-id"] == hashlib.sha256(b"session-a").hexdigest()


async def test_codex_isolates_concurrent_sessions(codex_peer):
    provider, server, _ = codex_peer
    first_a, first_b = await asyncio.gather(*(
        provider.chat(_messages(session), provider_context=_context(session=session))
        for session in ("session-a", "session-b")
    ))
    await asyncio.gather(*(
        provider.chat(_messages("next"), provider_context=_context(result, session=session))
        for result, session in ((first_a, "session-a"), (first_b, "session-b"))
    ))
    assert len(server.peers) == 2
    assert all(len(peer.requests) == 2 for peer in server.peers)
    assert server.peers[0].headers["session-id"] != server.peers[1].headers["session-id"]
    for peer in server.peers:
        assert "previous_response_id" not in peer.requests[0]
        assert peer.requests[1]["previous_response_id"] in {"resp_1", "resp_2"}
        assert len(peer.requests[1]["input"]) == 1
    assert server.peers[0].requests[1]["previous_response_id"] != server.peers[1].requests[1]["previous_response_id"]


@pytest.mark.parametrize("change", ["instructions", "tools", "model", "history"])
async def test_codex_replays_full_input_when_context_changes(codex_peer, change):
    provider, server, _ = codex_peer
    first = await provider.chat(_messages(), provider_context=_context())
    messages = _messages("next")
    context = _context(first)
    kwargs = {}
    if change == "instructions":
        messages = _messages("next", instructions="Use a different system prompt.")
    elif change == "tools":
        kwargs["tools"] = [{"type": "function", "function": {"name": "read_file", "parameters": {"type": "object"}}}]
    elif change == "model":
        kwargs["model"] = "gpt-6-luna"
        messages = [*_messages(), {"role": "assistant", "content": "answer"}, {"role": "user", "content": "next"}]
    else:
        context = _context()
        messages = _messages("Edited previous message")
    result = await provider.chat(messages, provider_context=context, **kwargs)
    assert result.content == "answer"
    body = server.requests[-1][1]
    assert "previous_response_id" not in body
    assert len(body["input"]) == (1 if change == "history" else 3)
    assert not server.http_requests


async def test_codex_reconnects_after_auth_change(codex_peer):
    provider, server, token = codex_peer
    first = await provider.chat(_messages(), provider_context=_context())
    token.account_id = "other-account"
    token.access = "other-token"
    result = await provider.chat(_messages("next"), provider_context=_context(first))
    assert result.content == "answer"
    assert len(server.peers) == 2
    assert server.peers[0].closed.is_set()
    assert server.peers[1].headers["Authorization"] == "Bearer other-token"
    assert server.peers[1].headers["chatgpt-account-id"] == "other-account"
    assert "previous_response_id" not in server.requests[-1][1]
    assert len(server.requests[-1][1]["input"]) == 3


async def test_codex_reconnects_with_durable_history_after_disconnect(codex_peer):
    provider, server, _ = codex_peer

    async def respond(peer, _body):
        await _complete(peer, f"resp_{len(server.requests)}")
        if len(server.requests) == 1:
            await peer.socket.close()

    server.respond = respond
    first = await provider.chat(_messages(), provider_context=_context())
    await asyncio.wait_for(server.peers[0].closed.wait(), 2)
    result = await provider.chat(_messages("next"), provider_context=_context(first))
    assert result.content == "answer"
    assert len(server.peers) == 2
    assert "previous_response_id" not in server.requests[-1][1]
    assert len(server.requests[-1][1]["input"]) == 3


@pytest.mark.parametrize("code", ["previous_response_not_found", "websocket_connection_limit_reached"])
async def test_codex_recovers_expired_connection_cache_once(codex_peer, code):
    provider, server, _ = codex_peer

    async def respond(peer, _body):
        if len(server.requests) == 2:
            await peer.socket.send_json({"type": "error", "status": 400, "error": {"code": code, "message": "expired"}})
        else:
            await _complete(peer, f"resp_{len(server.requests)}")

    server.respond = respond
    first = await provider.chat(_messages(), provider_context=_context())
    result = await provider.chat(_messages("next"), provider_context=_context(first))
    assert result.content == "answer"
    assert len(server.peers) == 2
    assert len(server.requests) == 3
    assert server.requests[1][1]["previous_response_id"] == "resp_1"
    assert len(server.requests[1][1]["input"]) == 1
    assert "previous_response_id" not in server.requests[2][1]
    assert len(server.requests[2][1]["input"]) == 3
    assert not server.http_requests


async def test_codex_cancelled_stream_closes_socket_before_next_request(codex_peer):
    provider, server, _ = codex_peer
    delta_received = asyncio.Event()

    async def respond(peer, _body):
        if len(server.requests) == 2:
            await peer.socket.send_json({"type": "response.output_text.delta", "delta": "partial"})
        else:
            await _complete(peer, f"resp_{len(server.requests)}")

    async def on_delta(_delta):
        delta_received.set()

    server.respond = respond
    first = await provider.chat(_messages(), provider_context=_context())
    task = asyncio.create_task(provider.chat_stream(
        _messages("next"), provider_context=_context(first), on_content_delta=on_delta,
    ))
    await asyncio.wait_for(delta_received.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.wait_for(server.peers[0].closed.wait(), 2)
    result = await provider.chat(_messages("next"), provider_context=_context(first))
    assert result.content == "answer"
    assert len(server.peers) == 2
    assert "previous_response_id" not in server.requests[-1][1]
    assert len(server.requests[-1][1]["input"]) == 3


async def test_codex_unsupported_upgrade_uses_sticky_http_full_replay(codex_peer):
    provider, server, _ = codex_peer
    server.reject_upgrade = True
    first = await provider.chat(_messages(), provider_context=_context())
    second = await provider.chat(_messages("next"), provider_context=_context(first))
    assert first.content == second.content == "answer"
    assert server.upgrade_attempts == 1
    assert len(server.http_requests) == 2
    assert len(server.http_requests[1]["input"]) == 3
    assert all("previous_response_id" not in body for body in server.http_requests)


async def test_codex_rejected_handshake_accepts_repeated_response_headers(codex_peer):
    provider, server, _ = codex_peer
    server.reject_upgrade = True
    server.upgrade_status = 401
    server.upgrade_headers = [("Set-Cookie", "first=fixture"), ("Set-Cookie", "second=fixture")]
    result = await provider.chat(_messages(), provider_context=_context())
    assert result.finish_reason == "error"
    assert result.error_status_code == 401
    assert result.error_code == "token_revoked"
    assert result.error_should_retry is False
    assert "PRIVATE INPUT" not in result.content
    assert not server.http_requests


@pytest.mark.parametrize("code, retry", [("insufficient_quota", False), ("rate_limit_exceeded", True)])
async def test_codex_websocket_errors_preserve_retry_policy_without_echoes(codex_peer, code, retry):
    provider, server, _ = codex_peer

    async def respond(peer, _body):
        await peer.socket.send_json({
            "type": "error", "status": 429, "headers": {"Retry-After": "2"},
            "error": {"type": code, "code": code, "message": "PRIVATE INPUT test-token"},
        })

    server.respond = respond
    result = await provider.chat(_messages(), provider_context=_context())
    assert result.finish_reason == "error"
    assert result.error_kind == "http"
    assert result.error_status_code == 429
    assert result.error_code == code
    assert result.error_should_retry is retry
    assert result.error_retry_after_s == 2
    assert "PRIVATE INPUT" not in result.content
    assert "test-token" not in result.content
    assert not server.http_requests


async def test_codex_interrupted_stream_does_not_replay_accepted_request(codex_peer):
    provider, server, _ = codex_peer
    deltas = []

    async def respond(peer, _body):
        await peer.socket.send_json({"type": "response.output_text.delta", "delta": "partial"})
        await peer.socket.close(code=1011, message=b"PRIVATE INPUT")

    async def on_delta(delta):
        deltas.append(delta)

    server.respond = respond
    result = await provider.chat_stream(_messages(), provider_context=_context(), on_content_delta=on_delta)
    assert result.finish_reason == "error"
    assert result.error_kind == "connection"
    assert result.error_should_retry is True
    assert result.provider_state is None
    assert deltas == ["partial"]
    assert len(server.requests) == 1
    assert not server.http_requests
    assert "PRIVATE INPUT" not in result.content


@pytest.mark.parametrize("event", [
    {"type": "response.failed", "response": {"error": {"code": "server_error", "message": "PRIVATE INPUT"}}},
    {"type": "error", "status_code": 503, "error": {"code": "server_error", "message": "PRIVATE INPUT"}},
])
async def test_codex_failed_response_envelopes_keep_server_errors_retryable(codex_peer, event):
    provider, server, _ = codex_peer

    async def respond(peer, _body):
        await peer.socket.send_json(event)

    server.respond = respond
    result = await provider.chat(_messages(), provider_context=_context())
    assert result.finish_reason == "error"
    assert result.error_code == "server_error"
    assert result.error_should_retry is True
    assert "PRIVATE INPUT" not in result.content
    assert not server.http_requests


async def test_codex_compaction_restarts_continuation_from_rewritten_history(codex_peer):
    provider, server, _ = codex_peer
    compaction = {"type": "compaction", "id": "cmp_1", "encrypted_content": "compacted"}

    async def respond(peer, _body):
        await _complete(peer, f"resp_{len(server.requests)}", [compaction] if len(server.requests) == 2 else None)

    server.respond = respond
    first = await provider.chat(_messages(), provider_context=_context())
    result = await provider.chat(
        _messages("next"),
        provider_context=_context(first, context_window_tokens=4_000, compaction_input_budget=10_000),
        max_tokens=10,
    )
    assert result.content == "answer"
    assert result.provider_compaction_applied
    assert len(server.requests) == 3
    assert server.requests[1][1]["previous_response_id"] == "resp_1"
    assert server.requests[1][1]["input"] == [{"type": "compaction_trigger"}]
    assert "previous_response_id" not in server.requests[2][1]
    assert any(item.get("type") == "compaction" for item in server.requests[2][1]["input"])


async def test_codex_inline_compaction_starts_next_request_with_compacted_state(codex_peer):
    provider, server, _ = codex_peer
    compaction = {"type": "compaction", "id": "cmp_1", "encrypted_content": "compacted"}

    async def respond(peer, _body):
        await _complete(peer, f"resp_{len(server.requests)}", [compaction] if len(server.requests) == 1 else None)

    server.respond = respond
    first = await provider.chat(_messages(), provider_context=_context())
    result = await provider.chat(_messages("next"), provider_context=_context(first))
    assert result.content == "answer"
    assert "previous_response_id" not in server.requests[1][1]
    assert server.requests[1][1]["input"][0] == {"type": "compaction", "encrypted_content": "compacted"}
    assert len(server.requests[1][1]["input"]) == 2


async def test_codex_idle_socket_eviction_preserves_replay(codex_peer, monkeypatch):
    provider, server, _ = codex_peer
    monkeypatch.setattr("nanobot.providers.openai_codex_provider._MAX_WEBSOCKET_SESSIONS", 1)
    first = await provider.chat(_messages(), provider_context=_context())
    await provider.chat(_messages("other"), provider_context=_context(session="session-b"))
    await asyncio.wait_for(server.peers[0].closed.wait(), 2)
    result = await provider.chat(_messages("next"), provider_context=_context(first))
    assert result.content == "answer"
    assert len(server.peers) == 3
    assert "previous_response_id" not in server.requests[-1][1]
    assert len(server.requests[-1][1]["input"]) == 3


async def test_runtime_shutdown_closes_replaced_codex_providers(codex_peer):
    provider, server, _ = codex_peer
    replacement = OpenAICodexProvider(default_model="gpt-6-astra")
    resolver = ModelRuntimeResolver(LLMRuntime.capture(
        provider, provider.get_default_model(), context_window_tokens=None,
    ))
    try:
        await provider.chat(_messages(), provider_context=_context())
        resolver.adopt_snapshot(ProviderSnapshot(
            provider=replacement, model=replacement.get_default_model(),
            context_window_tokens=100_000, signature=("replacement",),
        ))
        await replacement.chat(_messages(), provider_context=_context(session="session-b"))
        await resolver.aclose()
        await resolver.aclose()
        await asyncio.gather(*(asyncio.wait_for(peer.closed.wait(), 2) for peer in server.peers))
        assert len(server.peers) == 2
    finally:
        await replacement.aclose()
