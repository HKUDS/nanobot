"""Tests for nanobot.channels.web and nanobot.web.streaming."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.channels.web import WebChannel

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def bus() -> MagicMock:
    b = MagicMock()
    b.publish_inbound = AsyncMock()
    b.consume_outbound = AsyncMock()
    return b


@pytest.fixture()
def channel(bus: MagicMock) -> WebChannel:
    cfg = MagicMock()
    cfg.allowFrom = []
    return WebChannel(cfg, bus)


# ---------------------------------------------------------------------------
# WebChannel unit tests
# ---------------------------------------------------------------------------


class TestWebChannelStartStop:
    async def test_start_creates_dispatcher_task(self, channel: WebChannel):
        await channel.start()
        assert channel._dispatcher_task is not None
        assert not channel._dispatcher_task.done()
        await channel.stop()

    async def test_stop_cancels_dispatcher_task(self, channel: WebChannel):
        await channel.start()
        task = channel._dispatcher_task
        await channel.stop()
        assert task is not None
        assert task.done()

    async def test_stop_noop_without_start(self, channel: WebChannel):
        await channel.stop()  # should not raise


class TestWebChannelSend:
    async def test_send_routes_to_registered_stream(self, channel: WebChannel):
        q = channel.register_stream("chat-1")
        msg = OutboundMessage(channel="web", chat_id="chat-1", content="hello", metadata={})
        await channel.send(msg)
        assert not q.empty()
        result = await q.get()
        assert result.content == "hello"

    async def test_send_drops_unknown_chat_id(self, channel: WebChannel):
        msg = OutboundMessage(channel="web", chat_id="unknown", content="hello", metadata={})
        await channel.send(msg)  # should not raise


class TestWebChannelStreamRegistration:
    def test_register_and_unregister(self, channel: WebChannel):
        channel.register_stream("chat-1")
        assert "chat-1" in channel._streams
        channel.unregister_stream("chat-1")
        assert "chat-1" not in channel._streams

    def test_unregister_missing_noop(self, channel: WebChannel):
        channel.unregister_stream("nonexistent")  # should not raise


class TestPublishUserMessage:
    async def test_publishes_inbound_message(self, channel: WebChannel, bus: MagicMock):
        # is_allowed returns True for any sender when allowFrom is empty
        with patch.object(channel, "is_allowed", return_value=True):
            await channel.publish_user_message("chat-1", "hi there")
        bus.publish_inbound.assert_awaited_once()
        msg = bus.publish_inbound.call_args[0][0]
        assert msg.content == "hi there"
        assert msg.chat_id == "chat-1"


class TestDispatchOutbound:
    async def test_routes_web_messages(self, channel: WebChannel, bus: MagicMock):
        q = channel.register_stream("chat-1")
        msg = OutboundMessage(channel="web", chat_id="chat-1", content="response", metadata={})
        bus.consume_outbound = AsyncMock(side_effect=[msg, asyncio.CancelledError])

        channel._running = True
        await channel._dispatch_outbound()  # CancelledError handled internally

        result = await q.get()
        assert result.content == "response"

    async def test_ignores_other_channels(self, channel: WebChannel, bus: MagicMock):
        q = channel.register_stream("chat-1")
        other_msg = OutboundMessage(
            channel="telegram", chat_id="chat-1", content="wrong", metadata={}
        )
        bus.consume_outbound = AsyncMock(side_effect=[other_msg, asyncio.CancelledError])

        channel._running = True
        await channel._dispatch_outbound()  # CancelledError handled internally

        assert q.empty()


# ---------------------------------------------------------------------------
# Streaming protocol tests
# ---------------------------------------------------------------------------


async def _feed_queue(channel: WebChannel, chat_id: str, msgs: list, delay: float = 0.05):
    """Helper: wait briefly then feed messages into the channel's stream queue."""
    await asyncio.sleep(delay)
    q = channel._streams.get(chat_id)
    if q:
        for m in msgs:
            await q.put(m)


