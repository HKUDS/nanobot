"""Helpers for restart notification messages."""

from __future__ import annotations

import json
import os
import time
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any

RESTART_NOTIFY_CHANNEL_ENV = "NANOBOT_RESTART_NOTIFY_CHANNEL"
RESTART_NOTIFY_CHAT_ID_ENV = "NANOBOT_RESTART_NOTIFY_CHAT_ID"
RESTART_NOTIFY_METADATA_ENV = "NANOBOT_RESTART_NOTIFY_METADATA"
RESTART_STARTED_AT_ENV = "NANOBOT_RESTART_STARTED_AT"


@dataclass(frozen=True)
class RestartNotice:
    channel: str
    chat_id: str
    started_at_raw: str
    metadata: dict[str, Any] = field(default_factory=dict)


def format_restart_completed_message(started_at_raw: str) -> str:
    """Build restart completion text and include elapsed time when available."""
    elapsed_suffix = ""
    if started_at_raw:
        with suppress(ValueError):
            elapsed_s = max(0.0, time.time() - float(started_at_raw))
            elapsed_suffix = f" in {elapsed_s:.1f}s"
    return f"Restart completed{elapsed_suffix}."


def set_restart_notice_to_env(
    *, channel: str, chat_id: str, metadata: dict[str, Any] | None = None,
) -> None:
    """Write restart notice env values for the next process."""
    os.environ[RESTART_NOTIFY_CHANNEL_ENV] = channel
    os.environ[RESTART_NOTIFY_CHAT_ID_ENV] = chat_id
    os.environ[RESTART_STARTED_AT_ENV] = str(time.time())
    if metadata:
        try:
            os.environ[RESTART_NOTIFY_METADATA_ENV] = json.dumps(metadata, default=str)
        except (TypeError, ValueError):
            os.environ.pop(RESTART_NOTIFY_METADATA_ENV, None)
    else:
        os.environ.pop(RESTART_NOTIFY_METADATA_ENV, None)


def consume_restart_notice_from_env() -> RestartNotice | None:
    """Read and clear restart notice env values once for this process."""
    channel = os.environ.pop(RESTART_NOTIFY_CHANNEL_ENV, "").strip()
    chat_id = os.environ.pop(RESTART_NOTIFY_CHAT_ID_ENV, "").strip()
    started_at_raw = os.environ.pop(RESTART_STARTED_AT_ENV, "").strip()
    metadata_raw = os.environ.pop(RESTART_NOTIFY_METADATA_ENV, "").strip()
    if not (channel and chat_id):
        return None
    metadata: dict[str, Any] = {}
    if metadata_raw:
        try:
            parsed = json.loads(metadata_raw)
        except (TypeError, ValueError):
            parsed = None
        if isinstance(parsed, dict):
            metadata = parsed
    return RestartNotice(
        channel=channel,
        chat_id=chat_id,
        started_at_raw=started_at_raw,
        metadata=metadata,
    )


def should_show_cli_restart_notice(notice: RestartNotice, session_id: str) -> bool:
    """Return True when a restart notice should be shown in this CLI session."""
    if notice.channel != "cli":
        return False
    if ":" in session_id:
        _, cli_chat_id = session_id.split(":", 1)
    else:
        cli_chat_id = session_id
    return not notice.chat_id or notice.chat_id == cli_chat_id
