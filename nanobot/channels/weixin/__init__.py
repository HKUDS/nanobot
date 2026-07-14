"""Personal WeChat channel package with a dependency-free manifest surface."""

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
