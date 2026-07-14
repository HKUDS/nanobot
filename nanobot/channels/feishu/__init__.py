"""Feishu/Lark channel package.

The package stays dependency-free during manifest discovery. Runtime symbols
are resolved lazily to preserve the historical ``nanobot.channels.feishu``
import surface without importing the runtime for settings-only consumers.
"""

from __future__ import annotations

import importlib
from typing import Any


def __getattr__(name: str) -> Any:
    if name.startswith("__"):
        raise AttributeError(name)
    runtime = importlib.import_module(f"{__name__}.runtime")
    try:
        return getattr(runtime, name)
    except AttributeError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc


def __dir__() -> list[str]:
    runtime = importlib.import_module(f"{__name__}.runtime")
    return sorted(set(globals()) | set(dir(runtime)))
