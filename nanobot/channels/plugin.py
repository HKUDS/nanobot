"""Typed metadata for self-contained built-in channel packages."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from typing import TYPE_CHECKING, Any

from nanobot.channels.contracts import ChannelSetupSpec

if TYPE_CHECKING:
    from nanobot.channels.base import BaseChannel


@dataclass(frozen=True)
class ChannelPlugin:
    """Dependency-free manifest for one built-in channel package.

    ``runtime`` is an absolute ``module:attribute`` target. Keeping it as an
    import string lets discovery inspect metadata without importing optional
    platform SDKs.
    """

    name: str
    display_name: str
    runtime: str
    setup: ChannelSetupSpec | None = None
    optional_extra: str | None = None
    default_enabled: bool = False
    settings_visible: bool = True
    capabilities: frozenset[str] = frozenset()
    webui: str | None = None

    def __post_init__(self) -> None:
        if not self.name.isidentifier() or self.name.startswith("_"):
            raise ValueError("channel plugin name must be a public Python identifier")
        module_name, separator, attr_name = self.runtime.partition(":")
        if not separator or not module_name or not attr_name:
            raise ValueError("channel plugin runtime must use 'module:attribute' syntax")
        if not all(part.isidentifier() for part in module_name.split(".")):
            raise ValueError("channel plugin runtime module must be an absolute import path")
        if not attr_name.isidentifier():
            raise ValueError("channel plugin runtime attribute must be a Python identifier")
        if self.setup is not None and not isinstance(self.setup, ChannelSetupSpec):
            raise TypeError("channel plugin setup must be a ChannelSetupSpec or None")
        if self.webui is not None:
            webui = self.webui.replace("\\", "/")
            if webui.startswith("/") or ".." in webui.split("/"):
                raise ValueError("channel plugin webui entry must stay inside its package")
            object.__setattr__(self, "webui", webui)

    def load_channel_class(self) -> type[BaseChannel]:
        """Resolve and validate the runtime class only when the channel is needed."""
        from nanobot.channels.base import BaseChannel

        module_name, _, attr_name = self.runtime.partition(":")
        module = importlib.import_module(module_name)
        channel_cls: Any = getattr(module, attr_name, None)
        if (
            not isinstance(channel_cls, type)
            or not issubclass(channel_cls, BaseChannel)
            or channel_cls is BaseChannel
        ):
            raise ImportError(
                f"Channel plugin '{self.name}' runtime '{self.runtime}' "
                "does not resolve to a BaseChannel subclass"
            )
        if channel_cls.name != self.name:
            raise ImportError(
                f"Channel plugin '{self.name}' runtime declares name '{channel_cls.name}'"
            )
        return channel_cls


def has_builtin_channel_package(name: str) -> bool:
    """Return whether *name* owns a dependency-free package manifest."""
    if not name.isidentifier() or name.startswith("_"):
        return False
    return files("nanobot.channels").joinpath(name, "manifest.py").is_file()


@lru_cache(maxsize=None)
def load_builtin_channel_plugin(name: str) -> ChannelPlugin | None:
    """Load one built-in package manifest without importing its runtime."""
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

    runtime_module, _, _ = plugin.runtime.partition(":")
    package_name = f"nanobot.channels.{name}"
    if not runtime_module.startswith(f"{package_name}."):
        raise TypeError(
            f"{module_name}.PLUGIN runtime must stay inside {package_name}: "
            f"{runtime_module}"
        )
    runtime_parts = runtime_module.removeprefix(f"{package_name}.").split(".")
    package_root = files("nanobot.channels").joinpath(name)
    runtime_file = package_root.joinpath(
        *runtime_parts[:-1],
        f"{runtime_parts[-1]}.py",
    )
    runtime_package = package_root.joinpath(*runtime_parts, "__init__.py")
    if not (runtime_file.is_file() or runtime_package.is_file()):
        raise TypeError(
            f"{module_name}.PLUGIN runtime module does not exist inside its package: "
            f"{runtime_module}"
        )
    if plugin.webui is not None:
        webui_entry = files("nanobot.channels").joinpath(name, *plugin.webui.split("/"))
        if not webui_entry.is_file():
            raise TypeError(
                f"{module_name}.PLUGIN webui entry does not exist: {plugin.webui}"
            )
    return plugin


__all__ = [
    "ChannelPlugin",
    "has_builtin_channel_package",
    "load_builtin_channel_plugin",
]
