"""Unit and lightweight integration tests for the WebSocket channel."""

import asyncio
import functools
import json
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import websockets
from websockets.exceptions import ConnectionClosed
from websockets.frames import Close

from nanobot.bus.events import OutboundMessage
from nanobot.channels.websocket import (
    WebSocketChannel,
    WebSocketConfig,
    _is_valid_chat_id,
    _issue_route_secret_matches,
    _normalize_config_path,
    _normalize_http_path,
    _parse_envelope,
    _parse_inbound_payload,
    _parse_query,
    _parse_request_path,
)
from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import Config

# -- Shared helpers (aligned with test_websocket_integration.py) ---------------

_PORT = 29876


def _ch(bus: Any, **kw: Any) -> WebSocketChannel:
    cfg: dict[str, Any] = {
        "enabled": True,
        "allowFrom": ["*"],
        "host": "127.0.0.1",
        "port": _PORT,
        "path": "/ws",
        "websocketRequiresToken": False,
    }
    cfg.update(kw)
    return WebSocketChannel(cfg, bus)


@pytest.fixture()
def bus() -> MagicMock:
    b = MagicMock()
    b.publish_inbound = AsyncMock()
    return b


async def _http_get(url: str, headers: dict[str, str] | None = None) -> httpx.Response:
    """Run GET in a thread to avoid blocking the asyncio loop shared with websockets."""
    return await asyncio.to_thread(
        functools.partial(httpx.get, url, headers=headers or {}, timeout=5.0)
    )


def test_normalize_http_path_strips_trailing_slash_except_root() -> None:
    assert _normalize_http_path("/chat/") == "/chat"
    assert _normalize_http_path("/chat?x=1") == "/chat"
    assert _normalize_http_path("/") == "/"


def test_parse_request_path_matches_normalize_and_query() -> None:
    path, query = _parse_request_path("/ws/?token=secret&client_id=u1")
    assert path == _normalize_http_path("/ws/?token=secret&client_id=u1")
    assert query == _parse_query("/ws/?token=secret&client_id=u1")


def test_normalize_config_path_matches_request() -> None:
    assert _normalize_config_path("/ws/") == "/ws"
    assert _normalize_config_path("/") == "/"


def test_parse_query_extracts_token_and_client_id() -> None:
    query = _parse_query("/?token=secret&client_id=u1")
    assert query.get("token") == ["secret"]
    assert query.get("client_id") == ["u1"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("plain", "plain"),
        ('{"content": "hi"}', "hi"),
        ('{"text": "there"}', "there"),
        ('{"message": "x"}', "x"),
        ("  ", None),
        ("{}", None),
    ],
)
def test_parse_inbound_payload(raw: str, expected: str | None) -> None:
    assert _parse_inbound_payload(raw) == expected


def test_parse_inbound_invalid_json_falls_back_to_raw_string() -> None:
    assert _parse_inbound_payload("{not json") == "{not json"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('{"content": ""}', None),           # empty string content
        ('{"content": 123}', None),          # non-string content
        ('{"content": "  "}', None),         # whitespace-only content
        ('["hello"]', '["hello"]'),           # JSON array: not a dict, treated as plain text
        ('{"unknown_key": "val"}', None),    # unrecognized key
        ('{"content": null}', None),         # null content
    ],
)
def test_parse_inbound_payload_edge_cases(raw: str, expected: str | None) -> None:
    assert _parse_inbound_payload(raw) == expected


def test_web_socket_config_path_must_start_with_slash() -> None:
    with pytest.raises(ValueError, match='path must start with "/"'):
        WebSocketConfig(path="bad")


def test_ssl_context_requires_both_cert_and_key_files() -> None:
    bus = MagicMock()
    channel = WebSocketChannel(
        {"enabled": True, "allowFrom": ["*"], "sslCertfile": "/tmp/c.pem", "sslKeyfile": ""},
        bus,
    )
    with pytest.raises(ValueError, match="ssl_certfile and ssl_keyfile"):
        channel._build_ssl_context()


def test_default_config_includes_safe_bind_and_streaming() -> None:
    defaults = WebSocketChannel.default_config()
    assert defaults["enabled"] is False
    assert defaults["host"] == "127.0.0.1"
    assert defaults["streaming"] is True
    assert defaults["allowFrom"] == ["*"]
    assert defaults.get("tokenIssuePath", "") == ""


