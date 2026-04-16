"""Tests for bounded MessageBus inbound queue."""

import pytest

from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus


def _msg(content: str = "hi") -> InboundMessage:
    return InboundMessage(
        channel="test",
        sender_id="u1",
        chat_id="c1",
        content=content,
    )


@pytest.fixture()
def small_bus(monkeypatch):
    """A MessageBus with inbound maxsize=2 for fast overflow testing."""
    monkeypatch.setenv("NANOBOT_BUS_INBOUND_MAXSIZE", "2")
    return MessageBus()


async def test_publish_returns_true_when_space(small_bus):
    assert await small_bus.publish_inbound(_msg()) is True


async def test_publish_returns_false_when_full(small_bus):
    await small_bus.publish_inbound(_msg("a"))
    await small_bus.publish_inbound(_msg("b"))
    assert await small_bus.publish_inbound(_msg("c")) is False


async def test_queued_messages_preserved_on_overflow(small_bus):
    await small_bus.publish_inbound(_msg("a"))
    await small_bus.publish_inbound(_msg("b"))
    await small_bus.publish_inbound(_msg("c"))  # dropped
    assert small_bus.inbound_size == 2
    first = await small_bus.consume_inbound()
    assert first.content == "a"


async def test_space_after_consume(small_bus):
    await small_bus.publish_inbound(_msg("a"))
    await small_bus.publish_inbound(_msg("b"))
    assert await small_bus.publish_inbound(_msg("c")) is False
    await small_bus.consume_inbound()  # free a slot
    assert await small_bus.publish_inbound(_msg("d")) is True


async def test_outbound_stays_unbounded():
    from nanobot.bus.events import OutboundMessage

    bus = MessageBus()
    for i in range(200):
        await bus.publish_outbound(OutboundMessage(channel="t", chat_id="c", content=str(i)))
    assert bus.outbound_size == 200


async def test_default_maxsize(monkeypatch):
    monkeypatch.delenv("NANOBOT_BUS_INBOUND_MAXSIZE", raising=False)
    bus = MessageBus()
    assert bus.inbound.maxsize == 100
