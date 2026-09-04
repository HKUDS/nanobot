"""Connection-local outbound delivery guarantees for the WebSocket channel."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket import runtime
from nanobot.channels.websocket.runtime import WebSocketChannel, WebSocketConfig
from nanobot.webui.gateway_services import build_gateway_services


class _RecordingConnection:
    def __init__(
        self,
        *,
        block_first_send: bool = False,
        block_close: bool = False,
    ) -> None:
        self.block_first_send = block_first_send
        self.block_close = block_close
        self.send_started = asyncio.Event()
        self.release_send = asyncio.Event()
        self.send_cancelled = asyncio.Event()
        self.closed = asyncio.Event()
        self.release_close = asyncio.Event()
        self.sent: asyncio.Queue[str] = asyncio.Queue()
        self.close_calls: list[tuple[int, str]] = []
        self.transport = MagicMock()
        self.send_calls = 0
        self.active_sends = 0
        self.max_active_sends = 0

    async def send(self, raw: str) -> None:
        self.send_calls += 1
        call_number = self.send_calls
        self.active_sends += 1
        self.max_active_sends = max(self.max_active_sends, self.active_sends)
        self.send_started.set()
        try:
            if self.block_first_send and call_number == 1:
                await self.release_send.wait()
            await self.sent.put(raw)
        except asyncio.CancelledError:
            self.send_cancelled.set()
            raise
        finally:
            self.active_sends -= 1

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.close_calls.append((code, reason))
        self.closed.set()
        if self.block_close:
            await self.release_close.wait()


def _channel() -> WebSocketChannel:
    bus = MagicMock(spec=MessageBus)
    config = WebSocketConfig(
        enabled=True,
        allow_from=["*"],
        websocket_requires_token=False,
    )
    gateway = build_gateway_services(
        config=config,
        bus=bus,
        session_manager=None,
        static_dist_path=None,
        workspace_path=Path.cwd(),
        default_restrict_to_workspace=False,
        runtime_model_name=None,
        runtime_surface="tui",
        runtime_capabilities_overrides=None,
    )
    return WebSocketChannel(config, bus, gateway=gateway)


def _message(chat_id: str, text: str) -> OutboundMessage:
    return OutboundMessage(channel="websocket", chat_id=chat_id, content=text)


async def _next_text(connection: _RecordingConnection) -> str:
    raw = await asyncio.wait_for(connection.sent.get(), timeout=1)
    return str(json.loads(raw)["text"])


async def _wait_for_connection_cleanup(
    channel: WebSocketChannel,
    connection: _RecordingConnection,
) -> None:
    while cast(Any, connection) in channel._connection_outbound:
        await asyncio.sleep(0)


async def _wait_for_retire_tasks(channel: WebSocketChannel) -> None:
    while channel._outbound_retire_tasks:
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_slow_tui_does_not_block_a_different_topic() -> None:
    channel = _channel()
    slow = _RecordingConnection(block_first_send=True)
    healthy = _RecordingConnection()
    channel._attach(cast(Any, slow), "chat-slow")
    channel._attach(cast(Any, healthy), "chat-healthy")

    try:
        await asyncio.wait_for(channel.send(_message("chat-slow", "slow")), timeout=1)
        await asyncio.wait_for(slow.send_started.wait(), timeout=1)

        await asyncio.wait_for(channel.send(_message("chat-healthy", "healthy")), timeout=1)
        assert await _next_text(healthy) == "healthy"
        assert slow.sent.empty()
    finally:
        slow.release_send.set()
        await channel._cleanup_connection(cast(Any, slow))
        await channel._cleanup_connection(cast(Any, healthy))


@pytest.mark.asyncio
async def test_slow_tui_does_not_block_same_topic_fanout() -> None:
    channel = _channel()
    slow = _RecordingConnection(block_first_send=True)
    healthy = _RecordingConnection()
    channel._attach(cast(Any, slow), "chat-shared")
    channel._attach(cast(Any, healthy), "chat-shared")

    try:
        await asyncio.wait_for(channel.send(_message("chat-shared", "hello")), timeout=1)
        await asyncio.wait_for(slow.send_started.wait(), timeout=1)
        assert await _next_text(healthy) == "hello"
        assert slow.sent.empty()
    finally:
        slow.release_send.set()
        await channel._cleanup_connection(cast(Any, slow))
        await channel._cleanup_connection(cast(Any, healthy))


@pytest.mark.asyncio
async def test_connection_writer_preserves_order_without_concurrent_sends() -> None:
    channel = _channel()
    connection = _RecordingConnection(block_first_send=True)
    channel._attach(cast(Any, connection), "chat-order")

    try:
        await channel.send(_message("chat-order", "one"))
        await asyncio.wait_for(connection.send_started.wait(), timeout=1)
        await channel.send(_message("chat-order", "two"))
        await channel.send(_message("chat-order", "three"))

        connection.release_send.set()
        assert [await _next_text(connection) for _ in range(3)] == ["one", "two", "three"]
        assert connection.max_active_sends == 1
    finally:
        connection.release_send.set()
        await channel._cleanup_connection(cast(Any, connection))


@pytest.mark.asyncio
async def test_full_outbound_queue_disconnects_only_the_slow_tui(monkeypatch) -> None:
    monkeypatch.setattr(runtime, "_OUTBOUND_QUEUE_MAX_FRAMES", 2)
    monkeypatch.setattr(runtime, "_OUTBOUND_QUEUE_MAX_BYTES", 1024 * 1024)
    channel = _channel()
    slow = _RecordingConnection(block_first_send=True)
    healthy = _RecordingConnection()
    channel._attach(cast(Any, slow), "chat-shared")
    channel._attach(cast(Any, healthy), "chat-shared")

    try:
        for index in range(4):
            await channel.send(_message("chat-shared", str(index)))
            assert await _next_text(healthy) == str(index)
            if index == 0:
                await asyncio.wait_for(slow.send_started.wait(), timeout=1)

        await asyncio.wait_for(slow.closed.wait(), timeout=1)
        await asyncio.wait_for(_wait_for_connection_cleanup(channel, slow), timeout=1)
        assert slow.close_calls == [(1013, "outbound queue full")]
        assert slow not in channel._conn_chats
        assert slow not in channel._subs["chat-shared"]
        assert healthy in channel._subs["chat-shared"]
    finally:
        slow.release_send.set()
        await channel._cleanup_connection(cast(Any, slow))
        await channel._cleanup_connection(cast(Any, healthy))


@pytest.mark.asyncio
async def test_outbound_byte_budget_disconnects_oversized_connection(monkeypatch) -> None:
    monkeypatch.setattr(runtime, "_OUTBOUND_QUEUE_MAX_BYTES", 64)
    channel = _channel()
    connection = _RecordingConnection()
    channel._attach(cast(Any, connection), "chat-large")

    try:
        await channel.send(_message("chat-large", "x" * 256))
        await asyncio.wait_for(connection.closed.wait(), timeout=1)
        await asyncio.wait_for(_wait_for_connection_cleanup(channel, connection), timeout=1)
        assert connection.send_calls == 0
        assert connection.close_calls == [(1013, "outbound queue full")]
    finally:
        await channel._cleanup_connection(cast(Any, connection))


@pytest.mark.asyncio
async def test_cleanup_cancels_a_blocked_writer_and_discards_pending_frames() -> None:
    channel = _channel()
    connection = _RecordingConnection(block_first_send=True)
    channel._attach(cast(Any, connection), "chat-cleanup")
    channel._conn_default[cast(Any, connection)] = "chat-cleanup"

    await channel.send(_message("chat-cleanup", "one"))
    await asyncio.wait_for(connection.send_started.wait(), timeout=1)
    await channel.send(_message("chat-cleanup", "two"))

    await asyncio.wait_for(channel._cleanup_connection(cast(Any, connection)), timeout=1)
    await channel._cleanup_connection(cast(Any, connection))

    assert connection.send_cancelled.is_set()
    assert connection not in channel._conn_chats
    assert connection not in channel._conn_default
    assert connection not in channel._connection_outbound
    assert channel._subs == {}


@pytest.mark.asyncio
async def test_send_timeout_retires_only_the_slow_connection(monkeypatch) -> None:
    monkeypatch.setattr(runtime, "_OUTBOUND_SEND_TIMEOUT_S", 0.01)
    channel = _channel()
    slow = _RecordingConnection(block_first_send=True)
    healthy = _RecordingConnection()
    channel._attach(cast(Any, slow), "chat-shared")
    channel._attach(cast(Any, healthy), "chat-shared")

    try:
        await channel.send(_message("chat-shared", "hello"))

        assert await _next_text(healthy) == "hello"
        await asyncio.wait_for(slow.closed.wait(), timeout=1)
        await asyncio.wait_for(_wait_for_connection_cleanup(channel, slow), timeout=1)
        assert slow.close_calls == [(1013, "outbound send timeout")]
        assert slow not in channel._conn_chats
        assert healthy in channel._subs["chat-shared"]
    finally:
        slow.release_send.set()
        await channel._cleanup_connection(cast(Any, slow))
        await channel._cleanup_connection(cast(Any, healthy))


@pytest.mark.asyncio
async def test_stop_cancels_connection_writers() -> None:
    channel = _channel()
    connection = _RecordingConnection(block_first_send=True)
    channel._attach(cast(Any, connection), "chat-stop")

    await channel.send(_message("chat-stop", "one"))
    await asyncio.wait_for(connection.send_started.wait(), timeout=1)
    await asyncio.wait_for(channel.stop(), timeout=1)

    assert connection.send_cancelled.is_set()
    assert channel._connection_outbound == {}
    assert channel._outbound_retire_tasks == set()
    assert channel._subs == {}


@pytest.mark.asyncio
async def test_stop_cancels_writers_before_waiting_for_the_server_task() -> None:
    channel = _channel()
    connection = _RecordingConnection(block_first_send=True)
    channel._attach(cast(Any, connection), "chat-stop-order")
    channel._running = True
    channel._stop_event = asyncio.Event()

    await channel.send(_message("chat-stop-order", "one"))
    await asyncio.wait_for(connection.send_started.wait(), timeout=1)

    async def _server_shutdown() -> None:
        assert channel._stop_event is not None
        await channel._stop_event.wait()
        await connection.send_cancelled.wait()

    channel._server_task = asyncio.create_task(_server_shutdown())

    await asyncio.wait_for(channel.stop(), timeout=1)

    assert connection.send_cancelled.is_set()
    assert channel._server_task is None


@pytest.mark.asyncio
async def test_send_to_cleaned_connection_does_not_recreate_outbound_state() -> None:
    channel = _channel()
    connection = _RecordingConnection()
    channel._attach(cast(Any, connection), "chat-stale")
    await channel._cleanup_connection(cast(Any, connection))

    await channel._safe_send_to(cast(Any, connection), "stale")

    assert connection.send_calls == 0
    assert connection not in channel._connection_outbound


@pytest.mark.asyncio
async def test_attach_does_not_revive_a_cleaned_connection() -> None:
    channel = _channel()
    connection = _RecordingConnection()
    channel._attach(cast(Any, connection), "chat-before-cleanup")
    await channel._cleanup_connection(cast(Any, connection))

    channel._attach(cast(Any, connection), "chat-after-cleanup")

    assert connection not in channel._connection_outbound
    assert connection not in channel._conn_chats
    assert "chat-after-cleanup" not in channel._subs


@pytest.mark.asyncio
async def test_buffered_envelope_does_not_revive_a_cleaned_connection(monkeypatch) -> None:
    channel = _channel()
    connection = _RecordingConnection()
    channel._attach(cast(Any, connection), "chat-before-cleanup")
    await channel._cleanup_connection(cast(Any, connection))
    dispatch = AsyncMock()
    monkeypatch.setattr(channel._commands, "dispatch", dispatch)

    await channel._dispatch_envelope(cast(Any, connection), "client", {"type": "attach"})

    dispatch.assert_not_awaited()
    assert connection not in channel._connection_outbound


@pytest.mark.asyncio
async def test_control_broadcast_cannot_precede_ready() -> None:
    channel = _channel()
    connection = _RecordingConnection()
    channel._webui_connections.add(cast(Any, connection))

    await channel._send_event(cast(Any, connection), "session_updated", chat_id="chat")

    assert connection.send_calls == 0
    assert connection not in channel._connection_outbound


@pytest.mark.asyncio
async def test_close_timeout_aborts_transport_and_cleans_connection(monkeypatch) -> None:
    monkeypatch.setattr(runtime, "_OUTBOUND_QUEUE_MAX_BYTES", 64)
    monkeypatch.setattr(runtime, "_OUTBOUND_CLOSE_TIMEOUT_S", 0.01)
    channel = _channel()
    connection = _RecordingConnection(block_close=True)
    channel._attach(cast(Any, connection), "chat-close-timeout")

    await channel.send(_message("chat-close-timeout", "x" * 256))
    await asyncio.wait_for(connection.closed.wait(), timeout=1)
    await asyncio.wait_for(_wait_for_connection_cleanup(channel, connection), timeout=1)

    connection.transport.abort.assert_called_once_with()
    assert connection not in channel._conn_chats


@pytest.mark.asyncio
async def test_retirement_contains_cleanup_failure(monkeypatch) -> None:
    monkeypatch.setattr(runtime, "_OUTBOUND_QUEUE_MAX_BYTES", 64)
    channel = _channel()
    connection = _RecordingConnection()
    channel._attach(cast(Any, connection), "chat-cleanup-failure")
    channel._webui_connections.add(cast(Any, connection))
    monkeypatch.setattr(
        channel._commands,
        "cleanup_connection",
        AsyncMock(side_effect=RuntimeError("cleanup failed")),
    )

    await channel.send(_message("chat-cleanup-failure", "x" * 256))
    await asyncio.wait_for(_wait_for_retire_tasks(channel), timeout=1)

    assert connection.close_calls == [(1013, "outbound queue full")]
    assert connection not in channel._connection_outbound
    assert connection not in channel._conn_chats
    assert connection not in channel._webui_connections
    assert channel._subs == {}


@pytest.mark.asyncio
async def test_normal_cleanup_can_overlap_connection_retirement(monkeypatch) -> None:
    monkeypatch.setattr(runtime, "_OUTBOUND_QUEUE_MAX_BYTES", 64)
    channel = _channel()
    connection = _RecordingConnection(block_close=True)
    channel._attach(cast(Any, connection), "chat-retire-race")

    await channel.send(_message("chat-retire-race", "x" * 256))
    await asyncio.wait_for(connection.closed.wait(), timeout=1)
    await asyncio.wait_for(channel._cleanup_connection(cast(Any, connection)), timeout=1)
    connection.release_close.set()
    await asyncio.wait_for(_wait_for_retire_tasks(channel), timeout=1)

    assert connection not in channel._connection_outbound
    assert connection not in channel._conn_chats
    assert channel._subs == {}
