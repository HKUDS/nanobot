"""Exercise credential authority from real loopback handshakes through file tools."""

import asyncio
from contextlib import asynccontextmanager

import pytest

from nanobot.agent.tools.filesystem import EditFileTool, ReadFileTool, WriteFileTool
from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket.runtime import WebSocketChannel, WebSocketConfig
from nanobot.security.workspace_access import (
    WorkspaceScopeResolver,
    bind_workspace_scope,
    reset_workspace_scope,
)
from nanobot.session.manager import SessionManager
from nanobot.webui.gateway_services import build_gateway_services
from nanobot.webui.workspaces import write_webui_default_access_mode

from .ws_test_client import WsTestClient


@asynccontextmanager
async def _running_gateway(tmp_path, *, restricted=True, surface="browser"):
    workspace = tmp_path / "workspace"
    project = tmp_path / "project"
    workspace.mkdir()
    project.mkdir()
    (workspace / "canary.txt").write_text("ordinary-workspace")
    (project / "canary.txt").write_text("owner-project")
    bus = MessageBus()
    cfg = WebSocketConfig.model_validate({
        "enabled": True, "allowFrom": ["*"], "host": "127.0.0.1", "port": 0,
        "path": "/ws", "websocketRequiresToken": True,
    })
    gateway = build_gateway_services(
        config=cfg, bus=bus, config_path=tmp_path / "config.json",
        session_manager=SessionManager(tmp_path / "sessions"),
        static_dist_path=None, workspace_path=workspace, default_restrict_to_workspace=restricted,
        runtime_model_name=None, runtime_surface=surface, runtime_capabilities_overrides=None,
    )
    channel = WebSocketChannel(cfg.model_dump(by_alias=True), bus, gateway=gateway)
    task = asyncio.create_task(channel.start())
    try:
        async with asyncio.timeout(5):
            while channel._server is None:
                if task.done():
                    await task
                await asyncio.sleep(0.01)
        port = channel._server.sockets[0].getsockname()[1]
        yield channel, f"ws://127.0.0.1:{port}/ws", workspace, project, bus
    finally:
        await channel.stop()
        await task


async def _result(client, event):
    """Ignore hydration/broadcast events, but never ignore a command rejection."""
    async with asyncio.timeout(5):
        while True:
            result = await client.recv_raw()
            if result["event"] in (event, "error"):
                return result


async def _check_file_authority(msg, workspace, project, *, allowed, restricted=True):
    scope = WorkspaceScopeResolver(workspace, default_restrict_to_workspace=restricted).for_turn(
        channel="websocket", message_metadata=msg.metadata, session_metadata=None,
    )
    bound = bind_workspace_scope(scope)
    try:
        read = ReadFileTool(workspace=workspace, restrict_to_workspace=restricted)
        write = WriteFileTool(workspace=workspace, restrict_to_workspace=restricted)
        edit = EditFileTool(workspace=workspace, restrict_to_workspace=restricted)
        outside = project / "canary.txt"
        results = [
            await read.execute(path=str(outside)),
            await write.execute(path=str(project / "written.txt"), content="owner-write"),
            await edit.execute(path=str(outside), old_text="owner-project", new_text="owner-edited"),
        ]
        if allowed:
            assert "owner-project" in results[0]
            assert (project / "written.txt").read_text() == "owner-write"
            assert outside.read_text() == "owner-edited"
        else:
            assert all("outside allowed directory" in result for result in results)
            assert "owner-project" not in results[0]
            assert not (project / "written.txt").exists()
            assert outside.read_text() == "owner-project"
            assert "ordinary-workspace" in await read.execute(path="canary.txt")
            await write.execute(path="local.txt", content="ordinary-write")
            await edit.execute(path="local.txt", old_text="ordinary-write", new_text="ordinary-edit")
            assert (workspace / "local.txt").read_text() == "ordinary-edit"
    finally:
        reset_workspace_scope(bound)


@pytest.mark.parametrize("entrypoint", ["new_chat", "set_workspace_scope", "message"])
@pytest.mark.parametrize("audience", ["client", "webui"])
@pytest.mark.parametrize("selection", ["project", "full"])
async def test_workspace_selection_requires_owner_on_wire(tmp_path, entrypoint, audience, selection):
    async with _running_gateway(tmp_path) as (channel, uri, workspace, project, bus):
        gateway = channel.gateway
        token = gateway.tokens.issue_token(60, audience=audience)
        async with WsTestClient(uri, token=token) as client:
            await client.recv_ready()
            chat_id = f"selected-{tmp_path.name}"
            await client.send_json({
                "type": entrypoint, "chat_id": chat_id, "content": "read canary", "webui": True,
                "workspace_scope": {
                    "project_path": str(project if selection == "project" else workspace),
                    "access_mode": "restricted" if selection == "project" else "full",
                },
            })
            if audience == "client":
                result = await _result(client, {
                    "new_chat": "attached", "set_workspace_scope": "session_updated", "message": "error",
                }[entrypoint])
                assert result["event"] == "error", result
                assert result["detail"] == "workspace_scope_rejected"
                assert result["reason"] == "project selection is unavailable for this connection"
                # Rejection precedes staging as well as persistence/agent dispatch.
                assert not gateway.workspaces._draft_scopes
                assert gateway.session_manager.list_sessions() == []
                chat_id = "ordinary-topic"
            elif entrypoint != "message":
                result = await _result(client, "attached" if entrypoint == "new_chat" else "session_updated")
                assert result["event"] != "error"
                chat_id = result["chat_id"]
            if audience == "client" or entrypoint != "message":
                # No explicit scope: exercise the selected owner's draft or the
                # ordinary client's operator-configured default, respectively.
                await client.send_json({"type": "message", "chat_id": chat_id, "content": "read canary"})
            msg = await asyncio.wait_for(bus.consume_inbound(), timeout=5)
            assert msg.chat_id == chat_id  # No rejected message preceded the safe one.
            await _check_file_authority(msg, workspace, project, allowed=audience == "webui")


