"""Utility functions for nanobot."""

import re
from pathlib import Path
from datetime import datetime
from typing import Any


def ensure_dir(path: Path) -> Path:
    """Ensure directory exists, return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_data_path() -> Path:
    """~/.nanobot data directory."""
    return ensure_dir(Path.home() / ".nanobot")


def get_workspace_path(workspace: str | None = None) -> Path:
    """Resolve and ensure workspace path. Defaults to ~/.nanobot/workspace."""
    path = Path(workspace).expanduser() if workspace else Path.home() / ".nanobot" / "workspace"
    return ensure_dir(path)


def timestamp() -> str:
    """Current ISO timestamp."""
    return datetime.now().isoformat()


_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*]')

def safe_filename(name: str) -> str:
    """Replace unsafe path characters with underscores."""
    return _UNSAFE_CHARS.sub("_", name).strip()


def get_logs_path() -> Path:
    """Get the logs directory (~/.nanobot/logs)."""
    return ensure_dir(get_data_path() / "logs")


def setup_file_logging() -> Path:
    """Add a file sink to loguru. Returns the log directory path."""
    from loguru import logger

    log_dir = get_logs_path()
    logger.add(
        log_dir / "nanobot_{time:YYYY-MM-DD}.log",
        rotation="00:00",
        retention="7 days",
        compression="gz",
        encoding="utf-8",
        enqueue=True,
        level="DEBUG",
    )
    return log_dir


def _heartbeat_log_filter(record: dict[str, Any]) -> bool:
    """Return True for heartbeat-related log records."""
    name = str(record.get("name") or "")
    message = str(record.get("message") or "")
    return name.startswith("nanobot.heartbeat") or message.startswith("Heartbeat:")


def setup_heartbeat_logging() -> Path:
    """Add a dedicated heartbeat log sink and return the log directory path."""
    from loguru import logger

    log_dir = get_logs_path()
    logger.add(
        log_dir / "heartbeat_{time:YYYY-MM-DD}.log",
        rotation="00:00",
        retention="7 days",
        compression="gz",
        encoding="utf-8",
        enqueue=True,
        level="DEBUG",
        filter=_heartbeat_log_filter,
    )
    return log_dir


def parse_session_key(key: str) -> tuple[str, str]:
    """
    Parse a session key into channel and chat_id.

    Args:
        key: Session key in format "channel:chat_id"

    Returns:
        Tuple of (channel, chat_id)
    """
    parts = key.split(":", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid session key: {key}")
    return parts[0], parts[1]


def sync_workspace_templates(workspace: Path, silent: bool = False) -> list[str]:
    """Sync bundled templates to workspace. Only creates missing files."""
    from importlib.resources import files as pkg_files
    try:
        tpl = pkg_files("nanobot") / "templates"
    except Exception:
        return []
    if not tpl.is_dir():
        return []

    added: list[str] = []

    def _write(src, dest: Path):
        if dest.exists():
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(src.read_text(encoding="utf-8") if src else "", encoding="utf-8")
        added.append(str(dest.relative_to(workspace)))

    for item in tpl.iterdir():
        if item.name.endswith(".md"):
            _write(item, workspace / item.name)
    _write(tpl / "memory" / "MEMORY.md", workspace / "memory" / "MEMORY.md")
    _write(None, workspace / "memory" / "HISTORY.md")
    (workspace / "skills").mkdir(exist_ok=True)

    if added and not silent:
        from rich.console import Console
        for name in added:
            Console().print(f"  [dim]Created {name}[/dim]")
    return added
