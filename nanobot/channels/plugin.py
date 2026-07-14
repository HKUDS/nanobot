"""Typed metadata for self-contained built-in channel packages."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nanobot.channels.base import BaseChannel
    from nanobot.channels.contracts import ChannelSetupSpec


@dataclass(frozen=True)
class ChannelPlugin:
    """Dependency-free manifest for one built-in channel package.

    ``runtime`` stays as an import string so discovery and settings metadata do
    not import the channel runtime or any optional platform SDK.
    """

    name: str
    display_name: str
    runtime: str
    setup: ChannelSetupSpec | None = None
    optional_extra: str | None = None
    default_enabled: bool = False
    capabilities: frozenset[str] = frozenset()
    webui: str | None = None

    def __post_init__(self) -> None:
        if not self.name.isidentifier() or self.name.startswith("_"):
            raise ValueError("channel plugin name must be a public Python identifier")
        module_name, separator, attr_name = self.runtime.partition(":")
        if not separator or not module_name or not attr_name:
            raise ValueError("channel plugin runtime must use 'module:attribute' syntax")
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


__all__ = ["ChannelPlugin"]
