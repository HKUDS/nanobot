"""Tests for ChannelManager delta coalescing to reduce streaming latency."""
import asyncio
from unittest.mock import AsyncMock

import pytest

from janniebot.bus.events import OutboundMessage
from janniebot.bus.queue import MessageBus
from janniebot.channels.base import BaseChannel
from janniebot.channels.manager import ChannelManager
from janniebot.config.schema import Config


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
        """Implement abstract method."""
        return await self._send_mock(msg)

    async def send_delta(self, chat_id, delta, metadata=None):
        """Override send_delta for testing."""
        return await self._send_delta_mock(chat_id, delta, metadata)


@pytest.fixture
def config():
    """Create a minimal config for testing."""
    return Config()


@pytest.fixture
def bus():
    """Create a message bus for testing."""
    return MessageBus()


@pytest.fixture
def manager(config, bus):
    """Create a channel manager with a mock channel."""
    manager = ChannelManager(config, bus)
    manager.channels["mock"] = MockChannel({}, bus)
    return manager


class TestDeltaCoalescing:
    """Tests for _stream_delta message coalescing."""

    @pytest.mark.asyncio
    async def test_single_delta_not_coalesced(self, manager, bus):
        """A single delta should be sent as-is."""
        msg = OutboundMessage(
            channel="mock",
            chat_id="chat1",
            content="Hello",
            metadata={"_stream_delta": True},
        )
        await bus.publish_outbound(msg)

        # Process one message
        async def process_one():
            try:
                m = await asyncio.wait_for(bus.consume_outbound(), timeout=0.1)
                if m.metadata.get("_stream_delta"):
                    m, pending = manager._coalesce_stream_deltas(m)
                    # Put pending back (none expected)
                    for p in pending:
                        await bus.publish_outbound(p)
                channel = manager.channels.get(m.channel)
                if channel:
                    await channel.send_delta(m.chat_id, m.content, m.metadata)
            except asyncio.TimeoutError:
                pass

        await process_one()

        manager.channels["mock"]._send_delta_mock.assert_called_once_with(
            "chat1", "Hello", {"_stream_delta": True}
        )

    @pytest.mark.asyncio
    async def test_multiple_deltas_coalesced(self, manager, bus):
        """Multiple consecutive deltas for same chat should be merged."""
        # Put multiple deltas in queue
        for text in ["Hello", " ", "world", "!"]:
            await bus.publish_outbound(OutboundMessage(
                channel="mock",
                chat_id="chat1",
                content=text,
                metadata={"_stream_delta": True},
            ))

        # Process using coalescing logic
        first_msg = await bus.consume_outbound()
        merged, pending = manager._coalesce_stream_deltas(first_msg)

        # Should have merged all deltas
        assert merged.content == "Hello world!"
        assert merged.metadata.get("_stream_delta") is True
        # No pending messages (all were coalesced)
        assert len(pending) == 0

    @pytest.mark.asyncio
    async def test_deltas_different_chats_not_coalesced(self, manager, bus):
        """Deltas for different chats should not be merged."""
        # Put deltas for different chats
        await bus.publish_outbound(OutboundMessage(
            channel="mock",
            chat_id="chat1",
            content="Hello",
            metadata={"_stream_delta": True},
        ))
        await bus.publish_outbound(OutboundMessage(
            channel="mock",
            chat_id="chat2",
            content="World",
            metadata={"_stream_delta": True},
        ))

        first_msg = await bus.consume_outbound()
        merged, pending = manager._coalesce_stream_deltas(first_msg)

        # First chat should not include second chat's content
        assert merged.content == "Hello"
        assert merged.chat_id == "chat1"
        # Second chat should be in pending
        assert len(pending) == 1
        assert pending[0].chat_id == "chat2"
        assert pending[0].content == "World"

    @pytest.mark.asyncio
    async def test_stream_end_terminates_coalescing(self, manager, bus):
        """_stream_end should stop coalescing and be included in final message."""
        # Put deltas with stream_end at the end
        await bus.publish_outbound(OutboundMessage(
            channel="mock",
            chat_id="chat1",
            content="Hello",
            metadata={"_stream_delta": True},
        ))
        await bus.publish_outbound(OutboundMessage(
            channel="mock",
            chat_id="chat1",
            content=" world",
            metadata={"_stream_delta": True, "_stream_end": True},
        ))

        first_msg = await bus.consume_outbound()
        merged, pending = manager._coalesce_stream_deltas(first_msg)

        # Should have merged content
        assert merged.content == "Hello world"
        # Should have stream_end flag
        assert merged.metadata.get("_stream_end") is True
        # No pending
        assert len(pending) == 0

    @pytest.mark.asyncio
    async def test_coalescing_stops_at_first_non_matching_boundary(self, manager, bus):
        """Only consecutive deltas should be merged; later deltas stay queued."""
        await bus.publish_outbound(OutboundMessage(
            channel="mock",
            chat_id="chat1",
            content="Hello",
            metadata={"_stream_delta": True, "_stream_id": "seg-1"},
        ))
        await bus.publish_outbound(OutboundMessage(
            channel="mock",
            chat_id="chat1",
            content="",
            metadata={"_stream_end": True, "_stream_id": "seg-1"},
        ))
        await bus.publish_outbound(OutboundMessage(
            channel="mock",
            chat_id="chat1",
            content="world",
            metadata={"_stream_delta": True, "_stream_id": "seg-2"},
        ))

        first_msg = await bus.consume_outbound()
        merged, pending = manager._coalesce_stream_deltas(first_msg)

        assert merged.content == "Hello"
        assert merged.metadata.get("_stream_end") is None
        assert len(pending) == 1
        assert pending[0].metadata.get("_stream_end") is True
        assert pending[0].metadata.get("_stream_id") == "seg-1"

        # The next stream segment must remain in queue order for later dispatch.
        remaining = await bus.consume_outbound()
        assert remaining.content == "world"
        assert remaining.metadata.get("_stream_id") == "seg-2"

    @pytest.mark.asyncio
    async def test_non_delta_message_preserved(self, manager, bus):
        """Non-delta messages should be preserved in pending list."""
        await bus.publish_outbound(OutboundMessage(
            channel="mock",
            chat_id="chat1",
            content="Delta",
            metadata={"_stream_delta": True},
        ))
        await bus.publish_outbound(OutboundMessage(
            channel="mock",
            chat_id="chat1",
            content="Final message",
            metadata={},  # Not a delta
        ))

        first_msg = await bus.consume_outbound()
        merged, pending = manager._coalesce_stream_deltas(first_msg)

        assert merged.content == "Delta"
        assert len(pending) == 1
        assert pending[0].content == "Final message"
        assert pending[0].metadata.get("_stream_delta") is None

    @pytest.mark.asyncio
    async def test_empty_queue_stops_coalescing(self, manager, bus):
        """Coalescing should stop when queue is empty."""
        await bus.publish_outbound(OutboundMessage(
            channel="mock",
            chat_id="chat1",
            content="Only message",
            metadata={"_stream_delta": True},
        ))

        first_msg = await bus.consume_outbound()
        merged, pending = manager._coalesce_stream_deltas(first_msg)

        assert merged.content == "Only message"
        assert len(pending) == 0


