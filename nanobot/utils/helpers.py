"""Utility functions for nanobot."""

from pathlib import Path
from datetime import datetime

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


def safe_filename(name: str) -> str:
    """Convert a string to a safe filename."""
    # Replace unsafe characters
    unsafe = '<>:"/\\|?*'
    for char in unsafe:
        name = name.replace(char, "_")
    return name.strip()


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
    """
    Synchronize default workspace template files from bundled templates.
    Only creates files that do not exist. Returns list of added file names.
    """
    from importlib.resources import files as pkg_files
    from rich.console import Console
    console = Console()
    added = []

    try:
        templates_dir = pkg_files("nanobot") / "templates"
    except Exception:
        # Fallback for some environments where pkg_files might fail
        return []

    if not templates_dir.is_dir():
        return []

    # 1. Sync root templates
    for item in templates_dir.iterdir():
        if not item.name.endswith(".md"):
            continue
        dest = workspace / item.name
        if not dest.exists():
            try:
                dest.write_text(item.read_text(encoding="utf-8"), encoding="utf-8")
                added.append(item.name)
            except Exception:
                pass

    # 2. Sync memory templates
    memory_dir = workspace / "memory"
    memory_dir.mkdir(exist_ok=True)
    
    memory_src = templates_dir / "memory" / "MEMORY.md"
    memory_dest = memory_dir / "MEMORY.md"
    if memory_src.is_file() and not memory_dest.exists():
        try:
            memory_dest.write_text(memory_src.read_text(encoding="utf-8"), encoding="utf-8")
            added.append("memory/MEMORY.md")
        except Exception:
            pass

    # 3. History file (always ensure it exists)
    history_file = memory_dir / "HISTORY.md"
    if not history_file.exists():
        try:
            history_file.write_text("", encoding="utf-8")
            added.append("memory/HISTORY.md")
        except Exception:
            pass

    # 4. Ensure skills dir exists
    (workspace / "skills").mkdir(exist_ok=True)

    # Print notices if files were added
    if added and not silent:
        for name in added:
            console.print(f"  [dim]Created {name}[/dim]")
            
    return added