"""Typed metadata for self-contained channel packages."""

from __future__ import annotations

import importlib
import re
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from typing import TYPE_CHECKING, Any

from packaging.requirements import InvalidRequirement, Requirement

from nanobot.channels.contracts import ChannelManagementSpec, ChannelSetupSpec

if TYPE_CHECKING:
    from nanobot.channels.base import BaseChannel

_CHANNEL_PACKAGE_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]*")


@dataclass(frozen=True)
class ChannelPlugin:
    """Dependency-free manifest for one channel package.

    ``runtime`` is an absolute ``module:attribute`` target. Keeping it as an
    import string lets discovery inspect metadata without importing optional
    platform SDKs.
    """

    name: str
    display_name: str
    runtime: str
    connector: str | None = None
    setup: ChannelSetupSpec | None = None
    management: ChannelManagementSpec = ChannelManagementSpec()
    dependencies: tuple[str, ...] = ()
    default_enabled: bool = False
    settings_visible: bool = True
    capabilities: frozenset[str] = frozenset()
    webui: str | None = None

    def __post_init__(self) -> None:
        if _CHANNEL_PACKAGE_NAME.fullmatch(self.name) is None:
            raise ValueError(
                "channel plugin name must start with a letter and contain only letters, "
                "digits, or underscores"
            )
        _target_parts(self.runtime, label="runtime")
        if self.connector is not None:
            _target_parts(self.connector, label="connector")
        if self.setup is not None and not isinstance(self.setup, ChannelSetupSpec):
            raise TypeError("channel plugin setup must be a ChannelSetupSpec or None")
        if not isinstance(self.management, ChannelManagementSpec):
            raise TypeError("channel plugin management must be a ChannelManagementSpec")
        if not isinstance(self.dependencies, tuple) or not all(
            isinstance(requirement, str) and requirement.strip()
            for requirement in self.dependencies
        ):
            raise TypeError("channel plugin dependencies must be a tuple of requirements")
        for dependency in self.dependencies:
            try:
                Requirement(dependency)
            except InvalidRequirement as exc:
                raise ValueError(
                    f"channel plugin dependency is not a valid requirement: {dependency}"
                ) from exc
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

    def load_connector(self) -> Any:
        """Construct the optional channel-owned interactive connector."""
        if self.connector is None:
            raise ImportError(f"Channel plugin '{self.name}' does not provide a connector")
        module_name, attr_name = _target_parts(self.connector, label="connector")
        module = importlib.import_module(module_name)
        factory = getattr(module, attr_name, None)
        if not callable(factory):
            raise ImportError(
                f"Channel plugin '{self.name}' connector '{self.connector}' is not callable"
            )
        connector = factory()
        if not callable(getattr(connector, "handle", None)):
            raise ImportError(
                f"Channel plugin '{self.name}' connector '{self.connector}' "
                "does not provide handle()"
            )
        return connector


def _target_parts(target: str, *, label: str) -> tuple[str, str]:
    module_name, separator, attr_name = target.partition(":")
    if not separator or not module_name or not attr_name:
        raise ValueError(f"channel plugin {label} must use 'module:attribute' syntax")
    if not all(part.isidentifier() for part in module_name.split(".")):
        raise ValueError(f"channel plugin {label} module must be an absolute import path")
    if not attr_name.isidentifier():
        raise ValueError(f"channel plugin {label} attribute must be a Python identifier")
    return module_name, attr_name


def has_channel_package(name: str) -> bool:
    """Return whether *name* owns a dependency-free package manifest."""
    if _CHANNEL_PACKAGE_NAME.fullmatch(name) is None:
        return False
    return files("nanobot.channels").joinpath(name, "manifest.py").is_file()


@lru_cache(maxsize=None)
def load_channel_package(name: str) -> ChannelPlugin | None:
    """Load one package manifest without importing its runtime."""
    if not has_channel_package(name):
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

    package_name = f"nanobot.channels.{name}"
    package_root = files("nanobot.channels").joinpath(name)
    targets = [("runtime", plugin.runtime)]
    if plugin.connector is not None:
        targets.append(("connector", plugin.connector))
    for label, target in targets:
        target_module, _ = _target_parts(target, label=label)
        if not target_module.startswith(f"{package_name}."):
            raise TypeError(
                f"{module_name}.PLUGIN {label} must stay inside {package_name}: "
                f"{target_module}"
            )
        target_parts = target_module.removeprefix(f"{package_name}.").split(".")
        target_file = package_root.joinpath(
            *target_parts[:-1],
            f"{target_parts[-1]}.py",
        )
        target_package = package_root.joinpath(*target_parts, "__init__.py")
        if not (target_file.is_file() or target_package.is_file()):
            raise TypeError(
                f"{module_name}.PLUGIN {label} module does not exist inside its package: "
                f"{target_module}"
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
    "has_channel_package",
    "load_channel_package",
]