def test_token_issue_path_must_differ_from_websocket_path() -> None:
    with pytest.raises(ValueError, match="token_issue_path must differ"):
        WebSocketConfig(path="/ws", token_issue_path="/ws")


def test_issue_route_secret_matches_bearer_and_header() -> None:
    from websockets.datastructures import Headers

    secret = "my-secret"
    bearer_headers = Headers([("Authorization", "Bearer my-secret")])
    assert _issue_route_secret_matches(bearer_headers, secret) is True
    x_headers = Headers([("X-Nanobot-Auth", "my-secret")])
    assert _issue_route_secret_matches(x_headers, secret) is True
    wrong = Headers([("Authorization", "Bearer other")])
    assert _issue_route_secret_matches(wrong, secret) is False


def test_issue_route_secret_matches_empty_secret() -> None:
    from websockets.datastructures import Headers

    # Empty secret always returns True regardless of headers
    assert _issue_route_secret_matches(Headers([]), "") is True
    assert _issue_route_secret_matches(Headers([("Authorization", "Bearer anything")]), "") is True


@pytest.mark.asyncio
async def test_webui_message_envelope_marks_inbound_metadata(bus: MagicMock) -> None:
    channel = _ch(bus)
    conn = MagicMock()
    conn.remote_address = ("127.0.0.1", 50123)

    await channel._dispatch_envelope(
        conn,
        "webui-client",
        {"type": "message", "chat_id": "chat-1", "content": "hello", "webui": True},
    )

    msg = bus.publish_inbound.await_args.args[0]
    assert msg.channel == "websocket"
    assert msg.chat_id == "chat-1"
    assert msg.metadata["webui"] is True
    assert msg.metadata["_wants_stream"] is True


@pytest.mark.asyncio
async def test_plain_websocket_message_does_not_mark_webui(bus: MagicMock) -> None:
    channel = _ch(bus)
    conn = MagicMock()

    await channel._dispatch_envelope(
        conn,
        "custom-client",
        {"type": "message", "chat_id": "chat-1", "content": "hello"},
    )

    msg = bus.publish_inbound.await_args.args[0]
    assert "webui" not in msg.metadata


@pytest.mark.asyncio
async def test_send_delivers_json_message_with_media_and_reply() -> None:
    bus = MagicMock()
    channel = WebSocketChannel({"enabled": True, "allowFrom": ["*"]}, bus)
    mock_ws = AsyncMock()
    channel._attach(mock_ws, "chat-1")

    msg = OutboundMessage(
        channel="websocket",
        chat_id="chat-1",
        content="hello",
        reply_to="m1",
        media=["/tmp/a.png"],
        buttons=[["Yes", "No"]],
    )
    await channel.send(msg)

    mock_ws.send.assert_awaited_once()
    payload = json.loads(mock_ws.send.call_args[0][0])
    assert payload["event"] == "message"
    assert payload["chat_id"] == "chat-1"
    assert payload["text"] == "hello\n\n1. Yes\n2. No"
    assert payload["button_prompt"] == "hello"
    assert payload["reply_to"] == "m1"
    assert payload["media"] == ["/tmp/a.png"]
    assert payload["buttons"] == [["Yes", "No"]]


@pytest.mark.asyncio
async def test_send_stages_external_media_as_signed_url(monkeypatch, tmp_path) -> None:
    bus = MagicMock()
    media_root = tmp_path / "media"
    ws_media = media_root / "websocket"
    ws_media.mkdir(parents=True)
    external = tmp_path / "clip.mp4"
    external.write_bytes(b"video")

    def fake_media_dir(channel: str | None = None):
        return ws_media if channel == "websocket" else media_root

    monkeypatch.setattr("nanobot.channels.websocket.get_media_dir", fake_media_dir)
    channel = WebSocketChannel({"enabled": True, "allowFrom": ["*"]}, bus)
    mock_ws = AsyncMock()
    channel._attach(mock_ws, "chat-1")

    await channel.send(
        OutboundMessage(
            channel="websocket",
            chat_id="chat-1",
            content="video",
            media=[str(external)],
        )
    )

    payload = json.loads(mock_ws.send.call_args[0][0])
    assert payload["media"] == [str(external)]
    assert payload["media_urls"][0]["name"] == "clip.mp4"
    assert payload["media_urls"][0]["url"].startswith("/api/media/")
    assert any(p.name.endswith("-clip.mp4") for p in ws_media.iterdir())


