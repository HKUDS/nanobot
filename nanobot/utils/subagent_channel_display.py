"""Strip internal subagent inject scaffolding for human-facing channel surfaces.

Persisted subagent announcements mirror ``agent/subagent_announce.md``: header,
full ``Task:`` assignment (model context), ``Result:``, and a trailing model-only
``Summarize…`` instruction. External channels (embedded WebUI, session previews)
should show only the header plus a truncated result body."""

from __future__ import annotations

from typing import Any

# Cap Result section length so WebSocket session replay stays readable; full text
# remains on disk for LLM replay (we only mutate outgoing API copies in websocket).
_SUBAGENT_CHANNEL_RESULT_MAX_CHARS = 800


def scrub_subagent_announce_body(content: str) -> str:
    """Return channel-safe text derived from a full subagent announce blob."""
    stripped = content.replace("\r\n", "\n").strip()
    lines = stripped.splitlines()
    header = ""
    if lines and lines[0].startswith("[Subagent"):
        header = lines[0].strip()

    lower = stripped.lower()
    key = "\nresult:\n"
    ri = lower.find(key)
    if ri == -1:
        key = "\nresult:"
        ri = lower.find(key)
    if ri == -1:
        return header if header else stripped

    after = stripped[ri + len(key) :].lstrip()
    summ_marker = "summarize this naturally"
    si = after.lower().find(summ_marker)
    if si != -1:
        after = after[:si].rstrip()

    body = after.strip()
    limit = _SUBAGENT_CHANNEL_RESULT_MAX_CHARS
    if limit and len(body) > limit:
        body = body[: limit - 1].rstrip() + "…"
    if header and body:
        return f"{header}\n\n{body}"
    return header or body or stripped


def scrub_subagent_messages_for_channel(messages: list[dict[str, Any]]) -> None:
    """Mutate message dicts in place when they carry ``subagent_result`` inject."""
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        if msg.get("injected_event") != "subagent_result":
            continue
        raw = msg.get("content")
        if not isinstance(raw, str) or not raw.strip():
            continue
        msg["content"] = scrub_subagent_announce_body(raw)
