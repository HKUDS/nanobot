"""Default instance paths selected by NANOBOT_HOME."""

import os
from pathlib import Path


def get_home_path() -> Path:
    """Return the selected instance root, or the default ~/.nanobot directory."""
    home = os.environ.get("NANOBOT_HOME")
    return Path(home).expanduser().resolve() if home else Path.home() / ".nanobot"


def get_default_workspace() -> str:
    """Keep the portable default unless an instance home was selected."""
    if os.environ.get("NANOBOT_HOME"):
        return str(get_home_path() / "workspace")
    return "~/.nanobot/workspace"
