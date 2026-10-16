"""Read searchable conversation text from persisted session records."""

from __future__ import annotations

import sys
from collections.abc import Mapping
from typing import Any, TypedDict, cast

from nanobot.runtime_context import public_history_message
from nanobot.session.history_visibility import is_hidden_history_message
from nanobot.session.manager import SessionManager
from nanobot.session.search_index import SessionSearchIndex


class SessionMessage(TypedDict):
    message_index: int
    role: str
    timestamp: str | int | None
    content: str


class SessionMatch(TypedDict):
    session_key: str
    title: str
    updated_at: str | None
    messages: list[SessionMessage]


def _text(value: object) -> str:
    return value.strip()[:160] if isinstance(value, str) else ""


def _message_text(message: Mapping[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for raw_block in cast(list[object], content):
        if not isinstance(raw_block, dict):
            continue
        block = cast(dict[object, object], raw_block)
        text = block.get("text")
        if block.get("type") == "text" and isinstance(text, str):
            parts.append(text)
    return "\n".join(parts).strip()


def _matching_messages(raw_messages: object, *, needle: str, limit: int) -> list[SessionMessage]:
    if not isinstance(raw_messages, list):
        return []
    messages = cast(list[object], raw_messages)
    matches: list[SessionMessage] = []
    for index in range(len(messages) - 1, -1, -1):
        raw_message = messages[index]
        if not isinstance(raw_message, dict):
            continue
        message = cast(dict[str, Any], raw_message)
        role = message.get("role")
        if role not in {"user", "assistant"} or message.get("_command") or is_hidden_history_message(message):
            continue
        public = public_history_message(message)
        text = _message_text(public)
        if not text or (needle and needle not in text.casefold()):
            continue
        timestamp = public.get("timestamp")
        matches.append({
            "message_index": index,
            "role": cast(str, role),
            "timestamp": timestamp if isinstance(timestamp, (str, int)) else None,
            "content": text,
        })
        if len(matches) == limit:
            break
    matches.reverse()
    return matches


class SessionHistoryReader:
    """Search full persisted history, including messages before summary checkpoints."""

    def __init__(self, sessions: SessionManager) -> None:
        self._sessions = sessions
        self._search_index = SessionSearchIndex(sessions)

    def search(
        self,
        query: str,
        limit: int,
        *,
        exclude_session_key: str | None = None,
    ) -> list[SessionMatch]:
        with self._sessions.locked_session_files():
            ranked, remaining, public_rows = self._candidates(query, exclude_session_key)
        ranked.sort(key=lambda item: item[0])
        if len(ranked) < limit and remaining:
            keys = self._search_index.matching_session_keys(query, public_rows, self._index_content)
            if keys is not None:
                remaining = [row for row in remaining if row["key"] in keys]
        for row in remaining:
            if len(ranked) >= limit:
                break
            match = self.read(cast(str, row["key"]), query=query, limit=2)
            if match is not None and match["messages"]:
                match["title"] = _text(row.get("title")) or _text(match["messages"][0]["content"])
                ranked.append((3, match))
        return [item[1] for item in ranked[:limit]]

    def _candidates(
        self,
        query: str,
        exclude_session_key: str | None,
    ) -> tuple[list[tuple[int, SessionMatch]], list[dict[str, Any]], list[dict[str, Any]]]:
        needle = query.casefold()
        ranked: list[tuple[int, SessionMatch]] = []
        remaining: list[dict[str, Any]] = []
        public_rows: list[dict[str, Any]] = []
        for row in self._sessions.list_sessions():
            key = row.get("key")
            if not isinstance(key, str):
                continue
            payload = self._sessions.read_session_metadata(key)
            if payload is None:
                continue
            raw_metadata = cast(object, payload.get("metadata"))
            metadata = cast(dict[str, Any], raw_metadata) if isinstance(raw_metadata, dict) else {}
            if not self._sessions.types.public_history(metadata):
                continue
            public_rows.append(row)
            if key == exclude_session_key:
                continue
            title = _text(row.get("title"))
            folded = title.casefold()
            rank = (
                0 if folded == needle
                else 1 if folded.startswith(needle)
                else 2 if needle in folded
                else None
            )
            if rank is None:
                remaining.append(row)
                continue
            updated = row.get("updated_at")
            ranked.append((rank, {
                "session_key": key,
                "title": title,
                "updated_at": updated if isinstance(updated, str) else None,
                "messages": [],
            }))

        return ranked, remaining, public_rows

    def _index_content(self, key: str) -> str:
        match = self.read(key, query="", limit=sys.maxsize)
        return "\n".join(message["content"] for message in match["messages"]) if match else ""

    def read(
        self,
        session_key: str,
        *,
        query: str,
        limit: int,
        exclude_session_key: str | None = None,
    ) -> SessionMatch | None:
        if session_key == exclude_session_key:
            return None
        payload = self._sessions.read_session_file(session_key)
        if payload is None:
            return None
        raw_metadata = cast(object, payload.get("metadata"))
        metadata = cast(dict[str, Any], raw_metadata) if isinstance(raw_metadata, dict) else {}
        if not self._sessions.types.public_history(metadata):
            return None
        updated = payload.get("updated_at")
        return {
            "session_key": session_key,
            "title": _text(metadata.get("title")),
            "updated_at": updated if isinstance(updated, str) else None,
            "messages": _matching_messages(payload.get("messages"), needle=query.casefold(), limit=limit),
        }
