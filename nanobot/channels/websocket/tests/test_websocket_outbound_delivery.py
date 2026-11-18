from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.bus.events import INBOUND_META_USER_SHELL, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.manager import ChannelManager
from nanobot.channels.websocket import runtime
from nanobot.channels.websocket.runtime import WebSocketChannel, WebSocketConfig
from nanobot.config.schema import Config
from nanobot.runtime_admission import RuntimeBusyError
from nanobot.session.manager import SessionManager
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


def _channel(session_manager: SessionManager | None = None) -> WebSocketChannel:
    bus = MessageBus()
    config = WebSocketConfig(
        enabled=True,
        allow_from=["*"],
        websocket_requires_token=False,
    )
    gateway = build_gateway_services(
        config=config,
        bus=bus,
        session_manager=session_manager,
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
async def test_message_bus_delivers_to_ten_tuis_with_one_blocked_connection() -> None:
    channel = _channel()
    bus = MessageBus()
    config = Config.model_validate({"channels": {"websocket": {"enabled": False}}})
    manager = ChannelManager(config, bus)
    manager.channels["websocket"] = channel
    connections = [_RecordingConnection(block_first_send=i == 0) for i in range(10)]
    for i, connection in enumerate(connections):
        channel._attach(cast(Any, connection), f"chat-{i}")
    dispatcher = asyncio.create_task(manager._dispatch_outbound())
    try:
        for text in ("first", "last"):
            for i in range(10):
                await bus.publish_outbound(_message(f"chat-{i}", text))
        await asyncio.wait_for(connections[0].send_started.wait(), 2)
        for connection in connections[1:]:
            assert await _next_text(connection) == "first"
            assert await _next_text(connection) == "last"
        assert connections[0].sent.empty()
        async with asyncio.timeout(2):
            while manager._outbound_tasks or bus.outbound_size:
                await asyncio.sleep(0)
        # The manager's send has finished; the physical transport still owns
        # its final frames. A shutdown idle check must include that second queue.
        assert channel.has_pending_delivery
        with pytest.raises(RuntimeBusyError):
            with bus.admission.pause_if_idle(lambda: False):
                pytest.fail("The blocked WebSocket transport was missed")
        assert not bus.admission.paused
        connections[0].release_send.set()
        assert await _next_text(connections[0]) == "first"
        assert await _next_text(connections[0]) == "last"
        async with asyncio.timeout(2):
            while manager.has_pending_delivery:
                await asyncio.sleep(0)
        with bus.admission.pause_if_idle(lambda: False):
            assert bus.admission.paused
    finally:
        dispatcher.cancel()
        await asyncio.gather(dispatcher, return_exceptions=True)
        for connection in connections:
            await channel._cleanup_connection(cast(Any, connection))
    assert not manager._outbound_tasks
    assert not manager._outbound_tails
    assert not channel._connection_outbound


@pytest.mark.asyncio
async def test_delivery_remains_busy_until_timed_out_transport_is_retired(monkeypatch) -> None:
    monkeypatch.setattr(runtime, "_OUTBOUND_SEND_TIMEOUT_S", 0.02)
    channel = _channel()
    connection = _RecordingConnection(block_first_send=True, block_close=True)
    channel._attach(cast(Any, connection), "chat-retiring")
    try:
        await channel.send(_message("chat-retiring", "reply"))
        await asyncio.wait_for(connection.closed.wait(), 2)
        assert connection.send_cancelled.is_set()
        assert channel.has_pending_delivery
        connection.release_close.set()
        await asyncio.wait_for(_wait_for_retire_tasks(channel), 2)
        assert not channel.has_pending_delivery
    finally:
        connection.release_send.set()
        connection.release_close.set()
        await channel._cleanup_connection(cast(Any, connection))


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
async def test_message_recipients_are_snapshotted_before_history_append(history, monkeypatch) -> None:
    channel = _channel(history.sessions)
    first_connection = _RecordingConnection()
    late_connection = _RecordingConnection()
    channel._attach(cast(Any, first_connection), "chat-snapshot")
    first_message = await history.message(
        channel="websocket", chat_id="chat-snapshot", content="first",
    )
    append_started = asyncio.Event()
    release_append = asyncio.Event()
    append_history = history.sessions.state.append_history

    async def blocked_append(*args, **kwargs):
        append_started.set()
        await release_append.wait()
        return await append_history(*args, **kwargs)

    monkeypatch.setattr(history.sessions.state, "append_history", blocked_append)
    sending = asyncio.create_task(channel.send(first_message))
    try:
        await asyncio.wait_for(append_started.wait(), timeout=1)
        channel._attach(cast(Any, late_connection), "chat-snapshot")
        release_append.set()
        await asyncio.wait_for(sending, timeout=1)
        assert await _next_text(first_connection) == "first"

        await channel.send(await history.message(
            channel="websocket", chat_id="chat-snapshot", content="second",
        ))
        assert await _next_text(first_connection) == "second"
        assert await _next_text(late_connection) == "second"
        assert late_connection.sent.empty()
        assert [record["text"] for record in history.read("websocket:chat-snapshot")] == [
            "first", "second",
        ]
    finally:
        release_append.set()
        await asyncio.gather(sending, return_exceptions=True)
        await channel._cleanup_connection(cast(Any, first_connection))
        await channel._cleanup_connection(cast(Any, late_connection))


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


@pytest.mark.asyncio
@pytest.mark.parametrize("user_shell", [True, False])
async def test_shell_output_is_literal_without_changing_other_command_replies(
    history, user_shell: bool, monkeypatch: pytest.MonkeyPatch,
) -> None:
    channel = _channel(history.sessions)
    connection = _RecordingConnection()
    channel._attach(cast(Any, connection), "shell-output")
    output = "Path\n----\n  __pycache__\n```mermaid\nflowchart LR\n```\n![preview](local.png)\n"
    rewritten = output.replace("local.png", "/api/media/signed")
    monkeypatch.setattr(channel.gateway.media, "rewrite_local_markdown_images", lambda text: rewritten)
    message = await history.message(
        channel="websocket", chat_id="shell-output", content=output,
        metadata={"render_as": "text", INBOUND_META_USER_SHELL: user_shell},
    )
    try:
        await channel.send(message)
        payload = json.loads(await asyncio.wait_for(connection.sent.get(), timeout=1))
        assert payload["text"] == (output if user_shell else rewritten)
        assert payload.get("render_as") == ("text" if user_shell else None)
        [persisted] = history.read("websocket:shell-output")
        assert persisted["event"] == "message"
        assert persisted["text"] == output
        assert persisted.get("render_as") == ("text" if user_shell else None)
        assert message.content == output
    finally:
        await channel._cleanup_connection(cast(Any, connection))


@pytest.mark.asyncio
async def test_ready_activity_group_commits_before_ordered_fanout(history, monkeypatch, tmp_path) -> None:
    from nanobot.bus.outbound_events import ProgressEvent, RetryStatusEvent, TurnEndEvent
    from nanobot.events import ModelRequestEvent
    from nanobot.providers.base import LLMUsage

    channel = _channel(history.sessions)
    manager = ChannelManager(
        Config.model_validate({"channels": {"websocket": {"enabled": False}}}), channel.bus,
        config_path=tmp_path / "config.json",
    )
    manager.channels["websocket"] = channel
    chat = "group-commit"
    metadata = await history.metadata(chat, {"webui_turn_id": "turn-group"})
    connection, late = _RecordingConnection(), _RecordingConnection()
    channel._attach(cast(Any, connection), chat)
    entered, release = [asyncio.Event(), asyncio.Event()], [asyncio.Event(), asyncio.Event()]
    append = history.sessions.state.append_history
    writes = []

    async def gated_append(key, facts, **kwargs):
        index = len(writes)
        writes.append(list(facts))
        if index < 2:
            entered[index].set()
            await release[index].wait()
        return await append(key, facts, **kwargs)

    monkeypatch.setattr(history.sessions.state, "append_history", gated_append)
    usage = LLMUsage.reported(input_tokens=100, output_tokens=20)
    from nanobot.context_graph import graph_from_sources
    from nanobot.context_sources import PromptSource, PromptSourcesEvent
    from nanobot.file_references import source_receipt
    source = PromptSource(tmp_path / "guide.md", "Guide content")
    graph = graph_from_sources([source_receipt(source.path, source.content)])
    await channel.send(OutboundMessage(
        "websocket", chat, "", metadata=metadata, event=PromptSourcesEvent((source,)),
    ))
    events = [
        ModelRequestEvent("request", "run", 1, "started"),
        RetryStatusEvent(state="cleared", attempt=1, max_attempts=None, error_kind="unknown"),
        ModelRequestEvent("request", "run", 2, "completed", usage=usage, round_usages=(usage,)),
        ProgressEvent(tool_hint=True, tool_events=[{"call_id": "tool", "name": "read", "phase": "start"}]),
        ProgressEvent(tool_events=[{"call_id": "tool", "name": "read", "phase": "end", "result": "complete"}]),
    ]
    try:
        await manager._queue_outbound(channel, OutboundMessage(
            "websocket", chat, "seed", metadata=metadata, event=ProgressEvent(content="seed"),
        ))
        await asyncio.wait_for(entered[0].wait(), 1)
        for event in events:
            await manager._queue_outbound(channel, OutboundMessage("websocket", chat, "", metadata=metadata, event=event))
        await manager._queue_outbound(channel, OutboundMessage("websocket", chat, "answer", metadata=metadata))
        await manager._queue_outbound(channel, OutboundMessage(
            "websocket", chat, "", metadata=metadata, event=TurnEndEvent(usage=usage),
        ))
        assert connection.sent.empty()
        release[0].set()
        await asyncio.wait_for(entered[1].wait(), 1)
        assert await _next_text(connection) == "seed"
        assert connection.sent.empty()
        assert [row["text"] for row in history.read(f"websocket:{chat}")] == ["seed"]
        channel._attach(cast(Any, late), chat)
        release[1].set()
        async with asyncio.timeout(2):
            while manager.has_pending_delivery:
                await asyncio.sleep(0)
        frames = [json.loads(connection.sent.get_nowait()) for _ in range(connection.sent.qsize())]
        assert [frame["event"] for frame in frames] == [
            "model_request", "retry_status", "model_request", "message", "message", "message", "turn_end", "session_updated",
        ]
        assert frames[2]["usage"] == usage.to_turn_dict()
        assert frames[0]["context_graph"] == frames[2]["context_graph"] == graph
        assert frames[4]["tool_events"][0]["result"] == "complete"
        assert [len(facts) for facts in writes] == [1, 4, 1, 1]
        durable = history.read(f"websocket:{chat}")
        assert [row["turn_seq"] for row in durable] == list(range(1, 8))
        assert durable[4]["tool_events"][0]["result"] == "complete"
        assert durable[-1]["event"] == "turn_end"
        assert all(row["context_graph"] == graph for row in durable if row["event"] == "model_request")
        late_frames = [json.loads(late.sent.get_nowait()) for _ in range(late.sent.qsize())]
        assert [frame["event"] for frame in late_frames] == ["message", "turn_end", "session_updated"]
        assert late_frames[0]["text"] == "answer"
    finally:
        for gate in release:
            gate.set()
        await manager.stop_all()


@pytest.mark.asyncio
async def test_activity_batches_keep_replaced_session_generations_separate(history, tmp_path) -> None:
    from nanobot.bus.outbound_events import ProgressEvent

    channel = _channel(history.sessions)
    manager = ChannelManager(
        Config.model_validate({"channels": {"websocket": {"enabled": False}}}), channel.bus,
        config_path=tmp_path / "config.json",
    )
    manager.channels["websocket"] = channel
    chat = "replaced-batch"
    key = f"websocket:{chat}"
    old = await history.metadata(chat, {"webui_turn_id": "reused-turn"})
    await history.sessions.state.reset(key)
    fresh = await history.metadata(chat, {"webui_turn_id": "reused-turn"})
    try:
        for metadata, prefix in ((old, "stale"), (fresh, "current")):
            for index in range(2):
                text = f"{prefix}-{index}"
                await manager._queue_outbound(channel, OutboundMessage(
                    "websocket", chat, text, metadata=metadata, event=ProgressEvent(content=text),
                ))
        async with asyncio.timeout(2):
            while manager.has_pending_delivery:
                await asyncio.sleep(0)
        assert [row["text"] for row in history.read(key)] == ["current-0", "current-1"]
    finally:
        await manager.stop_all()


@pytest.mark.asyncio
async def test_cancelled_activity_batch_settles_admitted_write_without_fanout(history, monkeypatch) -> None:
    import threading

    from nanobot.bus.outbound_events import ProgressEvent

    channel = _channel(history.sessions)
    chat = "cancelled-batch"
    metadata = await history.metadata(chat, {"webui_turn_id": "turn-cancel"})
    connection = _RecordingConnection()
    channel._attach(cast(Any, connection), chat)
    entered = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    append = history.sessions._store.append_history

    def gated_append(*args, **kwargs):
        loop.call_soon_threadsafe(entered.set)
        assert release.wait(2), "test did not release admitted write"
        return append(*args, **kwargs)

    monkeypatch.setattr(history.sessions._store, "append_history", gated_append)
    sending = asyncio.create_task(channel.send_batch([
        OutboundMessage("websocket", chat, text, metadata=metadata, event=ProgressEvent(content=text))
        for text in ("one", "two")
    ]))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        sending.cancel()
        await asyncio.sleep(0)
        assert not sending.done()
        assert connection.sent.empty()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await sending
        assert [row["text"] for row in history.read(f"websocket:{chat}")] == ["one", "two"]
        assert connection.sent.empty()
    finally:
        release.set()
        await asyncio.gather(sending, return_exceptions=True)
        await channel.stop()


@pytest.mark.asyncio
async def test_activity_batch_byte_limit_preserves_large_progress(history, monkeypatch) -> None:
    from nanobot.bus.outbound_events import ProgressEvent
    from nanobot.webui import outbound_delivery

    monkeypatch.setattr(outbound_delivery, "_ACTIVITY_BATCH_BYTES", 1024)
    channel = _channel(history.sessions)
    chat = "large-batch"
    metadata = await history.metadata(chat, {"webui_turn_id": "turn-large"})
    append = AsyncMock(wraps=history.sessions.state.append_history)
    monkeypatch.setattr(history.sessions.state, "append_history", append)
    texts = ["a" * 600, "b" * 1500, "c" * 100, "d" * 100]
    await channel.send_batch([
        OutboundMessage("websocket", chat, text, metadata=metadata, event=ProgressEvent(content=text))
        for text in texts
    ])
    assert [len(call.args[1]) for call in append.await_args_list] == [1, 1, 2]
    assert [row["text"] for row in history.read(f"websocket:{chat}")] == texts


@pytest.mark.asyncio
async def test_oversized_activity_does_not_poison_valid_batch_neighbors(history, monkeypatch) -> None:
    from nanobot.bus.outbound_events import ProgressEvent
    from nanobot.session import display_history

    monkeypatch.setattr(display_history, "MAX_HISTORY_FACT_BYTES", 1024)
    channel = _channel(history.sessions)
    chat = "invalid-batch-member"
    metadata = await history.metadata(chat, {"webui_turn_id": "turn-size"})
    connection = _RecordingConnection()
    channel._attach(cast(Any, connection), chat)
    texts = ["first", "x" * 1500, "last"]
    try:
        await channel.send_batch([
            OutboundMessage("websocket", chat, text, metadata=metadata, event=ProgressEvent(content=text))
            for text in texts
        ])
        assert [await _next_text(connection) for _ in texts] == texts
        assert [row["text"] for row in history.read(f"websocket:{chat}")] == ["first", "last"]
    finally:
        await channel.stop()


@pytest.mark.asyncio
async def test_unencodable_tool_argument_does_not_discard_neighboring_activity(history) -> None:
    from nanobot.bus.outbound_events import ProgressEvent

    channel = _channel(history.sessions)
    chat = "invalid-tool-argument"
    metadata = await history.metadata(chat, {"webui_turn_id": "turn-encoding"})
    connection = _RecordingConnection()
    channel._attach(cast(Any, connection), chat)
    # JSON decoding accepts this provider argument, but UTF-8 transport cannot.
    arguments = json.loads('{"query":"\\ud800"}')
    messages = [
        OutboundMessage("websocket", chat, "first", metadata=metadata, event=ProgressEvent(content="first")),
        OutboundMessage("websocket", chat, "", metadata=metadata, event=ProgressEvent(tool_events=[{
            "call_id": "bad", "name": "search", "phase": "start", "arguments": arguments,
        }])),
        OutboundMessage("websocket", chat, "last", metadata=metadata, event=ProgressEvent(content="last")),
    ]
    try:
        await channel.send_batch(messages)
        assert [await _next_text(connection) for _ in range(2)] == ["first", "last"]
        assert connection.sent.empty()
        assert [row["text"] for row in history.read(f"websocket:{chat}")] == ["first", "last"]
    finally:
        await channel.stop()


@pytest.mark.parametrize("batched", [False, True])
async def test_context_observer_orders_reads_requests_and_compaction(history, tmp_path, batched):
    from nanobot.agent.tools.filesystem import ReadFileTool
    from nanobot.bus.outbound_events import ContextCompactionEvent, ProgressEvent, TurnEndEvent
    from nanobot.events import ModelRequestEvent
    from nanobot.webui.metadata import WEBUI_TURN_METADATA_KEY

    (tmp_path / "guide.md").write_text("[Reference](reference.md)")
    result = await ReadFileTool(workspace=tmp_path).execute(path="guide.md")
    tool = {"name": "read_file", "call_id": "read", "phase": "end",
            "arguments": {"path": "guide.md"}, "result": result}
    channel = _channel(history.sessions)
    chat = "observed-context"

    async def message(event):
        return await history.message(channel="websocket", chat_id=chat, content="", event=event,
                                     metadata={WEBUI_TURN_METADATA_KEY: "turn"})

    events = [
        ModelRequestEvent("before", "run", 1, "started"),
        ProgressEvent(tool_events=[{**tool, "working_directory": str(tmp_path)}]),
        ModelRequestEvent("after", "run", 2, "started"),
    ]
    messages = [await message(event) for event in events]
    if batched:
        await channel.send_batch(messages)
    else:
        for msg in messages:
            await channel.send(msg)
    requests = [row for row in history.read(f"websocket:{chat}") if row["event"] == "model_request"]
    assert requests[0]["context_graph"] == {"nodes": [], "edges": []}
    graph = requests[-1]["context_graph"]
    assert [(node["name"], node["state"]) for node in graph["nodes"]] == [
        ("guide.md", "loaded"), ("reference.md", "discovered"),
    ]
    # End-of-turn cleanup and a fresh delivery service must recover display state.
    await channel.send(await message(TurnEndEvent()))
    channel = _channel(history.sessions)
    await channel.send(await message(ContextCompactionEvent("failed", "failed")))
    await channel.send(await message(ModelRequestEvent("restored", "run", 3, "started")))
    requests = [row for row in history.read(f"websocket:{chat}") if row["event"] == "model_request"]
    assert requests[-1]["context_graph"] == graph
    await channel.send(await message(ContextCompactionEvent("done", "succeeded")))
    await channel.send(await message(ModelRequestEvent("reset", "run", 4, "started")))
    requests = [row for row in history.read(f"websocket:{chat}") if row["event"] == "model_request"]
    assert requests[-1]["context_graph"] == {"nodes": [], "edges": []}


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["local", "native", "response"])
async def test_compaction_keeps_system_sources_in_new_graph(history, tmp_path, mode) -> None:
    from functools import partial

    from nanobot.agent.context import ContextBuilder, TranscriptInput
    from nanobot.agent.runner import AgentRunner, AgentRunSpec
    from nanobot.bus.outbound_events import ProgressEvent
    from nanobot.events import EventSink, ModelRequestEvent
    from nanobot.providers.base import GenerationSettings, LLMResponse
    from nanobot.providers.compaction import NativeCompaction, ProviderCompactionEvents
    from nanobot.providers.openai_responses.state import (
        attach_responses_state,
        build_responses_compaction_state,
    )
    from nanobot.utils.llm_runtime import LLMRuntime
    from nanobot.webui.context_observer import ContextGraphObserver
    from nanobot.webui.context_source_hook import ContextSourceHook

    workspace = tmp_path / "prompt-workspace"
    workspace.mkdir()
    soul = workspace / "SOUL.md"
    soul.write_text("Be precise. [Old](old.md)" if mode == "local" else "Be precise. [Guide](guide.md)", encoding="utf-8")
    skill = workspace / "skills" / "review" / "SKILL.md"
    if mode == "local":
        skill.parent.mkdir(parents=True)
        skill.write_text("---\nname: review\ndescription: Review changes.\n---\n\n# Review workflow", encoding="utf-8")
    channel = _channel(history.sessions)
    chat = "compacted-graph"
    metadata = await history.metadata(chat, {"webui_turn_id": "turn"})
    connection = _RecordingConnection()
    channel._attach(cast(Any, connection), chat)

    async def send(event):
        await channel.send(OutboundMessage("websocket", chat, "", metadata=metadata, event=event))

    def read_event(name, call_id):
        return ProgressEvent(tool_events=[{
            "name": "read_file", "phase": "end", "call_id": call_id,
            "arguments": {"path": str(workspace / name)}, "result": "1| content",
        }])

    async def provider_call(**kwargs):
        assert "Be precise" in kwargs["messages"][0]["content"]
        response = LLMResponse(content="done")
        if mode == "native":
            compaction = ProviderCompactionEvents(kwargs["provider_context"].events)
            event_id = await compaction.start("provider_native")
            state = build_responses_compaction_state(provider="codex", model="test", output_items=[
                {"type": "compaction", "encrypted_content": "synthetic"},
            ])
            assert state is not None
            await compaction.accept(NativeCompaction(state, state, event_id), commit=None)
            response.provider_compaction_applied = True
            response.provider_compaction_state = state
            response.provider_compaction_scope = "prior_context"
            response.provider_compaction_event_id = event_id
            async with asyncio.timeout(2):
                while True:
                    frame = json.loads(await connection.sent.get())
                    if frame.get("event") == "context_compaction" and frame.get("phase") == "succeeded":
                        break
            graph = frame["context_graph"]
            assert {"SOUL.md", "guide.md"} <= {node["name"] for node in graph["nodes"]}
            assert "before.py" not in {node["name"] for node in graph["nodes"]}
            replay = history.build(f"websocket:{chat}", include_model_requests=True)
            boundary = next(row for row in replay["events"] if row.get("event") == "context_compaction")
            assert boundary["context_graph"] == graph
            observer = ContextGraphObserver(history.sessions)
            assert await observer.snapshot(chat, metadata, persistent=True) == graph
        elif mode == "local":
            assert "Summary of earlier work" in kwargs["messages"][0]["content"]
        else:
            attach_responses_state(response, provider="codex", model="test", input_items=[], output_items=[
                {"type": "compaction", "encrypted_content": "synthetic"},
            ])
        return response

    provider = MagicMock()
    provider.chat_stream_with_retry = provider_call
    tools = MagicMock()
    tools.get_definitions.return_value = []
    events = EventSink(send)

    async def consolidate_history(_messages, _summary):
        soul.write_text("Be precise. [Guide](guide.md)", encoding="utf-8")
        return "Summary of earlier work"

    try:
        await send(read_event("before.py", "before"))
        result = await AgentRunner().run(AgentRunSpec(
            initial_messages=None, tools=tools,
            runtime=LLMRuntime(provider=provider, model="test", generation=GenerationSettings(max_tokens=1000),
                               context_window_tokens=8192 if mode == "local" else 128000),
            max_iterations=2, max_tool_result_chars=10000, workspace=workspace,
            transcript_input=TranscriptInput(
                history=[{"role": "user", "content": "previous work " * 12000}] if mode == "local" else [],
                current_message="hello $review" if mode == "local" else "hello",
            ),
            transcript_builder=partial(ContextBuilder(workspace).build_transcript, channel="websocket"),
            consolidate_history=consolidate_history, hook=ContextSourceHook(events), events=events,
        ))
        assert result.final_content == "done"
        records = history.read(f"websocket:{chat}")
        boundary = next(row for row in records if row.get("event") == "context_compaction" and row.get("phase") == "succeeded")
        if mode != "local":
            started = next(row for row in records if row.get("event") == "model_request" and row.get("phase") == "started")
            assert "before.py" in {node["name"] for node in started["context_graph"]["nodes"]}
        boundary_names = {node["name"] for node in boundary["context_graph"]["nodes"]}
        assert {"SOUL.md", "guide.md"} <= boundary_names
        assert "before.py" not in boundary_names
        assert "old.md" not in boundary_names
        completed = next(row for row in records if row.get("event") == "model_request" and row.get("phase") == "completed")
        names = {node["name"] for node in completed["context_graph"]["nodes"]}
        assert {"SOUL.md", "guide.md"} <= names
        if mode == "local":
            boundary_skill = next(node for node in boundary["context_graph"]["nodes"] if node["path"] == str(skill))
            request_skill = next(node for node in completed["context_graph"]["nodes"] if node["path"] == str(skill))
            assert boundary_skill["state"] == "discovered"
            assert request_skill["state"] == "loaded"
        assert {"source": str(soul), "target": str(workspace / "guide.md")} in completed["context_graph"]["edges"]
        if mode == "response":
            assert records.index(completed) < records.index(boundary)
        else:
            assert records.index(boundary) < records.index(completed)
            assert "before.py" not in names
        assert "old.md" not in names

        await send(read_event("after.py", "after"))
        request = ModelRequestEvent("next", "run-next", 1, "started")
        restored_channel = _channel(history.sessions)
        await restored_channel.send(OutboundMessage("websocket", chat, "", metadata=metadata, event=request))
        records = history.read(f"websocket:{chat}")
        latest = next(row for row in reversed(records) if row.get("event") == "model_request")
        names = {node["name"] for node in latest["context_graph"]["nodes"]}
        assert {"SOUL.md", "guide.md", "after.py"} <= names
        assert "before.py" not in names
    finally:
        await channel._cleanup_connection(cast(Any, connection))


