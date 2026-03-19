"""Utility functions for nanobot."""

from __future__ import annotations

import unicodedata
from datetime import datetime
from pathlib import Path


def ensure_dir(path: Path) -> Path:
    """Ensure a directory exists, creating it if necessary."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_data_path() -> Path:
    """Get the nanobot data directory (~/.nanobot)."""
    return ensure_dir(Path.home() / ".nanobot")


def get_workspace_path(workspace: str | None = None) -> Path:
    """
    Get the workspace path.

    Args:
        workspace: Optional workspace path. Defaults to ~/.nanobot/workspace.

    Returns:
        Expanded and ensured workspace path.
    """
    if workspace:
        path = Path(workspace).expanduser()
    else:
        path = Path.home() / ".nanobot" / "workspace"
    return ensure_dir(path)


def get_sessions_path() -> Path:
    """Get the sessions storage directory."""
    return ensure_dir(get_data_path() / "sessions")


def get_skills_path(workspace: Path | None = None) -> Path:
    """Get the skills directory within the workspace."""
    ws = workspace or get_workspace_path()
    return ensure_dir(ws / "skills")


def timestamp() -> str:
    """Get current timestamp in ISO format."""
    return datetime.now().isoformat()


def truncate_string(s: str, max_len: int = 100, suffix: str = "...") -> str:
    """Truncate a string to max length, adding suffix if truncated."""
    if len(s) <= max_len:
        return s
    return s[: max_len - len(suffix)] + suffix


def safe_filename(name: str, max_len: int = 200) -> str:
    """Convert a string to a safe filename.

    Hardening applied (SEC-L3):
    - Null bytes and control characters stripped before any other processing.
    - NFKC Unicode normalization collapses homoglyphs and compatibility forms.
    - Result truncated to *max_len* bytes (default 200) to prevent filesystem
      limits from raising unexpected errors on very long session keys.
    """
    # Strip null bytes and ASCII control characters (U+0000–U+001F, U+007F).
    name = "".join(c for c in name if unicodedata.category(c) != "Cc")
    # NFKC normalization: collapse Unicode homoglyphs / compatibility variants.
    name = unicodedata.normalize("NFKC", name)
    # Replace characters that are unsafe in filenames on common OSes.
    for char in '<>:"/\\|?*':
        name = name.replace(char, "_")
    name = name.strip()
    # Encode to UTF-8 and truncate to byte budget, then decode back safely.
    encoded = name.encode("utf-8")[:max_len]
    return encoded.decode("utf-8", errors="ignore")


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
