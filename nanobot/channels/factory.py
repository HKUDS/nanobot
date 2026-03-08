"""Factory for loading built-in channels from registry metadata."""

from __future__ import annotations

import importlib

from loguru import logger

from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.channels.builtins import BUILTIN_CHANNEL_REGISTRY
from nanobot.channels.registry import ChannelRegistry
from nanobot.config.schema import Config


class BuiltinChannelFactory:
    def __init__(self, registry: ChannelRegistry | None = None) -> None:
        self.registry = registry or BUILTIN_CHANNEL_REGISTRY

    def build_enabled_channels(
        self,
        config: Config,
        bus: MessageBus,
    ) -> dict[str, BaseChannel]:
        channels: dict[str, BaseChannel] = {}

        for spec in self.registry.all():
            channel_config = getattr(config.channels, spec.name)
            if not channel_config.enabled:
                continue

            try:
                module = importlib.import_module(spec.module_path)
                channel_cls = getattr(module, spec.class_name)
                channels[spec.name] = channel_cls(
                    channel_config,
                    bus,
                    **spec.extra_kwargs_factory(config),
                )
                logger.info("{} channel enabled", spec.display_name or spec.name.title())
            except (ImportError, AttributeError) as e:
                logger.warning(
                    "{} channel not available: {}",
                    spec.display_name or spec.name.title(),
                    e,
                )

        return channels