class TestStreamingProtocol:
    async def test_final_response_emitted(self, channel: WebChannel, bus: MagicMock):
        from nanobot.web.streaming import stream_agent_response

        final = OutboundMessage(
            channel="web",
            chat_id="s1",
            content="Hello world",
            metadata={},
        )

        with patch.object(channel, "publish_user_message", new_callable=AsyncMock):
            feeder = asyncio.create_task(_feed_queue(channel, "s1", [final]))
            events: list[str] = []
            async for ev in stream_agent_response(channel, "s1", "hi"):
                events.append(ev)
            await feeder

        assert any('"Hello world"' in e for e in events)
        assert any(e.startswith("d:") for e in events)

    async def test_streaming_delta(self, channel: WebChannel, bus: MagicMock):
        from nanobot.web.streaming import stream_agent_response

        msg1 = OutboundMessage(
            channel="web",
            chat_id="s2",
            content="Hello",
            metadata={"_streaming": True},
        )
        msg2 = OutboundMessage(
            channel="web",
            chat_id="s2",
            content="Hello world",
            metadata={"_streaming": True},
        )
        final = OutboundMessage(
            channel="web",
            chat_id="s2",
            content="Hello world!",
            metadata={},
        )

        with patch.object(channel, "publish_user_message", new_callable=AsyncMock):
            feeder = asyncio.create_task(_feed_queue(channel, "s2", [msg1, msg2, final]))
            events: list[str] = []
            async for ev in stream_agent_response(channel, "s2", "hi"):
                events.append(ev)
            await feeder

        text_events = [e for e in events if e.startswith("0:")]
        assert len(text_events) >= 3

    async def test_tool_hint_emits_tool_call(self, channel: WebChannel, bus: MagicMock):
        from nanobot.web.streaming import stream_agent_response

        tool_msg = OutboundMessage(
            channel="web",
            chat_id="s3",
            content="\U0001f527 Calling `web_search` with query",
            metadata={"_tool_hint": True},
        )
        final = OutboundMessage(channel="web", chat_id="s3", content="Done", metadata={})

        with patch.object(channel, "publish_user_message", new_callable=AsyncMock):
            feeder = asyncio.create_task(_feed_queue(channel, "s3", [tool_msg, final]))
            events: list[str] = []
            async for ev in stream_agent_response(channel, "s3", "hi"):
                events.append(ev)
            await feeder

        assert any(e.startswith("9:") for e in events)
        assert any(e.startswith("a:") for e in events)
        assert any(e.startswith("d:") for e in events)

    async def test_progress_text_emitted(self, channel: WebChannel, bus: MagicMock):
        from nanobot.web.streaming import stream_agent_response

        progress = OutboundMessage(
            channel="web",
            chat_id="s4",
            content="Thinking...",
            metadata={"_progress": True},
        )
        final = OutboundMessage(channel="web", chat_id="s4", content="Done", metadata={})

        with patch.object(channel, "publish_user_message", new_callable=AsyncMock):
            feeder = asyncio.create_task(_feed_queue(channel, "s4", [progress, final]))
            events: list[str] = []
            async for ev in stream_agent_response(channel, "s4", "hi"):
                events.append(ev)
            await feeder

        assert any("Thinking..." in e for e in events)

    async def test_timeout_emits_timeout_message(self, channel: WebChannel, bus: MagicMock):
        from nanobot.web.streaming import stream_agent_response

        with patch.object(channel, "publish_user_message", new_callable=AsyncMock):
            with patch("nanobot.web.streaming.asyncio.wait_for") as mock_wait:
                mock_wait.side_effect = asyncio.TimeoutError
                events: list[str] = []
                async for ev in stream_agent_response(channel, "s5", "hi"):
                    events.append(ev)

        assert any("timeout" in e for e in events)

    async def test_none_sentinel_ends_stream(self, channel: WebChannel, bus: MagicMock):
        from nanobot.web.streaming import stream_agent_response

        with patch.object(channel, "publish_user_message", new_callable=AsyncMock):
            feeder = asyncio.create_task(_feed_queue(channel, "s6", [None]))
            events: list[str] = []
            async for ev in stream_agent_response(channel, "s6", "hi"):
                events.append(ev)
            await feeder

        assert any(e.startswith("d:") for e in events)

    async def test_unregister_on_completion(self, channel: WebChannel, bus: MagicMock):
        from nanobot.web.streaming import stream_agent_response

        final = OutboundMessage(channel="web", chat_id="s7", content="ok", metadata={})

        with patch.object(channel, "publish_user_message", new_callable=AsyncMock):
            feeder = asyncio.create_task(_feed_queue(channel, "s7", [final]))
            async for _ in stream_agent_response(channel, "s7", "hi"):
                pass
            await feeder

        assert "s7" not in channel._streams
