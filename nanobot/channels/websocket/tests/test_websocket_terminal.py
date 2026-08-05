from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket.runtime import WebSocketChannel, WebSocketConfig
from nanobot.security.workspace_access import build_workspace_scope
from nanobot.session.manager import SessionManager
from nanobot.terminal.runtime import (
    TRUSTED_TERMINAL_REQUEST_METADATA_KEY,
    TerminalInfo,
    TerminalRead,
)
from nanobot.webui.gateway_services import build_gateway_services


def _channel(tmp_path: Path, manager: Any) -> WebSocketChannel:
    config = WebSocketConfig.model_validate(
        {
            "enabled": True,
            "allowFrom": ["*"],
            "host": "127.0.0.1",
            "port": 29876,
            "path": "/ws",
            "websocketRequiresToken": False,
        }
    )
    sessions = SessionManager(tmp_path)
    gateway = build_gateway_services(
        config=config,
        bus=MessageBus(),
        session_manager=sessions,
        static_dist_path=None,
        workspace_path=tmp_path,
        default_restrict_to_workspace=False,
        runtime_model_name=None,
        runtime_surface="browser",
        runtime_capabilities_overrides=None,
        terminal_manager=manager,
    )
    return WebSocketChannel(config, MessageBus(), gateway=gateway)


def _connection() -> MagicMock:
    connection = MagicMock()
    connection.remote_address = ("127.0.0.1", 51234)
    connection.send = AsyncMock()
    return connection


def _sent_events(connection: MagicMock) -> list[dict[str, Any]]:
    return [json.loads(call.args[0]) for call in connection.send.await_args_list]


@pytest.mark.asyncio
async def test_terminal_open_attaches_to_full_access_project(tmp_path: Path) -> None:
    manager = MagicMock()
    manager.open = AsyncMock(
        return_value=TerminalInfo(
            terminal_id="term-123",
            project_path=str(tmp_path),
            rows=32,
            cols=110,
            running=True,
            exit_code=None,
            created_at=1.0,
        )
    )
    manager.read = AsyncMock(
        return_value=TerminalRead(
            data="boot\r\n",
            next_seq=4,
            running=False,
            exit_code=0,
        )
    )
    channel = _channel(tmp_path, manager)
    channel.gateway.workspaces.persist_scope(
        "chat-1",
        build_workspace_scope(tmp_path, "full", source_channel="websocket"),
    )
    connection = _connection()
    channel._webui_connections.add(connection)

    await channel._dispatch_envelope(
        connection,
        "client-1",
        {"type": "terminal_open", "chat_id": "chat-1", "rows": 32, "cols": 110},
    )

    manager.open.assert_awaited_once_with(tmp_path.resolve(), rows=32, cols=110)
    events = _sent_events(connection)
    assert events[-1] == {
        "event": "terminal_ready",
        "chat_id": "chat-1",
        "terminal_id": "term-123",
        "project_path": str(tmp_path),
        "rows": 32,
        "cols": 110,
        "data": "boot\r\n",
        "seq": 4,
        "running": False,
        "exit_code": 0,
    }


@pytest.mark.asyncio
async def test_terminal_requires_trusted_local_full_access(tmp_path: Path) -> None:
    manager = MagicMock()
    manager.open = AsyncMock()
    channel = _channel(tmp_path, manager)
    connection = _connection()

    await channel._dispatch_envelope(
        connection,
        "client-1",
        {"type": "terminal_open", "chat_id": "chat-1", "rows": 30, "cols": 100},
    )
    assert _sent_events(connection)[-1]["detail"] == "terminal_unavailable"

    connection.send.reset_mock()
    channel._webui_connections.add(connection)
    channel.gateway.workspaces.persist_scope(
        "chat-1",
        build_workspace_scope(tmp_path, "restricted", source_channel="websocket"),
    )
    await channel._dispatch_envelope(
        connection,
        "client-1",
        {"type": "terminal_open", "chat_id": "chat-1", "rows": 30, "cols": 100},
    )
    assert _sent_events(connection)[-1]["detail"] == "terminal_requires_full_access"
    manager.open.assert_not_awaited()


