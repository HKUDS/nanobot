"""Runtime path helpers derived from the active config context."""

from __future__ import annotations

import os
from pathlib import Path

from nanobot.utils.helpers import ensure_dir

# Stock config default; resolved via :func:`get_nanobot_home` so ``NANOBOT_HOME`` works.
DEFAULT_WORKSPACE_SETTING = "~/.nanobot/workspace"


def get_nanobot_home() -> Path:
    """Return the nanobot home directory used for default config and workspace.

    When ``NANOBOT_HOME`` is set, that path is used (after ``expanduser``).
    Otherwise defaults to ``~/.nanobot``. This lets multiple instances on
    Windows isolate config/data without rewriting ``USERPROFILE``.
    """
    raw = os.environ.get("NANOBOT_HOME", "").strip()
    if raw:
        return Path(raw).expanduser().resolve(strict=False)
    return (Path.home() / ".nanobot").resolve(strict=False)


def default_workspace_path() -> Path:
    """Return the default agent workspace under :func:`get_nanobot_home`."""
    return get_nanobot_home() / "workspace"


def get_config_path() -> Path:
    """Get the configuration file path (lazy import to break circular dependency).

    Delegates to ``nanobot.config.loader.get_config_path`` at call time so
    that importing this module never triggers a circular import during startup.
    """
    from nanobot.config.loader import get_config_path as _loader_get_config_path
    return _loader_get_config_path()


def get_data_dir() -> Path:
    """Return the instance-level runtime data directory."""
    return ensure_dir(get_config_path().parent)


def get_runtime_subdir(name: str) -> Path:
    """Return a named runtime subdirectory under the instance data dir."""
    return ensure_dir(get_data_dir() / name)


def get_media_dir(channel: str | None = None) -> Path:
    """Return the media directory, optionally namespaced per channel."""
    base = get_runtime_subdir("media")
    return ensure_dir(base / channel) if channel else base


def get_cron_dir() -> Path:
    """Return the cron storage directory."""
    return get_runtime_subdir("cron")


def get_logs_dir() -> Path:
    """Return the logs directory."""
    return get_runtime_subdir("logs")


def get_webui_dir() -> Path:
    """Return the directory for WebUI-only persisted display threads (JSON)."""
    return get_runtime_subdir("webui")


def get_workspace_path(workspace: str | Path | None = None) -> Path:
    """Resolve and ensure the agent workspace path."""
    if workspace is None:
        path = default_workspace_path()
    elif str(workspace) == DEFAULT_WORKSPACE_SETTING:
        path = default_workspace_path()
    else:
        path = Path(workspace).expanduser()
    return ensure_dir(path)


def is_default_workspace(workspace: str | Path | None) -> bool:
    """Return whether a workspace resolves to nanobot's default workspace path."""
    if workspace is None or str(workspace) == DEFAULT_WORKSPACE_SETTING:
        current = default_workspace_path()
    else:
        current = Path(workspace).expanduser()
    default = default_workspace_path()
    return current.resolve(strict=False) == default.resolve(strict=False)


def get_cli_history_path() -> Path:
    """Return the shared CLI history file path."""
    return Path.home() / ".nanobot" / "history" / "cli_history"


def get_legacy_sessions_dir() -> Path:
    """Return the legacy global session directory used for migration fallback."""
    return Path.home() / ".nanobot" / "sessions"
