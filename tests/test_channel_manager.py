"""Tests for channel manager lifecycle supervision."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import cast

import pytest

from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.channels.dispatcher import OutboundDispatcher
from nanobot.channels.factory import BuiltinChannelFactory
from nanobot.channels.manager import ChannelManager
from nanobot.config.schema import Config


class _LifecycleChannel(BaseChannel):
    def __init__(self, bus: MessageBus):
        super().__init__(SimpleNamespace(allow_from=["*"]), bus)
        self.start_calls = 0
        self.stop_calls = 0

    async def start(self) -> None:
        self.start_calls += 1
        self._running = True

    async def stop(self) -> None:
        self.stop_calls += 1
        self._running = False

    async def send(self, msg) -> None:
        return None


class _RecordingFactory:
    def __init__(self, channels):
        self.channels = channels
        self.calls = []

    def build_enabled_channels(self, runtime_config, runtime_bus):
        self.calls.append((runtime_config, runtime_bus))
        return self.channels


class _RecordingDispatcher:
    def __init__(self, channels=None):
        self.started = asyncio.Event()
        self.cancelled = False
        self.channels = {} if channels is None else channels

    async def run(self) -> None:
        self.started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


@pytest.mark.asyncio
async def test_channel_manager_uses_injected_factory_and_dispatcher() -> None:
    bus = MessageBus()
    config = Config()
    channel = _LifecycleChannel(bus)
    factory = _RecordingFactory({"telegram": channel})
    dispatcher = _RecordingDispatcher()

    manager = ChannelManager(
        config,
        bus,
        channel_factory=cast(BuiltinChannelFactory, factory),
        dispatcher=cast(OutboundDispatcher, dispatcher),
    )

    await manager.start_all()
    await dispatcher.started.wait()

    assert factory.calls == [(config, bus)]
    assert manager.dispatcher is dispatcher
    assert manager.get_channel("telegram") is channel
    assert manager.get_status() == {"telegram": {"enabled": True, "running": True}}
    assert manager.enabled_channels == ["telegram"]

    await manager.stop_all()


def test_channel_manager_rebinds_injected_dispatcher_to_final_channel_map() -> None:
    bus = MessageBus()
    config = Config()
    channel = _LifecycleChannel(bus)
    dispatcher = _RecordingDispatcher(channels={})

    manager = ChannelManager(
        config,
        bus,
        channel_factory=cast(BuiltinChannelFactory, _RecordingFactory({"telegram": channel})),
        dispatcher=cast(OutboundDispatcher, dispatcher),
    )

    assert manager.dispatcher is dispatcher
    assert dispatcher.channels is manager.channels
    assert dispatcher.channels == {"telegram": channel}


@pytest.mark.asyncio
async def test_channel_manager_stop_all_stops_channels_and_cancels_dispatcher() -> None:
    bus = MessageBus()
    config = Config()
    channel = _LifecycleChannel(bus)
    dispatcher = _RecordingDispatcher()
    manager = ChannelManager(
        config,
        bus,
        channel_factory=cast(BuiltinChannelFactory, _RecordingFactory({"telegram": channel})),
        dispatcher=cast(OutboundDispatcher, dispatcher),
    )

    await manager.start_all()
    await dispatcher.started.wait()
    await manager.stop_all()

    assert channel.start_calls == 1
    assert channel.stop_calls == 1
    assert dispatcher.cancelled is True
    assert manager.get_status() == {"telegram": {"enabled": True, "running": False}}
