"""Tests for ChannelManager delta coalescing to reduce streaming latency."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.outbound_events import (
    ProgressEvent,
    RetryWaitEvent,
    StreamDeltaEvent,
    StreamEndEvent,
    outbound_event_from_message,
    outbound_message_for_event,
)
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.channels.manager import ChannelManager
from nanobot.config.schema import Config


class MockChannel(BaseChannel):
    """Mock channel for testing."""

    name = "mock"
    display_name = "Mock"

    def __init__(self, config, bus):
        super().__init__(config, bus)
        self._send_delta_mock = AsyncMock()
        self._send_mock = AsyncMock()

    async def start(self):
        pass

    async def stop(self):
        pass

    async def send(self, msg):
        return await self._send_mock(msg)

    async def send_delta(
        self,
        chat_id,
        delta,
        metadata=None,
        *,
        stream_id=None,
        stream_end=False,
        resuming=False,
    ):
        return await self._send_delta_mock(
            chat_id,
            delta,
            metadata,
            stream_id=stream_id,
            stream_end=stream_end,
            resuming=resuming,
        )


@pytest.fixture
def config():
    """Create a minimal config for testing."""
    return Config.model_validate({"channels": {"websocket": {"enabled": False}}})


@pytest.fixture
def bus():
    return MessageBus()


@pytest.fixture
def manager(config, bus):
    manager = ChannelManager(config, bus)
    manager.channels["mock"] = MockChannel({}, bus)
    return manager


def _delta(content: str, *, chat_id: str = "chat1", stream_id: str | None = None):
    return outbound_message_for_event(
        channel="mock",
        chat_id=chat_id,
        event=StreamDeltaEvent(content=content, stream_id=stream_id),
    )


def _end(
    content: str = "",
    *,
    chat_id: str = "chat1",
    stream_id: str | None = None,
    resuming: bool = False,
):
    return outbound_message_for_event(
        channel="mock",
        chat_id=chat_id,
        event=StreamEndEvent(content=content, stream_id=stream_id, resuming=resuming),
    )


class TestDeltaCoalescing:
    """Tests for stream delta message coalescing."""

    @pytest.mark.asyncio
    async def test_single_delta_not_coalesced(self, manager, bus):
        msg = _delta("Hello")
        await bus.publish_outbound(msg)

        async def process_one():
            try:
                m = await asyncio.wait_for(bus.consume_outbound(), timeout=0.1)
                event = outbound_event_from_message(m)
                if isinstance(event, StreamDeltaEvent):
                    m, pending = manager._coalesce_stream_deltas(m)
                    for p in pending:
                        await bus.publish_outbound(p)
                channel = manager.channels.get(m.channel)
                event = outbound_event_from_message(m)
                if channel and isinstance(event, StreamDeltaEvent):
                    await channel.send_delta(
                        m.chat_id,
                        m.content,
                        m.metadata,
                        stream_id=event.stream_id,
                    )
            except asyncio.TimeoutError:
                pass

        await process_one()

        manager.channels["mock"]._send_delta_mock.assert_called_once_with(
            "chat1",
            "Hello",
            {},
            stream_id=None,
            stream_end=False,
            resuming=False,
        )

    @pytest.mark.asyncio
    async def test_multiple_deltas_coalesced(self, manager, bus):
        for text in ["Hello", " ", "world", "!"]:
            await bus.publish_outbound(_delta(text))

        first_msg = await bus.consume_outbound()
        merged, pending = manager._coalesce_stream_deltas(first_msg)

        assert merged.content == "Hello world!"
        assert isinstance(merged.event, StreamDeltaEvent)
        assert len(pending) == 0

    @pytest.mark.asyncio
    async def test_deltas_different_chats_not_coalesced(self, manager, bus):
        await bus.publish_outbound(_delta("Hello", chat_id="chat1"))
        await bus.publish_outbound(_delta("World", chat_id="chat2"))

        first_msg = await bus.consume_outbound()
        merged, pending = manager._coalesce_stream_deltas(first_msg)

        assert merged.content == "Hello"
        assert merged.chat_id == "chat1"
        assert len(pending) == 1
        assert pending[0].chat_id == "chat2"
        assert pending[0].content == "World"

    @pytest.mark.asyncio
    async def test_deltas_different_stream_ids_not_coalesced(self, manager, bus):
        await bus.publish_outbound(_delta("A1", stream_id="stream-a"))
        await bus.publish_outbound(_delta("B1", stream_id="stream-b"))

        first_msg = await bus.consume_outbound()
        merged, pending = manager._coalesce_stream_deltas(first_msg)

        assert merged.content == "A1"
        assert isinstance(merged.event, StreamDeltaEvent)
        assert merged.event.stream_id == "stream-a"
        assert len(pending) == 1
        assert pending[0].content == "B1"
        assert isinstance(pending[0].event, StreamDeltaEvent)
        assert pending[0].event.stream_id == "stream-b"

    @pytest.mark.asyncio
    async def test_stream_end_terminates_coalescing(self, manager, bus):
        await bus.publish_outbound(_delta("Hello"))
        await bus.publish_outbound(_end(" world"))

        first_msg = await bus.consume_outbound()
        merged, pending = manager._coalesce_stream_deltas(first_msg)

        assert merged.content == "Hello world"
        assert isinstance(merged.event, StreamEndEvent)
        assert len(pending) == 0

    @pytest.mark.asyncio
    async def test_coalescing_stops_at_first_non_matching_boundary(self, manager, bus):
        await bus.publish_outbound(_delta("Hello", stream_id="seg-1"))
        await bus.publish_outbound(_end(stream_id="seg-1"))
        await bus.publish_outbound(_delta("world", stream_id="seg-2"))

        first_msg = await bus.consume_outbound()
        merged, pending = manager._coalesce_stream_deltas(first_msg)

        assert merged.content == "Hello"
        assert isinstance(merged.event, StreamDeltaEvent)
        assert len(pending) == 1
        assert isinstance(pending[0].event, StreamEndEvent)
        assert pending[0].event.stream_id == "seg-1"

        remaining = await bus.consume_outbound()
        assert remaining.content == "world"
        assert isinstance(remaining.event, StreamDeltaEvent)
        assert remaining.event.stream_id == "seg-2"

    @pytest.mark.asyncio
    async def test_non_delta_message_preserved(self, manager, bus):
        await bus.publish_outbound(_delta("Delta"))
        await bus.publish_outbound(OutboundMessage(
            channel="mock",
            chat_id="chat1",
            content="Final message",
        ))

        first_msg = await bus.consume_outbound()
        merged, pending = manager._coalesce_stream_deltas(first_msg)

        assert merged.content == "Delta"
        assert len(pending) == 1
        assert pending[0].content == "Final message"
        assert pending[0].event is None

    @pytest.mark.asyncio
    async def test_empty_queue_stops_coalescing(self, manager, bus):
        await bus.publish_outbound(_delta("Only message"))

        first_msg = await bus.consume_outbound()
        merged, pending = manager._coalesce_stream_deltas(first_msg)

        assert merged.content == "Only message"
        assert len(pending) == 0


class TestDispatchOutboundWithCoalescing:
    """Tests for the full _dispatch_outbound flow with coalescing."""

    @pytest.mark.asyncio
    async def test_dispatch_coalesces_and_processes_pending(self, manager, bus):
        await bus.publish_outbound(_delta("A"))
        await bus.publish_outbound(_delta("B"))
        await bus.publish_outbound(OutboundMessage(
            channel="mock",
            chat_id="chat1",
            content="Final",
        ))

        pending = []
        processed = []

        msg = pending.pop(0) if pending else await bus.consume_outbound()
        event = outbound_event_from_message(msg)
        if isinstance(event, StreamDeltaEvent):
            msg, extra_pending = manager._coalesce_stream_deltas(msg)
            pending.extend(extra_pending)

        channel = manager.channels.get(msg.channel)
        event = outbound_event_from_message(msg)
        if channel and isinstance(event, StreamDeltaEvent):
            await channel.send_delta(
                msg.chat_id,
                msg.content,
                msg.metadata,
                stream_id=event.stream_id,
            )
            processed.append(("delta", msg.content))

        assert processed == [("delta", "AB")]
        assert len(pending) == 1
        assert pending[0].content == "Final"


class TestProgressFiltering:
    """Progress filtering should honor per-channel settings."""

    def test_progress_visibility_uses_global_defaults(self, manager):
        assert manager._should_send_progress("mock", tool_hint=False) is True
        assert manager._should_send_progress("mock", tool_hint=True) is False

    def test_progress_visibility_uses_channel_overrides(self, manager):
        manager.channels["mock"].send_progress = False
        manager.channels["mock"].send_tool_hints = True

        assert manager._should_send_progress("mock", tool_hint=False) is False
        assert manager._should_send_progress("mock", tool_hint=True) is True

    def test_progress_visibility_returns_false_for_missing_channel(self, manager):
        assert manager._should_send_progress("nonexistent", tool_hint=False) is False
        assert manager._should_send_progress("nonexistent", tool_hint=True) is False

    def test_resolve_bool_override_dict(self, manager):
        assert manager._resolve_bool_override({}, "send_progress", True) is True
        assert manager._resolve_bool_override({"send_progress": False}, "send_progress", True) is False
        assert manager._resolve_bool_override({"sendProgress": False}, "send_progress", True) is False
        assert manager._resolve_bool_override({"send_progress": "false"}, "send_progress", True) is True

    def test_resolve_bool_override_model(self, manager):
        class FakeSection:
            send_progress = False
            send_tool_hints = True

        assert manager._resolve_bool_override(FakeSection(), "send_progress", True) is False
        assert manager._resolve_bool_override(FakeSection(), "send_tool_hints", False) is True
        assert manager._resolve_bool_override(FakeSection(), "unknown_key", True) is True

    @pytest.mark.asyncio
    async def test_channel_override_can_drop_progress_message(self, manager, bus):
        manager.channels["mock"].send_progress = False
        await bus.publish_outbound(outbound_message_for_event(
            channel="mock",
            chat_id="chat1",
            event=ProgressEvent(content="thinking"),
        ))
        await bus.publish_outbound(OutboundMessage(
            channel="mock",
            chat_id="chat1",
            content="final answer",
        ))

        task = asyncio.create_task(manager._dispatch_outbound())
        try:
            for _ in range(30):
                if manager.channels["mock"]._send_mock.await_count >= 1:
                    break
                await asyncio.sleep(0.05)
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        send_mock = manager.channels["mock"]._send_mock
        assert send_mock.await_count == 1
        assert send_mock.await_args_list[0].args[0].content == "final answer"

    @pytest.mark.asyncio
    async def test_legacy_progress_flag_uses_runtime_progress_filter(self, manager, bus):
        manager.channels["mock"].send_progress = False
        await bus.publish_outbound(OutboundMessage(
            channel="mock",
            chat_id="chat1",
            content="legacy progress-shaped message",
            metadata={"_progress": True},
        ))
        await bus.publish_outbound(OutboundMessage(
            channel="mock",
            chat_id="chat1",
            content="processing sentinel",
        ))

        task = asyncio.create_task(manager._dispatch_outbound())
        try:
            for _ in range(30):
                if manager.channels["mock"]._send_mock.await_count >= 1:
                    break
                await asyncio.sleep(0.05)
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        send_mock = manager.channels["mock"]._send_mock
        assert send_mock.await_count == 1
        assert send_mock.await_args.args[0].content == "processing sentinel"

    @pytest.mark.asyncio
    async def test_channel_override_can_enable_tool_hints(self, manager, bus):
        manager.channels["mock"].send_tool_hints = True
        await bus.publish_outbound(outbound_message_for_event(
            channel="mock",
            chat_id="chat1",
            event=ProgressEvent(content="read_file(foo.py)", tool_hint=True),
        ))

        task = asyncio.create_task(manager._dispatch_outbound())
        try:
            for _ in range(30):
                if manager.channels["mock"]._send_mock.await_count >= 1:
                    break
                await asyncio.sleep(0.05)
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        send_mock = manager.channels["mock"]._send_mock
        assert send_mock.await_count == 1
        assert send_mock.await_args_list[0].args[0].content == "read_file(foo.py)"


class TestRetryWaitFiltering:
    """Internal provider retry heartbeats must never reach channels."""

    @pytest.mark.asyncio
    async def test_retry_wait_message_dropped(self, manager, bus):
        retry_msg = outbound_message_for_event(
            channel="mock",
            chat_id="chat1",
            event=RetryWaitEvent(content="Model request failed, retry in 1s (attempt 1)."),
        )
        real_msg = OutboundMessage(
            channel="mock",
            chat_id="chat1",
            content="final answer",
        )
        await bus.publish_outbound(retry_msg)
        await bus.publish_outbound(real_msg)

        task = asyncio.create_task(manager._dispatch_outbound())
        try:
            for _ in range(30):
                if manager.channels["mock"]._send_mock.await_count >= 1:
                    break
                await asyncio.sleep(0.05)
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        send_mock = manager.channels["mock"]._send_mock
        assert send_mock.await_count == 1
        sent = send_mock.await_args_list[0].args[0]
        assert sent.content == "final answer"
        assert sent.event is None
