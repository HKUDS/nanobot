"""Discover channel descriptors and load their runtimes lazily."""

from __future__ import annotations

import pkgutil
from functools import cache
from importlib.metadata import entry_points
from typing import TYPE_CHECKING

from loguru import logger

from nanobot.channels.plugin import (
    ChannelPlugin,
    has_channel_package,
    load_channel_package,
)

if TYPE_CHECKING:
    from nanobot.channels.base import BaseChannel


@cache
def _warn_legacy_channel_entry_points() -> None:
    # TODO: Remove this legacy entry-point detection and warning after the migration window.
    names = sorted({entry_point.name for entry_point in entry_points(group="nanobot.channels")})
    if not names:
        return
    logger.warning(
        "Legacy channel entry points were detected but will not be loaded: {}. "
        "The '{}' entry-point group is no longer supported; use a built-in channel or "
        "migrate it into nanobot/channels/<channel>/.",
        ", ".join(names),
        "nanobot.channels",
    )


def _channel_package_names() -> list[str]:
    import nanobot.channels as package

    return [
        name
        for _, name, is_package in pkgutil.iter_modules(package.__path__)
        if is_package and has_channel_package(name)
    ]


def discover_plugins(
    enabled_names: set[str] | None = None,
) -> dict[str, ChannelPlugin]:
    """Load dependency-free descriptors from self-contained channel packages."""
    _warn_legacy_channel_entry_points()
    plugins: dict[str, ChannelPlugin] = {}
    for name in _channel_package_names():
        if enabled_names is not None and name not in enabled_names:
            continue
        try:
            plugin = load_channel_package(name)
            if plugin is not None:
                plugins[name] = plugin
        except Exception as exc:
            logger.warning("Failed to load channel package descriptor '{}': {}", name, exc)
    return plugins


def load_channel_plugin(name: str) -> ChannelPlugin:
    """Load one channel package descriptor."""
    plugin = discover_plugins({name}).get(name)
    if plugin is None:
        raise ImportError(f"Unknown channel: {name}")
    return plugin


def channel_default_enabled(name: str) -> bool:
    """Return the activation default declared by a channel descriptor."""
    try:
        return load_channel_plugin(name).default_enabled
    except ImportError:
        return False


def load_channel_class(name: str) -> type[BaseChannel]:
    """Load the runtime declared by one channel descriptor."""
    return load_channel_plugin(name).load_channel_class()


def discover_enabled(
    enabled_names: set[str],
    *,
    _plugins: dict[str, ChannelPlugin] | None = None,
    warn_import_errors: bool = False,
) -> dict[str, type[BaseChannel]]:
    """Load runtime classes only for enabled descriptors."""
    plugins = _plugins if _plugins is not None else discover_plugins(enabled_names)
    result: dict[str, type[BaseChannel]] = {}
    for name, plugin in plugins.items():
        if name not in enabled_names:
            continue
        try:
            result[name] = plugin.load_channel_class()
        except Exception as exc:
            message = "Enabled channel '{}' runtime is not available: {}"
            if warn_import_errors:
                logger.warning(message, name, exc)
            else:
                logger.debug(message, name, exc)
    return result


def discover_all() -> dict[str, type[BaseChannel]]:
    """Load every available channel runtime."""
    plugins = discover_plugins()
    return discover_enabled(set(plugins), _plugins=plugins)


__all__ = [
    "channel_default_enabled",
    "discover_all",
    "discover_enabled",
    "discover_plugins",
    "load_channel_class",
    "load_channel_plugin",
]
