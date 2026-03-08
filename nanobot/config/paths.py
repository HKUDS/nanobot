"""Runtime path helpers derived from the active workspace context."""

from __future__ import annotations

from pathlib import Path

from nanobot.config.loader import load_config
from nanobot.utils.helpers import ensure_dir


def get_data_dir() -> Path:
    """Return the workspace root used as runtime data root."""
    return get_workspace_path()


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


def get_workspace_path(workspace: str | None = None) -> Path:
    """Resolve and ensure the agent workspace path."""
    if workspace:
        return ensure_dir(Path(workspace).expanduser())
    return ensure_dir(load_config().workspace_path)


def get_cli_history_path() -> Path:
    """Return the shared CLI history file path."""
    return Path.home() / ".nanobot" / "history" / "cli_history"


def get_bridge_install_dir() -> Path:
    """Return the shared WhatsApp bridge installation directory."""
    return Path.home() / ".nanobot" / "bridge"


def get_legacy_sessions_dir() -> Path:
    """Return the legacy global session directory used for migration fallback."""
    return Path.home() / ".nanobot" / "sessions"
