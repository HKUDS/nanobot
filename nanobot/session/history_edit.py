"""Validated, version-bound edits of a persisted ordinary user input."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, cast

from nanobot.bus.events import InboundMessage
from nanobot.runtime_context import (
    RUNTIME_CONTEXT_HISTORY_META,
    WEBUI_QUOTE_SOURCE,
    public_history_message,
)
from nanobot.session.display_history import HistoryFact, HistoryReader
from nanobot.session.manager import Session


class HistoryEditError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def ordinary_text_error(message: dict[str, Any]) -> str | None:
    if message.get("role") != "user" or any(message.get(key) for key in (
        "_hidden_history", "_command", "session_message", "injected_event", "source", "automation",
        "automation_id", "cron_job_id", "_automation_turn", "_user_shell",
    )):
        return "edit_special_message"
    if any(message.get(key) for key in ("media", "media_paths", "media_urls")):
        return "edit_attachments_unsupported"
    if any(message.get(key) for key in ("cli_apps", "mcp_presets", "session_mentions")):
        return "edit_mentions_unsupported"
    text = public_history_message(message).get("content")
    if not isinstance(text, str) or not text.strip():
        return "edit_plain_text_only"
    context = message.get(RUNTIME_CONTEXT_HISTORY_META)
    sources: list[str] = cast(dict[str, Any], context).get("sources", []) if isinstance(context, dict) else []
    if WEBUI_QUOTE_SOURCE in sources or text.startswith("> [!QUOTE]"):
        return "edit_context_unsupported"
    if any(source in sources for source in ("session_mentions", "cli_apps", "mcp_presets")):
        return "edit_mentions_unsupported"
    if "session_message" in sources:
        return "edit_special_message"
    if text.lstrip().startswith(("/", "!")):
        return "edit_commands_unsupported"
    if re.search(r"(^|\s)@[\w-]+", text):
        return "edit_mentions_unsupported"
    return None


@dataclass(frozen=True)
class HistoryEditSource:
    revision: str
    message_id: str
    turn_id: str | None


@dataclass(frozen=True)
class HistoryEditTarget:
    model_position: int
    turn_ordinal: int
    position: int
    input: HistoryFact


# Resolve client identity against both histories inside the owner's transaction.
HistoryEditProjection = Callable[[Session, HistoryReader], HistoryEditTarget]
HistoryEditAccepted = Callable[[Session], Awaitable[None]]
HistoryEditSubmit = Callable[
    [InboundMessage, HistoryEditSource, HistoryEditProjection, HistoryEditAccepted], Awaitable[Session]
]
