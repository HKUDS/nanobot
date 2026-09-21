"""WhatsApp-owned persisted login-state detection."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nanobot.channels.contracts import channel_field_value
from nanobot.config.loader import get_config_path


def local_state_present(section: Any) -> bool:
    configured_path = channel_field_value(section, "databasePath")
    database_path = (
        Path(str(configured_path)).expanduser()
        if configured_path
        else get_config_path().parent / "whatsapp-auth" / "neonize.db"
    )
    try:
        return database_path.is_file() and database_path.stat().st_size > 0
    except OSError:
        return False


__all__ = ["local_state_present"]
