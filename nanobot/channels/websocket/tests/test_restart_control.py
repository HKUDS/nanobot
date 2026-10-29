"""Settings restarts are controls, not persisted chat turns."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from websockets.datastructures import Headers

from nanobot.bus.events import OutboundMessage
from nanobot.channels.websocket.runtime import WebSocketChannel
from nanobot.command.builtin import cmd_restart
from nanobot.command.router import CommandContext
from nanobot.session.manager import SessionManager
from nanobot.utils.restart import RestartController
from nanobot.webui.gateway_services import build_gateway_services
from nanobot.webui.metadata import WEBUI_RESTART_CONTROL_METADATA_KEY
from nanobot.webui.session_list_index import list_webui_sessions

from .test_websocket_channel import _basic_handler, _sent_ws_payloads
from .test_webui_session_admission import _Runtime
from .test_webui_session_admission import runtime as runtime


def _channel(tmp_path: Path, *, allowed: bool = True, sessions=None):
    sessions = sessions or SessionManager(tmp_path / "workspace")
    bus = MagicMock()
    bus.publish_inbound = AsyncMock()
    channel = WebSocketChannel(
        {"enabled": True, "allowFrom": ["*"] if allowed else ["someone-else"]}, bus,
        gateway=_basic_handler(bus, session_manager=sessions, workspace_path=tmp_path / "workspace"),
    )
    connection = AsyncMock()
    connection.remote_address = ("127.0.0.1", 50123)
    connection.request = SimpleNamespace(headers=Headers({"Host": "localhost:8765"}))
    channel.gateway.endpoint.webui_connections.add(connection)
    return sessions, bus, channel, connection


@pytest.mark.asyncio
@pytest.mark.parametrize("existing", ["none", "canonical", "transcript", "both"])
async def test_settings_restart_does_not_create_or_change_chat_history(history, tmp_path, monkeypatch, existing):
    sessions, bus, channel, connection = _channel(tmp_path, sessions=history.sessions)
    monkeypatch.setattr("nanobot.command.builtin.set_restart_notice_to_env", MagicMock())
    key = "websocket:existing"
    if existing in {"canonical", "both"}:
        session = sessions.get_or_create(key)
        session.add_message("user", "Keep my conversation")
        session.metadata.update({"webui": True, "title": "Keep this title"})
        sessions.save(session)
    if existing in {"transcript", "both"}:
        history.append(key, {
            "event": "user", "chat_id": "existing", "text": "Keep my conversation",
        })
    before_rows = list_webui_sessions(sessions)
    before_files = {p: p.read_bytes() for p in tmp_path.rglob("*.jsonl")}
    before_transcript = history.read(key)

    # Use each new connection's default ID, then an existing chat when present.
    chat_ids = ["ready-default-1", "ready-default-2"]
    if existing != "none":
        chat_ids.append("existing")
    for chat_id in chat_ids:
        envelope = {
            "type": "message", "chat_id": chat_id, "content": "/restart", "webui": True,
            "turn_id": f"webui-system:restart-{chat_id}",
        }
        await channel._dispatch_envelope(connection, "browser", envelope)
        message = bus.publish_inbound.await_args.args[0]
        assert message.metadata[WEBUI_RESTART_CONTROL_METADATA_KEY] is True
        controller = RestartController()
        response = await cmd_restart(CommandContext(
            msg=message, session=None, key=message.session_key, raw=message.content,
            loop=SimpleNamespace(restart_request=controller.request),
        ))
        assert not controller.committed
        await channel.send(response)
        await channel.webui_flush(connection)
        assert response.after_delivery is not None
        response.after_delivery()
        assert controller.committed
        # A lost ACK retry must not enqueue a second restart.
        calls = bus.publish_inbound.await_count
        await channel._dispatch_envelope(connection, "browser", envelope)
        assert bus.publish_inbound.await_count == calls

    frames = _sent_ws_payloads(connection)
    assert not any(frame["event"] == "user_message" for frame in frames)
    replies = [frame for frame in frames if frame["event"] == "message"]
    assert len(replies) == len(chat_ids)
    assert all(frame["text"] == "Restarting..." and frame["turn_id"].startswith("webui-system:") for frame in replies)
    assert {p: p.read_bytes() for p in tmp_path.rglob("*.jsonl")} == before_files
    assert history.read(key) == before_transcript
    # A fresh manager uses the public sidebar discovery path, not a cached count.
    fresh = SessionManager(sessions.workspace)
    assert list_webui_sessions(fresh) == before_rows
    if existing in {"canonical", "both"}:
        restored = fresh.get_existing(key)
        assert restored is not None and restored.messages[0]["content"] == "Keep my conversation"
        assert restored.metadata["title"] == "Keep this title"
    await channel._cleanup_connection(connection)


@pytest.mark.asyncio
@pytest.mark.parametrize(("text", "turn_id"), [
    ("/restart", "normal-user-turn"),
    ("/model fast", "webui-system:model-switch"),
    ("/restart later", "webui-system:not-a-restart"),
    ("ordinary message", "webui-system:not-a-command"),
])
async def test_control_prefix_does_not_suppress_ordinary_or_session_command_history(history, tmp_path, text, turn_id):
    sessions, bus, channel, connection = _channel(tmp_path, sessions=history.sessions)
    await channel._dispatch_envelope(connection, "browser", {
        "type": "message", "chat_id": "chat", "content": text, "webui": True, "turn_id": turn_id,
        "metadata": {WEBUI_RESTART_CONTROL_METADATA_KEY: True},
    })
    message = bus.publish_inbound.await_args.args[0]
    assert WEBUI_RESTART_CONTROL_METADATA_KEY not in message.metadata
    await channel.send(OutboundMessage(channel="websocket", chat_id="chat", content="Reply", metadata=message.metadata))
    assert len(list_webui_sessions(sessions)) == 1
    assert [row["text"] for row in history.read("websocket:chat")] == [text, "Reply"]
    await channel._cleanup_connection(connection)


@pytest.mark.asyncio
async def test_restart_control_keeps_the_client_allowlist_check(tmp_path):
    sessions, bus, channel, connection = _channel(tmp_path, allowed=False)
    await channel._dispatch_envelope(connection, "browser", {
        "type": "message", "chat_id": "chat", "content": "/restart", "webui": True,
        "turn_id": "webui-system:restart",
    })
    bus.publish_inbound.assert_not_awaited()
    assert json.loads(connection.send.await_args.args[0])["detail"] == "access_denied"
    assert list_webui_sessions(sessions) == []


@pytest.mark.asyncio
async def test_generic_websocket_cannot_claim_transient_webui_control(tmp_path):
    sessions, bus, channel, connection = _channel(tmp_path)
    channel.gateway.endpoint.webui_connections.remove(connection)
    await channel._dispatch_envelope(connection, "browser", {
        "type": "message", "chat_id": "chat", "content": "/restart", "webui": True,
        "turn_id": "webui-system:restart",
    })
    assert WEBUI_RESTART_CONTROL_METADATA_KEY not in bus.publish_inbound.await_args.args[0].metadata
    assert len(list_webui_sessions(sessions)) == 1
    await channel._cleanup_connection(connection)


async def test_gateway_restart_has_no_chat_side_effects_and_replays_one_receipt(
    runtime: _Runtime, history,
) -> None:
    message = await runtime.message("existing", "Keep this conversation")
    await runtime.execute(message)
    before_sessions = await runtime.sessions.state.list_sessions()
    before_history = history.read("websocket:existing")
    before_session = await runtime.sessions.state.read(runtime.loop._effective_session_key(message))
    runtime.connection.sent.clear()

    await runtime.request("restart-once", "gateway.restart", {})
    accepted = await runtime.response("restart-once")
    assert accepted["result"] == {
        "status": "accepted", "gateway_id": runtime.channel.gateway.tokens.instance_id,
    }
    assert runtime.restart.committed
    await runtime.request("restart-once", "gateway.restart", {})
    assert await runtime.response("restart-once") == accepted
    await runtime.request("restart-again", "gateway.restart", {})
    assert (await runtime.response("restart-again"))["error"] == {
        "status": 409, "message": "restart_unavailable",
    }

    assert runtime.bus.inbound_size == 0
    assert await runtime.sessions.state.list_sessions() == before_sessions
    assert history.read("websocket:existing") == before_history
    after_session = await runtime.sessions.state.read(runtime.loop._effective_session_key(message))
    assert after_session is not None and before_session is not None
    assert after_session.messages == before_session.messages
    assert after_session.metadata == before_session.metadata
    assert all(frame["event"] == "webui_response" for frame in runtime.connection.sent)


async def test_gateway_restart_receipt_from_old_instance_cannot_restart_replacement(
    runtime: _Runtime,
) -> None:
    await runtime.request("old-restart", "gateway.restart", {})
    await runtime.response("old-restart")
    replacement = RestartController()
    gateway = build_gateway_services(
        config=runtime.channel.config, bus=runtime.bus, session_manager=runtime.sessions,
        static_dist_path=None, workspace_path=runtime.sessions.workspace,
        default_restrict_to_workspace=False, runtime_model_name=None,
        runtime_surface="browser", runtime_capabilities_overrides=None, restart=replacement.request,
    )
    channel = WebSocketChannel(runtime.channel.config, runtime.bus, gateway=gateway)
    gateway.endpoint.webui_connections.add(runtime.connection)
    try:
        await channel._dispatch_envelope(runtime.connection, "webui-client", {
            "type": "webui_request", "request_id": "old-restart", "action": "gateway.restart",
            "payload": {"expected_gateway_id": runtime.channel.gateway.tokens.instance_id},
        })
        await channel.webui_flush(runtime.connection)
        assert runtime.connection.sent[-1]["error"] == {"status": 409, "message": "gateway_changed"}
        assert not replacement.committed
        assert replacement.request() is not None
    finally:
        await channel._cleanup_connection(runtime.connection)
        await channel._commands.close()


async def test_gateway_restart_commits_only_after_ack_is_physically_written(
    runtime: _Runtime, monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_started = asyncio.Event()
    release_write = asyncio.Event()
    sent = runtime.connection.send

    async def blocked_send(raw: str) -> None:
        write_started.set()
        await release_write.wait()
        assert not runtime.restart.committed
        await sent(raw)

    monkeypatch.setattr(runtime.connection, "send", blocked_send)
    try:
        await runtime.request("write-before-commit", "gateway.restart", {})
        await asyncio.wait_for(write_started.wait(), 3)
        assert not runtime.restart.committed
        assert not runtime.restart.shutdown_event.is_set()
        assert runtime.connection.sent == []
    finally:
        release_write.set()
    receipt = await runtime.response("write-before-commit")
    assert receipt["ok"] is True
    assert runtime.restart.committed
    assert runtime.restart.shutdown_event.is_set()
    assert await runtime.sessions.state.list_sessions() == []
