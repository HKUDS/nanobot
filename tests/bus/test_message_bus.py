"""Tests for the message bus and event types."""

import asyncio
from datetime import datetime

import pytest

from blackcat.bus.events import InboundMessage, OutboundMessage
from blackcat.bus.queue import MessageBus

# ── InboundMessage ─────────────────────────────────────────────────


def test_inbound_message_session_key():
    msg = InboundMessage(channel="telegram", sender_id="user1", chat_id="123", content="hi")
    assert msg.session_key == "telegram:123"


def test_inbound_message_defaults():
    msg = InboundMessage(channel="cli", sender_id="local", chat_id="0", content="hello")
    assert isinstance(msg.timestamp, datetime)
    assert msg.media == []
    assert msg.metadata == {}


# ── OutboundMessage ────────────────────────────────────────────────


def test_outbound_message_defaults():
    msg = OutboundMessage(channel="discord", chat_id="456", content="response")
    assert msg.reply_to is None
    assert msg.media == []
    assert msg.metadata == {}


def test_outbound_message_with_reply_to():
    msg = OutboundMessage(
        channel="telegram", chat_id="123", content="reply", reply_to="msg_42"
    )
    assert msg.reply_to == "msg_42"


# ── MessageBus ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bus_inbound_publish_consume():
    bus = MessageBus()
    msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="hi")
    await bus.publish_inbound(msg)
    assert bus.inbound_size == 1

    received = await bus.consume_inbound()
    assert received.content == "hi"
    assert bus.inbound_size == 0


@pytest.mark.asyncio
async def test_bus_outbound_publish_consume():
    bus = MessageBus()
    msg = OutboundMessage(channel="test", chat_id="c1", content="reply")
    await bus.publish_outbound(msg)
    assert bus.outbound_size == 1

    received = await bus.consume_outbound()
    assert received.content == "reply"
    assert bus.outbound_size == 0


@pytest.mark.asyncio
async def test_bus_fifo_order():
    bus = MessageBus()
    for i in range(3):
        await bus.publish_inbound(
            InboundMessage(channel="test", sender_id="u", chat_id="c", content=f"msg{i}")
        )

    for i in range(3):
        msg = await bus.consume_inbound()
        assert msg.content == f"msg{i}"


@pytest.mark.asyncio
async def test_bus_consume_blocks():
    """consume_inbound should block until a message is available."""
    bus = MessageBus()

    async def delayed_publish():
        await asyncio.sleep(0.05)
        await bus.publish_inbound(
            InboundMessage(channel="test", sender_id="u", chat_id="c", content="delayed")
        )

    asyncio.create_task(delayed_publish())
    msg = await asyncio.wait_for(bus.consume_inbound(), timeout=1.0)
    assert msg.content == "delayed"


@pytest.mark.asyncio
async def test_bus_size_properties():
    bus = MessageBus()
    assert bus.inbound_size == 0
    assert bus.outbound_size == 0

    await bus.publish_inbound(
        InboundMessage(channel="t", sender_id="u", chat_id="c", content="a")
    )
    await bus.publish_outbound(OutboundMessage(channel="t", chat_id="c", content="b"))

    assert bus.inbound_size == 1
    assert bus.outbound_size == 1
