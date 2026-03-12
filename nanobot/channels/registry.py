"""Auto-discovery for channel modules — no hardcoded registry."""

from __future__ import annotations

import importlib
import pkgutil
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nanobot.channels.base import BaseChannel

_INTERNAL = frozenset({"base", "manager", "registry"})


def discover_channel_names() -> list[str]:
    """Return all channel module names by scanning the package (zero imports)."""
    import nanobot.channels as pkg

    return [
        name
        for _, name, ispkg in pkgutil.iter_modules(pkg.__path__)
        if name not in _INTERNAL and not ispkg
    ]


def load_channel_class(module_name: str) -> type[BaseChannel]:
    """Import *module_name* and return the first BaseChannel subclass found."""
    from nanobot.channels.base import BaseChannel as _Base

    mod = importlib.import_module(f"nanobot.channels.{module_name}")
    for attr in dir(mod):
        obj = getattr(mod, attr)
        if isinstance(obj, type) and issubclass(obj, _Base) and obj is not _Base:
            return obj
    raise ImportError(f"No BaseChannel subclass in nanobot.channels.{module_name}")