class TestDispatchOutboundWithCoalescing:
    """Tests for the full _dispatch_outbound flow with coalescing."""

    @pytest.mark.asyncio
    async def test_dispatch_coalesces_and_processes_pending(self, manager, bus):
        """_dispatch_outbound should coalesce deltas and process pending messages."""
        # Put multiple deltas followed by a regular message
        await bus.publish_outbound(OutboundMessage(
            channel="mock",
            chat_id="chat1",
            content="A",
            metadata={"_stream_delta": True},
        ))
        await bus.publish_outbound(OutboundMessage(
            channel="mock",
            chat_id="chat1",
            content="B",
            metadata={"_stream_delta": True},
        ))
        await bus.publish_outbound(OutboundMessage(
            channel="mock",
            chat_id="chat1",
            content="Final",
            metadata={},  # Regular message
        ))

        # Run one iteration of dispatch logic manually
        pending = []
        processed = []

        # First iteration: should coalesce A+B
        if pending:
            msg = pending.pop(0)
        else:
            msg = await bus.consume_outbound()

        if msg.metadata.get("_stream_delta") and not msg.metadata.get("_stream_end"):
            msg, extra_pending = manager._coalesce_stream_deltas(msg)
            pending.extend(extra_pending)

        channel = manager.channels.get(msg.channel)
        if channel:
            await channel.send_delta(msg.chat_id, msg.content, msg.metadata)
            processed.append(("delta", msg.content))

        # Should have sent coalesced delta
        assert processed == [("delta", "AB")]
        # Should have pending regular message
        assert len(pending) == 1
        assert pending[0].content == "Final"
