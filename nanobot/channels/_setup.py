"""Resolve channel-owned setup contracts for settings consumers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nanobot.channels.contracts import ChannelSetupSpec

if TYPE_CHECKING:
    from nanobot.channels.plugin import ChannelPlugin


def channel_setup_spec(
    name: str,
    channel_cls: type[Any] | None = None,
    *,
    plugin: ChannelPlugin | None = None,
) -> ChannelSetupSpec | None:
    """Return the setup contract declared by one channel descriptor."""
    if plugin is None:
        from nanobot.channels.registry import load_channel_plugin

        plugin = load_channel_plugin(name)
    spec = plugin.setup
    if spec is not None:
        _validate_instance_mode(channel_cls, spec)
    return spec


def _validate_instance_mode(
    channel_cls: type[Any] | None,
    spec: ChannelSetupSpec,
) -> None:
    if channel_cls is None:
        return
    supports_multiple = bool(channel_cls.supports_multiple_instances())
    if spec.multi_instance != supports_multiple:
        raise TypeError(
            f"ChannelPlugin.setup.multi_instance for {channel_cls.__name__} must be "
            f"{supports_multiple} to match instance_specs()"
        )