@pytest.mark.asyncio
async def test_send_missing_connection_is_noop_without_error() -> None:
    bus = MagicMock()
    channel = WebSocketChannel({"enabled": True, "allowFrom": ["*"]}, bus)
    msg = OutboundMessage(channel="websocket", chat_id="missing", content="x")
    await channel.send(msg)


@pytest.mark.asyncio
async def test_send_removes_connection_on_connection_closed() -> None:
    bus = MagicMock()
    channel = WebSocketChannel({"enabled": True, "allowFrom": ["*"]}, bus)
    mock_ws = AsyncMock()
    mock_ws.send.side_effect = ConnectionClosed(Close(1006, ""), Close(1006, ""), True)
    channel._attach(mock_ws, "chat-1")

    msg = OutboundMessage(channel="websocket", chat_id="chat-1", content="hello")
    await channel.send(msg)

    assert "chat-1" not in channel._subs
    assert mock_ws not in channel._conn_chats


@pytest.mark.asyncio
async def test_send_delta_removes_connection_on_connection_closed() -> None:
    bus = MagicMock()
    channel = WebSocketChannel({"enabled": True, "allowFrom": ["*"], "streaming": True}, bus)
    mock_ws = AsyncMock()
    mock_ws.send.side_effect = ConnectionClosed(Close(1006, ""), Close(1006, ""), True)
    channel._attach(mock_ws, "chat-1")

    await channel.send_delta("chat-1", "chunk", {"_stream_delta": True, "_stream_id": "s1"})

    assert "chat-1" not in channel._subs
    assert mock_ws not in channel._conn_chats


@pytest.mark.asyncio
async def test_send_delta_emits_delta_and_stream_end() -> None:
    bus = MagicMock()
    channel = WebSocketChannel({"enabled": True, "allowFrom": ["*"], "streaming": True}, bus)
    mock_ws = AsyncMock()
    channel._attach(mock_ws, "chat-1")

    await channel.send_delta("chat-1", "part", {"_stream_delta": True, "_stream_id": "sid"})
    await channel.send_delta("chat-1", "", {"_stream_end": True, "_stream_id": "sid"})

    assert mock_ws.send.await_count == 2
    first = json.loads(mock_ws.send.call_args_list[0][0][0])
    second = json.loads(mock_ws.send.call_args_list[1][0][0])
    assert first["event"] == "delta"
    assert first["chat_id"] == "chat-1"
    assert first["text"] == "part"
    assert first["stream_id"] == "sid"
    assert second["event"] == "stream_end"
    assert second["chat_id"] == "chat-1"
    assert second["stream_id"] == "sid"


@pytest.mark.asyncio
async def test_send_turn_end_emits_turn_end_event() -> None:
    bus = MagicMock()
    channel = WebSocketChannel({"enabled": True, "allowFrom": ["*"]}, bus)
    mock_ws = AsyncMock()
    channel._attach(mock_ws, "chat-1")

    await channel.send(OutboundMessage(
        channel="websocket",
        chat_id="chat-1",
        content="",
        metadata={"_turn_end": True},
    ))

    mock_ws.send.assert_awaited_once()
    body = json.loads(mock_ws.send.await_args.args[0])
    assert body == {"event": "turn_end", "chat_id": "chat-1"}


@pytest.mark.asyncio
async def test_send_session_updated_emits_session_updated_event() -> None:
    bus = MagicMock()
    channel = WebSocketChannel({"enabled": True, "allowFrom": ["*"]}, bus)
    mock_ws = AsyncMock()
    channel._attach(mock_ws, "chat-1")

    await channel.send(OutboundMessage(
        channel="websocket",
        chat_id="chat-1",
        content="",
        metadata={"_session_updated": True},
    ))

    mock_ws.send.assert_awaited_once()
    body = json.loads(mock_ws.send.await_args.args[0])
    assert body == {"event": "session_updated", "chat_id": "chat-1"}


