"""Persist outbound message tool calls from heartbeat sessions."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol


class SessionLike(Protocol):
    """Minimal session interface for message logging."""
    messages: list[dict[str, Any]]


class SessionManagerLike(Protocol):
    """Minimal session manager interface for recipient injection."""
    def get_or_create(self, key: str) -> SessionLike: ...
    def save(self, session: SessionLike) -> None: ...


def extract_outbound_messages(
    messages: list[dict[str, Any]],
    task_name: str,
    since_idx: int = 0,
) -> list[dict[str, str]]:
    """Extract outbound message tool calls from session messages.

    Returns a list of dicts with timestamp, task, channel, chat_id, content.
    """
    results = []
    for msg in messages[since_idx:]:
        for tc in msg.get("tool_calls", []):
            if tc.get("function", {}).get("name") != "message":
                continue
            try:
                args = json.loads(tc["function"].get("arguments", "{}"))
            except (json.JSONDecodeError, TypeError):
                continue

            results.append({
                "timestamp": msg.get("timestamp", datetime.now().isoformat()),
                "task": task_name,
                "channel": args.get("channel", ""),
                "chat_id": args.get("chat_id", ""),
                "content": args.get("content", ""),
            })
    return results


def write_message_log(log_path: Path, entries: list[dict[str, str]]) -> None:
    """Append message entries to the JSONL log file."""
    if not entries:
        return
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def inject_into_recipient_sessions(
    entries: list[dict[str, str]],
    sessions: SessionManagerLike,
) -> None:
    """Inject outbound messages into recipient sessions."""
    for entry in entries:
        ch = entry.get("channel", "")
        cid = entry.get("chat_id", "")
        if not ch or not cid:
            continue
        recipient_key = f"{ch}:{cid}"
        recipient_session = sessions.get_or_create(recipient_key)
        recipient_session.messages.append({
            "role": "assistant",
            "content": entry.get("content", ""),
            "timestamp": entry.get("timestamp", ""),
            "_source": "heartbeat",
            "_task": entry.get("task", ""),
        })
        sessions.save(recipient_session)


def persist_outbound_messages(
    session: SessionLike,
    task_name: str,
    log_path: Path,
    sessions: SessionManagerLike,
    since_idx: int = 0,
) -> list[dict[str, str]]:
    """Extract, log, and inject outbound messages. Returns extracted entries."""
    entries = extract_outbound_messages(session.messages, task_name, since_idx)
    write_message_log(log_path, entries)
    inject_into_recipient_sessions(entries, sessions)
    return entries
