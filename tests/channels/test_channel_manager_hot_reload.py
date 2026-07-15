from __future__ import annotations

import asyncio

import pytest

from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.channels.contracts import ChannelInstanceSpec, ChannelSetupSpec
from nanobot.channels.manager import ChannelManager
from nanobot.channels.plugin import ChannelPlugin
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


class _MultiHotChannel(_HotChannel):
    name = "multi"
    display_name = "Multi"

    @classmethod
    def runtime_name(cls, instance_id: str = "default") -> str:
        return cls.name if instance_id == "default" else f"{cls.name}.{instance_id}"

    @classmethod
    def instance_specs(cls, section, *, enabled_only=True):
        instances = section.get("instances", []) if isinstance(section, dict) else []
        return [
            ChannelInstanceSpec(
                instance_id=item["id"],
                config=item,
            )
            for item in instances
            if not enabled_only or item.get("enabled", False)
        ]


class _AliasHotChannel(_HotChannel):
    """Plugin entry-point alias that claims another channel's runtime namespace."""

    name = "hot"
    display_name = "Alias"


def _plugin(channel_cls: type[BaseChannel]) -> ChannelPlugin:
    runtime_attr = f"_runtime_{channel_cls.display_name.lower()}"
    globals()[runtime_attr] = channel_cls
    setup = (
        ChannelSetupSpec(fields={}, multi_instance=True)
        if channel_cls.supports_multiple_instances()
        else None
    )
    return ChannelPlugin(
        name=channel_cls.name,
        display_name=channel_cls.display_name,
        runtime=f"{__name__}:{runtime_attr}",
        setup=setup,
    )


def _stub_registry(monkeypatch, *plugins: ChannelPlugin) -> None:
    by_name = {plugin.name: plugin for plugin in plugins}
    monkeypatch.setattr(
        "nanobot.channels.registry.discover_plugins",
        lambda enabled_names=None: {
            name: plugin
            for name, plugin in by_name.items()
            if enabled_names is None or name in enabled_names
        },
    )


def test_descriptor_rejects_runtime_class_owned_by_another_name():
    plugin = ChannelPlugin(
        name="alias",
        display_name="Alias",
        runtime=f"{__name__}:_AliasHotChannel",
    )

    with pytest.raises(ImportError, match="runtime declares name 'hot'"):
        plugin.load_channel_class()


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

    configs = iter([enabled, disabled])
    _stub_registry(monkeypatch, _plugin(_HotChannel))
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


@pytest.mark.asyncio
async def test_apply_channel_feature_action_keeps_running_channel_when_rebuild_fails(monkeypatch):
    enabled = Config.model_validate({
        "channels": {
            "websocket": {"enabled": False},
            "hot": {"enabled": True},
        }
    })

    _stub_registry(monkeypatch, _plugin(_HotChannel))
    monkeypatch.setattr("nanobot.config.loader.load_config", lambda: enabled)

    manager = ChannelManager(enabled, MessageBus())
    old_channel = manager.channels["hot"]
    old_channel._running = True

    def fail_build(*_args, **_kwargs):
        raise RuntimeError("invalid replacement config")

    monkeypatch.setattr(manager, "_build_channel", fail_build)

    result = await manager.apply_channel_feature_action("enable", "hot")

    assert result["requires_restart"] is True
    assert manager.channels["hot"] is old_channel
    assert old_channel.is_running is True
    assert not old_channel.stopped.is_set()


@pytest.mark.asyncio
async def test_apply_channel_feature_action_uses_channel_runtime_name(monkeypatch):
    config = Config.model_validate({
        "channels": {
            "websocket": {"enabled": False},
            "multi": {
                "enabled": True,
                "instances": [
                    {"id": "default", "enabled": True},
                    {"id": "product", "enabled": True},
                ]
            },
        }
    })

    _stub_registry(monkeypatch, _plugin(_MultiHotChannel))
    monkeypatch.setattr("nanobot.config.loader.load_config", lambda: config)

    manager = ChannelManager(config, MessageBus())
    product = manager.channels["multi.product"]
    product._running = True

    result = await manager.apply_channel_feature_action("disable", "multi", "product")

    assert result["requires_restart"] is False
    assert "multi" in manager.channels
    assert "multi.product" not in manager.channels
    assert product.is_running is False


@pytest.mark.asyncio
async def test_default_multi_channel_action_reconciles_only_default_runtime(monkeypatch):
    initial = Config.model_validate({
        "channels": {
            "websocket": {"enabled": False},
            "multi": {
                "enabled": True,
                "instances": [
                    {"id": "default", "enabled": True},
                    {"id": "product", "enabled": True},
                ],
            },
        }
    })
    disabled = Config.model_validate({
        "channels": {
            "websocket": {"enabled": False},
            "multi": {
                "enabled": True,
                "instances": [
                    {"id": "default", "enabled": False},
                    {"id": "product", "enabled": True},
                ],
            },
        }
    })
    enabled = Config.model_validate({
        "channels": {
            "websocket": {"enabled": False},
            "multi": {
                "enabled": True,
                "instances": [
                    {"id": "default", "enabled": True},
                    {"id": "product", "enabled": True},
                ],
            },
        }
    })

    _stub_registry(monkeypatch, _plugin(_MultiHotChannel))
    configs = iter([disabled, enabled])
    monkeypatch.setattr("nanobot.config.loader.load_config", lambda: next(configs))

    manager = ChannelManager(initial, MessageBus())
    default = manager.channels["multi"]
    product = manager.channels["multi.product"]

    disabled_result = await manager.apply_channel_feature_action("disable", "multi")

    assert disabled_result["requires_restart"] is False
    assert set(manager.channels) == {"multi.product"}
    assert default.stopped.is_set()
    assert not product.stopped.is_set()

    enabled_result = await manager.apply_channel_feature_action("enable", "multi")

    assert enabled_result["requires_restart"] is False
    assert set(manager.channels) == {"multi", "multi.product"}
    assert manager.channels["multi.product"] is product
