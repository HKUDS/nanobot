from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable, Iterator, Mapping
from concurrent.futures import CancelledError
from dataclasses import dataclass, field
from typing import Any, TypedDict, TypeVar, cast

from nanobot.runtime_context import public_history_message
from nanobot.session.history_visibility import is_hidden_history_message
from nanobot.session.manager import SessionHistoryPayload, SessionManager, metadata_title
from nanobot.session.session_handles import SESSION_HANDLE_METADATA_KEY, normalize_session_handle

_T = TypeVar("_T")


class SessionMessage(TypedDict):
    message_index: int
    role: str
    timestamp: str | int | None
    content: str


class SessionMatch(TypedDict):
    session_key: str
    generation: str
    title: str
    updated_at: str | None
    messages: list[SessionMessage]


def _check_cancelled(cancelled: threading.Event | None) -> None:
    if cancelled is not None and cancelled.is_set():
        raise CancelledError()


async def _run_cancellable(operation: Callable[[threading.Event], _T]) -> _T:
    """Cancel queued work immediately; drain a started transaction before returning."""
    cancelled = threading.Event()
    start_lock = threading.Lock()
    started = False

    def run() -> _T:
        nonlocal started
        # Cancellation and entry into the operation have one atomic ownership
        # handoff. A dequeued worker may not touch the database after cancellation.
        with start_lock:
            if cancelled.is_set():
                raise CancelledError()
            started = True
        return operation(cancelled)

    worker = asyncio.create_task(asyncio.to_thread(run))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError as cancellation:
        with start_lock:
            cancelled.set()
            drain = started
        if not drain:
            worker.cancel()
            raise
        while not worker.done():
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                # Repeated caller cancellation must not orphan an active reader.
                continue
            except BaseException:
                break
        try:
            worker.result()
        except (CancelledError, asyncio.CancelledError):
            pass
        except BaseException as exc:
            # Preserve unexpected worker failures while cancellation still wins.
            raise cancellation from exc
        raise


def _text(value: object) -> str:
    return value.strip()[:160] if isinstance(value, str) else ""


def _title_rank(title: str, needle: str) -> int | None:
    folded = title.casefold()
    return (
        0 if folded == needle
        else 1 if folded.startswith(needle)
        else 2 if needle in folded
        else None
    )


def _handle_name(raw: object) -> str | None:
    if not isinstance(raw, str):
        return None
    try:
        return normalize_session_handle(raw)
    except ValueError:
        return None


def _message_text(message: Mapping[str, Any], cancelled: threading.Event | None) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for raw_block in cast(list[object], content):
        _check_cancelled(cancelled)
        if not isinstance(raw_block, dict):
            continue
        block = cast(dict[object, object], raw_block)
        text = block.get("text")
        if block.get("type") == "text" and isinstance(text, str):
            parts.append(text)
    return "\n".join(parts).strip()


def _matching_messages(
    messages: Iterator[tuple[int, dict[str, Any]]], *, needle: str, limit: int,
    cancelled: threading.Event | None,
) -> list[SessionMessage]:
    matches: list[SessionMessage] = []
    for index, message in messages:
        _check_cancelled(cancelled)
        role = message.get("role")
        if role not in {"user", "assistant"} or message.get("_command") or is_hidden_history_message(message):
            continue
        public = public_history_message(message)
        text = _message_text(public, cancelled)
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


@dataclass
class _SearchCursor:
    """Detached header ranking and progress; never owns a database snapshot."""

    query: str
    exclude_session_key: str | None
    initialized: bool = False
    ranked: list[tuple[int, int, SessionMatch]] = field(default_factory=list)
    remaining: list[tuple[int, str]] = field(default_factory=list)
    ranked_offset: int = 0
    remaining_offset: int = 0
    ordering: dict[str, tuple[int, int]] = field(default_factory=dict)

    @property
    def exhausted(self) -> bool:
        return (
            self.initialized
            and self.ranked_offset == len(self.ranked)
            and self.remaining_offset == len(self.remaining)
        )

    def order(self, matches: list[SessionMatch]) -> list[SessionMatch]:
        # Retain only the bounded candidates currently under consideration.
        self.ordering = {match["session_key"]: self.ordering[match["session_key"]] for match in matches}
        return sorted(matches, key=lambda match: self.ordering[match["session_key"]])


