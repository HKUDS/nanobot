"""Unit and lightweight integration tests for the WebSocket channel."""

import asyncio
import functools
import json
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import websockets
from websockets.exceptions import ConnectionClosed
from websockets.frames import Close

from nanobot.bus.events import OUTBOUND_META_AGENT_UI, OutboundMessage
from nanobot.bus.outbound_events import (
    GoalStateSyncEvent,
    GoalStatusEvent,
    ProgressEvent,
    RuntimeModelUpdatedEvent,
    SessionUpdatedEvent,
    TurnEndEvent,
)
from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket import (
    WebSocketChannel,
    WebSocketConfig,
    _is_valid_chat_id,
    _parse_envelope,
    _parse_inbound_payload,
    publish_runtime_model_update,
)
from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import Config, ModelPresetConfig
from nanobot.session import webui_turns as wth
from nanobot.session.manager import SessionManager
from nanobot.webui.gateway_services import GatewayServices, build_gateway_services
from nanobot.webui.http_utils import (
    issue_route_secret_matches as _issue_route_secret_matches,
)
from nanobot.webui.http_utils import (
    normalize_config_path as _normalize_config_path,
)
from nanobot.webui.http_utils import (
    parse_query as _parse_query,
)
from nanobot.webui.http_utils import (
    parse_request_path as _parse_request_path,
)
from nanobot.webui.settings_api import settings_payload, update_provider_settings
from nanobot.webui.transcript import append_transcript_object, read_transcript_lines

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
    parsed = WebSocketConfig.model_validate(cfg)
    gateway = build_gateway_services(
        config=parsed,
        bus=bus,
        session_manager=None,
        static_dist_path=None,
        workspace_path=Path.cwd(),
        default_restrict_to_workspace=False,
        runtime_model_name=None,
        runtime_surface="browser",
        runtime_capabilities_overrides=None,
    )
    return WebSocketChannel(cfg, bus, gateway=gateway)


def _basic_handler(bus: Any, **kw: Any) -> GatewayServices:
    cfg = WebSocketConfig.model_validate({
        "enabled": True, "allowFrom": ["*"],
        "host": "127.0.0.1", "port": _PORT,
        "path": "/ws", "websocketRequiresToken": False,
        "tokenIssueSecret": kw.get("token_issue_secret", ""),
    })
    return build_gateway_services(
        config=cfg,
        bus=bus,
        session_manager=kw.get("session_manager"),
        static_dist_path=None,
        workspace_path=kw.get("workspace_path", Path.cwd()),
        default_restrict_to_workspace=kw.get("default_restrict_to_workspace", False),
        runtime_model_name=None,
        runtime_surface=kw.get("runtime_surface", "browser"),
        runtime_capabilities_overrides=kw.get("runtime_capabilities_overrides"),
    )


@pytest.mark.asyncio
async def test_stop_treats_cancelled_server_task_as_shutdown() -> None:
    channel = _ch(MessageBus())
    channel._running = True
    channel._stop_event = asyncio.Event()

    async def _server_task() -> None:
        await asyncio.Event().wait()

    task = asyncio.create_task(_server_task())
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.sleep(0)
    channel._server_task = task

    await channel.stop()

    assert channel._server_task is None
    assert task.cancelled()


@pytest.fixture()
def bus() -> MagicMock:
    b = MagicMock()
    b.publish_inbound = AsyncMock()
    return b


@pytest.mark.asyncio
async def test_start_extends_http_open_timeout_for_slow_settings_routes(
    bus,
    monkeypatch,
) -> None:
    import nanobot.channels.websocket as websocket_module

    channel = _ch(bus, port=0)
    seen: dict[str, Any] = {}

    class Server:
        def close(self) -> None:
            pass

        async def wait_closed(self) -> None:
            pass

    async def fake_serve(*args: Any, **kwargs: Any) -> Server:
        seen.update(kwargs)
        assert channel._stop_event is not None
        channel._stop_event.set()
        return Server()

    monkeypatch.setattr(websocket_module, "serve", fake_serve)

    await channel.start()

    assert seen["open_timeout"] >= 300


@pytest.fixture(autouse=True)
def isolate_webui_workspace_state(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "nanobot.webui.workspaces.get_webui_dir",
        lambda: tmp_path / "webui",
    )


async def _http_get(url: str, headers: dict[str, str] | None = None) -> httpx.Response:
    """Run GET in a thread to avoid blocking the asyncio loop shared with websockets."""
    return await asyncio.to_thread(
        functools.partial(httpx.get, url, headers=headers or {}, timeout=5.0, trust_env=False)
    )


@pytest.mark.asyncio
async def test_send_session_updated_broadcasts_to_other_webui_connections(bus) -> None:
    class Conn:
        remote_address = None

        def __init__(self) -> None:
            self.sent: list[str] = []

        async def send(self, raw: str) -> None:
            self.sent.append(raw)

    channel = _ch(bus)
    active_conn = Conn()
    other_conn = Conn()
    channel._attach(active_conn, "chat-a")
    channel._attach(other_conn, "chat-b")
    assert sorted(channel._subs) == ["chat-a", "chat-b"]
    assert sum(len(conns) for conns in channel._subs.values()) == 2

    await channel.send_session_updated("chat-a", scope="thread")

    active_events = [json.loads(raw)["event"] for raw in active_conn.sent]
    other_events = [json.loads(raw)["event"] for raw in other_conn.sent]

    assert (active_events, other_events) == (
        ["session_updated"],
        ["session_updated"],
    )
    payload = json.loads(other_conn.sent[0])
    assert payload == {
        "event": "session_updated",
        "chat_id": "chat-a",
        "scope": "thread",
    }


async def _recv_ws_event(client: Any, event: str) -> dict[str, Any]:
    """Receive until a specific websocket event appears."""
    for _ in range(10):
        payload = json.loads(await client.recv())
        if payload.get("event") == event:
            return payload
    raise AssertionError(f"websocket event {event!r} was not received")


def _sent_ws_payloads(mock_ws: AsyncMock) -> list[dict[str, Any]]:
    return [json.loads(call.args[0]) for call in mock_ws.send.await_args_list]


def test_parse_request_path_strips_trailing_slash_except_root() -> None:
    assert _parse_request_path("/chat/")[0] == "/chat"
    assert _parse_request_path("/chat?x=1")[0] == "/chat"
    assert _parse_request_path("/")[0] == "/"


def test_parse_request_path_matches_query() -> None:
    path, query = _parse_request_path("/ws/?token=secret&client_id=u1")
    assert path == "/ws"
    assert query == _parse_query("/ws/?token=secret&client_id=u1")


def test_normalize_config_path_matches_request() -> None:
    assert _normalize_config_path("/ws/") == "/ws"
    assert _normalize_config_path("/") == "/"


def test_websocket_config_accepts_absolute_unix_socket(tmp_path) -> None:
    socket_path = tmp_path / "engine.sock"

    cfg = WebSocketConfig(unix_socket_path=str(socket_path))

    assert cfg.unix_socket_path == str(socket_path)


def test_websocket_config_rejects_relative_unix_socket() -> None:
    with pytest.raises(ValueError, match="absolute path"):
        WebSocketConfig(unix_socket_path="engine.sock")


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
        gateway=_basic_handler(bus),
    )
    with pytest.raises(ValueError, match="ssl_certfile and ssl_keyfile"):
        channel._build_ssl_context()


def test_default_config_includes_safe_bind_and_streaming() -> None:
    defaults = WebSocketChannel.default_config()
    assert defaults["enabled"] is True
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
async def test_token_issue_route_requires_secret_when_static_token_configured(bus: MagicMock) -> None:
    port = 29882
    channel = _ch(
        bus,
        port=port,
        token="static-token",
        tokenIssuePath="/auth/token",
        websocketRequiresToken=True,
    )

    server_task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)

    try:
        denied = await _http_get(f"http://127.0.0.1:{port}/auth/token")
        assert denied.status_code == 401

        allowed = await _http_get(
            f"http://127.0.0.1:{port}/auth/token",
            headers={"Authorization": "Bearer static-token"},
        )
        assert allowed.status_code == 200
        assert allowed.json()["token"].startswith("nbwt_")
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_webui_message_envelope_marks_inbound_metadata(bus: MagicMock) -> None:
    from nanobot.webui.transcript import read_transcript_lines

    channel = _ch(bus)
    conn = MagicMock()
    conn.remote_address = ("127.0.0.1", 50123)

    await channel._dispatch_envelope(
        conn,
        "webui-client",
        {
            "type": "message",
            "chat_id": "chat-1",
            "content": "hello",
            "webui": True,
            "turn_id": "turn-1",
        },
    )

    msg = bus.publish_inbound.await_args.args[0]
    assert msg.channel == "websocket"
    assert msg.chat_id == "chat-1"
    assert msg.metadata["webui"] is True
    assert msg.metadata["webui_turn_id"] == "turn-1"
    assert msg.metadata["_wants_stream"] is True
    lines = read_transcript_lines("websocket:chat-1")
    assert lines == [{
        "event": "user",
        "chat_id": "chat-1",
        "text": "hello",
        "turn_id": "turn-1",
        "turn_phase": "user",
        "turn_seq": 1,
    }]


@pytest.mark.asyncio
async def test_webui_message_envelope_persists_user_transcript_for_refresh(
    bus: MagicMock,
    tmp_path,
    monkeypatch,
) -> None:
    from nanobot.webui.transcript import build_webui_thread_response, read_transcript_lines

    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    channel = _ch(bus)
    conn = AsyncMock()
    conn.remote_address = ("127.0.0.1", 50123)

    async def answer_during_publish(_msg: Any) -> None:
        await channel.send(OutboundMessage(channel="websocket", chat_id="chat-1", content="hi back"))

    bus.publish_inbound.side_effect = answer_during_publish

    await channel._dispatch_envelope(
        conn,
        "webui-client",
        {"type": "message", "chat_id": "chat-1", "content": "hello", "webui": True},
    )

    lines = read_transcript_lines("websocket:chat-1")
    assert [line["event"] for line in lines] == ["user", "message"]

    body = build_webui_thread_response("websocket:chat-1")
    assert body is not None
    assert [message["role"] for message in body["messages"]] == ["user", "assistant"]
    assert [message["content"] for message in body["messages"]] == ["hello", "hi back"]


@pytest.mark.asyncio
async def test_webui_stop_control_message_is_not_persisted_as_user_bubble(
    bus: MagicMock,
    tmp_path,
    monkeypatch,
) -> None:
    from nanobot.webui.transcript import read_transcript_lines

    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    channel = _ch(bus)
    conn = AsyncMock()
    conn.remote_address = ("127.0.0.1", 50123)

    await channel._dispatch_envelope(
        conn,
        "webui-client",
        {"type": "message", "chat_id": "chat-1", "content": "/stop", "webui": True},
    )

    msg = bus.publish_inbound.await_args.args[0]
    assert msg.content == "/stop"
    assert read_transcript_lines("websocket:chat-1") == []