@pytest.mark.asyncio
async def test_send_non_connection_closed_exception_is_raised() -> None:
    bus = MagicMock()
    channel = WebSocketChannel({"enabled": True, "allowFrom": ["*"]}, bus)
    mock_ws = AsyncMock()
    mock_ws.send.side_effect = RuntimeError("unexpected")
    channel._attach(mock_ws, "chat-1")

    msg = OutboundMessage(channel="websocket", chat_id="chat-1", content="hello")
    with pytest.raises(RuntimeError, match="unexpected"):
        await channel.send(msg)


@pytest.mark.asyncio
async def test_send_delta_missing_connection_is_noop() -> None:
    bus = MagicMock()
    channel = WebSocketChannel({"enabled": True, "allowFrom": ["*"], "streaming": True}, bus)
    # No exception, no error — just a no-op
    await channel.send_delta("nonexistent", "chunk", {"_stream_delta": True, "_stream_id": "s1"})


@pytest.mark.asyncio
async def test_stop_is_idempotent() -> None:
    bus = MagicMock()
    channel = WebSocketChannel({"enabled": True, "allowFrom": ["*"]}, bus)
    # stop() before start() should not raise
    await channel.stop()
    await channel.stop()


@pytest.mark.asyncio
async def test_end_to_end_client_receives_ready_and_agent_sees_inbound(bus: MagicMock) -> None:
    port = 29876
    channel = _ch(bus, port=port)

    server_task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)

    try:
        async with websockets.connect(f"ws://127.0.0.1:{port}/ws?client_id=tester") as client:
            ready_raw = await client.recv()
            ready = json.loads(ready_raw)
            assert ready["event"] == "ready"
            assert ready["client_id"] == "tester"
            chat_id = ready["chat_id"]

            await client.send(json.dumps({"content": "ping from client"}))
            await asyncio.sleep(0.08)

            bus.publish_inbound.assert_awaited()
            inbound = bus.publish_inbound.call_args[0][0]
            assert inbound.channel == "websocket"
            assert inbound.sender_id == "tester"
            assert inbound.chat_id == chat_id
            assert inbound.content == "ping from client"

            await client.send("plain text frame")
            await asyncio.sleep(0.08)
            assert bus.publish_inbound.await_count >= 2
            second = [c[0][0] for c in bus.publish_inbound.call_args_list][-1]
            assert second.content == "plain text frame"
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_token_rejects_handshake_when_mismatch(bus: MagicMock) -> None:
    port = 29877
    channel = _ch(bus, port=port, path="/", token="secret")

    server_task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)

    try:
        with pytest.raises(websockets.exceptions.InvalidStatus) as excinfo:
            async with websockets.connect(f"ws://127.0.0.1:{port}/?token=wrong"):
                pass
        assert excinfo.value.response.status_code == 401
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_wrong_path_returns_404(bus: MagicMock) -> None:
    port = 29878
    channel = _ch(bus, port=port)

    server_task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)

    try:
        with pytest.raises(websockets.exceptions.InvalidStatus) as excinfo:
            async with websockets.connect(f"ws://127.0.0.1:{port}/other"):
                pass
        assert excinfo.value.response.status_code == 404
    finally:
        await channel.stop()
        await server_task


def test_registry_discovers_websocket_channel() -> None:
    from nanobot.channels.registry import load_channel_class

    cls = load_channel_class("websocket")
    assert cls.name == "websocket"


