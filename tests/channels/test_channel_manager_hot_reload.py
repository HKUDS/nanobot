from __future__ import annotations

import asyncio

import pytest

from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.channels.manager import ChannelManager
from nanobot.config.schema import Config


class _HotChannel(BaseChannel):
    name = "hot"
    display_name = "Hot"

    def __init__(self, config, bus):
        super().__init__(config, bus)
        self.started = asyncio.Event()
        self.stopped = asyncio.Event()

    async def start(self):
        self._running = True
        self.started.set()
        await self.stopped.wait()

    async def stop(self):
        self._running = False
        self.stopped.set()

    async def send(self, msg):  # pragma: no cover - not used by this test
        raise AssertionError("send should not be called")


@pytest.mark.asyncio
async def test_apply_channel_feature_action_starts_and_stops_channel(monkeypatch):
    disabled = Config.model_validate({
        "channels": {
            "websocket": {"enabled": False},
            "hot": {"enabled": False},
        }
    })
    enabled = Config.model_validate({
        "channels": {
            "websocket": {"enabled": False},
            "hot": {"enabled": True},
        }
    })

    import nanobot.channels.registry as registry

    def discover_enabled(enabled_names, **_kwargs):
        return {"hot": _HotChannel} if "hot" in enabled_names else {}

    configs = iter([enabled, disabled])
    monkeypatch.setattr(registry, "discover_channel_names", lambda: ["hot"])
    monkeypatch.setattr(registry, "discover_plugins", lambda enabled_names=None: {})
    monkeypatch.setattr(registry, "discover_enabled", discover_enabled)
    monkeypatch.setattr("nanobot.config.loader.load_config", lambda: next(configs))

    manager = ChannelManager(disabled, MessageBus())
    manager._started = True

    enabled_result = await manager.apply_channel_feature_action("enable", "hot")

    assert enabled_result["handled"] is True
    assert enabled_result["requires_restart"] is False
    channel = manager.channels["hot"]
    await asyncio.wait_for(channel.started.wait(), timeout=1)
    assert channel.is_running is True

    disabled_result = await manager.apply_channel_feature_action("disable", "hot")

    assert disabled_result["handled"] is True
    assert disabled_result["requires_restart"] is False
    assert "hot" not in manager.channels
    assert channel.is_running is False
