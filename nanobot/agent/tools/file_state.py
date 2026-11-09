from __future__ import annotations

import hashlib
from collections import OrderedDict
from collections.abc import Callable, Generator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class _FileReadContext:
    call_id: str
    tool_results: Callable[[], Mapping[str, str]] | None


_current_file_read: ContextVar[_FileReadContext | None] = ContextVar(
    "nanobot_file_read_context", default=None,
)


@contextmanager
def file_read_context(
    call_id: str, tool_results: Callable[[], Mapping[str, str]],
) -> Generator[None]:
    """Bind call-local receipts without indexing results unless a read needs them."""
    context = _FileReadContext(call_id, tool_results)
    token = _current_file_read.set(context)
    try:
        yield
    finally:
        # A tool can spawn a task that inherits this context and outlives the call.
        # It must not retain the model request or use its read receipts afterward.
        context.tool_results = None
        _current_file_read.reset(token)


@dataclass(slots=True)
class ReadState:
    offset: int
    limit: int | None
    content_hash: str
    call_id: str | None
    result_hash: str


class FileStates:
    """Cache read receipts per session; deduplicate only while their results are visible."""

    __slots__ = ("_state",)

    def __init__(self) -> None:
        self._state: dict[str, ReadState] = {}

    def record_read(
        self, path: str | Path, offset: int = 1, limit: int | None = None, *,
        content_hash: str, result: str,
    ) -> None:
        """Record the file snapshot and complete result of a successful text read."""
        p = str(Path(path).resolve())
        context = _current_file_read.get()
        self._state[p] = ReadState(
            offset=offset,
            limit=limit,
            content_hash=content_hash,
            call_id=context.call_id if context is not None and context.tool_results else None,
            result_hash=hashlib.sha256(result.encode("utf-8")).hexdigest(),
        )

    def record_write(self, path: str | Path) -> None:
        """Invalidate a prior read after a write; a write summary is not file content."""
        self._state.pop(str(Path(path).resolve()), None)

    def visible_read_hash(
        self, path: str | Path, offset: int = 1, limit: int | None = None,
    ) -> str | None:
        """Return a matching receipt's hash only while its result is in the model input."""
        p = str(Path(path).resolve())
        entry = self._state.get(p)
        context = _current_file_read.get()
        if entry is None or context is None or context.tool_results is None or not entry.call_id:
            return None
        if entry.offset != offset or entry.limit != limit:
            return None
        result = context.tool_results().get(entry.call_id)
        if result is None or hashlib.sha256(result.encode("utf-8")).hexdigest() != entry.result_hash:
            self._state.pop(p, None)
            return None
        return entry.content_hash

    def get(self, path: str | Path) -> ReadState | None:
        """Return the raw ReadState entry for a path, or None."""
        return self._state.get(str(Path(path).resolve()))

    def clear(self) -> None:
        """Clear all tracked state (useful for testing)."""
        self._state.clear()


class FileStateStore:
    """Bounded lookup table for per-session file read/write state."""

    __slots__ = ("_max_sessions", "_states_by_key")

    def __init__(self, *, max_sessions: int = 128) -> None:
        if max_sessions <= 0:
            raise ValueError("max_sessions must be positive")
        self._max_sessions = max_sessions
        self._states_by_key: OrderedDict[str, FileStates] = OrderedDict()

    def for_session(self, session_key: str | None) -> FileStates:
        key = session_key or "__default__"
        states = self._states_by_key.pop(key, None)
        if states is None:
            states = FileStates()
        self._states_by_key[key] = states
        while len(self._states_by_key) > self._max_sessions:
            self._states_by_key.popitem(last=False)
        return states

    def discard(self, session_key: str | None) -> None:
        """Forget file state when a session is reset or removed."""
        self._states_by_key.pop(session_key or "__default__", None)

    def clear(self) -> None:
        self._states_by_key.clear()


_current_file_states: ContextVar[FileStates | None] = ContextVar(
    "nanobot_file_states",
    default=None,
)


def current_file_states(default: FileStates) -> FileStates:
    """Return the FileStates bound to the current agent task, or a fallback."""
    return _current_file_states.get() or default


def bind_file_states(file_states: FileStates) -> Token[FileStates | None]:
    """Bind file read/write state for the current async task."""
    return _current_file_states.set(file_states)


def reset_file_states(token: Token[FileStates | None]) -> None:
    _current_file_states.reset(token)
