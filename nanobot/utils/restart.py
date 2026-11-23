from __future__ import annotations

import json
import os
import time
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any, cast

from nanobot.bus.events import INBOUND_META_TURN_ID
from nanobot.bus.outbound_events import CommandLine
from nanobot.command.results import line, render
from nanobot.session.display_history import HISTORY_GENERATION_METADATA_KEY
from nanobot.webui.metadata import WEBUI_RESTART_CONTROL_METADATA_KEY

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

    @property
    def should_notify_chat(self) -> bool:
        """WebSocket reconnects are silent except for explicit restarts in admitted WebUI chats."""
        return self.channel != "websocket" or (
            self.metadata.get("webui") is True
            and self.metadata.get(WEBUI_RESTART_CONTROL_METADATA_KEY) is not True
            and bool(self.metadata.get(HISTORY_GENERATION_METADATA_KEY))
        )


def restart_completed_line(started_at_raw: str) -> CommandLine:
    """Report elapsed time when the requesting process recorded its start time."""
    if started_at_raw:
        with suppress(ValueError):
            elapsed_s = max(0.0, time.time() - float(started_at_raw))
            return line("restart.elapsed", seconds=f"{elapsed_s:.1f}")
    return line("restart.complete")


def format_restart_completed_message(started_at_raw: str, locale: object = None) -> str:
    return render((restart_completed_line(started_at_raw),), locale)


def set_restart_notice_to_env(
    *, channel: str, chat_id: str, metadata: dict[str, Any] | None = None,
) -> None:
    """Write restart notice env values for the next process."""
    os.environ[RESTART_NOTIFY_CHANNEL_ENV] = channel
    os.environ[RESTART_NOTIFY_CHAT_ID_ENV] = chat_id
    os.environ[RESTART_STARTED_AT_ENV] = str(time.time())
    persisted_metadata = dict(metadata or {})
    if channel == "websocket":
        # Keep the admitted history destination, not the command's turn, owner or input context.
        fields = ("webui", "locale", HISTORY_GENERATION_METADATA_KEY, WEBUI_RESTART_CONTROL_METADATA_KEY)
        persisted_metadata = {key: persisted_metadata[key] for key in fields if key in persisted_metadata}
    else:
        persisted_metadata.pop(INBOUND_META_TURN_ID, None)
    if persisted_metadata:
        try:
            os.environ[RESTART_NOTIFY_METADATA_ENV] = json.dumps(
                persisted_metadata,
                default=str,
            )
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
            metadata = cast(dict[str, Any], parsed)
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
