"""Helpers for bridging SimpleX chats into nanobot's WebSocket channel."""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_PROGRESS_KINDS = frozenset({"progress", "tool_hint"})
_STATE_STEM_RE = re.compile(r"[^A-Za-z0-9_.-]+")


@dataclass(frozen=True)
class SimplexInboundMessage:
    """One received SimpleX text message."""

    chat_item_id: int
    contact_name: str
    text: str
    item_ts: str


def default_simplex_db_path() -> Path:
    """Return the default SimpleX chat database path."""
    return Path.home() / ".simplex" / "simplex_v1_chat.db"


def default_simplex_state_path(name: str) -> Path:
    """Return a stable bridge state path for *name*."""
    stem = _STATE_STEM_RE.sub("-", name.strip()).strip("-") or "default"
    return Path.home() / ".nanobot" / "simplex-bridge" / f"{stem}.json"


def load_last_seen_id(path: Path) -> int | None:
    """Load a persisted chat_item_id watermark."""
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    value = data.get("last_seen_id")
    return value if isinstance(value, int) and value >= 0 else None


def save_last_seen_id(path: Path, last_seen_id: int) -> None:
    """Persist the latest delivered chat_item_id."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"last_seen_id": last_seen_id}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def get_latest_received_item_id(db_path: Path, contact_name: str) -> int:
    """Return the latest received text-message id for *contact_name*."""
    with closing(_connect_readonly(db_path)) as conn:
        row = conn.execute(
            """
            SELECT COALESCE(MAX(ci.chat_item_id), 0) AS last_id
            FROM chat_items AS ci
            JOIN contacts AS c ON c.contact_id = ci.contact_id
            WHERE c.local_display_name = ?
              AND ci.item_sent = 0
              AND ci.item_deleted = 0
              AND ci.msg_content_tag = 'text'
            """,
            (contact_name,),
        ).fetchone()
    assert row is not None
    return int(row["last_id"])


def fetch_received_text_messages(
    db_path: Path,
    contact_name: str,
    *,
    after_id: int,
    limit: int = 100,
) -> list[SimplexInboundMessage]:
    """Fetch received text messages for *contact_name* after *after_id*."""
    with closing(_connect_readonly(db_path)) as conn:
        rows = conn.execute(
            """
            SELECT
                ci.chat_item_id,
                c.local_display_name AS contact_name,
                ci.item_text,
                ci.item_ts
            FROM chat_items AS ci
            JOIN contacts AS c ON c.contact_id = ci.contact_id
            WHERE c.local_display_name = ?
              AND ci.item_sent = 0
              AND ci.item_deleted = 0
              AND ci.msg_content_tag = 'text'
              AND ci.chat_item_id > ?
            ORDER BY ci.chat_item_id ASC
            LIMIT ?
            """,
            (contact_name, after_id, limit),
        ).fetchall()
    return [
        SimplexInboundMessage(
            chat_item_id=int(row["chat_item_id"]),
            contact_name=str(row["contact_name"]),
            text=str(row["item_text"]),
            item_ts=str(row["item_ts"]),
        )
        for row in rows
    ]


def parse_receiver_line(raw: str) -> SimplexInboundMessage:
    """Parse one JSONL line emitted by ``bridge/simplex_receiver.py``."""
    data = json.loads(raw)
    return SimplexInboundMessage(
        chat_item_id=int(data["id"]),
        contact_name=str(data["contact"]),
        text=str(data["text"]),
        item_ts=str(data["timestamp"]),
    )


def extract_simplex_reply_text(payload: dict[str, Any], *, chat_id: str) -> str | None:
    """Return outbound reply text to send into SimpleX, or ``None`` to ignore."""
    if payload.get("event") != "message":
        return None
    if payload.get("chat_id") != chat_id:
        return None
    if payload.get("kind") in _PROGRESS_KINDS:
        return None
    text = payload.get("text")
    if not isinstance(text, str) or not text.strip():
        return None
    return text


def _connect_readonly(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn
