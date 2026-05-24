"""Tests for ChannelManager routing of model reasoning content.

Reasoning is delivered through plugin streaming primitives
(``send_reasoning_delta`` / ``send_reasoning_end``) so each channel
controls in-place rendering — mirroring the existing answer ``send_delta``
/ ``stream_end`` pair. The manager forwards reasoning frames only to
channels that opt in via ``channel.show_reasoning``; plugins without a
low-emphasis UI primitive keep the base no-op and the content silently
drops at dispatch.

One-shot ``_reasoning`` frames are accepted for back-compat with hooks
that haven't migrated yet — ``BaseChannel.send_reasoning`` expands them
to a single delta + end pair so plugins only implement the streaming
primitives.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.channels.manager import ChannelManager
from nanobot.config.schema import Config


class _MockChannel(BaseChannel):
    name = "mock"
    display_name = "Mock"

    def __init__(self, config, bus):
        super().__init__(config, bus)
        self._send_mock = AsyncMock()
        self._delta_mock = AsyncMock()
        self._end_mock = AsyncMock()

    async def start(self):  # pragma: no cover - not exercised
        pass

    async def stop(self):  # pragma: no cover - not exercised
        pass

    async def send(self, msg):
        return await self._send_mock(msg)

    async def send_reasoning_delta(self, chat_id, delta, metadata=None):
        return await self._delta_mock(chat_id, delta, metadata)

    async def send_reasoning_end(self, chat_id, metadata=None):
        return await self._end_mock(chat_id, metadata)


@pytest.fixture
def manager() -> ChannelManager:
    mgr = ChannelManager(Config(), MessageBus())
    mgr.channels["mock"] = _MockChannel({}, mgr.bus)
    return mgr


@pytest.mark.asyncio
async def test_reasoning_delta_routes_to_send_reasoning_delta(manager):
    channel = manager.channels["mock"]
    msg = OutboundMessage(
        channel="mock",
        chat_id="c1",
        content="step-by-step",
        metadata={"_progress": True, "_reasoning_delta": True, "_stream_id": "r1"},
    )
    await manager._send_once(channel, msg)
    channel._delta_mock.assert_awaited_once()
    args = channel._delta_mock.await_args.args
    assert args[0] == "c1"
    assert args[1] == "step-by-step"
    channel._send_mock.assert_not_awaited()
    channel._end_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_reasoning_end_routes_to_send_reasoning_end(manager):
    channel = manager.channels["mock"]
    msg = OutboundMessage(
        channel="mock",
        chat_id="c1",
        content="",
        metadata={"_progress": True, "_reasoning_end": True, "_stream_id": "r1"},
    )
    await manager._send_once(channel, msg)
    channel._end_mock.assert_awaited_once()
    channel._delta_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_legacy_one_shot_reasoning_expands_to_delta_plus_end(manager):
    """`_reasoning` (no delta/end pair) falls back through `send_reasoning`
    which the base class expands to a single delta + end. Hooks that haven't
    migrated still surface in WebUI as a complete stream segment."""
    channel = manager.channels["mock"]
    msg = OutboundMessage(
        channel="mock",
        chat_id="c1",
        content="one-shot reasoning",
        metadata={"_progress": True, "_reasoning": True},
    )
    await manager._send_once(channel, msg)
    channel._delta_mock.assert_awaited_once()
    channel._end_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_dispatch_drops_reasoning_when_channel_opts_out(manager):
    channel = manager.channels["mock"]
    channel.show_reasoning = False
    msg = OutboundMessage(
        channel="mock",
        chat_id="c1",
        content="hidden thinking",
        metadata={"_progress": True, "_reasoning_delta": True},
    )
    await manager.bus.publish_outbound(msg)

    await _pump_one(manager)

    channel._delta_mock.assert_not_awaited()
    channel._end_mock.assert_not_awaited()
    channel._send_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_delivers_reasoning_when_channel_opts_in(manager):
    channel = manager.channels["mock"]
    channel.show_reasoning = True
    for chunk in ("first ", "second"):
        await manager.bus.publish_outbound(OutboundMessage(
            channel="mock",
            chat_id="c1",
            content=chunk,
            metadata={"_progress": True, "_reasoning_delta": True, "_stream_id": "r1"},
        ))
    await manager.bus.publish_outbound(OutboundMessage(
        channel="mock",
        chat_id="c1",
        content="",
        metadata={"_progress": True, "_reasoning_end": True, "_stream_id": "r1"},
    ))

    await _pump_one(manager)

    assert channel._delta_mock.await_count == 2
    channel._end_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_dispatch_silently_drops_reasoning_for_unknown_channel(manager):
    msg = OutboundMessage(
        channel="ghost",
        chat_id="c1",
        content="nobody home",
        metadata={"_progress": True, "_reasoning_delta": True},
    )
    await manager.bus.publish_outbound(msg)

    await _pump_one(manager)

    manager.channels["mock"]._delta_mock.assert_not_awaited()
    manager.channels["mock"]._send_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_base_channel_reasoning_primitives_are_noop_safe():
    """Plugins that don't override the streaming primitives must not blow up."""

    class _Plain(BaseChannel):
        name = "plain"
        display_name = "Plain"

        async def start(self):  # pragma: no cover
            pass

        async def stop(self):  # pragma: no cover
            pass

        async def send(self, msg):  # pragma: no cover
            pass

    channel = _Plain({}, MessageBus())
    assert await channel.send_reasoning_delta("c", "x") is None
    assert await channel.send_reasoning_end("c") is None
    # And the one-shot wrapper translates without raising.
    assert await channel.send_reasoning(
        OutboundMessage(channel="plain", chat_id="c", content="x", metadata={})
    ) is None


@pytest.mark.asyncio
async def test_reasoning_routing_does_not_consult_send_progress(manager):
    """`show_reasoning` is orthogonal to `send_progress` — turning off
    progress streaming must not silence reasoning."""
    channel = manager.channels["mock"]
    channel.send_progress = False
    channel.show_reasoning = True
    await manager.bus.publish_outbound(OutboundMessage(
        channel="mock",
        chat_id="c1",
        content="still surfaces",
        metadata={"_progress": True, "_reasoning_delta": True},
    ))

    await _pump_one(manager)

    channel._delta_mock.assert_awaited_once()


async def _pump_one(manager: ChannelManager) -> None:
    """Drive the dispatcher until the outbound queue drains, then cancel."""
    task = asyncio.create_task(manager._dispatch_outbound())
    for _ in range(50):
        await asyncio.sleep(0.01)
        if manager.bus.outbound.qsize() == 0:
            break
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
