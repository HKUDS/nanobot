"""Behavioral delegation and executable ownership boundaries for WebSocket."""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from websockets.datastructures import Headers
from websockets.http11 import Request, Response

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket import runtime
from nanobot.webui.gateway_services import build_gateway_services

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_SESSION_IDENTITY_PATH = _REPOSITORY_ROOT / "nanobot" / "webui" / "session_identity.py"


@pytest.fixture
async def channel(tmp_path, monkeypatch):
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    config = runtime.WebSocketConfig(allow_from=["client-1"], websocket_requires_token=False)
    bus = MessageBus()
    gateway = build_gateway_services(
        config=config,
        bus=bus,
        session_manager=None,
        static_dist_path=None,
        workspace_path=tmp_path,
        default_restrict_to_workspace=True,
        config_path=tmp_path / "config.json",
        runtime_model_name=None,
        runtime_surface="browser",
        runtime_capabilities_overrides=None,
    )
    channel = runtime.WebSocketChannel(config, bus, gateway=gateway)
    try:
        yield channel
    finally:
        async with asyncio.timeout(2):
            await channel.stop()
        assert channel._server_task is None
        assert not channel._connection_outbound
        assert not channel._outbound_retire_tasks
        assert not channel._commands.request_tasks


async def test_send_delegates_the_outbound_message_to_the_projector(channel, monkeypatch):
    send = AsyncMock()
    hydrate = AsyncMock()
    monkeypatch.setattr(channel._outbound, "send", send)
    monkeypatch.setattr(channel._outbound, "hydrate", hydrate)
    msg = OutboundMessage(
        channel="websocket", chat_id="chat-1", content="hello", reply_to="m1",
        media=["/example/image.png"], metadata={"turn_id": "turn-1"},
    )

    await channel.send(msg)

    send.assert_awaited_once_with(msg)
    hydrate.assert_not_awaited()


async def test_subscribe_hydration_delegates_the_requested_chat(channel, monkeypatch):
    hydrate = AsyncMock()
    send = AsyncMock()
    monkeypatch.setattr(channel._outbound, "hydrate", hydrate)
    monkeypatch.setattr(channel._outbound, "send", send)

    await channel._hydrate_after_subscribe("chat-2")

    hydrate.assert_awaited_once_with("chat-2")
    send.assert_not_awaited()


async def test_envelope_delegates_connection_client_and_payload_to_application(channel, monkeypatch):
    dispatch = AsyncMock()
    monkeypatch.setattr(channel._commands, "dispatch", dispatch)
    connection = AsyncMock()
    envelope = {"type": "subscribe", "chat_id": "chat-2"}

    await channel._dispatch_envelope(connection, "client-1", envelope)

    dispatch.assert_awaited_once_with(connection, "client-1", envelope)


@pytest.mark.parametrize("allow_upgrade", [False, True])
async def test_http_delegates_authorization_and_preserves_endpoint_result(
    channel, monkeypatch, allow_upgrade,
):
    response = None if allow_upgrade else Response(
        403, "Forbidden", Headers({"Content-Type": "text/plain"}), b"access denied",
    )
    process_request = AsyncMock(return_value=response)
    monkeypatch.setattr(channel.gateway.endpoint, "process_request", process_request)
    connection = AsyncMock()
    request = Request("/webui/thread?chat_id=chat-2", Headers())

    result = await channel._dispatch_http(connection, request)

    assert result is response
    process_request.assert_awaited_once_with(connection, request, is_allowed=channel.is_allowed)
    authorize = process_request.await_args.kwargs["is_allowed"]
    assert authorize("client-1") is True
    assert authorize("other-client") is False


def _session_namespace_literal_lines(source: str) -> list[int]:
    """Locate executable namespace literals, not prose or type annotations."""
    tree = ast.parse(source)
    ignored = set()
    for node in ast.walk(tree):
        annotation = None
        if isinstance(node, ast.AnnAssign | ast.arg):
            annotation = node.annotation
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            annotation = node.returns
        if annotation is not None:
            ignored.update(ast.walk(annotation))
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            # A standalone string (including a docstring) does not define runtime policy.
            ignored.add(node.value)
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.startswith("websocket:")
        and node not in ignored
    ]


def test_persisted_webui_session_prefix_has_one_production_owner() -> None:
    # Consumers import session_identity; independent literal keys/prefixes fork its policy.
    # Exact persisted values and mapping round trips live in test_session_identity.py.
    owners = {}
    for path in (_REPOSITORY_ROOT / "nanobot").rglob("*.py"):
        if "tests" in path.parts:
            continue
        lines = _session_namespace_literal_lines(path.read_text(encoding="utf-8"))
        if lines:
            owners[path.relative_to(_REPOSITORY_ROOT).as_posix()] = lines
    assert set(owners) == {_SESSION_IDENTITY_PATH.relative_to(_REPOSITORY_ROOT).as_posix()}, owners


def test_runtime_exports_compatibility_protocol_helpers() -> None:
    assert runtime._is_valid_chat_id("unified:default")  # pyright: ignore[reportPrivateUsage]
    assert not runtime._is_valid_chat_id("../escape")  # pyright: ignore[reportPrivateUsage]
