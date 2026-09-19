"""Track file reads whose original results may still be in model context."""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from collections.abc import Callable, Generator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class _FileReadContext:
    call_id: str
    tool_results: Callable[[], Mapping[str, str]]


_current_file_read: ContextVar[_FileReadContext | None] = ContextVar(
    "nanobot_file_read_context", default=None,
)


@contextmanager
def file_read_context(
    call_id: str, tool_results: Callable[[], Mapping[str, str]],
) -> Generator[None]:
    """Bind one file read; resolve visible results only when checking a prior read."""
    token = _current_file_read.set(_FileReadContext(call_id, tool_results))
    try:
        yield
    finally:
        _current_file_read.reset(token)


@dataclass(slots=True)
class ReadState:
    offset: int
    limit: int | None
    content_hash: str | None
    call_id: str | None
    result_hash: str | None


def _hash_file(p: str) -> str | None:
    try:
        return hashlib.sha256(Path(p).read_bytes()).hexdigest()
    except OSError:
        return None


class FileStates:
    """Cache read receipts per session; deduplicate only while their results are visible."""

    __slots__ = ("_state",)

    def __init__(self) -> None:
        self._state: dict[str, ReadState] = {}

    def record_read(
        self, path: str | Path, offset: int = 1, limit: int | None = None, *,
        content_hash: str | None = None, result: str | None = None,
    ) -> None:
        """Record the file snapshot and complete result of a successful text read."""
        p = str(Path(path).resolve())
        context = _current_file_read.get()
        self._state[p] = ReadState(
            offset=offset,
            limit=limit,
            content_hash=content_hash if content_hash is not None else _hash_file(p),
            call_id=context.call_id if context is not None else None,
            result_hash=hashlib.sha256(result.encode("utf-8")).hexdigest() if result else None,
        )

    def record_write(self, path: str | Path) -> None:
        """Invalidate a prior read after a write; a write summary is not file content."""
        self._state.pop(str(Path(path).resolve()), None)

    def is_unchanged(
        self, path: str | Path, offset: int = 1, limit: int | None = None, *,
        content_hash: str | None = None,
    ) -> bool:
        """Check both file identity and the original result in the actual model input."""
        p = str(Path(path).resolve())
        entry = self._state.get(p)
        context = _current_file_read.get()
        if entry is None or context is None or not entry.call_id or not entry.result_hash:
            return False
        if entry.offset != offset or entry.limit != limit:
            return False
        result = context.tool_results().get(entry.call_id)
        if result is None or hashlib.sha256(result.encode("utf-8")).hexdigest() != entry.result_hash:
            self._state.pop(p, None)
            return False
        current_hash = content_hash if content_hash is not None else _hash_file(p)
        return current_hash is not None and current_hash == entry.content_hash

    def get(self, path: str | Path) -> ReadState | None:
        """Return the raw ReadState entry for a path, or None."""
        return self._state.get(str(Path(path).resolve()))

    def raw_state(self) -> dict[str, ReadState]:
        """Return the mutable backing map for legacy compatibility."""
        return self._state

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


# Module-level default instance, retained for backward compatibility with
# tests and callers that reach in directly. Per-session callers should hold
# their own FileStates instance instead of touching this one.
_default = FileStates()


def record_read(path: str | Path, offset: int = 1, limit: int | None = None) -> None:
    _default.record_read(path, offset=offset, limit=limit)


def record_write(path: str | Path) -> None:
    _default.record_write(path)


def is_unchanged(path: str | Path, offset: int = 1, limit: int | None = None) -> bool:
    return _default.is_unchanged(path, offset=offset, limit=limit)


def clear() -> None:
    _default.clear()


# Legacy attribute for callers that reached into the module-level dict
# directly (filesystem.py used to do this). Kept as a property-like accessor
# so existing imports keep working.
def __getattr__(name: str):
    if name == "_state":
        return _default.raw_state()
    raise AttributeError(name)
