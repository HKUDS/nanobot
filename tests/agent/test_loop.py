"""Tests for AgentLoop._dispatch streaming metadata passthrough."""

from unittest.mock import AsyncMock, patch

import pytest

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus


def _make_inbound(**meta) -> InboundMessage:
    meta.setdefault("_wants_stream", True)
    return InboundMessage(
        channel="telegram",
        sender_id="user1",
        chat_id="chat1",
        content="hello",
        metadata=meta,
    )


@pytest.mark.asyncio
async def test_on_stream_forwards_message_metadata() -> None:
    """on_stream should include original message metadata (e.g. message_thread_id)."""
    from nanobot.agent.loop import AgentLoop

    bus = MessageBus()
    msg = _make_inbound(message_thread_id="42")

    loop = AgentLoop.__new__(AgentLoop)
    loop.bus = bus
    loop._session_locks = {}
    loop._concurrency_gate = None

    async def fake_process_message(msg_in, **kwargs):
        on_stream = kwargs.get("on_stream")
        on_stream_end = kwargs.get("on_stream_end")
        if on_stream:
            await on_stream("hello")
        if on_stream_end:
            await on_stream_end()
        return OutboundMessage(
            channel=msg_in.channel, chat_id=msg_in.chat_id,
            content="done", metadata=msg_in.metadata,
        )

    with patch.object(loop, "_process_message", side_effect=fake_process_message):
        await loop._dispatch(msg)

    # Collect all outbound messages (stream delta, stream end, final response)
    outbound: list[OutboundMessage] = []
    while not bus.outbound.empty():
        outbound.append(await bus.outbound.get())

    stream_msg = next(m for m in outbound if m.metadata.get("_stream_delta"))
    assert stream_msg.metadata["message_thread_id"] == "42"
    assert stream_msg.metadata["_stream_delta"] is True
    assert "_stream_id" in stream_msg.metadata


@pytest.mark.asyncio
async def test_on_stream_end_forwards_message_metadata() -> None:
    """on_stream_end should include original message metadata."""
    from nanobot.agent.loop import AgentLoop

    bus = MessageBus()
    msg = _make_inbound(message_thread_id="42")

    loop = AgentLoop.__new__(AgentLoop)
    loop.bus = bus
    loop._session_locks = {}
    loop._concurrency_gate = None

    async def fake_process_message(msg_in, **kwargs):
        on_stream = kwargs.get("on_stream")
        on_stream_end = kwargs.get("on_stream_end")
        if on_stream:
            await on_stream("hello")
        if on_stream_end:
            await on_stream_end()
        return OutboundMessage(
            channel=msg_in.channel, chat_id=msg_in.chat_id,
            content="done", metadata=msg_in.metadata,
        )

    with patch.object(loop, "_process_message", side_effect=fake_process_message):
        await loop._dispatch(msg)

    outbound: list[OutboundMessage] = []
    while not bus.outbound.empty():
        outbound.append(await bus.outbound.get())

    end_msg = next(m for m in outbound if m.metadata.get("_stream_end"))
    assert end_msg.metadata["message_thread_id"] == "42"
    assert end_msg.metadata["_stream_end"] is True
    assert end_msg.metadata["_resuming"] is False
    assert "_stream_id" in end_msg.metadata


@pytest.mark.asyncio
async def test_streaming_preserves_arbitrary_metadata_keys() -> None:
    """Both streaming callbacks should forward all original metadata keys untouched."""
    from nanobot.agent.loop import AgentLoop

    bus = MessageBus()
    msg = _make_inbound(message_thread_id="99", custom_flag="abc", reply_to_id="msg77")

    loop = AgentLoop.__new__(AgentLoop)
    loop.bus = bus
    loop._session_locks = {}
    loop._concurrency_gate = None

    async def fake_process_message(msg_in, **kwargs):
        on_stream = kwargs.get("on_stream")
        on_stream_end = kwargs.get("on_stream_end")
        if on_stream:
            await on_stream("hi")
        if on_stream_end:
            await on_stream_end()
        return OutboundMessage(
            channel=msg_in.channel, chat_id=msg_in.chat_id,
            content="done", metadata=msg_in.metadata,
        )

    with patch.object(loop, "_process_message", side_effect=fake_process_message):
        await loop._dispatch(msg)

    outbound: list[OutboundMessage] = []
    while not bus.outbound.empty():
        outbound.append(await bus.outbound.get())

    stream_msg = next(m for m in outbound if m.metadata.get("_stream_delta"))
    for key in ("message_thread_id", "custom_flag", "reply_to_id"):
        assert stream_msg.metadata[key] == msg.metadata[key]

    end_msg = next(m for m in outbound if m.metadata.get("_stream_end"))
    for key in ("message_thread_id", "custom_flag", "reply_to_id"):
        assert end_msg.metadata[key] == msg.metadata[key]
