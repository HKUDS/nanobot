"""Registry primitives for built-in channel metadata."""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

from nanobot.config.schema import Config

if TYPE_CHECKING:
    from nanobot.channels.base import BaseChannel

_INTERNAL = frozenset(
    {
        "base",
        "builtins",
        "dispatcher",
        "factory",
        "manager",
        "policy",
        "registry",
    }
)


def _default_extra_kwargs_factory(config: Config) -> dict[str, Any]:
    """Return constructor kwargs derived from the root runtime config."""
    return {}


@dataclass(frozen=True)
class ChannelSpec:
    """Metadata describing a built-in channel.

    `extra_kwargs_factory` receives the root runtime `Config` object so future
    factory code can derive constructor extras without hardcoded special cases.
    """

    name: str
    module_path: str
    class_name: str
    display_name: str = ""
    extra_kwargs_factory: Callable[[Config], dict[str, Any]] = field(
        default=_default_extra_kwargs_factory,
    )

    def __post_init__(self) -> None:
        for field_name in ("name", "module_path", "class_name"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} must not be blank")


class ChannelRegistry:
    """In-memory registry for built-in channel specs."""

    def __init__(self) -> None:
        self._specs: dict[str, ChannelSpec] = {}

    def register(self, spec: ChannelSpec) -> None:
        if spec.name in self._specs:
            raise ValueError(f"channel already registered: {spec.name}")
        self._specs[spec.name] = spec

    def get(self, name: str) -> ChannelSpec | None:
        return self._specs.get(name)

    def all(self) -> tuple[ChannelSpec, ...]:
        return tuple(self._specs.values())


def discover_channel_names() -> list[str]:
    """Return all loadable channel module names for CLI discovery."""
    import nanobot.channels as pkg

    return [
        name
        for _, name, ispkg in pkgutil.iter_modules(pkg.__path__)
        if name not in _INTERNAL and not ispkg
    ]


def load_channel_class(module_name: str) -> type[BaseChannel]:
    """Import a channel module and return the first BaseChannel subclass."""
    from nanobot.channels.base import BaseChannel as _Base

    module = importlib.import_module(f"nanobot.channels.{module_name}")
    for attr in dir(module):
        obj = getattr(module, attr)
        if isinstance(obj, type) and issubclass(obj, _Base) and obj is not _Base:
            return obj
    raise ImportError(f"No BaseChannel subclass in nanobot.channels.{module_name}")
