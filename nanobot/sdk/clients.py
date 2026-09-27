"""Small convenience clients exposed by the high-level Python SDK."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Mapping
from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nanobot.bus.runtime_events import SessionTurnPersisted
from nanobot.runtime_context import RUNTIME_CONTEXT_HISTORY_META, RuntimeContextProvider
from nanobot.sdk.types import (
    SessionInfo,
    SessionSnapshot,
    snapshot_from_session,
)

if TYPE_CHECKING:
    from nanobot.agent.loop import AgentLoop


class SessionClient:
    """Asynchronous operations over committed session state."""

    _RESERVED_MESSAGE_KEYS = {"role", "content", RUNTIME_CONTEXT_HISTORY_META}

    def __init__(self, loop: AgentLoop) -> None:
        self._loop = loop
        self._state = loop.sessions.state

    async def ingest(
        self, session_key: str, messages: Iterable[Mapping[str, Any]], *,
        metadata: Mapping[str, Any] | None = None, source: str | None = None,
    ) -> SessionSnapshot:
        """Validate and durably import a transcript as one operation."""
        prepared: list[dict[str, Any]] = []
        for raw in messages:
            if "role" not in raw or "content" not in raw:
                raise ValueError("ingested messages must include role and content")
            message = {
                key: deepcopy(value) for key, value in raw.items()
                if key != RUNTIME_CONTEXT_HISTORY_META
            }
            message["role"] = str(raw["role"]).strip()
            if source is not None:
                message.setdefault("source", source)
            prepared.append(message)
        session = await self._state.import_messages(session_key, prepared, metadata=metadata)
        return snapshot_from_session(session)

    async def get(self, session_key: str) -> SessionSnapshot | None:
        """Return a detached display-safe view of committed state."""
        session = await self._state.read(session_key)
        return snapshot_from_session(session) if session is not None else None

    async def list(self) -> list[SessionInfo]:
        return [
            SessionInfo(
                key=str(row.get("key") or ""),
                created_at=row.get("created_at"), updated_at=row.get("updated_at"),
                title=str(row.get("title") or ""), preview=str(row.get("preview") or ""),
                path=row.get("path"),
            )
            for row in await self._state.list_sessions()
        ]

    async def export(self, session_key: str) -> SessionSnapshot | None:
        """Return a trusted detached snapshot including model-only context."""
        session = await self._state.read(session_key)
        return (
            snapshot_from_session(session, include_runtime_context=True)
            if session is not None else None
        )

    async def restore(
        self, snapshot: SessionSnapshot, *, session_key: str | None = None,
    ) -> SessionSnapshot:
        """Atomically restore a trusted snapshot into an empty session."""
        key = session_key or snapshot.key
        if not key:
            raise ValueError("restored snapshots must include a session key")
        session = await self._state.import_messages(
            key, snapshot.messages, metadata=snapshot.metadata, require_empty=True,
        )
        return snapshot_from_session(session)

    async def clear(self, session_key: str) -> SessionSnapshot:
        """Reset state and invalidate results from an older execution."""
        await self._state.reset(session_key)
        self._loop.discard_session_file_state(session_key)
        return snapshot_from_session(await self._state.get(session_key))

    async def delete(self, session_key: str) -> bool:
        return await self._state.delete(session_key)


class MemoryClient:
    """Long-term memory helpers exposed through ``bot.memory``."""

    def __init__(self, loop: AgentLoop) -> None:
        self._loop = loop

    def read(self) -> str:
        """Read ``memory/MEMORY.md``."""
        return self._loop.context.memory.read_memory()

    def write(self, text: str) -> None:
        """Overwrite ``memory/MEMORY.md``."""
        self._loop.context.memory.write_memory(text)

    def append_history(self, text: str, *, session_key: str | None = None) -> int:
        """Append one entry to ``memory/history.jsonl`` and return its cursor."""
        return self._loop.context.memory.append_history(text, session_key=session_key)

    def read_history(self, *, session_key: str | None = None) -> list[dict[str, Any]]:
        """Read memory history entries, optionally filtered by session."""
        entries = self._loop.context.memory.read_unprocessed_history(since_cursor=0)
        if session_key is not None:
            entries = [entry for entry in entries if entry.get("session_key") == session_key]
        return deepcopy(entries)


class RuntimeClient:
    """Runtime control helpers exposed through ``bot.runtime``."""

    def __init__(self, loop: AgentLoop) -> None:
        self._loop = loop

    @property
    def model(self) -> str:
        """Current runtime model name."""
        return self._loop.model

    @property
    def workspace(self) -> Path:
        """Current runtime workspace."""
        return self._loop.workspace

    def add_context_provider(
        self,
        provider: RuntimeContextProvider,
    ) -> Callable[[], None]:
        """Register per-turn model context and return an unsubscribe callback."""
        return self._loop.register_runtime_context_provider(provider)

    def on_session_turn_persisted(
        self,
        handler: Callable[[SessionTurnPersisted], Awaitable[None] | None],
    ) -> Callable[[], None]:
        """Register a persisted-turn callback and return an unsubscribe callback."""
        return self._loop.bus.subscribe(handler, SessionTurnPersisted)

    async def compact_session(self, session_key: str) -> SessionSnapshot:
        """Summarize one session and exclude its archived messages from replay."""
        session = await self._loop.sessions.state.get(session_key)
        runtime = await self._loop.runtime_for_session(session)
        await self._loop.consolidator.compact_idle_session(
            session_key,
            runtime=runtime,
        )
        return snapshot_from_session(
            await self._loop.sessions.state.get(session_key)
        )

    async def compact_idle_session(self, session_key: str, *, max_suffix: int = 0) -> str | None:
        """Return a replacement summary; legacy ``max_suffix`` no longer retains history."""
        session = await self._loop.sessions.state.get(session_key)
        runtime = await self._loop.runtime_for_session(session)
        return await self._loop.consolidator.compact_idle_session(
            session_key,
            runtime=runtime,
            max_suffix=max_suffix,
        )
