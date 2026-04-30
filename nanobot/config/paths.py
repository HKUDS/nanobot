"""Runtime path helpers, all rooted at ``<workspace>/.nanobot/``.

Under the unified layout, the **workspace** is the user's working directory
(default: ``$HOME``) and *all* agent state — config, sessions, memory, cron,
media, logs, bridge, channel state — lives under ``<workspace>/.nanobot/``.

Set ``NANOBOT_WORKSPACE`` or call :func:`set_workspace` to override the default.
"""

from __future__ import annotations

import os
from pathlib import Path

from nanobot.utils.helpers import ensure_dir

_DATA_SUBDIR = ".nanobot"

# Active workspace (set by CLI bootstrap or ``set_workspace``).
_current_workspace: Path | None = None


def set_workspace(path: Path | str | None) -> None:
    """Pin the active workspace. Pass ``None`` to clear."""
    global _current_workspace
    _current_workspace = Path(path).expanduser() if path else None


def _resolved_default_workspace() -> Path:
    """Default workspace = $NANOBOT_WORKSPACE or $HOME."""
    env = os.environ.get("NANOBOT_WORKSPACE")
    if env:
        return Path(env).expanduser()
    return Path.home()


def get_workspace_path(workspace: str | Path | None = None) -> Path:
    """Resolve and ensure the workspace path (the user's working directory)."""
    if workspace is not None:
        return ensure_dir(Path(workspace).expanduser())
    if _current_workspace is not None:
        return ensure_dir(_current_workspace)
    return ensure_dir(_resolved_default_workspace())


def is_default_workspace(workspace: str | Path | None) -> bool:
    """Return whether *workspace* equals the default workspace."""
    current = Path(workspace).expanduser() if workspace is not None else get_workspace_path()
    default = _resolved_default_workspace()
    return current.resolve(strict=False) == default.resolve(strict=False)


def get_data_dir(workspace: str | Path | None = None) -> Path:
    """Return ``<workspace>/.nanobot/`` — root of all agent state."""
    ws = get_workspace_path(workspace) if workspace is not None else get_workspace_path()
    return ensure_dir(ws / _DATA_SUBDIR)


def get_runtime_subdir(name: str) -> Path:
    """Return a named runtime subdirectory under the data dir."""
    return ensure_dir(get_data_dir() / name)


def get_media_dir(channel: str | None = None) -> Path:
    """Return the media directory, optionally namespaced per channel."""
    base = get_runtime_subdir("media")
    return ensure_dir(base / channel) if channel else base


def get_cron_dir() -> Path:
    """Return the cron storage directory (``<workspace>/.nanobot/cron``)."""
    return get_runtime_subdir("cron")


def get_logs_dir() -> Path:
    """Return the logs directory (``<workspace>/.nanobot/logs``)."""
    return get_runtime_subdir("logs")


def get_cli_history_path() -> Path:
    """Return the CLI prompt-toolkit history file path."""
    return get_runtime_subdir("history") / "cli_history"


def get_bridge_install_dir() -> Path:
    """Return the WhatsApp bridge installation directory."""
    return get_data_dir() / "bridge"


def get_legacy_sessions_dir() -> Path:
    """Return the legacy global session directory used for migration fallback."""
    return Path.home() / ".nanobot" / "sessions"
