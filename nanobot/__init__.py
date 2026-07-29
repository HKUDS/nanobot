"""
nanobot - A lightweight AI agent framework
"""

import tomllib
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .agent.tools.context import RequestContext
    from .bus.runtime_events import SessionTurnPersisted
    from .nanobot import (
        STREAM_EVENT_REASONING_COMPLETED,
        STREAM_EVENT_REASONING_DELTA,
        STREAM_EVENT_RUN_COMPLETED,
        STREAM_EVENT_RUN_FAILED,
        STREAM_EVENT_RUN_STARTED,
        STREAM_EVENT_TEXT_COMPLETED,
        STREAM_EVENT_TEXT_DELTA,
        STREAM_EVENT_TOOL_COMPLETED,
        STREAM_EVENT_TOOL_FAILED,
        STREAM_EVENT_TOOL_STARTED,
        STREAM_EVENT_TYPES,
        Nanobot,
        RunResult,
        RunStream,
        SessionInfo,
        SessionSnapshot,
        StreamEvent,
        StreamEventType,
    )
    from .runtime_context import RuntimeContextBlock, RuntimeContextProvider


def _read_pyproject_version() -> str | None:
    """Read the source-tree version when package metadata is unavailable."""
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    if not pyproject.exists():
        return None
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    return data.get("project", {}).get("version")


def _resolve_version() -> str:
    try:
        return _pkg_version("nanobot-ai")
    except PackageNotFoundError:
        # Source checkouts often import nanobot without installed dist-info.
        return _read_pyproject_version() or "0.3.0"


__version__ = _resolve_version()
__logo__ = "🐈"

_LAZY_EXPORTS = {
    "Nanobot": ".nanobot",
    "RunStream": ".nanobot",
    "RunResult": ".nanobot",
    "RequestContext": ".agent.tools.context",
    "RuntimeContextBlock": ".runtime_context",
    "RuntimeContextProvider": ".runtime_context",
    "SessionInfo": ".nanobot",
    "SessionSnapshot": ".nanobot",
    "STREAM_EVENT_REASONING_COMPLETED": ".nanobot",
    "STREAM_EVENT_REASONING_DELTA": ".nanobot",
    "STREAM_EVENT_RUN_COMPLETED": ".nanobot",
    "STREAM_EVENT_RUN_FAILED": ".nanobot",
    "STREAM_EVENT_RUN_STARTED": ".nanobot",
    "STREAM_EVENT_TEXT_COMPLETED": ".nanobot",
    "STREAM_EVENT_TEXT_DELTA": ".nanobot",
    "STREAM_EVENT_TOOL_COMPLETED": ".nanobot",
    "STREAM_EVENT_TOOL_FAILED": ".nanobot",
    "STREAM_EVENT_TOOL_STARTED": ".nanobot",
    "STREAM_EVENT_TYPES": ".nanobot",
    "StreamEvent": ".nanobot",
    "StreamEventType": ".nanobot",
    "SessionTurnPersisted": ".bus.runtime_events",
}


def __getattr__(name: str) -> Any:
    module_path = _LAZY_EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module
    mod = import_module(module_path, __name__)
    val = getattr(mod, name)
    globals()[name] = val
    return val


__all__ = [
    "Nanobot",
    "RunResult",
    "RequestContext",
    "RuntimeContextBlock",
    "RuntimeContextProvider",
    "RunStream",
    "SessionInfo",
    "SessionSnapshot",
    "STREAM_EVENT_REASONING_COMPLETED",
    "STREAM_EVENT_REASONING_DELTA",
    "STREAM_EVENT_RUN_COMPLETED",
    "STREAM_EVENT_RUN_FAILED",
    "STREAM_EVENT_RUN_STARTED",
    "STREAM_EVENT_TEXT_COMPLETED",
    "STREAM_EVENT_TEXT_DELTA",
    "STREAM_EVENT_TOOL_COMPLETED",
    "STREAM_EVENT_TOOL_FAILED",
    "STREAM_EVENT_TOOL_STARTED",
    "STREAM_EVENT_TYPES",
    "StreamEvent",
    "StreamEventType",
    "SessionTurnPersisted",
]
