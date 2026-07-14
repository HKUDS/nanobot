"""Dependency-free management manifests for built-in channels.

Runtime channel modules may import optional platform SDKs.  Their adjacent
manifest modules keep setup discovery cheap and safe for disabled channels.
"""

from __future__ import annotations

import importlib
from functools import lru_cache
from importlib.resources import files

from nanobot.channels.contracts import ChannelSetupSpec
from nanobot.channels.plugin import ChannelPlugin


def has_builtin_channel_package(name: str) -> bool:
    """Return whether *name* owns a package-local dependency-free manifest."""
    if not name.isidentifier() or name.startswith("_"):
        return False
    return files("nanobot.channels").joinpath(name, "manifest.py").is_file()


@lru_cache(maxsize=None)
def load_builtin_channel_plugin(name: str) -> ChannelPlugin | None:
    """Load ``nanobot.channels.<name>.manifest.PLUGIN`` without its runtime."""
    if not has_builtin_channel_package(name):
        return None

    module_name = f"nanobot.channels.{name}.manifest"
    module = importlib.import_module(module_name)
    plugin = getattr(module, "PLUGIN", None)
    if not isinstance(plugin, ChannelPlugin):
        raise TypeError(f"{module_name}.PLUGIN must be a ChannelPlugin")
    if plugin.name != name:
        raise TypeError(
            f"{module_name}.PLUGIN declares name '{plugin.name}', expected '{name}'"
        )
    if plugin.webui is not None:
        webui_entry = files("nanobot.channels").joinpath(name, *plugin.webui.split("/"))
        if not webui_entry.is_file():
            raise TypeError(
                f"{module_name}.PLUGIN webui entry does not exist: {plugin.webui}"
            )
    return plugin


@lru_cache(maxsize=None)
def load_builtin_setup_spec(name: str) -> ChannelSetupSpec | None:
    """Load a package-owned setup contract or the legacy built-in manifest."""
    plugin = load_builtin_channel_plugin(name)
    if plugin is not None:
        return plugin.setup

    if not name.isidentifier() or name.startswith("_"):
        return None

    module_name = f"{__name__}.{name}"
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name == module_name:
            return None
        raise

    spec = getattr(module, "SETUP_SPEC", None)
    if not isinstance(spec, ChannelSetupSpec):
        raise TypeError(f"{module_name}.SETUP_SPEC must be a ChannelSetupSpec")
    return spec
