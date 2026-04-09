"""Tests for inbound queue deduplication."""

import asyncio

import pytest

from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus


def _msg(content: str, channel: str = "telegram", chat: str = "c1", **meta) -> InboundMessage:
    return InboundMessage(
        channel=channel,
        sender_id="u1",
        chat_id=chat,
        content=content,
        metadata=dict(meta),
    )


@pytest.mark.asyncio
async def test_duplicate_dropped_while_first_is_queued():
    bus = MessageBus(inbound_queue_dedup=True)
    m1 = _msg("What is 2+2?")
    m2 = _msg("What   is  2+2?")  # same after normalize

    await bus.publish_inbound(m1)
    await bus.publish_inbound(m2)

    assert bus.inbound_size == 1
    got = await asyncio.wait_for(bus.consume_inbound(), timeout=1.0)
    assert got.content == m1.content
    assert bus.inbound_size == 0
    bus.release_inbound_dedup(got)


@pytest.mark.asyncio
async def test_triple_spam_only_one_queued_until_release():
    """Same as rapid re-send while agent still processing: duplicates drop after first is taken."""
    bus = MessageBus(inbound_queue_dedup=True)
    m = _msg("hello")
    await bus.publish_inbound(m)
    await bus.publish_inbound(_msg("hello"))
    await bus.publish_inbound(_msg("HELLO"))
    assert bus.inbound_size == 1
    got = await bus.consume_inbound()
    assert got.content == "hello"
    # Slot still held until release (simulates in-flight _dispatch)
    await bus.publish_inbound(_msg("hello"))
    assert bus.inbound_size == 0
    bus.release_inbound_dedup(got)
    await bus.publish_inbound(_msg("hello"))
    assert bus.inbound_size == 1


@pytest.mark.asyncio
async def test_same_text_allowed_after_consume():
    bus = MessageBus(inbound_queue_dedup=True)
    m1 = _msg("ping")
    m2 = _msg("ping")

    await bus.publish_inbound(m1)
    first = await bus.consume_inbound()
    bus.release_inbound_dedup(first)
    await bus.publish_inbound(m2)

    assert bus.inbound_size == 1
    got = await asyncio.wait_for(bus.consume_inbound(), timeout=1.0)
    assert got.content == "ping"
    bus.release_inbound_dedup(got)


@pytest.mark.asyncio
async def test_slash_commands_not_deduped():
    bus = MessageBus(inbound_queue_dedup=True)
    await bus.publish_inbound(_msg("/stop"))
    await bus.publish_inbound(_msg("/stop"))
    assert bus.inbound_size == 2


@pytest.mark.asyncio
async def test_skip_metadata_bypasses_dedup():
    bus = MessageBus(inbound_queue_dedup=True)
    await bus.publish_inbound(_msg("x", _skip_inbound_dedup=True))
    await bus.publish_inbound(_msg("x", _skip_inbound_dedup=True))
    assert bus.inbound_size == 2


@pytest.mark.asyncio
async def test_dedup_disabled():
    bus = MessageBus(inbound_queue_dedup=False)
    await bus.publish_inbound(_msg("a"))
    await bus.publish_inbound(_msg("a"))
    assert bus.inbound_size == 2


@pytest.mark.asyncio
async def test_different_sessions_not_deduped():
    bus = MessageBus(inbound_queue_dedup=True)
    await bus.publish_inbound(_msg("hi", chat="room1"))
    await bus.publish_inbound(_msg("hi", chat="room2"))
    assert bus.inbound_size == 2