@pytest.mark.asyncio
async def test_terminal_input_is_scoped_to_the_saved_project(tmp_path: Path) -> None:
    manager = MagicMock()
    manager.write = AsyncMock()
    channel = _channel(tmp_path, manager)
    channel.gateway.workspaces.persist_scope(
        "chat-1",
        build_workspace_scope(tmp_path, "full", source_channel="websocket"),
    )
    connection = _connection()
    channel._webui_connections.add(connection)

    await channel._dispatch_envelope(
        connection,
        "client-1",
        {
            "type": "terminal_input",
            "chat_id": "chat-1",
            "terminal_id": "term-123",
            "data": "git status\r",
        },
    )

    manager.write.assert_awaited_once_with(
        "term-123",
        "git status\r",
        project_path=tmp_path.resolve(),
    )


@pytest.mark.asyncio
async def test_terminal_detach_still_cancels_pump_after_scope_downgrade(
    tmp_path: Path,
) -> None:
    channel = _channel(tmp_path, MagicMock())
    channel.gateway.workspaces.persist_scope(
        "chat-1",
        build_workspace_scope(tmp_path, "restricted", source_channel="websocket"),
    )
    connection = _connection()
    pump = asyncio.create_task(asyncio.Event().wait())
    channel._terminal_pumps[(connection, "term-123")] = pump

    await channel._dispatch_envelope(
        connection,
        "client-1",
        {
            "type": "terminal_detach",
            "chat_id": "chat-1",
            "terminal_id": "term-123",
        },
    )
    await asyncio.gather(pump, return_exceptions=True)

    assert pump.cancelled()
    assert (connection, "term-123") not in channel._terminal_pumps
    assert _sent_events(connection)[-1]["event"] == "terminal_detached"


@pytest.mark.asyncio
async def test_terminal_kill_cancels_its_connection_pump(tmp_path: Path) -> None:
    manager = MagicMock()
    manager.close = AsyncMock()
    channel = _channel(tmp_path, manager)
    channel.gateway.workspaces.persist_scope(
        "chat-1",
        build_workspace_scope(tmp_path, "full", source_channel="websocket"),
    )
    connection = _connection()
    channel._webui_connections.add(connection)
    pump = asyncio.create_task(asyncio.Event().wait())
    channel._terminal_pumps[(connection, "term-123")] = pump

    await channel._dispatch_envelope(
        connection,
        "client-1",
        {
            "type": "terminal_kill",
            "chat_id": "chat-1",
            "terminal_id": "term-123",
        },
    )
    await asyncio.gather(pump, return_exceptions=True)

    assert pump.cancelled()
    manager.close.assert_awaited_once_with("term-123", project_path=tmp_path.resolve())
    assert _sent_events(connection)[-1]["event"] == "terminal_exit"


@pytest.mark.asyncio
async def test_trusted_local_webui_message_carries_terminal_authority(
    tmp_path: Path,
) -> None:
    channel = _channel(tmp_path, MagicMock())
    channel.bus.publish_inbound = AsyncMock()
    channel.gateway.workspaces.persist_scope(
        "chat-1",
        build_workspace_scope(tmp_path, "full", source_channel="websocket"),
    )
    connection = _connection()
    channel._webui_connections.add(connection)

    await channel._dispatch_envelope(
        connection,
        "client-1",
        {
            "type": "message",
            "chat_id": "chat-1",
            "content": "use the shared terminal",
            "turn_id": "turn-1",
            "webui": True,
        },
    )

    inbound = channel.bus.publish_inbound.await_args.args[0]
    assert inbound.metadata[TRUSTED_TERMINAL_REQUEST_METADATA_KEY] is True


@pytest.mark.asyncio
async def test_generic_websocket_message_cannot_claim_terminal_authority(
    tmp_path: Path,
) -> None:
    channel = _channel(tmp_path, MagicMock())
    channel.bus.publish_inbound = AsyncMock()
    channel.gateway.workspaces.persist_scope(
        "chat-1",
        build_workspace_scope(tmp_path, "full", source_channel="websocket"),
    )
    connection = _connection()

    await channel._dispatch_envelope(
        connection,
        "client-1",
        {
            "type": "message",
            "chat_id": "chat-1",
            "content": "pretend to be the WebUI",
            "turn_id": "turn-1",
            "webui": True,
        },
    )

    inbound = channel.bus.publish_inbound.await_args.args[0]
    assert TRUSTED_TERMINAL_REQUEST_METADATA_KEY not in inbound.metadata