@pytest.mark.asyncio
async def test_webui_user_transcript_append_failure_does_not_block_inbound(
    bus: MagicMock,
    monkeypatch,
) -> None:
    def fail_append(_session_key: str, _obj: dict[str, Any]) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("nanobot.webui.transcript.append_transcript_object", fail_append)
    channel = _ch(bus)
    conn = AsyncMock()
    conn.remote_address = ("127.0.0.1", 50123)

    await channel._dispatch_envelope(
        conn,
        "webui-client",
        {"type": "message", "chat_id": "chat-1", "content": "hello", "webui": True},
    )

    msg = bus.publish_inbound.await_args.args[0]
    assert msg.chat_id == "chat-1"
    assert msg.content == "hello"


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
async def test_webui_message_scope_inherits_persisted_session_scope(
    bus: MagicMock,
    tmp_path,
) -> None:
    default_workspace = tmp_path / "default"
    project = tmp_path / "project"
    default_workspace.mkdir()
    project.mkdir()
    sessions = SessionManager(tmp_path / "sessions")
    channel = WebSocketChannel(
        {"enabled": True, "allowFrom": ["*"], "host": "127.0.0.1"},
        bus,
        gateway=_basic_handler(bus, session_manager=sessions, workspace_path=default_workspace),
    )
    conn = AsyncMock()
    conn.remote_address = ("127.0.0.1", 50123)

    await channel._dispatch_envelope(
        conn,
        "webui-client",
        {
            "type": "set_workspace_scope",
            "chat_id": "chat-scope",
            "workspace_scope": {
                "project_path": str(project),
                "access_mode": "full",
            },
        },
    )
    await channel._dispatch_envelope(
        conn,
        "webui-client",
        {"type": "message", "chat_id": "chat-scope", "content": "hello", "webui": True},
    )

    msg = bus.publish_inbound.await_args.args[0]
    assert msg.metadata["workspace_scope"] == {
        "project_path": str(project.resolve()),
        "access_mode": "full",
    }


