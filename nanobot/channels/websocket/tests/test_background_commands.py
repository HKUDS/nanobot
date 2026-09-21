import json
import os
import sys
from unittest.mock import AsyncMock

import pytest

from nanobot.agent.tools.exec_session import ExecSessionManager
from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket.runtime import WebSocketChannel, WebSocketConfig
from nanobot.session.manager import SessionManager
from nanobot.webui.gateway_services import build_gateway_services


async def start(manager, path, owner="websocket:a"):
    command = ("Write-Output 'synthetic'; $null = [Console]::In.ReadLine()" if sys.platform == "win32"
               else "printf 'synthetic\\n'; IFS= read -r _")
    return await manager.start(command=command, cwd=str(path), env=os.environ.copy(), timeout=30,
        shell_program=None, login=False, yield_time_ms=1000, max_output_chars=10000,
        owner_session_key=owner)


@pytest.fixture
async def setup(tmp_path):
    bus = MessageBus()
    sessions = SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "state")
    manager = ExecSessionManager()
    cfg = WebSocketConfig(enabled=True, allow_from=["*"])
    gateway = build_gateway_services(config=cfg, bus=bus, session_manager=sessions,
        static_dist_path=None, workspace_path=tmp_path / "workspace", default_restrict_to_workspace=True,
        runtime_model_name=None, runtime_surface="browser", runtime_capabilities_overrides=None,
        exec_sessions=manager)
    channel = WebSocketChannel(cfg.model_dump(), bus, gateway=gateway)
    connection = AsyncMock()
    channel._webui_connections.add(connection)
    yield channel, connection, sessions, manager, tmp_path
    await manager.close_all()


async def request(channel, conn, action="background.list", **payload):
    await channel._dispatch_envelope(conn, "webui", {"type": "webui_request", "request_id": "repeat",
        "action": action, "payload": payload})
    return json.loads(conn.send.await_args.args[0])


async def test_auth_scope_and_live_read_bypasses_replay_cache(setup):
    channel, conn, sessions, manager, path = setup
    sessions.get_or_create("websocket:a")
    sessions.get_or_create("websocket:b")
    sid, _ = await start(manager, path)
    assert (await request(channel, AsyncMock(), chat_id="a"))["error"]["status"] == 403
    assert len((await request(channel, conn, chat_id="a"))["result"]["commands"]) == 1
    assert (await request(channel, conn, chat_id="b"))["result"]["commands"] == []
    assert (await request(channel, conn, "background.stop", chat_id="b", session_id=sid))["error"]["status"] == 404
    stopped = await request(channel, conn, "background.stop", chat_id="a", session_id=sid)
    assert stopped["result"]["command"]["state"] == "stopped"
    again = await request(channel, conn, "background.read", chat_id="a", session_id=sid)
    assert again["result"]["command"]["state"] == "stopped"
    assert not channel._webui_request_operations
    sessions.invalidate("websocket:a")
    assert (await request(channel, conn, chat_id="a"))["error"]["status"] == 404


async def test_temporary_owner_close_and_no_persistence(setup):
    channel, conn, sessions, manager, path = setup
    private = channel.gateway.temporary_chats.create(conn, trusted_webui=True)
    sid, _ = await start(manager, path, owner=f"websocket:{private}")
    other = AsyncMock()
    channel._webui_connections.add(other)
    assert (await request(channel, conn, chat_id=private))["result"]["commands"]
    assert (await request(channel, other, "background.read", chat_id=private, session_id=sid))["error"]["status"] == 404
    await channel.gateway.temporary_chats.discard(conn, private)
    assert (await request(channel, conn, chat_id=private))["error"]["status"] == 404
    assert not channel._webui_request_operations
    assert sessions.read_session_metadata(f"websocket:{private}") is None


async def test_owner_closing_during_stop_cannot_receive_a_late_snapshot(setup, monkeypatch):
    channel, conn, _, manager, _ = setup
    private = channel.gateway.temporary_chats.create(conn, trusted_webui=True)

    async def stop_then_close(*args, **kwargs):
        await channel.gateway.temporary_chats.discard(conn, private)
        return {"chunks": [{"text": "late private output"}]}

    monkeypatch.setattr(manager, "inspect_output", stop_then_close)
    response = await request(channel, conn, "background.stop", chat_id=private, session_id="0" * 12)
    assert response["error"]["status"] == 404
    assert "late private output" not in json.dumps(response)
    assert not channel._webui_request_operations


@pytest.mark.parametrize("payload", [{"chat_id": "../x"}, {"chat_id": "a", "session_id": "arbitrary"},
    {"chat_id": "a", "session_id": "0" * 12, "after": True},
    {"chat_id": "a", "session_id": "0" * 12, "after": -1}])
async def test_invalid_input_rejected(setup, payload):
    channel, conn, sessions, _, _ = setup
    sessions.get_or_create("websocket:a")
    assert "error" in await request(channel, conn, "background.read", **payload)
