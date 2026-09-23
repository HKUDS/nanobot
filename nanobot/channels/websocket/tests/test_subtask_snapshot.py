import json
from unittest.mock import AsyncMock

import pytest

from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket.runtime import WebSocketChannel, WebSocketConfig
from nanobot.session.manager import SessionManager
from nanobot.session.subtask_outputs import SubtaskOutput
from nanobot.webui.gateway_services import build_gateway_services


@pytest.fixture
def setup(tmp_path):
    bus = MessageBus()
    sessions = SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "state")
    cfg = WebSocketConfig(enabled=True, allow_from=["*"])
    gateway = build_gateway_services(config=cfg, bus=bus, session_manager=sessions,
        static_dist_path=None, workspace_path=tmp_path / "workspace", default_restrict_to_workspace=True,
        runtime_model_name=None, runtime_surface="browser", runtime_capabilities_overrides=None)
    channel = WebSocketChannel(cfg.model_dump(), bus, gateway=gateway)
    connection = AsyncMock()
    channel._webui_connections.add(connection)
    return channel, connection, sessions


async def request(channel, conn, chat_id):
    await channel._dispatch_envelope(conn, "webui", {
        "type": "webui_request", "request_id": "same-id", "action": "subtasks.snapshot",
        "payload": {"chat_id": chat_id},
    })
    return json.loads(conn.send.await_args.args[0])


async def test_live_restart_and_repeated_read_never_replay_stale_or_consume(setup):
    channel, conn, sessions = setup
    parent = sessions.get_or_create("websocket:parent")
    subtask = SubtaskOutput(sessions, parent.key, "id", "Task", "turn")
    subtask.update(output="First")
    assert (await request(channel, conn, "parent"))["result"]["tasks"][0]["output"] == "First"
    subtask.update(state="completed", output="Final")
    assert (await request(channel, conn, "parent"))["result"]["tasks"][0]["output"] == "Final"
    assert not channel._webui_request_operations
    sessions.save(parent)
    sessions.invalidate(parent.key)
    assert (await request(channel, conn, "parent"))["result"]["tasks"][0]["output"] == "Final"
    assert (await request(channel, conn, "other"))["result"]["tasks"] == []


async def test_unauthenticated_and_other_temporary_owner_are_denied(setup):
    channel, conn, sessions = setup
    unknown = AsyncMock()
    assert (await request(channel, unknown, "parent"))["error"]["status"] == 403
    private = channel.gateway.temporary_chats.create(conn, trusted_webui=True)
    subtask = SubtaskOutput(sessions, f"websocket:{private}", "id", "Task", "turn")
    subtask.update(output="Synthetic private output")
    assert (await request(channel, conn, private))["result"]["tasks"][0]["output"] == "Synthetic private output"
    channel._webui_connections.add(unknown)
    assert (await request(channel, unknown, private))["error"]["status"] == 404
    await channel.gateway.temporary_chats.discard(conn, private)
    assert (await request(channel, conn, private))["error"]["status"] == 404
    assert not channel._webui_request_operations
    assert sessions.read_session_metadata(f"websocket:{private}") is None


@pytest.mark.parametrize("chat_id", [None, "../escape", "", 3])
async def test_invalid_scope_rejected(setup, chat_id):
    channel, conn, _ = setup
    assert (await request(channel, conn, chat_id))["error"]["status"] == 404