@pytest.mark.asyncio
async def test_webui_scope_expands_home_project_path(
    bus: MagicMock,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    default_workspace = tmp_path / "default"
    home = tmp_path / "home"
    project = home / "Desktop" / "Photos"
    default_workspace.mkdir()
    project.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    channel = WebSocketChannel(
        {"enabled": True, "allowFrom": ["*"], "host": "127.0.0.1"},
        bus,
        gateway=_basic_handler(bus, session_manager=SessionManager(tmp_path / "sessions"), workspace_path=default_workspace),
    )
    conn = AsyncMock()
    conn.remote_address = ("127.0.0.1", 50123)

    await channel._dispatch_envelope(
        conn,
        "webui-client",
        {
            "type": "set_workspace_scope",
            "chat_id": "chat-scope",
            "workspace_scope": {
                "project_path": "~/Desktop/Photos",
                "access_mode": "restricted",
            },
        },
    )
    await channel._dispatch_envelope(
        conn,
        "webui-client",
        {"type": "message", "chat_id": "chat-scope", "content": "hello", "webui": True},
    )

    msg = bus.publish_inbound.await_args.args[0]
    assert msg.metadata["workspace_scope"] == {
        "project_path": str(project.resolve()),
        "access_mode": "restricted",
    }


@pytest.mark.asyncio
async def test_webui_scope_rejects_missing_project_path(bus: MagicMock, tmp_path) -> None:
    default_workspace = tmp_path / "default"
    default_workspace.mkdir()
    channel = WebSocketChannel(
        {"enabled": True, "allowFrom": ["*"], "host": "127.0.0.1"},
        bus,
        gateway=_basic_handler(bus, session_manager=SessionManager(tmp_path / "sessions"), workspace_path=default_workspace),
    )
    conn = AsyncMock()
    conn.remote_address = ("127.0.0.1", 50123)

    await channel._dispatch_envelope(
        conn,
        "webui-client",
        {
            "type": "set_workspace_scope",
            "chat_id": "chat-scope",
            "workspace_scope": {
                "project_path": str(tmp_path / "missing"),
                "access_mode": "restricted",
            },
        },
    )

    conn.send.assert_awaited()
    payload = json.loads(conn.send.await_args.args[0])
    assert payload["event"] == "error"
    assert payload["detail"] == "workspace_scope_rejected"
    bus.publish_inbound.assert_not_awaited()


@pytest.mark.asyncio
async def test_webui_scope_rejects_running_scope_change(bus: MagicMock, tmp_path) -> None:
    default_workspace = tmp_path / "default"
    project = tmp_path / "project"
    other = tmp_path / "other"
    default_workspace.mkdir()
    project.mkdir()
    other.mkdir()
    sessions = SessionManager(tmp_path / "sessions")
    channel = WebSocketChannel(
        {"enabled": True, "allowFrom": ["*"], "host": "127.0.0.1"},
        bus,
        gateway=_basic_handler(bus, session_manager=sessions, workspace_path=default_workspace),
    )
    conn = AsyncMock()
    conn.remote_address = ("127.0.0.1", 50123)

    await channel._dispatch_envelope(
        conn,
        "webui-client",
        {
            "type": "set_workspace_scope",
            "chat_id": "chat-running",
            "workspace_scope": {
                "project_path": str(project),
                "access_mode": "restricted",
            },
        },
    )
    wth._WEBSOCKET_TURN_WALL_STARTED_AT["chat-running"] = 123.0
    try:
        await channel._dispatch_envelope(
            conn,
            "webui-client",
            {
                "type": "message",
                "chat_id": "chat-running",
                "content": "hello",
                "webui": True,
                "workspace_scope": {
                    "project_path": str(other),
                    "access_mode": "full",
                },
            },
        )
    finally:
        wth._WEBSOCKET_TURN_WALL_STARTED_AT.clear()

    payload = json.loads(conn.send.await_args.args[0])
    assert payload["event"] == "error"
    assert payload["detail"] == "workspace_scope_rejected"
    assert payload["reason"] == "chat_running"
    assert payload["chat_id"] == "chat-running"
    bus.publish_inbound.assert_not_awaited()


@pytest.mark.asyncio
async def test_webui_set_workspace_scope_rejects_running_chat(bus: MagicMock, tmp_path) -> None:
    default_workspace = tmp_path / "default"
    project = tmp_path / "project"
    other = tmp_path / "other"
    default_workspace.mkdir()
    project.mkdir()
    other.mkdir()
    sessions = SessionManager(tmp_path / "sessions")
    channel = WebSocketChannel(
        {"enabled": True, "allowFrom": ["*"], "host": "127.0.0.1"},
        bus,
        gateway=_basic_handler(bus, session_manager=sessions, workspace_path=default_workspace),
    )
    conn = AsyncMock()
    conn.remote_address = ("127.0.0.1", 50123)

    await channel._dispatch_envelope(
        conn,
        "webui-client",
        {
            "type": "set_workspace_scope",
            "chat_id": "chat-running",
            "workspace_scope": {
                "project_path": str(project),
                "access_mode": "restricted",
            },
        },
    )
    conn.send.reset_mock()

    wth._WEBSOCKET_TURN_WALL_STARTED_AT["chat-running"] = 123.0
    try:
        await channel._dispatch_envelope(
            conn,
            "webui-client",
            {
                "type": "set_workspace_scope",
                "chat_id": "chat-running",
                "workspace_scope": {
                    "project_path": str(other),
                    "access_mode": "full",
                },
            },
        )
    finally:
        wth._WEBSOCKET_TURN_WALL_STARTED_AT.clear()

    payload = json.loads(conn.send.await_args.args[0])
    assert payload["event"] == "error"
    assert payload["detail"] == "workspace_scope_rejected"
    assert payload["reason"] == "chat_running"
    assert payload["chat_id"] == "chat-running"

    saved = sessions.read_session_file("websocket:chat-running")
    assert saved["metadata"]["workspace_scope"] == {
        "project_path": str(project.resolve()),
        "access_mode": "restricted",
    }


@pytest.mark.asyncio
async def test_remote_webui_scope_allows_access_reduction(
    bus: MagicMock,
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("nanobot.webui.workspaces.get_webui_dir", lambda: tmp_path / "webui")
    default_workspace = tmp_path / "default"
    default_workspace.mkdir()
    sessions = SessionManager(tmp_path / "sessions")
    channel = WebSocketChannel(
        {"enabled": True, "allowFrom": ["*"], "host": "127.0.0.1"},
        bus,
        gateway=_basic_handler(bus, session_manager=sessions, workspace_path=default_workspace),
    )
    conn = AsyncMock()
    conn.remote_address = ("203.0.113.8", 50123)

    await channel._dispatch_envelope(
        conn,
        "webui-client",
        {
            "type": "set_workspace_scope",
            "chat_id": "chat-remote",
            "workspace_scope": {
                "project_path": str(default_workspace),
                "access_mode": "restricted",
            },
        },
    )

    payload = json.loads(conn.send.await_args.args[0])
    assert payload["event"] == "session_updated"
    assert payload["workspace_scope"]["access_mode"] == "restricted"
    saved = sessions.read_session_file("websocket:chat-remote")
    assert saved["metadata"]["workspace_scope"] == {
        "project_path": str(default_workspace.resolve()),
        "access_mode": "restricted",
    }


@pytest.mark.asyncio
async def test_remote_access_reduction_rejects_stale_in_flight_message_scope(
    bus: MagicMock,
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("nanobot.webui.workspaces.get_webui_dir", lambda: tmp_path / "webui")
    default_workspace = tmp_path / "default"
    default_workspace.mkdir()
    sessions = SessionManager(tmp_path / "sessions")
    channel = WebSocketChannel(
        {"enabled": True, "allowFrom": ["*"], "host": "127.0.0.1"},
        bus,
        gateway=_basic_handler(bus, session_manager=sessions, workspace_path=default_workspace),
    )
    hydrate_started = asyncio.Event()
    release_hydrate = asyncio.Event()

    async def blocked_hydrate(_chat_id: str) -> None:
        hydrate_started.set()
        await release_hydrate.wait()

    channel._hydrate_after_subscribe = blocked_hydrate
    message_conn = AsyncMock()
    message_conn.remote_address = ("203.0.113.8", 50123)
    settings_conn = AsyncMock()
    settings_conn.remote_address = ("203.0.113.8", 50124)
    chat_id = "race-chat"

    message_task = asyncio.create_task(
        channel._dispatch_envelope(
            message_conn,
            "remote-message",
            {
                "type": "message",
                "chat_id": chat_id,
                "content": "hello",
                "webui": True,
                "workspace_scope": {
                    "project_path": str(default_workspace),
                    "access_mode": "full",
                },
            },
        )
    )
    await hydrate_started.wait()

    await channel._dispatch_envelope(
        settings_conn,
        "remote-settings",
        {
            "type": "set_workspace_scope",
            "chat_id": chat_id,
            "workspace_scope": {
                "project_path": str(default_workspace),
                "access_mode": "restricted",
            },
        },
    )
    release_hydrate.set()
    await message_task

    saved = sessions.read_session_file(f"websocket:{chat_id}")
    assert saved["metadata"]["workspace_scope"]["access_mode"] == "restricted"
    payload = json.loads(message_conn.send.await_args.args[0])
    assert payload["event"] == "error"
    assert payload["detail"] == "workspace_scope_rejected"
    bus.publish_inbound.assert_not_awaited()


@pytest.mark.asyncio
async def test_webui_scope_rejects_non_loopback_custom_scope(bus: MagicMock, tmp_path) -> None:
    default_workspace = tmp_path / "default"
    project = tmp_path / "project"
    default_workspace.mkdir()
    project.mkdir()
    sessions = SessionManager(tmp_path / "sessions")
    channel = WebSocketChannel(
        {"enabled": True, "allowFrom": ["*"], "host": "127.0.0.1"},
        bus,
        gateway=_basic_handler(bus, session_manager=sessions, workspace_path=default_workspace),
    )
    conn = AsyncMock()
    conn.remote_address = ("203.0.113.8", 50123)

    await channel._dispatch_envelope(
        conn,
        "webui-client",
        {
            "type": "set_workspace_scope",
            "chat_id": "chat-remote",
            "workspace_scope": {
                "project_path": str(project),
                "access_mode": "full",
            },
        },
    )

    payload = json.loads(conn.send.await_args.args[0])
    assert payload["event"] == "error"
    assert payload["detail"] == "workspace_scope_rejected"
    assert payload["reason"] == "workspace controls are localhost-only"
    assert payload["chat_id"] == "chat-remote"
    assert sessions.read_session_file("websocket:chat-remote") is None


@pytest.mark.asyncio
async def test_native_webui_scope_allows_custom_scope_without_loopback(
    bus: MagicMock,
    tmp_path,
) -> None:
    default_workspace = tmp_path / "default"
    project = tmp_path / "project"
    default_workspace.mkdir()
    project.mkdir()
    sessions = SessionManager(tmp_path / "sessions")
    channel = WebSocketChannel(
        {"enabled": True, "allowFrom": ["*"], "host": "127.0.0.1"},
        bus,
        gateway=_basic_handler(
            bus,
            session_manager=sessions,
            workspace_path=default_workspace,
            runtime_surface="native",
        ),
    )
    conn = AsyncMock()
    conn.remote_address = None

    await channel._dispatch_envelope(
        conn,
        "native-client",
        {
            "type": "set_workspace_scope",
            "chat_id": "chat-native",
            "workspace_scope": {
                "project_path": str(project),
                "access_mode": "full",
            },
        },
    )

    payload = json.loads(conn.send.await_args.args[0])
    assert payload["event"] == "session_updated"
    assert payload["chat_id"] == "chat-native"
    assert payload["workspace_scope"]["project_path"] == str(project.resolve())
    assert payload["workspace_scope"]["project_name"] == "project"
    assert payload["workspace_scope"]["access_mode"] == "full"
    assert payload["workspace_scope"]["restrict_to_workspace"] is False
    assert payload["workspace_scope"]["sandbox_status"]["restrict_to_workspace"] is False
    assert payload["workspace_scope"]["sandbox_status"]["workspace_root"] == str(project.resolve())
    saved = sessions.read_session_file("websocket:chat-native")
    assert saved["metadata"]["workspace_scope"] == {
        "project_path": str(project.resolve()),
        "access_mode": "full",
    }


@pytest.mark.asyncio
async def test_send_delivers_json_message_with_media_and_reply() -> None:
    bus = MagicMock()
    channel = WebSocketChannel({"enabled": True, "allowFrom": ["*"]}, bus, gateway=_basic_handler(bus))
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
    assert payload["text"] == "hello"
    assert payload["reply_to"] == "m1"
    assert payload["media"] == ["/tmp/a.png"]


@pytest.mark.asyncio
async def test_send_broadcasts_runtime_model_updates() -> None:
    bus = MessageBus()
    channel = WebSocketChannel({"enabled": True, "allowFrom": ["*"]}, bus, gateway=_basic_handler(bus))
    mock_ws = AsyncMock()
    channel._attach(mock_ws, "chat-1")

    publish_runtime_model_update(bus, "openai/gpt-4.1", "fast")
    await channel.send(bus.outbound.get_nowait())

    payload = json.loads(mock_ws.send.call_args[0][0])
    assert payload["event"] == "runtime_model_updated"
    assert payload["model_name"] == "openai/gpt-4.1"
    assert payload["model_preset"] == "fast"


@pytest.mark.asyncio
async def test_runtime_model_update_publisher_uses_websocket_outbound_event() -> None:
    bus = MessageBus()

    publish_runtime_model_update(
        bus,
        "openai/gpt-4.1",
        "fast",
    )

    event = bus.outbound.get_nowait()
    assert event.channel == "websocket"
    assert event.chat_id == "*"
    assert event.content == ""
    assert event.metadata == {}
    assert isinstance(event.event, RuntimeModelUpdatedEvent)
    assert event.event.model == "openai/gpt-4.1"
    assert event.event.model_preset == "fast"


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

    monkeypatch.setattr("nanobot.webui.media_gateway.get_media_dir", fake_media_dir)
    channel = WebSocketChannel({"enabled": True, "allowFrom": ["*"]}, bus, gateway=_basic_handler(bus))
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
    channel = WebSocketChannel({"enabled": True, "allowFrom": ["*"]}, bus, gateway=_basic_handler(bus))
    msg = OutboundMessage(channel="websocket", chat_id="missing", content="x")
    await channel.send(msg)
    assert channel._subs == {}


@pytest.mark.asyncio
async def test_send_removes_connection_on_connection_closed() -> None:
    bus = MagicMock()
    channel = WebSocketChannel({"enabled": True, "allowFrom": ["*"]}, bus, gateway=_basic_handler(bus))
    mock_ws = AsyncMock()
    mock_ws.send.side_effect = ConnectionClosed(Close(1006, ""), Close(1006, ""), True)
    channel._attach(mock_ws, "chat-1")

    msg = OutboundMessage(channel="websocket", chat_id="chat-1", content="hello")
    await channel.send(msg)

    assert "chat-1" not in channel._subs
    assert mock_ws not in channel._conn_chats


@pytest.mark.asyncio
async def test_send_progress_includes_structured_tool_events() -> None:
    bus = MagicMock()
    channel = WebSocketChannel({"enabled": True, "allowFrom": ["*"]}, bus, gateway=_basic_handler(bus))
    mock_ws = AsyncMock()
    channel._attach(mock_ws, "chat-1")

    await channel.send(OutboundMessage(
        channel="websocket",
        chat_id="chat-1",
        content='search "hermes"',
        event=ProgressEvent(
            content='search "hermes"',
            tool_hint=True,
            tool_events=[
                {
                    "version": 1,
                    "phase": "start",
                    "call_id": "call-1",
                    "name": "web_search",
                    "arguments": {"query": "hermes", "count": 8},
                    "result": None,
                    "error": None,
                    "files": [],
                    "embeds": [],
                }
            ],
        ),
        metadata={
            "webui_turn_id": "turn-1",
        },
    ))

    payload = json.loads(mock_ws.send.await_args.args[0])
    assert payload["event"] == "message"
    assert payload["kind"] == "tool_hint"
    assert payload["turn_id"] == "turn-1"
    assert payload["turn_phase"] == "activity"
    assert payload["turn_seq"] == 1
    assert payload["tool_events"] == [
        {
            "version": 1,
            "phase": "start",
            "call_id": "call-1",
            "name": "web_search",
            "arguments": {"query": "hermes", "count": 8},
            "result": None,
            "error": None,
            "files": [],
            "embeds": [],
        }
    ]


@pytest.mark.asyncio
async def test_send_file_edit_progress_uses_file_edit_event() -> None:
    bus = MagicMock()
    channel = WebSocketChannel({"enabled": True, "allowFrom": ["*"]}, bus, gateway=_basic_handler(bus))
    mock_ws = AsyncMock()
    channel._attach(mock_ws, "chat-1")

    await channel.send(OutboundMessage(
        channel="websocket",
        chat_id="chat-1",
        content="",
        event=ProgressEvent(
            file_edit_events=[
                {
                    "version": 1,
                    "phase": "start",
                    "call_id": "call-1",
                    "tool": "write_file",
                    "path": "src/app.py",
                    "added": 12,
                    "deleted": 2,
                    "approximate": True,
                    "status": "editing",
                }
            ],
        ),
    ))

    payload = json.loads(mock_ws.send.await_args.args[0])
    assert payload == {
        "event": "file_edit",
        "chat_id": "chat-1",
        "edits": [
            {
                "version": 1,
                "phase": "start",
                "call_id": "call-1",
                "tool": "write_file",
                "path": "src/app.py",
                "added": 12,
                "deleted": 2,
                "approximate": True,
                "status": "editing",
            }
        ],
    }


@pytest.mark.asyncio
async def test_send_progress_includes_agent_ui_blob() -> None:
    bus = MagicMock()
    channel = WebSocketChannel({"enabled": True, "allowFrom": ["*"]}, bus, gateway=_basic_handler(bus))
    mock_ws = AsyncMock()
    channel._attach(mock_ws, "chat-1")

    blob = {
        "kind": "panel",
        "data": {"version": 1, "event": "tick", "id": "r1"},
    }
    await channel.send(OutboundMessage(
        channel="websocket",
        chat_id="chat-1",
        content="progress · panel",
        event=ProgressEvent(content="progress · panel"),
        metadata={OUTBOUND_META_AGENT_UI: blob},
    ))

    payload = json.loads(mock_ws.send.await_args.args[0])
    assert payload["event"] == "message"
    assert payload["kind"] == "progress"
    assert payload["agent_ui"] == blob


@pytest.mark.asyncio
async def test_send_delta_removes_connection_on_connection_closed() -> None:
    bus = MagicMock()
    channel = WebSocketChannel({"enabled": True, "allowFrom": ["*"], "streaming": True}, bus, gateway=_basic_handler(bus))
    mock_ws = AsyncMock()
    mock_ws.send.side_effect = ConnectionClosed(Close(1006, ""), Close(1006, ""), True)
    channel._attach(mock_ws, "chat-1")

    await channel.send_delta("chat-1", "chunk", stream_id="s1")

    assert "chat-1" not in channel._subs
    assert mock_ws not in channel._conn_chats


@pytest.mark.asyncio
async def test_send_delta_emits_delta_and_stream_end() -> None:
    bus = MagicMock()
    channel = WebSocketChannel({"enabled": True, "allowFrom": ["*"], "streaming": True}, bus, gateway=_basic_handler(bus))
    mock_ws = AsyncMock()
    channel._attach(mock_ws, "chat-1")

    await channel.send_delta("chat-1", "part", stream_id="sid")
    await channel.send_delta("chat-1", "", stream_id="sid", stream_end=True)

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
    assert "text" not in second


@pytest.mark.asyncio
async def test_send_delta_stream_end_includes_inline_final_text() -> None:
    bus = MagicMock()
    channel = WebSocketChannel({"enabled": True, "allowFrom": ["*"], "streaming": True}, bus, gateway=_basic_handler(bus))
    mock_ws = AsyncMock()
    channel._attach(mock_ws, "chat-1")

    await channel.send_delta(
        "chat-1",
        "merged plain text",
        stream_id="sid",
        stream_end=True,
    )

    mock_ws.send.assert_awaited_once()
    final = json.loads(mock_ws.send.await_args.args[0])
    assert final["event"] == "stream_end"
    assert final["chat_id"] == "chat-1"
    assert final["stream_id"] == "sid"
    assert final["text"] == "merged plain text"


@pytest.mark.asyncio
async def test_send_delta_stream_end_rewrites_local_markdown_image(monkeypatch, tmp_path) -> None:
    bus = MagicMock()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "diagram.png").write_bytes(b"\x89PNG\r\n\x1a\nimage")
    media = tmp_path / "media"

    def fake_media_dir(channel: str | None = None):
        path = media / channel if channel else media
        path.mkdir(parents=True, exist_ok=True)
        return path

    monkeypatch.setattr("nanobot.webui.media_gateway.get_media_dir", fake_media_dir)
    channel = WebSocketChannel(
        {"enabled": True, "allowFrom": ["*"], "streaming": True},
        bus,
        gateway=_basic_handler(bus, workspace_path=workspace),
    )
    mock_ws = AsyncMock()
    channel._attach(mock_ws, "chat-1")

    await channel.send_delta("chat-1", "![Diagram](", stream_id="sid")
    await channel.send_delta("chat-1", "diagram.png)", stream_id="sid")
    await channel.send_delta("chat-1", "", stream_id="sid", stream_end=True)

    assert mock_ws.send.await_count == 3
    final = json.loads(mock_ws.send.call_args_list[2][0][0])
    assert final["event"] == "stream_end"
    assert final["text"].startswith("![Diagram](/api/media/")


@pytest.mark.asyncio
async def test_send_delta_stream_end_rewrites_inline_final_text(monkeypatch, tmp_path) -> None:
    bus = MagicMock()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "diagram.png").write_bytes(b"\x89PNG\r\n\x1a\nimage")
    media = tmp_path / "media"

    def fake_media_dir(channel: str | None = None):
        path = media / channel if channel else media
        path.mkdir(parents=True, exist_ok=True)
        return path

    monkeypatch.setattr("nanobot.webui.media_gateway.get_media_dir", fake_media_dir)
    channel = WebSocketChannel(
        {"enabled": True, "allowFrom": ["*"], "streaming": True},
        bus,
        gateway=_basic_handler(bus, workspace_path=workspace),
    )
    mock_ws = AsyncMock()
    channel._attach(mock_ws, "chat-1")

    await channel.send_delta(
        "chat-1",
        "![Diagram](diagram.png)",
        stream_id="sid",
        stream_end=True,
    )

    mock_ws.send.assert_awaited_once()
    final = json.loads(mock_ws.send.await_args.args[0])
    assert final["event"] == "stream_end"
    assert final["text"].startswith("![Diagram](/api/media/")


@pytest.mark.asyncio
async def test_send_reasoning_delta_emits_streaming_frame() -> None:
    bus = MagicMock()
    channel = WebSocketChannel({"enabled": True, "allowFrom": ["*"]}, bus, gateway=_basic_handler(bus))
    mock_ws = AsyncMock()
    channel._attach(mock_ws, "chat-1")

    await channel.send_reasoning_delta(
        "chat-1",
        "step-by-step thinking",
        stream_id="r1",
    )

    mock_ws.send.assert_awaited_once()
    payload = json.loads(mock_ws.send.await_args.args[0])
    assert payload["event"] == "reasoning_delta"
    assert payload["chat_id"] == "chat-1"
    assert payload["text"] == "step-by-step thinking"
    assert payload["stream_id"] == "r1"


@pytest.mark.asyncio
async def test_send_reasoning_end_emits_close_frame() -> None:
    bus = MagicMock()
    channel = WebSocketChannel({"enabled": True, "allowFrom": ["*"]}, bus, gateway=_basic_handler(bus))
    mock_ws = AsyncMock()
    channel._attach(mock_ws, "chat-1")

    await channel.send_reasoning_end("chat-1", stream_id="r1")

    payload = json.loads(mock_ws.send.await_args.args[0])
    assert payload == {"event": "reasoning_end", "chat_id": "chat-1", "stream_id": "r1"}


@pytest.mark.asyncio
async def test_send_reasoning_one_shot_expands_to_delta_plus_end() -> None:
    """``send_reasoning`` produces one delta and one end."""
    bus = MagicMock()
    channel = WebSocketChannel({"enabled": True, "allowFrom": ["*"]}, bus, gateway=_basic_handler(bus))
    mock_ws = AsyncMock()
    channel._attach(mock_ws, "chat-1")

    await channel.send_reasoning(OutboundMessage(
        channel="websocket",
        chat_id="chat-1",
        content="thinking",
        event=ProgressEvent(content="thinking", reasoning=True),
    ))

    assert mock_ws.send.await_count == 2
    first = json.loads(mock_ws.send.call_args_list[0][0][0])
    second = json.loads(mock_ws.send.call_args_list[1][0][0])
    assert first["event"] == "reasoning_delta"
    assert first["text"] == "thinking"
    assert second["event"] == "reasoning_end"


@pytest.mark.asyncio
async def test_send_reasoning_delta_drops_empty_chunks() -> None:
    bus = MagicMock()
    channel = WebSocketChannel({"enabled": True, "allowFrom": ["*"]}, bus, gateway=_basic_handler(bus))
    mock_ws = AsyncMock()
    channel._attach(mock_ws, "chat-1")

    await channel.send_reasoning_delta("chat-1", "")

    mock_ws.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_reasoning_without_subscribers_is_noop() -> None:
    bus = MagicMock()
    channel = WebSocketChannel({"enabled": True, "allowFrom": ["*"]}, bus, gateway=_basic_handler(bus))

    await channel.send_reasoning_delta("unattached", "thinking", None)
    await channel.send_reasoning_end("unattached", None)
    assert channel._subs == {}


@pytest.mark.asyncio
async def test_stream_transcript_persists_without_subscribers() -> None:
    from nanobot.webui.transcript import build_webui_thread_response, read_transcript_lines

    bus = MagicMock()
    channel = WebSocketChannel(
        {"enabled": True, "allowFrom": ["*"], "streaming": True},
        bus,
        gateway=_basic_handler(bus),
    )

    await channel.send_delta("chat-1", "hello", stream_id="s1")
    await channel.send_delta("chat-1", " world", stream_id="s1")
    await channel.send_delta("chat-1", "", stream_id="s1", stream_end=True)
    await channel.send(OutboundMessage(
        channel="websocket",
        chat_id="chat-1",
        content="",
        event=TurnEndEvent(latency_ms=42),
    ))

    assert channel._subs == {}
    lines = read_transcript_lines("websocket:chat-1")
    assert [line["event"] for line in lines] == ["delta", "delta", "stream_end", "turn_end"]
    body = build_webui_thread_response("websocket:chat-1")
    assert body is not None
    assert body["messages"][-1]["role"] == "assistant"
    assert body["messages"][-1]["content"] == "hello world"
    assert body["messages"][-1]["latencyMs"] == 42


@pytest.mark.asyncio
async def test_send_turn_end_emits_turn_end_event() -> None:
    bus = MagicMock()
    channel = WebSocketChannel({"enabled": True, "allowFrom": ["*"]}, bus, gateway=_basic_handler(bus))
    mock_ws = AsyncMock()
    channel._attach(mock_ws, "chat-1")

    await channel.send(OutboundMessage(
        channel="websocket",
        chat_id="chat-1",
        content="",
        event=TurnEndEvent(),
    ))

    assert _sent_ws_payloads(mock_ws) == [
        {"event": "turn_end", "chat_id": "chat-1"},
        {"event": "session_updated", "chat_id": "chat-1", "scope": "thread"},
    ]


@pytest.mark.asyncio
async def test_send_turn_end_includes_latency_ms_when_present() -> None:
    bus = MagicMock()
    channel = WebSocketChannel({"enabled": True, "allowFrom": ["*"]}, bus, gateway=_basic_handler(bus))
    mock_ws = AsyncMock()
    channel._attach(mock_ws, "chat-1")

    await channel.send(OutboundMessage(
        channel="websocket",
        chat_id="chat-1",
        content="",
        event=TurnEndEvent(latency_ms=1500),
    ))

    assert _sent_ws_payloads(mock_ws) == [
        {"event": "turn_end", "chat_id": "chat-1", "latency_ms": 1500},
        {"event": "session_updated", "chat_id": "chat-1", "scope": "thread"},
    ]


@pytest.mark.asyncio
async def test_send_turn_end_includes_goal_state_when_present() -> None:
    bus = MagicMock()
    channel = WebSocketChannel({"enabled": True, "allowFrom": ["*"]}, bus, gateway=_basic_handler(bus))
    mock_ws = AsyncMock()
    channel._attach(mock_ws, "chat-1")

    blob = {"active": True, "ui_summary": "Explore codebase"}
    await channel.send(OutboundMessage(
        channel="websocket",
        chat_id="chat-1",
        content="",
        event=TurnEndEvent(goal_state=blob),
    ))

    assert _sent_ws_payloads(mock_ws) == [
        {"event": "turn_end", "chat_id": "chat-1", "goal_state": blob},
        {"event": "session_updated", "chat_id": "chat-1", "scope": "thread"},
    ]


@pytest.mark.asyncio
async def test_send_goal_status_running_emits_event_with_started_at() -> None:
    bus = MagicMock()
    channel = WebSocketChannel({"enabled": True, "allowFrom": ["*"]}, bus, gateway=_basic_handler(bus))
    mock_ws = AsyncMock()
    channel._attach(mock_ws, "chat-1")

    await channel.send(OutboundMessage(
        channel="websocket",
        chat_id="chat-1",
        content="",
        event=GoalStatusEvent(status="running", started_at=1_700_000_000.5),
    ))

    mock_ws.send.assert_awaited_once()
    body = json.loads(mock_ws.send.await_args.args[0])
    assert body == {
        "event": "goal_status",
        "chat_id": "chat-1",
        "status": "running",
        "started_at": 1_700_000_000.5,
    }


@pytest.mark.asyncio
async def test_send_goal_status_idle_omits_started_at() -> None:
    bus = MagicMock()
    channel = WebSocketChannel({"enabled": True, "allowFrom": ["*"]}, bus, gateway=_basic_handler(bus))
    mock_ws = AsyncMock()
    channel._attach(mock_ws, "chat-1")

    await channel.send(OutboundMessage(
        channel="websocket",
        chat_id="chat-1",
        content="",
        event=GoalStatusEvent(status="idle", started_at=99.0),
    ))

    mock_ws.send.assert_awaited_once()
    body = json.loads(mock_ws.send.await_args.args[0])
    assert body == {"event": "goal_status", "chat_id": "chat-1", "status": "idle"}


@pytest.mark.asyncio
async def test_send_goal_state_emits_blob_per_chat() -> None:
    bus = MagicMock()
    channel = WebSocketChannel({"enabled": True, "allowFrom": ["*"]}, bus, gateway=_basic_handler(bus))
    mock_a = AsyncMock()
    mock_b = AsyncMock()
    channel._attach(mock_a, "chat-a")
    channel._attach(mock_b, "chat-b")

    await channel.send(OutboundMessage(
        channel="websocket",
        chat_id="chat-a",
        content="",
        event=GoalStateSyncEvent(goal_state={"active": True, "ui_summary": "A"}),
    ))

    mock_a.send.assert_awaited_once()
    mock_b.send.assert_not_called()
    body = json.loads(mock_a.send.await_args.args[0])
    assert body == {
        "event": "goal_state",
        "chat_id": "chat-a",
        "goal_state": {"active": True, "ui_summary": "A"},
    }


@pytest.mark.asyncio
async def test_maybe_push_active_goal_state_noop_without_session_manager() -> None:
    bus = MagicMock()
    channel = WebSocketChannel({"enabled": True, "allowFrom": ["*"]}, bus, gateway=_basic_handler(bus))
    mock_ws = AsyncMock()
    channel._attach(mock_ws, "chat-1")
    await channel._maybe_push_active_goal_state("chat-1")
    mock_ws.send.assert_not_called()


@pytest.mark.asyncio
async def test_maybe_push_active_goal_state_skips_when_no_goal_on_disk() -> None:
    bus = MagicMock()
    sm = MagicMock()
    sm.read_session_file.return_value = None
    channel = WebSocketChannel(
        {"enabled": True, "allowFrom": ["*"]},
        bus,
        gateway=_basic_handler(bus, session_manager=sm),
    )
    mock_ws = AsyncMock()
    channel._attach(mock_ws, "chat-1")
    await channel._maybe_push_active_goal_state("chat-1")
    mock_ws.send.assert_not_called()


@pytest.mark.asyncio
async def test_maybe_push_active_goal_state_notifies_when_goal_active_on_disk() -> None:
    bus = MagicMock()
    sm = MagicMock()
    sm.read_session_file.return_value = {
        "metadata": {
            "goal_state": {
                "status": "active",
                "objective": "finish docs",
                "ui_summary": "Docs",
            },
        },
        "messages": [],
    }
    channel = WebSocketChannel(
        {"enabled": True, "allowFrom": ["*"]},
        bus,
        gateway=_basic_handler(bus, session_manager=sm),
    )
    mock_ws = AsyncMock()
    channel._attach(mock_ws, "chat-1")
    await channel._maybe_push_active_goal_state("chat-1")
    mock_ws.send.assert_awaited_once()
    body = json.loads(mock_ws.send.await_args.args[0])
    assert body["event"] == "goal_state"
    assert body["chat_id"] == "chat-1"
    assert body["goal_state"]["active"] is True
    assert body["goal_state"]["objective"] == "finish docs"
    assert body["goal_state"]["ui_summary"] == "Docs"


@pytest.mark.asyncio
async def test_maybe_push_turn_run_wall_clock_skips_when_no_active_turn() -> None:
    bus = MagicMock()
    channel = WebSocketChannel({"enabled": True, "allowFrom": ["*"]}, bus, gateway=_basic_handler(bus))
    mock_ws = AsyncMock()
    channel._attach(mock_ws, "chat-1")
    from nanobot.session import webui_turns as wth

    wth._WEBSOCKET_TURN_WALL_STARTED_AT.clear()
    await channel._maybe_push_turn_run_wall_clock("chat-1")
    mock_ws.send.assert_not_called()


@pytest.mark.asyncio
async def test_maybe_push_turn_run_wall_clock_replays_running() -> None:
    bus = MagicMock()
    channel = WebSocketChannel({"enabled": True, "allowFrom": ["*"]}, bus, gateway=_basic_handler(bus))
    mock_ws = AsyncMock()
    channel._attach(mock_ws, "chat-1")
    from nanobot.session import webui_turns as wth

    wth._WEBSOCKET_TURN_WALL_STARTED_AT.clear()
    try:
        wth._WEBSOCKET_TURN_WALL_STARTED_AT["chat-1"] = 1_700_000_000.0
        await channel._maybe_push_turn_run_wall_clock("chat-1")
    finally:
        wth._WEBSOCKET_TURN_WALL_STARTED_AT.pop("chat-1", None)

    mock_ws.send.assert_awaited_once()
    body = json.loads(mock_ws.send.await_args.args[0])
    assert body == {
        "event": "goal_status",
        "chat_id": "chat-1",
        "status": "running",
        "started_at": 1_700_000_000.0,
    }


@pytest.mark.asyncio
async def test_send_session_updated_emits_session_updated_event() -> None:
    bus = MagicMock()
    channel = WebSocketChannel({"enabled": True, "allowFrom": ["*"]}, bus, gateway=_basic_handler(bus))
    mock_ws = AsyncMock()
    channel._attach(mock_ws, "chat-1")

    await channel.send(OutboundMessage(
        channel="websocket",
        chat_id="chat-1",
        content="",
        event=SessionUpdatedEvent(),
    ))

    mock_ws.send.assert_awaited_once()
    body = json.loads(mock_ws.send.await_args.args[0])
    assert body == {"event": "session_updated", "chat_id": "chat-1"}


@pytest.mark.asyncio
async def test_send_session_updated_includes_scope_when_present() -> None:
    bus = MagicMock()
    channel = WebSocketChannel({"enabled": True, "allowFrom": ["*"]}, bus, gateway=_basic_handler(bus))
    mock_ws = AsyncMock()
    channel._attach(mock_ws, "chat-1")

    await channel.send(OutboundMessage(
        channel="websocket",
        chat_id="chat-1",
        content="",
        event=SessionUpdatedEvent(scope="metadata"),
    ))

    mock_ws.send.assert_awaited_once()
    body = json.loads(mock_ws.send.await_args.args[0])
    assert body == {"event": "session_updated", "chat_id": "chat-1", "scope": "metadata"}


@pytest.mark.asyncio
async def test_send_non_connection_closed_exception_is_raised() -> None:
    bus = MagicMock()
    channel = WebSocketChannel({"enabled": True, "allowFrom": ["*"]}, bus, gateway=_basic_handler(bus))
    mock_ws = AsyncMock()
    mock_ws.send.side_effect = RuntimeError("unexpected")
    channel._attach(mock_ws, "chat-1")

    msg = OutboundMessage(channel="websocket", chat_id="chat-1", content="hello")
    with pytest.raises(RuntimeError, match="unexpected"):
        await channel.send(msg)


@pytest.mark.asyncio
async def test_send_delta_missing_connection_is_noop() -> None:
    bus = MagicMock()
    channel = WebSocketChannel({"enabled": True, "allowFrom": ["*"], "streaming": True}, bus, gateway=_basic_handler(bus))
    # No exception, no error — just a no-op
    await channel.send_delta("nonexistent", "chunk", stream_id="s1")
    assert channel._subs == {}


@pytest.mark.asyncio
async def test_stop_is_idempotent() -> None:
    bus = MagicMock()
    channel = WebSocketChannel({"enabled": True, "allowFrom": ["*"]}, bus, gateway=_basic_handler(bus))
    # stop() before start() should not raise
    await channel.stop()
    await channel.stop()
    assert channel._subs == {}


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
    config.model_presets["deep"] = ModelPresetConfig(
        model="anthropic/claude-opus-4-5",
        provider="anthropic",
        reasoning_effort="high",
    )
    config.tools.web.search.provider = "brave"
    config.tools.web.search.api_key = "brave-secret"
    save_config(config, config_path)
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)
    monkeypatch.setattr(
        "nanobot.webui.settings_api._oauth_provider_status",
        lambda _spec: {
            "configured": False,
            "account": None,
            "expires_at": None,
            "login_supported": True,
        },
    )

    channel = _ch(bus, port=port)
    channel.gateway.tokens.api_tokens["tok"] = time.monotonic() + 300

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
        assert body["agent"]["model_preset"] == "default"
        assert body["agent"]["max_tokens"] == 8192
        assert body["agent"]["timezone"] == "UTC"
        assert body["agent"]["tool_hint_max_length"] == 40
        presets = {preset["name"]: preset for preset in body["model_presets"]}
        assert presets["default"]["active"] is True
        assert presets["deep"]["reasoning_effort"] == "high"
        providers = {provider["name"]: provider for provider in body["providers"]}
        assert providers["openai"]["configured"] is True
        assert providers["openai"]["api_key_hint"] == "secr••••-key"
        assert providers["azure_openai"]["api_key_required"] is False  # AAD auth supported; no static key required
        assert providers["openrouter"]["configured"] is False
        assert providers["openrouter"]["api_key_required"] is True
        assert providers["skywork"]["label"] == "Skywork"
        assert providers["skywork"]["default_api_base"] == "https://api.apifree.ai/agent/v1"
        assert providers["ant_ling"]["label"] == "Ant Ling"
        assert providers["ant_ling"]["default_api_base"] == "https://api.ant-ling.com/v1"
        assert providers["atomic_chat"]["configured"] is False
        assert providers["atomic_chat"]["api_key_required"] is False
        assert providers["atomic_chat"]["default_api_base"] == "http://localhost:1337/v1"
        assert providers["openai_codex"]["auth_type"] == "oauth"
        assert providers["openai_codex"]["configured"] is False
        assert body["agent"]["has_api_key"] is True
        assert body["web_search"]["provider"] == "brave"
        assert body["web_search"]["api_key_hint"] == "brav••••cret"
        assert body["web_search"]["max_results"] == 5
        assert body["web"]["fetch"]["use_jina_reader"] is True
        search_providers = {provider["name"]: provider for provider in body["web_search"]["providers"]}
        assert search_providers["duckduckgo"]["credential"] == "none"
        assert search_providers["exa"]["credential"] == "api_key"
        assert search_providers["bocha"]["credential"] == "api_key"
        assert search_providers["volcengine"]["credential"] == "api_key"
        assert search_providers["keenable"]["credential"] == "optional_api_key"
        assert search_providers["searxng"]["credential"] == "base_url"
        assert body["image_generation"]["enabled"] is False
        assert body["image_generation"]["provider"] == "openrouter"
        assert body["image_generation"]["provider_configured"] is False
        assert body["image_generation"]["default_aspect_ratio"] == "1:1"
        image_providers = {
            provider["name"]: provider
            for provider in body["image_generation"]["providers"]
        }
        assert image_providers["openrouter"]["label"] == "OpenRouter"
        assert image_providers["openrouter"]["configured"] is False
        assert image_providers["openai_codex"]["auth_type"] == "oauth"
        assert image_providers["openai_codex"]["configured"] is False
        assert image_providers["gemini"]["label"] == "Gemini"
        assert body["runtime"]["config_path"] == str(config_path)
        workspace_path = body["runtime"]["workspace_path"].replace("\\", "/")
        assert workspace_path.endswith("/.nanobot/workspace")
        assert body["runtime"]["gateway_port"] == 18790
        assert body["advanced"]["exec_enabled"] is True
        assert body["advanced"]["webui_allow_local_service_access"] is True
        assert body["advanced"]["webui_default_access_mode"] == "default"
        assert body["advanced"]["private_service_protection_enabled"] is True
        assert body["advanced"]["mcp_server_count"] == 0
        assert body["restart_required_sections"] == []
        assert "secret-key" not in settings.text
        assert "brave-secret" not in settings.text

        unknown_api = await _http_get(
            f"http://127.0.0.1:{port}/api/settings/model-configurations/missing",
            headers={"Authorization": "Bearer tok"},
        )
        assert unknown_api.status_code == 404
        assert "<!doctype html>" not in unknown_api.text.lower()

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
        assert provider_body["image_generation"]["provider_configured"] is True
        assert "sk-or-test" not in provider_updated.text

        local_provider_updated = await _http_get(
            "http://127.0.0.1:"
            f"{port}/api/settings/provider/update?provider=atomic_chat"
            "&api_base=http%3A%2F%2Flocalhost%3A1337%2Fv1",
            headers={"Authorization": "Bearer tok"},
        )
        assert local_provider_updated.status_code == 200
        local_provider_body = local_provider_updated.json()
        local_provider_rows = {
            provider["name"]: provider for provider in local_provider_body["providers"]
        }
        assert local_provider_rows["atomic_chat"]["configured"] is True
        assert "localhost:1337" in local_provider_updated.text

        updated = await _http_get(
            "http://127.0.0.1:"
            f"{port}/api/settings/update?model=atomic_chat/test"
            "&provider=atomic_chat&timezone=Asia%2FShanghai"
            "&bot_name=Nano&bot_icon=N&tool_hint_max_length=120",
            headers={"Authorization": "Bearer tok"},
        )
        assert updated.status_code == 200
        updated_body = updated.json()
        assert updated_body["requires_restart"] is True
        assert updated_body["restart_required_sections"] == ["runtime"]

        preset_updated = await _http_get(
            "http://127.0.0.1:"
            f"{port}/api/settings/update?model_preset=deep",
            headers={"Authorization": "Bearer tok"},
        )
        assert preset_updated.status_code == 200
        assert preset_updated.json()["agent"]["model"] == "anthropic/claude-opus-4-5"

        bad_preset = await _http_get(
            "http://127.0.0.1:"
            f"{port}/api/settings/update?model_preset=missing",
            headers={"Authorization": "Bearer tok"},
        )
        assert bad_preset.status_code == 400

        created_preset = await _http_get(
            "http://127.0.0.1:"
            f"{port}/api/settings/model-configurations/create"
            "?label=Fast%20writing&provider=openai&model=openai%2Fgpt-4.1-mini",
            headers={"Authorization": "Bearer tok"},
        )
        assert created_preset.status_code == 200
        created_body = created_preset.json()
        assert created_body["agent"]["model_preset"] == "fast-writing"
        assert created_body["agent"]["model"] == "openai/gpt-4.1-mini"
        created_presets = {
            preset["name"]: preset for preset in created_body["model_presets"]
        }
        assert created_presets["fast-writing"]["label"] == "Fast writing"
        assert created_presets["fast-writing"]["provider"] == "openai"

        updated_preset = await _http_get(
            "http://127.0.0.1:"
            f"{port}/api/settings/model-configurations/update"
            "?name=fast-writing&label=Codex&provider=openai&model=openai%2Fgpt-5.5",
            headers={"Authorization": "Bearer tok"},
        )
        assert updated_preset.status_code == 200
        updated_preset_body = updated_preset.json()
        assert updated_preset_body["agent"]["model_preset"] == "fast-writing"
        assert updated_preset_body["agent"]["model"] == "openai/gpt-5.5"
        updated_presets = {
            preset["name"]: preset for preset in updated_preset_body["model_presets"]
        }
        assert updated_presets["fast-writing"]["label"] == "Codex"

        duplicate_preset = await _http_get(
            "http://127.0.0.1:"
            f"{port}/api/settings/model-configurations/create"
            "?label=Fast%20writing&provider=openai&model=openai%2Fgpt-4.1-mini",
            headers={"Authorization": "Bearer tok"},
        )
        assert duplicate_preset.status_code == 409

        search_updated = await _http_get(
            "http://127.0.0.1:"
            f"{port}/api/settings/web-search/update?provider=searxng"
            "&base_url=https%3A%2F%2Fsearch.example.com"
            "&max_results=8&timeout=45&use_jina_reader=false",
            headers={"Authorization": "Bearer tok"},
        )
        assert search_updated.status_code == 200
        search_body = search_updated.json()
        assert search_body["requires_restart"] is True
        assert search_body["restart_required_sections"] == ["browser", "runtime"]
        assert search_body["web_search"]["provider"] == "searxng"
        assert search_body["web_search"]["api_key_hint"] is None
        assert search_body["web_search"]["base_url"] == "https://search.example.com"
        assert search_body["web_search"]["max_results"] == 8
        assert search_body["web"]["fetch"]["use_jina_reader"] is False

        network_safety_updated = await _http_get(
            "http://127.0.0.1:"
            f"{port}/api/settings/network-safety/update?webui_allow_local_service_access=false&webui_default_access_mode=full",
            headers={"Authorization": "Bearer tok"},
        )
        assert network_safety_updated.status_code == 200
        network_safety_body = network_safety_updated.json()
        assert network_safety_body["requires_restart"] is True
        assert network_safety_body["restart_required_sections"] == ["browser", "runtime"]
        assert network_safety_body["advanced"]["webui_allow_local_service_access"] is False
        assert network_safety_body["advanced"]["webui_default_access_mode"] == "full"
        assert network_safety_body["advanced"]["private_service_protection_enabled"] is True

        image_updated = await _http_get(
            "http://127.0.0.1:"
            f"{port}/api/settings/image-generation/update?enabled=true"
            "&provider=openrouter&model=openai%2Fgpt-image-1"
            "&default_aspect_ratio=16%3A9&default_image_size=2K"
            "&max_images_per_turn=3",
            headers={"Authorization": "Bearer tok"},
        )
        assert image_updated.status_code == 200
        image_body = image_updated.json()
        assert image_body["requires_restart"] is True
        assert image_body["restart_required_sections"] == ["browser", "image", "runtime"]
        assert image_body["image_generation"]["enabled"] is True
        assert image_body["image_generation"]["model"] == "openai/gpt-image-1"
        assert image_body["image_generation"]["default_aspect_ratio"] == "16:9"
        assert image_body["image_generation"]["default_image_size"] == "2K"
        assert image_body["image_generation"]["max_images_per_turn"] == 3

        image_provider_updated = await _http_get(
            "http://127.0.0.1:"
            f"{port}/api/settings/provider/update?provider=openrouter"
            "&api_key=sk-or-next&api_base=https%3A%2F%2Fopenrouter.ai%2Fapi%2Fv1",
            headers={"Authorization": "Bearer tok"},
        )
        assert image_provider_updated.status_code == 200
        assert image_provider_updated.json()["requires_restart"] is True
        assert image_provider_updated.json()["restart_required_sections"] == [
            "browser",
            "image",
            "runtime",
        ]
        assert "sk-or-next" not in image_provider_updated.text

        bad_web = await _http_get(
            "http://127.0.0.1:"
            f"{port}/api/settings/web-search/update?provider=duckduckgo&max_results=99",
            headers={"Authorization": "Bearer tok"},
        )
        assert bad_web.status_code == 400

        bad_image = await _http_get(
            "http://127.0.0.1:"
            f"{port}/api/settings/image-generation/update?provider=missing",
            headers={"Authorization": "Bearer tok"},
        )
        assert bad_image.status_code == 400

        saved = load_config(config_path)
        assert saved.agents.defaults.model == "atomic_chat/test"
        assert saved.agents.defaults.provider == "atomic_chat"
        assert saved.agents.defaults.model_preset == "fast-writing"
        assert saved.model_presets["fast-writing"].label == "Codex"
        assert saved.model_presets["fast-writing"].model == "openai/gpt-5.5"
        assert saved.model_presets["fast-writing"].provider == "openai"
        assert saved.agents.defaults.timezone == "Asia/Shanghai"
        assert saved.agents.defaults.bot_name == "Nano"
        assert saved.agents.defaults.bot_icon == "N"
        assert saved.agents.defaults.tool_hint_max_length == 120
        assert saved.providers.openrouter.api_key == "sk-or-next"
        assert saved.providers.openrouter.api_base == "https://openrouter.ai/api/v1"
        assert saved.providers.atomic_chat.api_base == "http://localhost:1337/v1"
        assert saved.tools.web.search.provider == "searxng"
        assert saved.tools.web.search.api_key == ""
        assert saved.tools.web.search.base_url == "https://search.example.com"
        assert saved.tools.web.search.max_results == 8
        assert saved.tools.web.search.timeout == 45
        assert saved.tools.web.fetch.use_jina_reader is False
        assert saved.tools.webui_allow_local_service_access is False
        assert saved.tools.image_generation.enabled is True
        assert saved.tools.image_generation.provider == "openrouter"
        assert saved.tools.image_generation.model == "openai/gpt-image-1"
        assert saved.tools.image_generation.default_aspect_ratio == "16:9"
        assert saved.tools.image_generation.default_image_size == "2K"
        assert saved.tools.image_generation.max_images_per_turn == 3
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_commands_api_returns_slash_command_metadata(bus: MagicMock) -> None:
    port = 29892
    channel = _ch(bus, port=port)
    channel.gateway.tokens.api_tokens["tok"] = time.monotonic() + 300

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
        assert commands["/new"]["lifecycle"] == "finalize_active_turn"
        assert commands["/stop"]["lifecycle"] == "stop_active_turn"
        assert commands["/history"]["lifecycle"] == "side_channel"
        assert commands["/history"]["arg_hint"] == "[n]"
        assert commands["/history"]["accepts_args"] is True
        assert commands["/goal"]["lifecycle"] == "agent_turn_with_args"
        assert commands["/goal"]["accepts_args"] is True
        assert all("description" in row for row in body["commands"])
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_bootstrap_exposes_native_surface(bus: MagicMock) -> None:
    port = 29893
    channel = WebSocketChannel(
        {
            "enabled": True,
            "allowFrom": ["*"],
            "host": "127.0.0.1",
            "port": port,
            "path": "/ws",
            "tokenIssueSecret": "native-secret",
            "websocketRequiresToken": True,
        },
        bus,
        gateway=_basic_handler(
            bus,
            token_issue_secret="native-secret",
            runtime_surface="native",
            runtime_capabilities_overrides={"can_pick_folder": True},
        ),
    )

    server_task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)

    try:
        response = await _http_get(
            f"http://127.0.0.1:{port}/webui/bootstrap",
            headers={"X-Nanobot-Auth": "native-secret"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["runtime_surface"] == "native"
        assert body["runtime_capabilities"]["can_pick_folder"] is True
        assert body["runtime_capabilities"]["can_restart_engine"] is True
        assert body["token"].startswith("nbwt_")
        assert body["api_token"].startswith("nbwt_")
        assert body["api_token"] != body["token"]
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

    body = settings_payload()

    assert body["agent"]["provider"] == "minimax_anthropic"


def test_settings_payload_exposes_api_type_only_for_openai(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config = Config()
    config.providers.openai.api_type = "responses"
    save_config(config, config_path)
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)

    body = settings_payload()
    providers = {provider["name"]: provider for provider in body["providers"]}

    assert providers["openai"]["api_type"] == "responses"
    assert "api_type" not in providers["custom"]


def test_settings_payload_reports_workspace_sandbox(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config = Config()
    config.tools.restrict_to_workspace = True
    save_config(config, config_path)
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)
    monkeypatch.setenv("NANOBOT_SANDBOX_ENFORCED", "macos_app_sandbox")

    body = settings_payload()
    sandbox = body["advanced"]["workspace_sandbox"]

    assert sandbox["restrict_to_workspace"] is True
    assert sandbox["level"] == "system"
    assert sandbox["enforced"] is True
    assert sandbox["provider"] == "macos_app_sandbox"
    assert sandbox["provider_label"] == "macOS App Sandbox"


def test_settings_payload_includes_native_runtime_surface(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / "config.json"
    save_config(Config(), config_path)
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)

    body = settings_payload(
        surface="native",
        runtime_capability_overrides={"can_open_logs": True},
        restart_required_sections=["runtime"],
    )

    assert body["surface"] == "native"
    assert body["runtime_surface"] == "native"
    assert body["runtime_capabilities"]["can_open_logs"] is True
    assert body["runtime_capabilities"]["can_restart_engine"] is True
    assert body["restart_behavior_by_section"]["runtime"] == "engineRestart"
    assert body["requires_restart"] is True
    assert body["apply_state"] == {"status": "pending", "sections": ["runtime"]}


def test_update_provider_settings_ignores_api_type_for_non_openai(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / "config.json"
    save_config(Config(), config_path)
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)

    body = update_provider_settings({
        "provider": ["custom"],
        "api_base": ["https://example.test/v1"],
        "api_type": ["responses"],
    })

    assert body["providers"]
    config = load_config(config_path)
    assert config.providers.custom.api_base == "https://example.test/v1"
    assert config.providers.custom.api_type == "auto"


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
                chat_id, "Hello ", stream_id="s1"
            )
            await channel.send_delta(
                chat_id, "world", stream_id="s1"
            )
            await channel.send_delta(
                chat_id, "", stream_id="s1", stream_end=True
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
                event=TurnEndEvent(),
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
        channel.gateway.tokens.issued_tokens = {
            f"nbwt_fill_{i}": time.monotonic() + 300
            for i in range(channel.gateway.tokens.max_tokens)
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
            if reply["event"] == "session_updated":
                reply = json.loads(await client.recv())
            assert reply["event"] == "message"
            assert reply["chat_id"] == new_chat
            assert reply["text"] == "ok"
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_fork_chat_copies_only_prefix_session_and_transcript(
    bus: MagicMock,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    sessions = SessionManager(tmp_path / "sessions")
    source = sessions.get_or_create("websocket:source")
    source.metadata["webui"] = True
    source.add_message("user", "round1")
    source.add_message("assistant", "answer1")
    source.add_message("user", "future")
    sessions.save(source)
    for ev in (
        {"event": "user", "chat_id": "source", "text": "round1"},
        {"event": "message", "chat_id": "source", "text": "answer1"},
        {"event": "user", "chat_id": "source", "text": "future"},
    ):
        append_transcript_object("websocket:source", ev)

    channel = WebSocketChannel(
        {"enabled": True, "allowFrom": ["*"], "host": "127.0.0.1"},
        bus,
        gateway=_basic_handler(bus, session_manager=sessions, workspace_path=tmp_path),
    )
    conn = AsyncMock()

    await channel._dispatch_envelope(
        conn,
        "webui-client",
        {
            "type": "fork_chat",
            "source_chat_id": "source",
            "before_user_index": 1,
            "title": "Fork: Old title",
        },
    )

    sent = [json.loads(call.args[0]) for call in conn.send.await_args_list]
    attached = next(item for item in sent if item["event"] == "attached")
    fork_id = attached["chat_id"]
    saved = sessions.read_session_file(f"websocket:{fork_id}")
    assert [m["content"] for m in saved["messages"]] == ["round1", "answer1"]
    assert saved["metadata"]["title"] == "Fork: Old title"
    fork_lines = read_transcript_lines(f"websocket:{fork_id}")
    assert [line.get("text") for line in fork_lines] == ["round1", "answer1", None]
    assert fork_lines[-1]["event"] == "fork_marker"
    assert all(line.get("chat_id") == fork_id for line in fork_lines)
    assert "future" not in json.dumps(saved, ensure_ascii=False)
    bus.publish_inbound.assert_not_awaited()

@pytest.mark.asyncio
async def test_webui_message_envelope_appends_user_transcript(
    bus: MagicMock,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    sessions = SessionManager(tmp_path / "sessions")
    channel = WebSocketChannel(
        {"enabled": True, "allowFrom": ["*"], "host": "127.0.0.1"},
        bus,
        gateway=_basic_handler(bus, session_manager=sessions, workspace_path=tmp_path),
    )
    conn = AsyncMock()
    conn.remote_address = ("127.0.0.1", 50123)

    await channel._dispatch_envelope(
        conn,
        "webui-client",
        {
            "type": "message",
            "chat_id": "source",
            "content": "round1",
            "webui": True,
        },
    )

    [line] = read_transcript_lines("websocket:source")
    assert {
        "event": line.get("event"),
        "chat_id": line.get("chat_id"),
        "text": line.get("text"),
    } == {"event": "user", "chat_id": "source", "text": "round1"}
    assert isinstance(line.get("turn_id"), str)
    assert line.get("turn_phase") == "user"
    assert line.get("turn_seq") == 1
    inbound = bus.publish_inbound.await_args.args[0]
    assert inbound.chat_id == "source"
    assert inbound.content == "round1"


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
            chat_a = (await _recv_ws_event(client, "attached"))["chat_id"]
            await client.send(json.dumps({"type": "new_chat"}))
            chat_b = (await _recv_ws_event(client, "attached"))["chat_id"]
            assert chat_a != chat_b

            # Push A → client sees A only (FIFO over the single WS).
            await channel.send(
                OutboundMessage(channel="websocket", chat_id=chat_a, content="for-A")
            )
            msg_a = await _recv_ws_event(client, "message")
            assert msg_a["chat_id"] == chat_a
            assert msg_a["text"] == "for-A"

            # Push B → client sees B only.
            await channel.send(
                OutboundMessage(channel="websocket", chat_id=chat_b, content="for-B")
            )
            msg_b = await _recv_ws_event(client, "message")
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


def test_sessions_list_includes_active_run_started_at(monkeypatch) -> None:
    from websockets.datastructures import Headers
    from websockets.http11 import Request

    from nanobot.session import webui_turns as wth
    from nanobot.webui import ws_http as ws_http_module

    bus = MagicMock()
    session_manager = MagicMock()
    sessions = [
        {
            "key": "websocket:chat-1",
            "created_at": "2026-05-19T10:00:00Z",
            "updated_at": "2026-05-19T10:01:00Z",
            "title": "Running",
            "preview": "work",
            "path": "/private/path",
        },
        {
            "key": "cli:chat-2",
            "created_at": "2026-05-19T10:00:00Z",
            "updated_at": "2026-05-19T10:01:00Z",
        },
    ]
    monkeypatch.setattr(ws_http_module, "list_webui_sessions", lambda _session_manager: sessions)
    channel = WebSocketChannel(
        {"enabled": True, "allowFrom": ["*"]},
        bus,
        gateway=_basic_handler(bus, session_manager=session_manager),
    )
    channel.gateway.tokens.api_tokens["tok"] = time.monotonic() + 300.0

    wth._WEBSOCKET_TURN_WALL_STARTED_AT.clear()
    try:
        wth._WEBSOCKET_TURN_WALL_STARTED_AT["chat-1"] = 1_700_000_000.0
        req = Request("/api/sessions", Headers([("Authorization", "Bearer tok")]))
        resp = asyncio.run(channel.gateway.http._handle_sessions_list(req))
    finally:
        wth._WEBSOCKET_TURN_WALL_STARTED_AT.clear()

    assert resp.status_code == 200
    body = json.loads(resp.body.decode())
    workspace_scope = body["sessions"][0].pop("workspace_scope")
    assert workspace_scope["project_path"] == str(channel.gateway.media.workspace_path)
    assert workspace_scope["access_mode"] in {"restricted", "full"}
    assert body["sessions"] == [
        {
            "key": "websocket:chat-1",
            "created_at": "2026-05-19T10:00:00Z",
            "updated_at": "2026-05-19T10:01:00Z",
            "title": "Running",
            "preview": "work",
            "run_started_at": 1_700_000_000.0,
        }
    ]


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


def test_handle_webui_thread_get_returns_json(tmp_path, monkeypatch) -> None:
    from urllib.parse import quote

    from websockets.datastructures import Headers
    from websockets.http11 import Request

    from nanobot.webui.transcript import append_transcript_object

    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:c1"
    append_transcript_object(key, {"event": "user", "chat_id": "c1", "text": "hi"})
    bus = MagicMock()
    channel = _ch(bus)
    channel.gateway.tokens.api_tokens["tok"] = time.monotonic() + 300.0
    enc = quote(key, safe="")
    req = Request(f"/api/sessions/{enc}/webui-thread", Headers([("Authorization", "Bearer tok")]))
    resp = channel.gateway.http._handle_webui_thread_get(req, enc)
    assert resp.status_code == 200
    body = json.loads(resp.body.decode())
    assert body["sessionKey"] == key
    assert len(body["messages"]) == 1
    assert body["messages"][0]["role"] == "user"
    assert body["messages"][0]["content"] == "hi"


def test_handle_webui_thread_get_accepts_pagination_query(tmp_path, monkeypatch) -> None:
    from urllib.parse import quote

    from websockets.datastructures import Headers
    from websockets.http11 import Request

    from nanobot.webui.transcript import append_transcript_object

    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:paged-route"
    for idx in range(1, 4):
        append_transcript_object(
            key,
            {"event": "user", "chat_id": "paged-route", "text": f"q{idx}"},
        )
        append_transcript_object(
            key,
            {"event": "message", "chat_id": "paged-route", "text": f"a{idx}"},
        )
        append_transcript_object(key, {"event": "turn_end", "chat_id": "paged-route"})

    bus = MagicMock()
    channel = _ch(bus)
    channel.gateway.tokens.api_tokens["tok"] = time.monotonic() + 300.0
    enc = quote(key, safe="")
    req = Request(
        f"/api/sessions/{enc}/webui-thread?limit=2&direction=latest",
        Headers([("Authorization", "Bearer tok")]),
    )

    resp = channel.gateway.http._handle_webui_thread_get(req, enc)

    assert resp.status_code == 200
    body = json.loads(resp.body.decode())
    assert [message["content"] for message in body["messages"]] == ["q3", "a3"]
    assert body["page"]["has_more_before"] is True
    assert body["page"]["before_cursor"]


def test_handle_file_preview_returns_workspace_file(tmp_path) -> None:
    from urllib.parse import quote

    from websockets.datastructures import Headers
    from websockets.http11 import Request

    workspace = tmp_path / "workspace"
    source = workspace / "nanobot" / "agent" / "hook.py"
    source.parent.mkdir(parents=True)
    source.write_text("print('hello')\n", encoding="utf-8")

    gateway = _basic_handler(MagicMock(), workspace_path=workspace)
    gateway.tokens.api_tokens["tok"] = time.monotonic() + 300.0
    key = "websocket:file-preview"
    enc = quote(key, safe="")
    path = quote("nanobot/agent/hook.py:12", safe="")
    req = Request(
        f"/api/sessions/{enc}/file-preview?path={path}",
        Headers([("Authorization", "Bearer tok")]),
    )

    resp = gateway.http._handle_file_preview(req, enc)

    assert resp.status_code == 200
    body = json.loads(resp.body.decode())
    assert body["display_path"] == "nanobot/agent/hook.py"
    assert body["language"] == "python"
    assert body["content"].splitlines() == ["print('hello')"]
    assert body["truncated"] is False


def test_file_preview_normalizes_windows_file_url() -> None:
    from nanobot.webui.file_preview import _clean_preview_path

    assert _clean_preview_path("file:///C:/Users/me/project/app.py") == (
        "C:/Users/me/project/app.py"
    )
    assert _clean_preview_path("file:///tmp/project/app.py") == "/tmp/project/app.py"


def test_handle_file_preview_rejects_paths_outside_workspace(tmp_path) -> None:
    from urllib.parse import quote

    from websockets.datastructures import Headers
    from websockets.http11 import Request

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "secret.py"
    outside.write_text("secret = True\n", encoding="utf-8")

    gateway = _basic_handler(
        MagicMock(),
        workspace_path=workspace,
        default_restrict_to_workspace=True,
    )
    gateway.tokens.api_tokens["tok"] = time.monotonic() + 300.0
    key = "websocket:file-preview"
    enc = quote(key, safe="")
    req = Request(
        f"/api/sessions/{enc}/file-preview?path={quote(str(outside), safe='')}",
        Headers([("Authorization", "Bearer tok")]),
    )

    resp = gateway.http._handle_file_preview(req, enc)

    assert resp.status_code == 403


def test_handle_file_preview_allows_paths_outside_workspace_in_full_access(tmp_path) -> None:
    from urllib.parse import quote

    from websockets.datastructures import Headers
    from websockets.http11 import Request

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "notes.py"
    outside.write_text("value = 42\n", encoding="utf-8")

    gateway = _basic_handler(
        MagicMock(),
        workspace_path=workspace,
        default_restrict_to_workspace=False,
    )
    gateway.tokens.api_tokens["tok"] = time.monotonic() + 300.0
    key = "websocket:file-preview"
    enc = quote(key, safe="")
    req = Request(
        f"/api/sessions/{enc}/file-preview?path={quote(str(outside), safe='')}",
        Headers([("Authorization", "Bearer tok")]),
    )

    resp = gateway.http._handle_file_preview(req, enc)

    assert resp.status_code == 200
    body = json.loads(resp.body.decode())
    assert body["path"] == str(outside.resolve())
    assert body["display_path"] == outside.resolve().as_posix()
    assert body["content"].splitlines() == ["value = 42"]


def test_handle_webui_thread_get_backfills_legacy_missing_user_rows(
    tmp_path,
    monkeypatch,
) -> None:
    from urllib.parse import quote

    from websockets.datastructures import Headers
    from websockets.http11 import Request

    from nanobot.webui.transcript import append_transcript_object

    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    workspace = tmp_path / "workspace"
    sessions = SessionManager(workspace)
    key = "websocket:c-legacy"
    session = sessions.get_or_create(key)
    session.add_message("user", "legacy question")
    session.add_message("assistant", "legacy answer")
    sessions.save(session)
    append_transcript_object(
        key,
        {"event": "message", "chat_id": "c-legacy", "text": "legacy answer"},
    )

    bus = MagicMock()
    channel = WebSocketChannel(
        {"enabled": True, "allowFrom": ["*"]},
        bus,
        gateway=_basic_handler(bus, session_manager=sessions, workspace_path=workspace),
    )
    channel.gateway.tokens.api_tokens["tok"] = time.monotonic() + 300.0
    enc = quote(key, safe="")
    req = Request(f"/api/sessions/{enc}/webui-thread", Headers([("Authorization", "Bearer tok")]))
    resp = channel.gateway.http._handle_webui_thread_get(req, enc)

    assert resp.status_code == 200
    body = json.loads(resp.body.decode())
    assert [message["role"] for message in body["messages"]] == ["user", "assistant"]
    assert [message["content"] for message in body["messages"]] == [
        "legacy question",
        "legacy answer",
    ]


def test_handle_webui_thread_get_does_not_backfill_cron_internal_prompt(
    tmp_path,
    monkeypatch,
) -> None:
    from urllib.parse import quote

    from websockets.datastructures import Headers
    from websockets.http11 import Request

    from nanobot.cron.session_turns import CRON_HISTORY_META
    from nanobot.webui.transcript import append_transcript_object

    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    workspace = tmp_path / "workspace"
    sessions = SessionManager(workspace)
    key = "websocket:c-cron"
    session = sessions.get_or_create(key)
    session.add_message(
        "user",
        "Scheduled cron job triggered: 30s-test\n\nInternal reminder prompt",
        **{CRON_HISTORY_META: True},
    )
    session.add_message("assistant", "提醒已经到期。")
    sessions.save(session)
    append_transcript_object(
        key,
        {"event": "message", "chat_id": "c-cron", "text": "提醒已经到期。"},
    )

    bus = MagicMock()
    channel = WebSocketChannel(
        {"enabled": True, "allowFrom": ["*"]},
        bus,
        gateway=_basic_handler(bus, session_manager=sessions, workspace_path=workspace),
    )
    channel.gateway.tokens.api_tokens["tok"] = time.monotonic() + 300.0
    enc = quote(key, safe="")
    req = Request(f"/api/sessions/{enc}/webui-thread", Headers([("Authorization", "Bearer tok")]))
    resp = channel.gateway.http._handle_webui_thread_get(req, enc)

    assert resp.status_code == 200
    body = json.loads(resp.body.decode())
    assert [message["role"] for message in body["messages"]] == ["assistant"]
    assert [message["content"] for message in body["messages"]] == ["提醒已经到期。"]


def test_handle_webui_thread_get_does_not_backfill_trigger_internal_prompt(
    tmp_path,
    monkeypatch,
) -> None:
    from urllib.parse import quote

    from websockets.datastructures import Headers
    from websockets.http11 import Request

    from nanobot.session.automation_turns import AUTOMATION_HISTORY_META
    from nanobot.webui.transcript import append_transcript_object

    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    workspace = tmp_path / "workspace"
    sessions = SessionManager(workspace)
    key = "websocket:c-trigger"
    session = sessions.get_or_create(key)
    session.add_message(
        "user",
        "Local trigger received: PR review",
        **{AUTOMATION_HISTORY_META: {"kind": "local_trigger", "trigger_id": "trg_123"}},
    )
    session.add_message("assistant", "PR #4502 已经开始 review。")
    sessions.save(session)
    append_transcript_object(
        key,
        {"event": "message", "chat_id": "c-trigger", "text": "PR #4502 已经开始 review。"},
    )

    bus = MagicMock()
    channel = WebSocketChannel(
        {"enabled": True, "allowFrom": ["*"]},
        bus,
        gateway=_basic_handler(bus, session_manager=sessions, workspace_path=workspace),
    )
    channel.gateway.tokens.api_tokens["tok"] = time.monotonic() + 300.0
    enc = quote(key, safe="")
    req = Request(f"/api/sessions/{enc}/webui-thread", Headers([("Authorization", "Bearer tok")]))
    resp = channel.gateway.http._handle_webui_thread_get(req, enc)

    assert resp.status_code == 200
    body = json.loads(resp.body.decode())
    assert [message["role"] for message in body["messages"]] == ["assistant"]
    assert [message["content"] for message in body["messages"]] == ["PR #4502 已经开始 review。"]


def test_handle_webui_thread_get_does_not_backfill_hidden_subagent_result(
    tmp_path,
    monkeypatch,
) -> None:
    from urllib.parse import quote

    from websockets.datastructures import Headers
    from websockets.http11 import Request

    from nanobot.session.history_visibility import HIDDEN_HISTORY_META
    from nanobot.webui.transcript import append_transcript_object

    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    workspace = tmp_path / "workspace"
    sessions = SessionManager(workspace)
    key = "websocket:c-subagent"
    session = sessions.get_or_create(key)
    session.add_message(
        "user",
        "internal subagent result",
        **{HIDDEN_HISTORY_META: {"kind": "subagent_result", "subagent_task_id": "sub-1"}},
    )
    session.add_message("assistant", "subagent summary")
    sessions.save(session)
    append_transcript_object(
        key,
        {"event": "message", "chat_id": "c-subagent", "text": "subagent summary"},
    )

    bus = MagicMock()
    channel = WebSocketChannel(
        {"enabled": True, "allowFrom": ["*"]},
        bus,
        gateway=_basic_handler(bus, session_manager=sessions, workspace_path=workspace),
    )
    channel.gateway.tokens.api_tokens["tok"] = time.monotonic() + 300.0
    enc = quote(key, safe="")
    req = Request(f"/api/sessions/{enc}/webui-thread", Headers([("Authorization", "Bearer tok")]))
    resp = channel.gateway.http._handle_webui_thread_get(req, enc)

    assert resp.status_code == 200
    body = json.loads(resp.body.decode())
    assert [message["role"] for message in body["messages"]] == ["assistant"]
    assert [message["content"] for message in body["messages"]] == ["subagent summary"]