@pytest.mark.asyncio
async def test_local_compaction_publishes_rebuilt_system_graph_before_next_request(history, tmp_path, monkeypatch) -> None:
    from functools import partial

    from nanobot.agent.context import ContextBuilder, TranscriptInput
    from nanobot.agent.runner import AgentRunner, AgentRunSpec
    from nanobot.events import EventSink
    from nanobot.providers.base import GenerationSettings, LLMProvider, LLMResponse, ToolCallRequest
    from nanobot.utils.llm_runtime import LLMRuntime
    from nanobot.webui.context_source_hook import ContextSourceHook

    workspace = tmp_path / "prompt-workspace"
    workspace.mkdir()
    soul = workspace / "SOUL.md"
    soul.write_text("[Old](old.md)", encoding="utf-8")
    channel = _channel(history.sessions)
    chat = "rebuilt-prompt"
    metadata = await history.metadata(chat, {"webui_turn_id": "turn"})

    async def send(event):
        await channel.send(OutboundMessage("websocket", chat, "", metadata=metadata, event=event))

    provider = MagicMock(spec=LLMProvider)
    provider.can_resume_conversation_state.return_value = False
    provider.supports_pre_request_compaction.return_value = False
    prompts = []

    async def provider_call(**kwargs):
        prompts.append(kwargs["messages"][0]["content"])
        if len(prompts) == 1:
            return LLMResponse(content=None, tool_calls=[ToolCallRequest(id="edit", name="edit_file", arguments={})])
        return LLMResponse(content="done")

    provider.chat_stream_with_retry = provider_call
    tools = MagicMock()
    tools.get_definitions.return_value = []

    async def edit_file(*_args, **_kwargs):
        soul.write_text("[New](new.md)", encoding="utf-8")
        return "updated"

    tools.execute = AsyncMock(side_effect=edit_file)

    def estimate(_provider, _model, messages, _tools):
        has_tool_result = any(message.get("role") == "tool" and message.get("content") == "updated" for message in messages)
        has_summary = any(message.get("role") == "system" and "Summary after compaction" in message.get("content", "") for message in messages)
        return (600 if has_tool_result and not has_summary else 100, "test-counter")

    monkeypatch.setattr("nanobot.agent.context_governance.estimate_prompt_tokens_chain", estimate)
    events = EventSink(send)
    result = await AgentRunner().run(AgentRunSpec(
        initial_messages=None, tools=tools,
        runtime=LLMRuntime(provider=provider, model="test", generation=GenerationSettings(max_tokens=100),
                           context_window_tokens=1624),
        max_iterations=2, max_tool_result_chars=10000, workspace=workspace,
        transcript_input=TranscriptInput(history=[], current_message="update the prompt"),
        transcript_builder=partial(ContextBuilder(workspace).build_transcript, channel="websocket"),
        consolidate_history=AsyncMock(return_value="Summary after compaction"),
        hook=ContextSourceHook(events), events=events,
    ))
    assert result.final_content == "done"
    assert "[Old](old.md)" in prompts[0]
    assert "[New](new.md)" in prompts[1]
    records = history.read(f"websocket:{chat}")
    boundary = next(row for row in records if row.get("event") == "context_compaction" and row.get("phase") == "succeeded")
    request = next(row for row in reversed(records) if row.get("event") == "model_request" and row.get("phase") == "started")
    assert boundary["context_graph"] == request["context_graph"]
    names = {node["name"] for node in boundary["context_graph"]["nodes"]}
    assert "new.md" in names and "old.md" not in names
    replay = history.build(f"websocket:{chat}", include_model_requests=True)
    replay_boundary = next(row for row in replay["events"] if row.get("event") == "context_compaction")
    assert replay_boundary["context_graph"] == boundary["context_graph"]


