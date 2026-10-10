"""Default instance paths selected by the global --home option."""

from pathlib import Path

_home_path: Path | None = None


def set_home_path(path: Path | None) -> None:
    """Select the instance root for the current CLI invocation."""
    global _home_path
    _home_path = path.expanduser().resolve() if path is not None else None


def get_selected_home_path() -> Path | None:
    """Return the explicit instance root, if one was selected."""
    return _home_path


def get_home_path() -> Path:
    """Return the selected instance root, or the default ~/.nanobot directory."""
    return _home_path if _home_path is not None else Path.home() / ".nanobot"


def get_default_workspace() -> str:
    """Keep the portable default unless an instance home was selected."""
    if _home_path is not None:
        return str(get_home_path() / "workspace")
    return "~/.nanobot/workspace"
