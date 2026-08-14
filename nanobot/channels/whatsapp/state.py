"""WhatsApp-owned persisted login-state detection."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nanobot.channels.contracts import channel_field_value
from nanobot.config.loader import get_config_path


class WhatsAppDatabaseRecoveryRequiredError(RuntimeError):
    """A durable recovery marker prevents unsafe access to the session database."""


def _database_path(section: Any, config_path: Path) -> Path:
    configured_path = channel_field_value(section, "databasePath")
    return (
        Path(str(configured_path)).expanduser()
        if configured_path
        else config_path.parent / "whatsapp-auth" / "neonize.db"
    )


def recovery_marker_path(database_path: Path) -> Path:
    """Return the durable guard written before replacing a SQLite file family."""
    return database_path.with_name(f".{database_path.name}.recovery-required")


def recovery_required_message(database_path: Path) -> str | None:
    marker = recovery_marker_path(database_path)
    try:
        marker.stat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        return f"WhatsApp database recovery status could not be verified: {exc}"
    return (
        "WhatsApp database recovery is required before this channel can start. "
        f"Reconcile the preserved files beside {database_path}, remove {marker}, "
        "then restart nanobot."
    )


def ensure_database_ready(database_path: Path) -> None:
    if message := recovery_required_message(database_path):
        raise WhatsAppDatabaseRecoveryRequiredError(message)


def local_state_present(section: Any) -> bool:
    database_path = _database_path(section, get_config_path())
    try:
        return database_path.is_file() and database_path.stat().st_size > 0
    except OSError:
        return False


__all__ = [
    "WhatsAppDatabaseRecoveryRequiredError",
    "ensure_database_ready",
    "local_state_present",
    "recovery_marker_path",
    "recovery_required_message",
]