@pytest.mark.asyncio
async def test_http_route_issues_token_then_websocket_requires_it(bus: MagicMock) -> None:
    port = 29879
    channel = _ch(
        bus, port=port,
        tokenIssuePath="/auth/token",
        tokenIssueSecret="route-secret",
        websocketRequiresToken=True,
    )

    server_task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)

    try:
        deny = await _http_get(f"http://127.0.0.1:{port}/auth/token")
        assert deny.status_code == 401

        issue = await _http_get(
            f"http://127.0.0.1:{port}/auth/token",
            headers={"Authorization": "Bearer route-secret"},
        )
        assert issue.status_code == 200
        token = issue.json()["token"]
        assert token.startswith("nbwt_")

        with pytest.raises(websockets.exceptions.InvalidStatus) as missing_token:
            async with websockets.connect(f"ws://127.0.0.1:{port}/ws?client_id=x"):
                pass
        assert missing_token.value.response.status_code == 401

        uri = f"ws://127.0.0.1:{port}/ws?token={token}&client_id=caller"
        async with websockets.connect(uri) as client:
            ready = json.loads(await client.recv())
            assert ready["event"] == "ready"
            assert ready["client_id"] == "caller"

        with pytest.raises(websockets.exceptions.InvalidStatus) as reuse:
            async with websockets.connect(uri):
                pass
        assert reuse.value.response.status_code == 401
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_settings_api_returns_safe_subset_and_updates_whitelist(
    bus: MagicMock,
    monkeypatch,
    tmp_path,
) -> None:
    port = 29891
    config_path = tmp_path / "config.json"
    config = Config()
    config.agents.defaults.model = "openai/gpt-4o"
    config.providers.openai.api_key = "secret-key"
    save_config(config, config_path)
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)

    channel = _ch(bus, port=port)
    channel._api_tokens["tok"] = time.monotonic() + 300

    server_task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)

    try:
        settings = await _http_get(
            f"http://127.0.0.1:{port}/api/settings",
            headers={"Authorization": "Bearer tok"},
        )
        assert settings.status_code == 200
        body = settings.json()
        assert body["agent"]["model"] == "openai/gpt-4o"
        assert body["agent"]["provider"] == "openai"
        providers = {provider["name"]: provider for provider in body["providers"]}
        assert providers["openai"]["configured"] is True
        assert providers["openai"]["api_key_hint"] == "secr••••-key"
        assert providers["openrouter"]["configured"] is False
        assert body["agent"]["has_api_key"] is True
        assert "secret-key" not in settings.text

        provider_updated = await _http_get(
            "http://127.0.0.1:"
            f"{port}/api/settings/provider/update?provider=openrouter"
            "&api_key=sk-or-test&api_base=https%3A%2F%2Fopenrouter.ai%2Fapi%2Fv1",
            headers={"Authorization": "Bearer tok"},
        )
        assert provider_updated.status_code == 200
        provider_body = provider_updated.json()
        assert provider_body["requires_restart"] is False
        provider_rows = {provider["name"]: provider for provider in provider_body["providers"]}
        assert provider_rows["openrouter"]["configured"] is True
        assert "sk-or-test" not in provider_updated.text

        updated = await _http_get(
            "http://127.0.0.1:"
            f"{port}/api/settings/update?model=openrouter/test"
            "&provider=openrouter",
            headers={"Authorization": "Bearer tok"},
        )
        assert updated.status_code == 200
        assert updated.json()["requires_restart"] is False

        saved = load_config(config_path)
        assert saved.agents.defaults.model == "openrouter/test"
        assert saved.agents.defaults.provider == "openrouter"
        assert saved.providers.openrouter.api_key == "sk-or-test"
        assert saved.providers.openrouter.api_base == "https://openrouter.ai/api/v1"
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_commands_api_returns_slash_command_metadata(bus: MagicMock) -> None:
    port = 29892
    channel = _ch(bus, port=port)
    channel._api_tokens["tok"] = time.monotonic() + 300

    server_task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)

    try:
        denied = await _http_get(f"http://127.0.0.1:{port}/api/commands")
        assert denied.status_code == 401

        response = await _http_get(
            f"http://127.0.0.1:{port}/api/commands",
            headers={"Authorization": "Bearer tok"},
        )
        assert response.status_code == 200
        body = response.json()
        commands = {row["command"]: row for row in body["commands"]}
        assert commands["/stop"]["title"] == "Stop current task"
        assert commands["/history"]["arg_hint"] == "[n]"
        assert all("description" in row for row in body["commands"])
    finally:
        await channel.stop()
        await server_task


def test_settings_payload_normalizes_camel_case_provider(
    bus: MagicMock,
    monkeypatch,
    tmp_path,
) -> None:
    config_path = tmp_path / "config.json"
    config = Config()
    config.agents.defaults.provider = "minimaxAnthropic"
    save_config(config, config_path)
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)

    body = _ch(bus)._settings_payload()

    assert body["agent"]["provider"] == "minimax_anthropic"


