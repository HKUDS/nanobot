import asyncio
import json
import re
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from websockets.datastructures import Headers

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.manager import ChannelManager
from nanobot.channels.websocket.runtime import WebSocketChannel
from nanobot.command.builtin import cmd_new, cmd_restart
from nanobot.command.router import CommandContext
from nanobot.config.schema import Config
from nanobot.session.manager import SessionManager
from nanobot.session.recovery import RECOVERY_METADATA_KEY
from nanobot.session.state import SessionOperationQueueFullError
from nanobot.webui.metadata import WEBUI_RESTART_CONTROL_METADATA_KEY
from nanobot.webui.session_list_index import list_webui_sessions

from .test_websocket_channel import _basic_handler, _sent_ws_payloads


def _channel(tmp_path: Path, *, allowed: bool = True, sessions=None):
    sessions = sessions or SessionManager(tmp_path / "workspace")
    bus = MagicMock()
    bus.publish_inbound = AsyncMock()
    channel = WebSocketChannel(
        {"enabled": True, "allowFrom": ["*"] if allowed else ["someone-else"]}, bus,
        gateway=_basic_handler(bus, session_manager=sessions, workspace_path=sessions.workspace),
    )
    connection = AsyncMock()
    connection.remote_address = ("127.0.0.1", 50123)
    connection.request = SimpleNamespace(headers=Headers({"Host": "localhost:8765"}))
    channel.gateway.endpoint.webui_connections.add(connection)
    return sessions, bus, channel, connection


async def _send_restart_acknowledgement(channel, message, monkeypatch):
    restarted = asyncio.Event()
    monkeypatch.setattr("nanobot.command.builtin.os.execv", lambda *_: restarted.set())
    reply = await cmd_restart(CommandContext(
        msg=message, session=None, key=message.session_key, raw=message.content, loop=MagicMock(restart_mode="exec"),
    ))
    await ChannelManager._send_once(channel, reply)
    await asyncio.wait_for(restarted.wait(), 2)


@pytest.mark.parametrize("scenario", ["typed", "settings", "reset", "busy", "reset_during_retry"])
async def test_restart_completion_after_gateway_start(history, tmp_path, monkeypatch, scenario):
    sessions, bus, channel, connection = _channel(tmp_path, sessions=history.sessions)
    chat_id = "restart-chat"
    recovery = {"status": "awaiting_user", "recovery_id": "checkpoint", "reason": "uncertain_tool_state"}
    session = sessions.get_or_create(f"websocket:{chat_id}")
    session.metadata[RECOVERY_METADATA_KEY] = recovery
    sessions.save(session)
    turn_id = "webui-system:restart" if scenario == "settings" else "typed-restart"
    await channel._dispatch_envelope(connection, "browser", {
        "type": "message", "chat_id": chat_id, "content": "/restart", "webui": True, "turn_id": turn_id,
    })
    message = bus.publish_inbound.await_args.args[0]
    await _send_restart_acknowledgement(channel, message, monkeypatch)
    await channel._cleanup_connection(connection)

    fresh = SessionManager(sessions.workspace)
    config = Config.model_validate({
        "agents": {"defaults": {"workspace": str(sessions.workspace)}},
        "channels": {"websocket": {"enabled": True, "allowFrom": ["*"]}},
    })
    manager = ChannelManager(config, MessageBus(), session_manager=fresh, config_path=tmp_path / "config.json")
    target = manager.channels["websocket"]
    target._running = True
    subscriber = AsyncMock()
    try:
        await target._dispatch_envelope(subscriber, "browser", {"type": "attach", "chat_id": chat_id})
        attached = _sent_ws_payloads(subscriber)[0]
        assert attached["event"] == "attached"
        assert attached["recovery_state"] == recovery
        if scenario == "reset":
            await target._dispatch_envelope(subscriber, "browser", {
                "type": "message", "chat_id": chat_id, "content": "/new", "webui": True,
            })
            assert manager.bus.inbound_size, _sent_ws_payloads(subscriber)
            reset = await manager.bus.consume_inbound()
            loop = MagicMock(sessions=fresh, _cancel_active_tasks=AsyncMock())
            await cmd_new(CommandContext(msg=reset, session=None, key=reset.session_key, raw=reset.content, loop=loop))
        subscriber.send.reset_mock()

        if scenario in {"busy", "reset_during_retry"}:
            append = fresh.state.append_history
            attempts = []

            async def busy_once(key, facts, *, expected_generation, skip_invalid):
                attempts.append(expected_generation)
                if len(attempts) == 1:
                    if scenario == "reset_during_retry":
                        await fresh.state.reset(key)
                        raise SessionOperationQueueFullError("session queue full")
                    raise sqlite3.OperationalError("database is locked")
                return await append(key, facts, expected_generation=expected_generation, skip_invalid=skip_invalid)

            monkeypatch.setattr(fresh.state, "append_history", busy_once)
            monkeypatch.setattr("nanobot.channels.manager._SEND_RETRY_DELAYS", (0,))

        task = manager._notify_restart_done_if_needed()
        if task is not None:
            await task
        frames = _sent_ws_payloads(subscriber)
        if scenario in {"busy", "reset_during_retry"}:
            assert len(attempts) == 2 and attempts[0] and attempts[1] == attempts[0]
        if scenario not in {"typed", "busy"}:
            assert frames == []
            assert history.read(message.session_key) == []
            return
        completed, = frames
        assert completed["event"] == "message"
        assert completed["side_channel"] is True
        assert completed["turn_id"] != turn_id
        assert re.fullmatch(r"Restart completed in \d+(?:\.\d+)?s\.", completed["text"])
        replay = [e for e in history.build(message.session_key)["events"] if e["event"] == "message"]
        ack, result = replay
        assert ack["turn_id"] == turn_id
        assert ack["text"] == "Restarting..."
        for key in ("turn_id", "turn_seq", "text", "side_channel"):
            assert result[key] == completed[key]
    finally:
        await fresh.state.aclose()


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
        await _send_restart_acknowledgement(channel, message, monkeypatch)
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
    ("/model fast", "typed-model-switch"),
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
