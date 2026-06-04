"""Runtime path helpers derived from the active config context."""

from __future__ import annotations

from pathlib import Path

from blackcat.config.loader import get_config_path


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


def get_workspace_path(workspace: str | None = None) -> Path:
    """Resolve and ensure the agent workspace path."""
    path = Path(workspace).expanduser() if workspace else Path.home() / ".blackcat" / "workspace"
    return ensure_dir(path)


def is_default_workspace(workspace: str | Path | None) -> bool:
    """Return whether a workspace resolves to blackcat's default workspace path."""
    current = Path(workspace).expanduser() if workspace is not None else Path.home() / ".blackcat" / "workspace"
    default = Path.home() / ".blackcat" / "workspace"
    return current.resolve(strict=False) == default.resolve(strict=False)


def get_cli_history_path() -> Path:
    """Return the shared CLI history file path."""
    return Path.home() / ".blackcat" / "history" / "cli_history"


def get_bridge_install_dir() -> Path:
    """Return the shared WhatsApp bridge installation directory."""
    return Path.home() / ".blackcat" / "bridge"


def get_legacy_sessions_dir() -> Path:
    """Return the legacy global session directory used for migration fallback."""
    return Path.home() / ".blackcat" / "sessions"

def get_sessions_path() -> Path:
    """Get the sessions storage directory."""
    return ensure_dir(get_data_path() / "sessions")


def get_memory_path(workspace: Path | None = None) -> Path:
    """Get the memory directory within the workspace."""
    ws = workspace or get_workspace_path()
    return ensure_dir(ws / "memory")


def get_skills_path(workspace: Path | None = None) -> Path:
    """Get the skills directory within the workspace."""
    ws = workspace or get_workspace_path()
    return ensure_dir(ws / "skills")


def get_webui_dir() -> Path:
    """Return the webui data directory for persistent state."""
    return ensure_dir(get_data_path() / "webui")


def get_data_path() -> Path:
    """Get the blackcat data directory (~/.blackcat)."""
    return ensure_dir(Path.home() / ".blackcat")

def resolve_path(
    path: str, workspace: Path | None = None, allowed_dir: Path | None = None
) -> Path:
    """Resolve path against workspace (if relative) and enforce directory restriction."""
    p = Path(path).expanduser()
    if not p.is_absolute() and workspace:
        p = workspace / p
    resolved = p.resolve()
    if allowed_dir:
        try:
            resolved.relative_to(allowed_dir.resolve())
        except ValueError:
            raise PermissionError(f"Path {path} is outside allowed directory {allowed_dir}")
    return resolved

def ensure_dir(path: Path) -> Path:
    """Ensure directory exists, return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path
