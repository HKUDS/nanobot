from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, TypedDict, cast

from nanobot.session.history_visibility import is_hidden_history_message

SUMMARY_CONTINUATION_TEXT = (
    "Continue the active task from the working-memory checkpoint above."
)

def is_empty_summary(text: str) -> bool:
    return text.strip() in ("(nothing)", "`(nothing)`")


_THINKING_PREFIX_REWRITTEN = "thinking_prefix_rewritten"


def mark_checkpoint_thinking(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Identify blocks carried across a prefix rewrite without changing the source transcript."""
    return [
        {**msg, "_meta": {**msg.get("_meta", {}), _THINKING_PREFIX_REWRITTEN: True}}
        if msg.get("thinking_blocks") else msg
        for msg in messages
    ]


def has_checkpoint_thinking(message: dict[str, Any]) -> bool:
    meta = message.get("_meta")
    return isinstance(meta, dict) and cast(dict[str, object], meta).get(_THINKING_PREFIX_REWRITTEN) is True


def is_summary_checkpoint(message: Mapping[str, Any]) -> bool:
    """Identify the durable boundary of a replacement summary."""
    return (
        is_hidden_history_message(message)
        and message.get("content") == SUMMARY_CONTINUATION_TEXT
    )


class SessionSummary(TypedDict):
    text: str
    last_active: str


@dataclass(frozen=True, slots=True)
class SessionSummaryCheckpoint:
    """A replacement summary and the raw transcript boundary it covers."""

    summary: str
    transcript_boundary: int


def session_summary_from_metadata(
    metadata: Mapping[str, object] | None,
    *,
    fallback_last_active: datetime,
) -> SessionSummary | None:
    raw: object = metadata.get("_last_summary") if metadata is not None else None
    if not isinstance(raw, Mapping):
        return None
    summary_data = cast(Mapping[str, object], raw)
    text = summary_data.get("text")
    if not isinstance(text, str) or not text:
        return None
    raw_last_active = summary_data.get("last_active")
    if isinstance(raw_last_active, str):
        try:
            datetime.fromisoformat(raw_last_active)
            last_active = raw_last_active
        except ValueError:
            last_active = fallback_last_active.isoformat()
    else:
        last_active = fallback_last_active.isoformat()
    return {"text": text, "last_active": last_active}
