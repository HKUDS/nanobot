"""Discover channel descriptors and load their runtimes lazily."""

from __future__ import annotations

import pkgutil
from typing import TYPE_CHECKING

from loguru import logger

from nanobot.channels.plugin import (
    ChannelPlugin,
    has_builtin_channel_package,
    load_builtin_channel_plugin,
)

if TYPE_CHECKING:
    from nanobot.channels.base import BaseChannel


def _builtin_package_names() -> list[str]:
    import nanobot.channels as package

    return [
        name
        for _, name, is_package in pkgutil.iter_modules(package.__path__)
        if is_package and has_builtin_channel_package(name)
    ]


def discover_builtin_plugins(
    enabled_names: set[str] | None = None,
    *,
    _names: list[str] | None = None,
) -> dict[str, ChannelPlugin]:
    """Load dependency-free descriptors from built-in channel packages."""
    plugins: dict[str, ChannelPlugin] = {}
    for name in _names if _names is not None else _builtin_package_names():
        if enabled_names is not None and name not in enabled_names:
            continue
        try:
            plugin = load_builtin_channel_plugin(name)
            if plugin is not None:
                plugins[name] = plugin
        except Exception as exc:
            logger.warning("Failed to load built-in channel descriptor '{}': {}", name, exc)
    return plugins


def discover_entrypoint_plugins(
    enabled_names: set[str] | None = None,
    *,
    _reserved_names: set[str] | None = None,
) -> dict[str, ChannelPlugin]:
    """Load external ``ChannelPlugin`` descriptors registered via entry points."""
    from importlib.metadata import entry_points

    reserved_names = _reserved_names or set()
    plugins: dict[str, ChannelPlugin] = {}
    for entry_point in entry_points(group="nanobot.channels"):
        if enabled_names is not None and entry_point.name not in enabled_names:
            continue
        if entry_point.name in reserved_names:
            logger.warning(
                "External channel descriptor '{}' is shadowed by a built-in channel",
                entry_point.name,
            )
            continue
        try:
            plugin = entry_point.load()
            if not isinstance(plugin, ChannelPlugin):
                raise TypeError(
                    "entry point must resolve to nanobot.channels.plugin.ChannelPlugin"
                )
            if plugin.name != entry_point.name:
                raise TypeError(
                    f"descriptor name '{plugin.name}' does not match entry point "
                    f"name '{entry_point.name}'"
                )
            plugins[entry_point.name] = plugin
        except Exception as exc:
            logger.warning(
                "Failed to load channel descriptor '{}': {}",
                entry_point.name,
                exc,
            )
    return plugins


def discover_plugins(enabled_names: set[str] | None = None) -> dict[str, ChannelPlugin]:
    """Return built-in and entry-point descriptors through one contract."""
    names = _builtin_package_names()
    builtin_names = set(names)
    plugins = discover_builtin_plugins(enabled_names, _names=names)
    plugins.update(
        discover_entrypoint_plugins(
            enabled_names,
            _reserved_names=builtin_names,
        )
    )
    return plugins


def load_channel_plugin(name: str) -> ChannelPlugin:
    """Load one built-in or entry-point descriptor."""
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
    "discover_builtin_plugins",
    "discover_enabled",
    "discover_entrypoint_plugins",
    "discover_plugins",
    "load_channel_class",
    "load_channel_plugin",
]