@pytest.mark.parametrize("stored", ["draft", "persisted"])
@pytest.mark.parametrize("selection", ["project", "full"])
async def test_client_cannot_resume_owner_scope(tmp_path, stored, selection):
    async with _running_gateway(tmp_path) as (channel, uri, workspace, project, bus):
        gateway = channel.gateway
        token = gateway.tokens.issue_token(60, audience="webui")
        async with WsTestClient(uri, token=token) as owner:
            await owner.recv_ready()
            await owner.send_json({
                "type": "new_chat", "workspace_scope": {
                    "project_path": str(project if selection == "project" else workspace),
                    "access_mode": "restricted" if selection == "project" else "full",
                },
            })
            attached = await _result(owner, "attached")
            assert attached["event"] == "attached"
            chat_id = attached["chat_id"]
            if stored == "persisted":
                await owner.send_json({"type": "message", "chat_id": chat_id, "content": "hello"})
                assert (await asyncio.wait_for(bus.consume_inbound(), timeout=5)).chat_id == chat_id
        saved = gateway.workspaces.scope_for_session_key(f"websocket:{chat_id}")
        token = gateway.tokens.issue_token(60)
        async with WsTestClient(uri, token=token) as client:
            await client.recv_ready()
            for entrypoint in ("set_workspace_scope", "message"):
                await client.send_json({"type": entrypoint, "chat_id": chat_id, "content": "read canary"})
                assert (await _result(client, "error"))["detail"] == "workspace_scope_rejected"
            assert gateway.workspaces.scope_for_session_key(f"websocket:{chat_id}") == saved
            await client.send_json({"type": "message", "chat_id": "safe", "content": "hello"})
            msg = await asyncio.wait_for(bus.consume_inbound(), timeout=5)
            assert msg.chat_id == "safe"
            await _check_file_authority(msg, workspace, project, allowed=False)


async def test_legacy_frames_cannot_inherit_owner_scope(tmp_path):
    async with _running_gateway(tmp_path) as (channel, uri, workspace, project, bus):
        gateway = channel.gateway
        token = gateway.tokens.issue_token(60)
        async with WsTestClient(uri, token=token) as client:
            ready = await client.recv_ready()
            chat_id = ready.chat_id
            await client.send_text("ordinary legacy message")
            msg = await asyncio.wait_for(bus.consume_inbound(), timeout=5)
            assert msg.metadata["workspace_scope"]["project_path"] == str(workspace.resolve())
            # An owner may update a still-connected client's default chat.
            owner_token = gateway.tokens.issue_token(60, audience="webui")
            async with WsTestClient(uri, token=owner_token) as owner:
                await owner.recv_ready()
                await owner.send_json({
                    "type": "set_workspace_scope", "chat_id": chat_id,
                    "workspace_scope": {"project_path": str(workspace), "access_mode": "full"},
                })
                assert (await _result(owner, "session_updated"))["event"] == "session_updated"
            for frame in ("read canary", '{"content":"read canary"}'):
                await client.ws.send(frame)
                assert (await _result(client, "error"))["detail"] == "workspace_scope_rejected"
            await client.send_json({"type": "message", "chat_id": "safe", "content": "hello"})
            msg = await asyncio.wait_for(bus.consume_inbound(), timeout=5)
            assert msg.chat_id == "safe"


@pytest.mark.parametrize("restricted", [True, False])
async def test_client_uses_operator_config_not_owner_full_default(tmp_path, restricted):
    # A native host permits owner Full Access; that capability is not client authority.
    async with _running_gateway(tmp_path, restricted=restricted, surface="native") as (
        channel, uri, workspace, project, bus,
    ):
        write_webui_default_access_mode("full")
        token = channel.gateway.tokens.issue_token(60)
        async with WsTestClient(uri, token=token) as client:
            await client.recv_ready()
            await client.send_json({"type": "new_chat"})
            result = await _result(client, "attached")
            assert result["event"] == "attached"
            await client.send_json({"type": "message", "chat_id": result["chat_id"], "content": "hello"})
            msg = await asyncio.wait_for(bus.consume_inbound(), timeout=5)
            assert msg.metadata["workspace_scope"]["access_mode"] == ("restricted" if restricted else "full")
            await _check_file_authority(msg, workspace, project, allowed=not restricted, restricted=restricted)
