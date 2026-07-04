"""
blackcat - A lightweight AI agent framework
"""

import tomllib
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path


def _read_pyproject_version() -> str | None:
    """Read the source-tree version when package metadata is unavailable."""
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    if not pyproject.exists():
        return None
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    return data.get("project", {}).get("version")


def _resolve_version() -> str:
    try:
        return _pkg_version("blackcat-ai")
    except PackageNotFoundError:
        # Source checkouts often import blackcat without installed dist-info.
        return _read_pyproject_version() or "0.2.2"


__version__ = _resolve_version()
__logo__ = "🐈"

_LAZY_EXPORTS = {
    "Blackcat": ".blackcat",
    "RunStream": ".blackcat",
    "RunResult": ".blackcat",
    "SessionInfo": ".blackcat",
    "SessionSnapshot": ".blackcat",
    "STREAM_EVENT_REASONING_COMPLETED": ".blackcat",
    "STREAM_EVENT_REASONING_DELTA": ".blackcat",
    "STREAM_EVENT_RUN_COMPLETED": ".blackcat",
    "STREAM_EVENT_RUN_FAILED": ".blackcat",
    "STREAM_EVENT_RUN_STARTED": ".blackcat",
    "STREAM_EVENT_TEXT_COMPLETED": ".blackcat",
    "STREAM_EVENT_TEXT_DELTA": ".blackcat",
    "STREAM_EVENT_TOOL_COMPLETED": ".blackcat",
    "STREAM_EVENT_TOOL_FAILED": ".blackcat",
    "STREAM_EVENT_TOOL_STARTED": ".blackcat",
    "STREAM_EVENT_TYPES": ".blackcat",
    "StreamEvent": ".blackcat",
    "StreamEventType": ".blackcat",
}


def __getattr__(name: str):
    module_path = _LAZY_EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module
    mod = import_module(module_path, __name__)
    val = getattr(mod, name)
    globals()[name] = val
    return val


__all__ = [
    "Blackcat",
    "RunResult",
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
]