@pytest.mark.asyncio
async def test_end_to_end_server_pushes_streaming_deltas_to_client(bus: MagicMock) -> None:
    port = 29880
    channel = _ch(bus, port=port, streaming=True)

    server_task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)

    try:
        async with websockets.connect(f"ws://127.0.0.1:{port}/ws?client_id=stream-tester") as client:
            ready_raw = await client.recv()
            ready = json.loads(ready_raw)
            chat_id = ready["chat_id"]

            # Server pushes deltas directly
            await channel.send_delta(
                chat_id, "Hello ", {"_stream_delta": True, "_stream_id": "s1"}
            )
            await channel.send_delta(
                chat_id, "world", {"_stream_delta": True, "_stream_id": "s1"}
            )
            await channel.send_delta(
                chat_id, "", {"_stream_end": True, "_stream_id": "s1"}
            )

            delta1 = json.loads(await client.recv())
            assert delta1["event"] == "delta"
            assert delta1["text"] == "Hello "
            assert delta1["stream_id"] == "s1"

            delta2 = json.loads(await client.recv())
            assert delta2["event"] == "delta"
            assert delta2["text"] == "world"
            assert delta2["stream_id"] == "s1"

            end = json.loads(await client.recv())
            assert end["event"] == "stream_end"
            assert end["stream_id"] == "s1"

            await channel.send(OutboundMessage(
                channel="websocket",
                chat_id=chat_id,
                content="",
                metadata={"_turn_end": True},
            ))

            turn_end = json.loads(await client.recv())
            assert turn_end == {"event": "turn_end", "chat_id": chat_id}
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_token_issue_rejects_when_at_capacity(bus: MagicMock) -> None:
    port = 29881
    channel = _ch(bus, port=port, tokenIssuePath="/auth/token", tokenIssueSecret="s")

    server_task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)

    try:
        # Fill issued tokens to capacity
        channel._issued_tokens = {
            f"nbwt_fill_{i}": time.monotonic() + 300 for i in range(channel._MAX_ISSUED_TOKENS)
        }

        resp = await _http_get(
            f"http://127.0.0.1:{port}/auth/token",
            headers={"Authorization": "Bearer s"},
        )
        assert resp.status_code == 429
        data = resp.json()
        assert "error" in data
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_allow_from_rejects_unauthorized_client_id(bus: MagicMock) -> None:
    port = 29882
    channel = _ch(bus, port=port, allowFrom=["alice", "bob"])

    server_task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)

    try:
        with pytest.raises(websockets.exceptions.InvalidStatus) as exc_info:
            async with websockets.connect(f"ws://127.0.0.1:{port}/ws?client_id=eve"):
                pass
        assert exc_info.value.response.status_code == 403
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_client_id_truncation(bus: MagicMock) -> None:
    port = 29883
    channel = _ch(bus, port=port)

    server_task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)

    try:
        long_id = "x" * 200
        async with websockets.connect(f"ws://127.0.0.1:{port}/ws?client_id={long_id}") as client:
            ready = json.loads(await client.recv())
            assert ready["client_id"] == "x" * 128
            assert len(ready["client_id"]) == 128
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_non_utf8_binary_frame_ignored(bus: MagicMock) -> None:
    port = 29884
    channel = _ch(bus, port=port)

    server_task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)

    try:
        async with websockets.connect(f"ws://127.0.0.1:{port}/ws?client_id=bin-test") as client:
            await client.recv()  # consume ready
            # Send non-UTF-8 bytes
            await client.send(b"\xff\xfe\xfd")
            await asyncio.sleep(0.05)
            # publish_inbound should NOT have been called
            bus.publish_inbound.assert_not_awaited()
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_static_token_accepts_issued_token_as_fallback(bus: MagicMock) -> None:
    port = 29885
    channel = _ch(
        bus, port=port,
        token="static-secret",
        tokenIssuePath="/auth/token",
        tokenIssueSecret="route-secret",
    )

    server_task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)

    try:
        # Get an issued token
        resp = await _http_get(
            f"http://127.0.0.1:{port}/auth/token",
            headers={"Authorization": "Bearer route-secret"},
        )
        assert resp.status_code == 200
        issued_token = resp.json()["token"]

        # Connect using issued token (not the static one)
        async with websockets.connect(f"ws://127.0.0.1:{port}/ws?token={issued_token}&client_id=caller") as client:
            ready = json.loads(await client.recv())
            assert ready["event"] == "ready"
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_allow_from_empty_list_denies_all(bus: MagicMock) -> None:
    port = 29886
    channel = _ch(bus, port=port, allowFrom=[])

    server_task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)

    try:
        with pytest.raises(websockets.exceptions.InvalidStatus) as exc_info:
            async with websockets.connect(f"ws://127.0.0.1:{port}/ws?client_id=anyone"):
                pass
        assert exc_info.value.response.status_code == 403
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_websocket_requires_token_without_issue_path(bus: MagicMock) -> None:
    """When websocket_requires_token is True but no token or issue path configured, all connections are rejected."""
    port = 29887
    channel = _ch(bus, port=port, websocketRequiresToken=True)

    server_task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)

    try:
        # No token at all → 401
        with pytest.raises(websockets.exceptions.InvalidStatus) as exc_info:
            async with websockets.connect(f"ws://127.0.0.1:{port}/ws?client_id=u"):
                pass
        assert exc_info.value.response.status_code == 401

        # Wrong token → 401
        with pytest.raises(websockets.exceptions.InvalidStatus) as exc_info:
            async with websockets.connect(f"ws://127.0.0.1:{port}/ws?client_id=u&token=wrong"):
                pass
        assert exc_info.value.response.status_code == 401
    finally:
        await channel.stop()
        await server_task