class SessionHistoryReader:
    """Search full persisted history, including messages before summary checkpoints."""

    def __init__(self, sessions: SessionManager) -> None:
        self._sessions = sessions

    def search_cursor(self, query: str, *, exclude_session_key: str | None = None) -> _SearchCursor:
        return _SearchCursor(query, exclude_session_key)

    async def asearch(
        self, query: str, limit: int, *, exclude_session_key: str | None = None,
        _cursor: _SearchCursor | None = None,
    ) -> list[SessionMatch]:
        return await _run_cancellable(lambda cancelled: self.search(
            query, limit, exclude_session_key=exclude_session_key, cancelled=cancelled, _cursor=_cursor,
        ))

    def search(
        self,
        query: str,
        limit: int,
        *,
        exclude_session_key: str | None = None,
        cancelled: threading.Event | None = None,
        _cursor: _SearchCursor | None = None,
    ) -> list[SessionMatch]:
        cursor = _cursor or self.search_cursor(query, exclude_session_key=exclude_session_key)
        return self._sessions.read_batch(lambda: self._search(cursor, limit, cancelled))

    def _search(
        self, cursor: _SearchCursor, limit: int, cancelled: threading.Event | None,
    ) -> list[SessionMatch]:
        needle = cursor.query.casefold()

        def headers() -> None:
            # Keep ranking, title and visibility together, but don't hold this
            # cross-session snapshot while searching potentially long histories.
            for position, row in enumerate(self._sessions.list_sessions()):
                _check_cancelled(cancelled)
                key = row.get("key")
                if not isinstance(key, str) or key == cursor.exclude_session_key:
                    continue
                payload = self._sessions.read_history_header(key)
                if payload is None:
                    continue
                if not self._sessions.types.public_history(payload["metadata"]):
                    continue
                title = _text(row.get("title"))
                rank = _title_rank(title, needle)
                if rank is None:
                    cursor.remaining.append((position, key))
                    continue
                updated = row.get("updated_at")
                cursor.ranked.append((rank, position, {
                    "session_key": key,
                    "generation": payload["generation"],
                    "title": title,
                    "updated_at": updated if isinstance(updated, str) else None,
                    "messages": [],
                }))

        if not cursor.initialized:
            self._sessions.read_consistently(headers, cancelled=cancelled)
            cursor.ranked.sort(key=lambda item: (item[0], item[1]))
            cursor.initialized = True

        matches: list[SessionMatch] = []
        while len(matches) < limit and cursor.ranked_offset < len(cursor.ranked):
            _check_cancelled(cancelled)
            rank, position, match = cursor.ranked[cursor.ranked_offset]
            cursor.ranked_offset += 1
            cursor.ordering[match["session_key"]] = (rank, position)
            matches.append(match)
        while len(matches) < limit and cursor.remaining_offset < len(cursor.remaining):
            _check_cancelled(cancelled)
            position, key = cursor.remaining[cursor.remaining_offset]
            cursor.remaining_offset += 1
            # Re-read title, visibility, generation and messages together. A
            # header captured before a reset or privacy change cannot be reused.
            match = self.read(key, query=cursor.query, limit=2, cancelled=cancelled, _for_search=True)
            if match is None:
                continue
            rank = _title_rank(match["title"], needle)
            if rank is not None:
                match["messages"] = []
            elif match["messages"]:
                match["title"] = match["title"] or _text(match["messages"][0]["content"])
                rank = 3
            else:
                continue
            cursor.ordering[key] = (rank, position)
            matches.append(match)
        return sorted(matches, key=lambda match: cursor.ordering[match["session_key"]])

    async def acomplete_search(
        self, cursor: _SearchCursor, matches: list[SessionMatch], handles: Mapping[str, str], limit: int,
    ) -> list[tuple[SessionMatch, str | None]]:
        return await _run_cancellable(lambda cancelled: self._sessions.read_batch(
            lambda: self._complete_search(cursor, matches, handles, limit, cancelled),
        ))

    def _complete_search(
        self, cursor: _SearchCursor, matches: list[SessionMatch], handles: Mapping[str, str],
        limit: int, cancelled: threading.Event,
    ) -> list[tuple[SessionMatch, str | None]]:
        while True:
            _check_cancelled(cancelled)
            # Only the final validation needs the workspace-wide ambiguity scan.
            # It also rechecks every retained generation in the same snapshot.
            minimum = 0 if cursor.exhausted else limit
            valid = self._validate(matches, handles, cancelled, conflict_minimum=minimum)
            if len(valid) >= limit or cursor.exhausted:
                return valid
            retained = [match for match, _ in valid]
            more = self._search(cursor, limit - len(retained), cancelled)
            matches = cursor.order(retained + more)

    async def aread(
        self, session_key: str, *, query: str, limit: int,
        exclude_session_key: str | None = None,
    ) -> SessionMatch | None:
        return await _run_cancellable(lambda cancelled: self.read(
            session_key, query=query, limit=limit, exclude_session_key=exclude_session_key, cancelled=cancelled,
        ))

    def read(
        self,
        session_key: str,
        *,
        query: str,
        limit: int,
        exclude_session_key: str | None = None,
        cancelled: threading.Event | None = None,
        _for_search: bool = False,
    ) -> SessionMatch | None:
        if session_key == exclude_session_key:
            return None

        def project(
            payload: SessionHistoryPayload, messages: Iterator[tuple[int, dict[str, Any]]],
        ) -> SessionMatch | None:
            _check_cancelled(cancelled)
            metadata = payload["metadata"]
            if not self._sessions.types.public_history(metadata):
                return None
            updated = payload.get("updated_at")
            return {
                "session_key": session_key,
                "generation": payload["generation"],
                "title": _text(metadata_title(metadata) if _for_search else metadata.get("title")),
                "updated_at": updated if isinstance(updated, str) else None,
                "messages": _matching_messages(
                    messages, needle=query.casefold(), limit=limit, cancelled=cancelled,
                ),
            }

        return self._sessions.read_consistently(
            lambda: self._sessions.project_session_messages(session_key, project), cancelled=cancelled,
        )

    async def avalidate(
        self, matches: list[SessionMatch], handles: Mapping[str, str],
    ) -> list[tuple[SessionMatch, str | None]]:
        return await _run_cancellable(lambda cancelled: self._validate(matches, handles, cancelled))

    def _validate(
        self, matches: list[SessionMatch], handles: Mapping[str, str], cancelled: threading.Event,
        *, conflict_minimum: int = 0,
    ) -> list[tuple[SessionMatch, str | None]]:
        def validate() -> list[tuple[SessionMatch, str | None]]:
            valid: list[tuple[SessionMatch, str | None]] = []
            for match in matches:
                _check_cancelled(cancelled)
                key = match["session_key"]
                payload = self._sessions.read_history_header(key)
                if payload is None or payload["generation"] != match["generation"]:
                    continue
                metadata = payload["metadata"]
                if not self._sessions.types.public_history(metadata):
                    continue
                handle = handles.get(key)
                if (
                    not self._sessions.types.needs_handle(metadata)
                    or _handle_name(metadata.get(SESSION_HANDLE_METADATA_KEY)) != handle
                ):
                    handle = None
                valid.append((match, handle))

            if len(valid) < conflict_minimum:
                return valid
            names = {handle for _, handle in valid if handle is not None}
            if not names:
                return valid

            def conflicts(rows: Iterator[tuple[str, object]]) -> set[str]:
                seen: set[str] = set()
                ambiguous: set[str] = set()
                for key, raw_name in rows:
                    _check_cancelled(cancelled)
                    name = _handle_name(raw_name)
                    if name not in names:
                        continue
                    payload = self._sessions.read_history_header(key)
                    if payload is None or not self._sessions.types.needs_handle(payload["metadata"]):
                        continue
                    if name in seen:
                        ambiguous.add(name)
                    else:
                        seen.add(name)
                return ambiguous

            # Another process may have imported a duplicate name after the
            # resolver snapshot. Do not return a handle that could route away.
            ambiguous = self._sessions.project_session_handle_names(conflicts)
            return [(match, None if handle in ambiguous else handle) for match, handle in valid]

        return self._sessions.read_consistently(validate, cancelled=cancelled)
