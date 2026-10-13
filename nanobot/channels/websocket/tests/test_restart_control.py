"""Settings restarts are controls, not persisted chat turns."""

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
from nanobot.webui.metadata import WEBUI_RESTART_CONTROL_METADATA_KEY
from nanobot.webui.session_list_index import list_webui_sessions
from nanobot.webui.transcript import append_transcript_object, read_transcript_lines

from .test_websocket_channel import _basic_handler, _sent_ws_payloads


def _channel(tmp_path: Path, *, allowed: bool = True):
    sessions = SessionManager(tmp_path / "workspace")
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
async def test_settings_restart_does_not_create_or_change_chat_history(tmp_path, monkeypatch, existing):
    sessions, bus, channel, connection = _channel(tmp_path)
    monkeypatch.setattr("nanobot.command.builtin.set_restart_notice_to_env", MagicMock())
    key = "websocket:existing"
    if existing in {"canonical", "both"}:
        session = sessions.get_or_create(key)
        session.add_message("user", "Keep my conversation")
        session.metadata.update({"webui": True, "title": "Keep this title"})
        sessions.save(session)
    if existing in {"transcript", "both"}:
        append_transcript_object(key, {
            "event": "user_message", "chat_id": "existing", "text": "Keep my conversation",
        })
    before_rows = list_webui_sessions(sessions)
    before_files = {p: p.read_bytes() for p in tmp_path.rglob("*.jsonl")}
    before_transcript = read_transcript_lines(key)

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
        # Exercise the real command response, but never execute a process restart.
        def discard_restart_task(coro):
            coro.close()
        with monkeypatch.context() as patch:
            patch.setattr("nanobot.command.builtin.asyncio.create_task", discard_restart_task)
            response = await cmd_restart(CommandContext(
                msg=message, session=None, key=message.session_key, raw=message.content, loop=MagicMock(),
            ))
        await channel.send(response)
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
    assert read_transcript_lines(key) == before_transcript
    # A fresh manager uses the public sidebar discovery path, not a cached count.
    fresh = SessionManager(tmp_path / "workspace")
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
async def test_control_prefix_does_not_suppress_ordinary_or_session_command_history(tmp_path, text, turn_id):
    sessions, bus, channel, connection = _channel(tmp_path)
    await channel._dispatch_envelope(connection, "browser", {
        "type": "message", "chat_id": "chat", "content": text, "webui": True, "turn_id": turn_id,
        "metadata": {WEBUI_RESTART_CONTROL_METADATA_KEY: True},
    })
    message = bus.publish_inbound.await_args.args[0]
    assert WEBUI_RESTART_CONTROL_METADATA_KEY not in message.metadata
    await channel.send(OutboundMessage(channel="websocket", chat_id="chat", content="Reply", metadata=message.metadata))
    assert len(list_webui_sessions(sessions)) == 1
    assert [row["text"] for row in read_transcript_lines("websocket:chat")] == [text, "Reply"]
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