# -- Multi-chat multiplexing -------------------------------------------------
#
# The multiplex protocol lets one WS connection route N logical chats over
# typed envelopes (`new_chat` / `attach` / `message`). Legacy frames must keep
# working on the connection's default chat_id.


@pytest.mark.asyncio
async def test_multiplex_legacy_still_works(bus: MagicMock) -> None:
    port = 29930
    channel = _ch(bus, port=port)
    server_task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)

    try:
        async with websockets.connect(f"ws://127.0.0.1:{port}/ws?client_id=legacy") as client:
            ready = json.loads(await client.recv())
            default_chat = ready["chat_id"]

            # Plain text frame routes to default chat_id
            await client.send("hello from legacy")
            await asyncio.sleep(0.1)
            inbound = bus.publish_inbound.call_args[0][0]
            assert inbound.chat_id == default_chat
            assert inbound.content == "hello from legacy"

            # {"content": ...} frame routes to default chat_id
            await client.send(json.dumps({"content": "structured legacy"}))
            await asyncio.sleep(0.1)
            assert bus.publish_inbound.call_args[0][0].chat_id == default_chat
            assert bus.publish_inbound.call_args[0][0].content == "structured legacy"

            # Outbound still reaches the legacy client, with chat_id annotated
            await channel.send(
                OutboundMessage(channel="websocket", chat_id=default_chat, content="reply")
            )
            reply = json.loads(await client.recv())
            assert reply["event"] == "message"
            assert reply["chat_id"] == default_chat
            assert reply["text"] == "reply"
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_multiplex_new_chat_roundtrip(bus: MagicMock) -> None:
    port = 29931
    channel = _ch(bus, port=port)
    server_task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)

    try:
        async with websockets.connect(f"ws://127.0.0.1:{port}/ws?client_id=mp") as client:
            ready = json.loads(await client.recv())
            default_chat = ready["chat_id"]

            await client.send(json.dumps({"type": "new_chat"}))
            attached = json.loads(await client.recv())
            assert attached["event"] == "attached"
            new_chat = attached["chat_id"]
            assert new_chat and new_chat != default_chat

            # Send on the new chat via typed envelope
            await client.send(
                json.dumps({"type": "message", "chat_id": new_chat, "content": "hi on new"})
            )
            await asyncio.sleep(0.1)
            inbound = bus.publish_inbound.call_args[0][0]
            assert inbound.chat_id == new_chat
            assert inbound.content == "hi on new"

            # Server pushes a message back; chat_id must match
            await channel.send(
                OutboundMessage(channel="websocket", chat_id=new_chat, content="ok")
            )
            reply = json.loads(await client.recv())
            assert reply["event"] == "message"
            assert reply["chat_id"] == new_chat
            assert reply["text"] == "ok"
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_multiplex_two_chats_isolated(bus: MagicMock) -> None:
    port = 29932
    channel = _ch(bus, port=port)
    server_task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)

    try:
        async with websockets.connect(f"ws://127.0.0.1:{port}/ws?client_id=two") as client:
            await client.recv()  # ready

            await client.send(json.dumps({"type": "new_chat"}))
            chat_a = json.loads(await client.recv())["chat_id"]
            await client.send(json.dumps({"type": "new_chat"}))
            chat_b = json.loads(await client.recv())["chat_id"]
            assert chat_a != chat_b

            # Push A → client sees A only (FIFO over the single WS).
            await channel.send(
                OutboundMessage(channel="websocket", chat_id=chat_a, content="for-A")
            )
            msg_a = json.loads(await client.recv())
            assert msg_a["chat_id"] == chat_a
            assert msg_a["text"] == "for-A"

            # Push B → client sees B only.
            await channel.send(
                OutboundMessage(channel="websocket", chat_id=chat_b, content="for-B")
            )
            msg_b = json.loads(await client.recv())
            assert msg_b["chat_id"] == chat_b
            assert msg_b["text"] == "for-B"
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_multiplex_invalid_frames_return_error(bus: MagicMock) -> None:
    port = 29933
    channel = _ch(bus, port=port)
    server_task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)

    try:
        async with websockets.connect(f"ws://127.0.0.1:{port}/ws?client_id=bad") as client:
            await client.recv()  # ready

            # attach with bad chat_id
            await client.send(json.dumps({"type": "attach", "chat_id": "has space"}))
            err1 = json.loads(await client.recv())
            assert err1["event"] == "error"

            # message with missing content
            await client.send(json.dumps({"type": "message", "chat_id": "abc", "content": ""}))
            err2 = json.loads(await client.recv())
            assert err2["event"] == "error"

            # unknown type
            await client.send(json.dumps({"type": "nope"}))
            err3 = json.loads(await client.recv())
            assert err3["event"] == "error"

            # Connection survives: legacy frame still works.
            await client.send("still-alive")
            await asyncio.sleep(0.1)
            bus.publish_inbound.assert_awaited()
            assert bus.publish_inbound.call_args[0][0].content == "still-alive"
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_multiplex_cleanup_on_disconnect(bus: MagicMock) -> None:
    port = 29934
    channel = _ch(bus, port=port)
    server_task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)

    try:
        async with websockets.connect(f"ws://127.0.0.1:{port}/ws?client_id=dc") as client:
            ready = json.loads(await client.recv())
            default_chat = ready["chat_id"]
            await client.send(json.dumps({"type": "new_chat"}))
            extra_chat = json.loads(await client.recv())["chat_id"]
            assert default_chat in channel._subs
            assert extra_chat in channel._subs
        # Client gone. Server-side tracking must be empty.
        await asyncio.sleep(0.2)
        assert default_chat not in channel._subs
        assert extra_chat not in channel._subs
        assert not channel._conn_chats
        assert not channel._conn_default
    finally:
        await channel.stop()
        await server_task


def test_parse_envelope_detects_typed_frames() -> None:
    assert _parse_envelope('{"type":"new_chat"}') == {"type": "new_chat"}
    env = _parse_envelope('{"type":"message","chat_id":"abc","content":"hi"}')
    assert env == {"type": "message", "chat_id": "abc", "content": "hi"}


def test_parse_envelope_rejects_legacy_and_garbage() -> None:
    # No `type` field → legacy, caller falls back to _parse_inbound_payload.
    assert _parse_envelope('{"content":"hi"}') is None
    assert _parse_envelope("plain text") is None
    assert _parse_envelope("{broken") is None
    assert _parse_envelope("[1,2,3]") is None
    # Non-string `type` is not a valid envelope.
    assert _parse_envelope('{"type":123}') is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("abc", True),
        ("a1b2_c:d-e", True),
        ("x" * 64, True),
        ("unified:default", True),
        ("", False),
        ("x" * 65, False),
        ("has space", False),
        ("a/b", False),
        ("a.b", False),
        (None, False),
        (123, False),
    ],
)
def test_is_valid_chat_id(value: Any, expected: bool) -> None:
    assert _is_valid_chat_id(value) is expected
