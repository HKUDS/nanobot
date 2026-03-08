"""Tests for the async message bus queue behavior."""

from __future__ import annotations

import asyncio

import pytest

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus


@pytest.mark.asyncio
async def test_publish_and_consume_inbound_and_outbound_messages() -> None:
    """Publishes and consumes inbound and outbound messages through the queue."""
    bus = MessageBus()
    inbound = InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="ping")
    outbound = OutboundMessage(channel="telegram", chat_id="c1", content="pong")

    await bus.publish_inbound(inbound)
    await bus.publish_outbound(outbound)

    got_inbound = await bus.consume_inbound()
    got_outbound = await bus.consume_outbound()

    assert got_inbound == inbound
    assert got_outbound == outbound


@pytest.mark.asyncio
async def test_dispatch_outbound_sends_messages_to_channel_subscribers() -> None:
    """Dispatches outbound messages to subscribers registered for that channel."""
    bus = MessageBus()
    received: list[OutboundMessage] = []

    async def _subscriber(msg: OutboundMessage) -> None:
        received.append(msg)

    bus.subscribe_outbound("telegram", _subscriber)
    task = asyncio.create_task(bus.dispatch_outbound())

    msg = OutboundMessage(channel="telegram", chat_id="c1", content="hello")
    await bus.publish_outbound(msg)
    await asyncio.sleep(0.05)

    bus.stop()
    await asyncio.wait_for(task, timeout=2.0)

    assert received == [msg]


@pytest.mark.asyncio
async def test_dispatch_outbound_continues_when_a_subscriber_raises() -> None:
    """Continues dispatching to remaining subscribers when one callback fails."""
    bus = MessageBus()
    received: list[OutboundMessage] = []

    async def _broken_subscriber(_msg: OutboundMessage) -> None:
        raise RuntimeError("boom")

    async def _healthy_subscriber(msg: OutboundMessage) -> None:
        received.append(msg)

    bus.subscribe_outbound("telegram", _broken_subscriber)
    bus.subscribe_outbound("telegram", _healthy_subscriber)
    task = asyncio.create_task(bus.dispatch_outbound())

    msg = OutboundMessage(channel="telegram", chat_id="c1", content="resilient")
    await bus.publish_outbound(msg)
    await asyncio.sleep(0.05)

    bus.stop()
    await asyncio.wait_for(task, timeout=2.0)

    assert received == [msg]
