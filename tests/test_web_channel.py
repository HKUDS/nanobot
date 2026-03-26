"""Tests for nanobot.channels.web and nanobot.web.streaming."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.channels.web import WebChannel

# ---------------------------------------------------------------------------
# SSE helpers (ui-message-stream protocol)
# ---------------------------------------------------------------------------


def _parse_sse_events(chunks: list[str]) -> list[dict]:
    """Extract all JSON payloads from SSE chunks (event: message / data: ...).

    Also handles the ``data: [DONE]`` terminator — that entry is skipped.
    """
    events: list[dict] = []
    for chunk in chunks:
        for line in chunk.splitlines():
            if line.startswith("data:"):
                raw = line[len("data:") :].strip()
                if raw == "[DONE]":
                    continue
                try:
                    events.append(json.loads(raw))
                except json.JSONDecodeError:
                    pass  # skip malformed SSE lines in test helper
    return events


def _events_of_type(chunks: list[str], event_type: str) -> list[dict]:
    return [e for e in _parse_sse_events(chunks) if e.get("type") == event_type]


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
            _ = await feeder

        assert any('"Hello world"' in e for e in events)
        assert any(_events_of_type(events, "finish"))

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
            _ = await feeder

        text_events = _events_of_type(events, "text-delta")
        assert len(text_events) == 3
        assert text_events[0]["textDelta"] == "Hello"
        assert text_events[1]["textDelta"] == " world"
        assert text_events[2]["textDelta"] == "!"

    async def test_tool_call_emits_real_events(self, channel: WebChannel, bus: MagicMock):
        from nanobot.web.streaming import stream_agent_response

        tool_call_msg = OutboundMessage(
            channel="web",
            chat_id="s3",
            content="",
            metadata={
                "_progress": True,
                "_tool_call": {
                    "toolCallId": "call_abc123",
                    "toolName": "web_search",
                    "args": {"query": "test query"},
                },
            },
        )
        tool_result_msg = OutboundMessage(
            channel="web",
            chat_id="s3",
            content="",
            metadata={
                "_progress": True,
                "_tool_result": {
                    "toolCallId": "call_abc123",
                    "result": '{"text": "search results"}',
                },
            },
        )
        final = OutboundMessage(channel="web", chat_id="s3", content="Done", metadata={})

        with patch.object(channel, "publish_user_message", new_callable=AsyncMock):
            feeder = asyncio.create_task(
                _feed_queue(channel, "s3", [tool_call_msg, tool_result_msg, final])
            )
            events: list[str] = []
            async for ev in stream_agent_response(channel, "s3", "hi"):
                events.append(ev)
            _ = await feeder

        tool_call_events = _events_of_type(events, "tool-call-start")
        tool_result_events = _events_of_type(events, "tool-result")
        assert len(tool_call_events) == 1
        assert len(tool_result_events) == 1
        # Verify real args and result are forwarded
        tc = tool_call_events[0]
        assert tc["toolCallId"] == "call_abc123"
        assert tc["toolName"] == "web_search"
        tr = tool_result_events[0]
        assert tr["toolCallId"] == "call_abc123"
        # result is the raw string value passed in _tool_result metadata
        assert '{"text": "search results"}' in tr["result"]

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
            _ = await feeder

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
            _ = await feeder

        assert any(_events_of_type(events, "finish"))

    async def test_unregister_on_completion(self, channel: WebChannel, bus: MagicMock):
        from nanobot.web.streaming import stream_agent_response

        final = OutboundMessage(channel="web", chat_id="s7", content="ok", metadata={})

        with patch.object(channel, "publish_user_message", new_callable=AsyncMock):
            feeder = asyncio.create_task(_feed_queue(channel, "s7", [final]))
            async for _ in stream_agent_response(channel, "s7", "hi"):
                pass
            _ = await feeder

        assert "s7" not in channel._streams

    async def test_revised_answer_no_garble(self, channel: WebChannel, bus: MagicMock):
        """When the verifier rewrites the answer, the final message text diverges
        from the already-streamed content.  The streamer must NOT compute a delta
        against the wrong text, which would produce garbled output."""
        from nanobot.web.streaming import stream_agent_response

        # Simulate streaming the original answer
        stream1 = OutboundMessage(
            channel="web",
            chat_id="s8",
            content="Original answer part 1",
            metadata={"_streaming": True},
        )
        stream2 = OutboundMessage(
            channel="web",
            chat_id="s8",
            content="Original answer part 1 and part 2",
            metadata={"_streaming": True},
        )
        # Verifier rewrites the answer — completely different text
        revised_final = OutboundMessage(
            channel="web",
            chat_id="s8",
            content="Completely revised answer from verifier",
            metadata={},
        )

        with patch.object(channel, "publish_user_message", new_callable=AsyncMock):
            feeder = asyncio.create_task(
                _feed_queue(channel, "s8", [stream1, stream2, revised_final])
            )
            events: list[str] = []
            async for ev in stream_agent_response(channel, "s8", "hi"):
                events.append(ev)
            _ = await feeder

        text_events = _events_of_type(events, "text-delta")
        # Only the two streaming deltas — no garbled final delta
        assert len(text_events) == 2
        assert text_events[0]["textDelta"] == "Original answer part 1"
        assert text_events[1]["textDelta"] == " and part 2"

    async def test_progress_dedup_after_streaming(self, channel: WebChannel, bus: MagicMock):
        """After streaming, the agent loop re-sends accumulated text as a
        non-streaming progress message before a tool call.  This must not
        produce duplicate output."""
        from nanobot.web.streaming import stream_agent_response

        stream1 = OutboundMessage(
            channel="web",
            chat_id="s9",
            content="Looking at",
            metadata={"_streaming": True, "_progress": True},
        )
        stream2 = OutboundMessage(
            channel="web",
            chat_id="s9",
            content="Looking at the data",
            metadata={"_streaming": True, "_progress": True},
        )
        # Agent loop flushes the same text before tool call (non-streaming)
        flush = OutboundMessage(
            channel="web",
            chat_id="s9",
            content="Looking at the data",
            metadata={"_progress": True},
        )
        # Tool call event follows the flush
        tool_call_ev = OutboundMessage(
            channel="web",
            chat_id="s9",
            content="",
            metadata={
                "_progress": True,
                "_tool_call": {
                    "toolCallId": "call_q1",
                    "toolName": "query_data",
                    "args": {"sql": "SELECT 42"},
                },
            },
        )
        # Tool result event
        tool_result_ev = OutboundMessage(
            channel="web",
            chat_id="s9",
            content="",
            metadata={
                "_progress": True,
                "_tool_result": {
                    "toolCallId": "call_q1",
                    "result": "42",
                },
            },
        )
        # Final answer (from a subsequent LLM call)
        final = OutboundMessage(
            channel="web",
            chat_id="s9",
            content="The answer is 42",
            metadata={},
        )

        with patch.object(channel, "publish_user_message", new_callable=AsyncMock):
            feeder = asyncio.create_task(
                _feed_queue(
                    channel, "s9", [stream1, stream2, flush, tool_call_ev, tool_result_ev, final]
                )
            )
            events: list[str] = []
            async for ev in stream_agent_response(channel, "s9", "hi"):
                events.append(ev)
            _ = await feeder

        text_events = _events_of_type(events, "text-delta")
        # Two streaming deltas + final answer — no duplicate from flush
        assert len(text_events) == 3
        assert text_events[0]["textDelta"] == "Looking at"
        assert text_events[1]["textDelta"] == " the data"
        assert text_events[2]["textDelta"] == "The answer is 42"

    async def test_multi_llm_call_streaming_reset(self, channel: WebChannel, bus: MagicMock):
        """When a tool call fails and the agent loop starts a new LLM call,
        the new streaming sequence starts from 0.  The tracker must reset
        instead of computing garbled deltas against the old cumulative text."""
        from nanobot.web.streaming import stream_agent_response

        # First LLM call streams text
        s1a = OutboundMessage(
            channel="web",
            chat_id="s10",
            content="Checking the data",
            metadata={"_streaming": True, "_progress": True},
        )
        # Tool call event (tool executes and fails)
        tc1 = OutboundMessage(
            channel="web",
            chat_id="s10",
            content="",
            metadata={
                "_progress": True,
                "_tool_call": {
                    "toolCallId": "call_t1",
                    "toolName": "query_data",
                    "args": {"sql": "SELECT *"},
                },
            },
        )
        tr1 = OutboundMessage(
            channel="web",
            chat_id="s10",
            content="",
            metadata={
                "_progress": True,
                "_tool_result": {
                    "toolCallId": "call_t1",
                    "result": "Error: table not found",
                },
            },
        )
        # Second LLM call — new streaming from 0
        s2a = OutboundMessage(
            channel="web",
            chat_id="s10",
            content="Let me try",
            metadata={"_streaming": True, "_progress": True},
        )
        s2b = OutboundMessage(
            channel="web",
            chat_id="s10",
            content="Let me try a different approach",
            metadata={"_streaming": True, "_progress": True},
        )
        final = OutboundMessage(
            channel="web",
            chat_id="s10",
            content="Let me try a different approach",
            metadata={},
        )

        with patch.object(channel, "publish_user_message", new_callable=AsyncMock):
            feeder = asyncio.create_task(
                _feed_queue(channel, "s10", [s1a, tc1, tr1, s2a, s2b, final])
            )
            events: list[str] = []
            async for ev in stream_agent_response(channel, "s10", "hi"):
                events.append(ev)
            _ = await feeder

        text_events = _events_of_type(events, "text-delta")
        # First LLM call text + second LLM call text (no garbling)
        assert text_events[0]["textDelta"] == "Checking the data"
        assert text_events[1]["textDelta"] == "Let me try"
        assert text_events[2]["textDelta"] == " a different approach"
        assert len(text_events) == 3

    async def test_verifier_revision_after_final_flush(self, channel: WebChannel, bus: MagicMock):
        """The LLM streaming layer now sends a final flush with the complete
        original text.  When the verifier subsequently revises the answer,
        the revised text diverges from the already-streamed content.
        The streamer must NOT emit the divergent revision — the user already
        has the complete original via the streaming flush."""
        from nanobot.web.streaming import stream_agent_response

        # Partial streaming chunks
        stream1 = OutboundMessage(
            channel="web",
            chat_id="s11",
            content="The total cost is 0.04.",
            metadata={"_streaming": True},
        )
        stream2 = OutboundMessage(
            channel="web",
            chat_id="s11",
            content="The total cost is 0.04. The currency is USD.",
            metadata={"_streaming": True},
        )
        # Final streaming flush — complete original text
        stream_flush = OutboundMessage(
            channel="web",
            chat_id="s11",
            content="The total cost is 0.04. The currency is USD. Let me know if you need more!",
            metadata={"_streaming": True},
        )
        # Verifier revises — different wording, diverges from original
        revised_final = OutboundMessage(
            channel="web",
            chat_id="s11",
            content="The total cost calculated from the data is 0.04 USD. Feel free to ask more!",
            metadata={},
        )

        with patch.object(channel, "publish_user_message", new_callable=AsyncMock):
            feeder = asyncio.create_task(
                _feed_queue(channel, "s11", [stream1, stream2, stream_flush, revised_final])
            )
            events: list[str] = []
            async for ev in stream_agent_response(channel, "s11", "hi"):
                events.append(ev)
            _ = await feeder

        text_events = _events_of_type(events, "text-delta")
        # Three streaming deltas — complete original text shown.
        # Revised final is dropped (diverges from what user already saw).
        assert len(text_events) == 3
        assert text_events[0]["textDelta"] == "The total cost is 0.04."
        assert text_events[1]["textDelta"] == " The currency is USD."
        assert text_events[2]["textDelta"] == " Let me know if you need more!"
