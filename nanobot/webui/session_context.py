"""Read-only projection of the session material available to the agent."""

from __future__ import annotations

from typing import Any, cast

from nanobot.providers.base import LLMUsage
from nanobot.session.manager import Session
from nanobot.utils.helpers import estimate_message_tokens, truncate_text

_SUMMARY_PREVIEW_CHARS = 4_000


def session_context_payload(session: Session) -> dict[str, Any]:
    """Return an explainable view of session replay without building a model prompt.

    The final prompt also contains workspace instructions, memory, skills, and a
    model-specific token budget.  This projection deliberately reports only the
    session-owned part: archived summary plus the replayable raw suffix.
    """
    replay = session.get_history(max_messages=0, include_runtime_context=False)
    raw_summary = session.metadata.get("_last_summary")
    summary = ""
    summary_preview = ""
    summary_at: str | None = None
    if isinstance(raw_summary, dict):
        summary_data = cast(dict[str, object], raw_summary)
        text = summary_data.get("text")
        last_active = summary_data.get("last_active")
        if isinstance(text, str):
            summary = text.strip()
            summary_preview = truncate_text(summary, _SUMMARY_PREVIEW_CHARS)
        if isinstance(last_active, str):
            summary_at = last_active

    replay_tokens = sum(estimate_message_tokens(message) for message in replay)
    summary_tokens = (
        estimate_message_tokens({"role": "system", "content": summary}) if summary else 0
    )
    stored_usage = LLMUsage.from_dict(session.metadata.get("_last_usage"))
    last_usage = stored_usage.to_turn_dict() if stored_usage is not None else None

    return {
        "schema_version": 1,
        "session_key": session.key,
        "total_messages": len(session.messages),
        "archived_messages": min(session.last_archived, len(session.messages)),
        "replay_messages": len(replay),
        "estimated_replay_tokens": replay_tokens,
        "estimated_summary_tokens": summary_tokens,
        "estimated_session_tokens": replay_tokens + summary_tokens,
        "archived_summary": summary_preview or None,
        "archived_summary_at": summary_at,
        "last_usage": last_usage,
    }
