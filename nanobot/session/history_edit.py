"""Validated, version-bound edits of a persisted ordinary user input."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Awaitable, Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any

from nanobot.bus.events import InboundMessage
from nanobot.runtime_context import (
    RUNTIME_CONTEXT_HISTORY_META,
    WEBUI_QUOTE_SOURCE,
    public_history_message,
)
from nanobot.session.manager import Session, history_prefix_boundary


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
    sources = context.get("sources", []) if isinstance(context, dict) else []
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


def message_digest(message: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(
        message, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str,
    ).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class HistoryEditAnchor:
    generation: str
    revision: int
    user_index: int
    message_digest: str

    def locate(self, session: Session) -> int:
        if (session.generation, session.revision) != (self.generation, self.revision):
            raise HistoryEditError("edit_source_changed")
        boundary = history_prefix_boundary(session, self.user_index)
        if boundary is None or boundary == len(session.messages):
            raise HistoryEditError("edit_source_changed")
        message = session.messages[boundary]
        if message_digest(message) != self.message_digest:
            raise HistoryEditError("edit_source_changed")
        if reason := ordinary_text_error(message):
            raise HistoryEditError(reason)
        return boundary


# The adapter prepares a rollback-capable display projection under the same
# owner transaction. Core never imports a channel's storage or wire format.
HistoryEditProjection = Callable[[Session], AbstractContextManager[None]]

HistoryEditAccepted = Callable[[Session], Awaitable[None]]
HistoryEditSubmit = Callable[
    [InboundMessage, HistoryEditAnchor, HistoryEditProjection, HistoryEditAccepted], Awaitable[Session]
]