@pytest.mark.asyncio
@pytest.mark.parametrize("batched", [False, True])
@pytest.mark.parametrize("request_after_read", [False, True])
async def test_next_turn_replaces_restored_system_sources_without_losing_reads(history, tmp_path, request_after_read, batched) -> None:
    from nanobot.bus.outbound_events import ProgressEvent, TurnEndEvent
    from nanobot.context_sources import PromptSource, PromptSourcesEvent
    from nanobot.events import AgentEvent, ContextCompactionEvent, ModelRequestEvent
    from nanobot.file_references import source_receipt

    channel = _channel(history.sessions)
    chat = "restored-prompt"
    first = await history.metadata(chat, {"webui_turn_id": "first"})
    second = await history.metadata(chat, {"webui_turn_id": "second"})
    soul = tmp_path / "SOUL.md"
    old_prompt, new_prompt, read_content = "[Old](old.md)", "[New](new.md)", "[Post](post.md)"

    async def send(event, metadata):
        await channel.send(OutboundMessage("websocket", chat, "", metadata=metadata, event=event))

    def read(path, content, call_id):
        return ProgressEvent(tool_events=[{
            "name": "read_file", "phase": "end", "call_id": call_id,
            "arguments": {"path": str(path)}, "result": f"1| {content}",
        }])

    async def send_events(events, metadata):
        messages = [OutboundMessage("websocket", chat, "", metadata=metadata, event=event) for event in events]
        if batched:
            await channel.send_batch(messages)
        else:
            for message in messages:
                await channel.send(message)

    await send(PromptSourcesEvent((), (PromptSource(soul, old_prompt),)), first)
    await send_events([
        ModelRequestEvent("first", "run-first", 1, "started"),
        read(tmp_path / "before.py", "old read", "before"),
    ], first)
    await send(ContextCompactionEvent("compact", "succeeded"), first)
    events: list[AgentEvent] = [read(soul, read_content, "after")]
    if request_after_read:
        events.append(ModelRequestEvent("after", "run-first", 2, "started"))
    await send_events(events, first)
    await send(TurnEndEvent(), first)

    await send(PromptSourcesEvent((), (PromptSource(soul, new_prompt),)), second)
    await send(ModelRequestEvent("second", "run-second", 1, "started"), second)
    records = history.read(f"websocket:{chat}")
    graph = next(row["context_graph"] for row in reversed(records) if row.get("event") == "model_request")
    nodes = {node["name"]: node for node in graph["nodes"]}
    assert {"SOUL.md", "new.md", "post.md"} <= nodes.keys()
    assert "old.md" not in nodes and "before.py" not in nodes
    assert nodes["SOUL.md"]["tokens"] == (
        source_receipt(soul, new_prompt)["tokens"] + source_receipt(soul, read_content)["tokens"]
    )
    assert {"source": str(soul), "target": str(tmp_path / "new.md")} in graph["edges"]
    assert {"source": str(soul), "target": str(tmp_path / "post.md")} in graph["edges"]
