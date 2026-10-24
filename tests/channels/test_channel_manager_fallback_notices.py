"""Fallback-model notices reach chat channels only when they opt in."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from nanobot.bus.outbound_events import (
    TurnModelUpdatedEvent,
    outbound_message_for_event,
)
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

    async def start(self):  # pragma: no cover - not exercised
        pass

    async def stop(self):  # pragma: no cover - not exercised
        pass

    async def send(self, msg):
        await self._send_mock(msg)


@pytest.fixture
def manager() -> ChannelManager:
    config = Config.model_validate({"channels": {"websocket": {"enabled": False}}})
    mgr = ChannelManager(config, MessageBus())
    mgr.channels["mock"] = _MockChannel({}, mgr.bus)
    return mgr


async def _dispatch_until(manager: ChannelManager, expected: int) -> None:
    task = asyncio.create_task(manager._dispatch_outbound())
    try:
        for _ in range(40):
            if manager.channels["mock"]._send_mock.await_count >= expected:
                break
            await asyncio.sleep(0.05)
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_fallback_notice_is_dropped_unless_channel_opts_in(
    manager: ChannelManager,
) -> None:
    await manager.bus.publish_outbound(outbound_message_for_event(
        channel="mock",
        chat_id="chat",
        event=TurnModelUpdatedEvent(model="backup", fallback=True),
        content="Primary model unavailable; using fallback model backup.",
    ))

    await _dispatch_until(manager, 0)

    manager.channels["mock"]._send_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_fallback_notice_is_delivered_when_channel_opts_in(
    manager: ChannelManager,
) -> None:
    channel = manager._build_channel("mock", _MockChannel, {"notifyModelFallback": True})
    manager.channels["mock"] = channel

    await manager.bus.publish_outbound(outbound_message_for_event(
        channel="mock",
        chat_id="chat",
        event=TurnModelUpdatedEvent(model="backup", fallback=True),
        content="Primary model unavailable; using fallback model backup.",
    ))

    await _dispatch_until(manager, 1)

    sent = channel._send_mock.await_args.args[0]
    assert sent.content == "Primary model unavailable; using fallback model backup."
    assert sent.event.fallback is True


@pytest.mark.asyncio
async def test_websocket_channel_renders_fallback_notices_without_opt_in(
    manager: ChannelManager,
) -> None:
    channel = _MockChannel({}, manager.bus)
    manager.channels["websocket"] = channel

    await manager.bus.publish_outbound(outbound_message_for_event(
        channel="websocket",
        chat_id="chat",
        event=TurnModelUpdatedEvent(model="backup", fallback=True),
    ))

    await _dispatch_until(manager, 1)

    channel._send_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_non_fallback_model_events_ignore_the_flag(
    manager: ChannelManager,
) -> None:
    await manager.bus.publish_outbound(outbound_message_for_event(
        channel="mock",
        chat_id="chat",
        event=TurnModelUpdatedEvent(model="primary", fallback=False),
    ))

    await _dispatch_until(manager, 1)

    manager.channels["mock"]._send_mock.assert_awaited_once()


@pytest.mark.parametrize("override", [None, False, True])
@pytest.mark.parametrize("key", ["notify_model_fallback", "notifyModelFallback"])
def test_fallback_flag_inherits_global_default_with_channel_override(
    manager: ChannelManager, key, override,
) -> None:
    section = {} if override is None else {key: override}
    channel = manager._build_channel("mock", _MockChannel, section)
    assert channel.notify_model_fallback is (override if override is not None else False)


def test_fallback_flag_config_round_trip(manager) -> None:
    assert Config().channels.notify_model_fallback is False
    manager.config = Config.model_validate({"channels": {"notifyModelFallback": True}})
    manager.config = Config.model_validate_json(manager.config.model_dump_json(by_alias=True))
    assert manager._build_channel("mock", _MockChannel, {}).notify_model_fallback is True
    # Rebuilding an adapter after a config change must resolve the new default.
    manager.config.channels.notify_model_fallback = False
    assert manager._build_channel("mock", _MockChannel, {}).notify_model_fallback is False
    assert manager._build_channel(
        "mock", _MockChannel, {"notifyModelFallback": True},
    ).notify_model_fallback is True
