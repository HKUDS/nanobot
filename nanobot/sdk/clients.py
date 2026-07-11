"""Small convenience clients exposed by the high-level Python SDK."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nanobot.runtime_context import RUNTIME_CONTEXT_HISTORY_META
from nanobot.sdk.types import (
    SessionInfo,
    SessionSnapshot,
    snapshot_from_payload,
    snapshot_from_session,
)
from nanobot.session.manager import replay_max_messages_for_context

if TYPE_CHECKING:
    from nanobot.agent.loop import AgentLoop


class SessionClient:
    """Session management helpers exposed through ``bot.sessions``."""

    _RESERVED_MESSAGE_KEYS = {"role", "content", RUNTIME_CONTEXT_HISTORY_META}
    _VALID_ROLES = {"user", "assistant", "tool", "system"}

    def __init__(self, loop: AgentLoop) -> None:
        self._loop = loop

    async def ingest(
        self,
        session_key: str,
        messages: Iterable[Mapping[str, Any]],
        *,
        metadata: Mapping[str, Any] | None = None,
        source: str | None = None,
        save: bool = True,
    ) -> SessionSnapshot:
        """Import an existing transcript without running the model."""
        session = self._loop.sessions.get_or_create(session_key)
        if metadata:
            session.metadata.update(deepcopy(dict(metadata)))

        for raw in messages:
            if "role" not in raw:
                raise ValueError("ingested messages must include a role")
            if "content" not in raw:
                raise ValueError("ingested messages must include content")
            role = str(raw["role"]).strip()
            if role not in self._VALID_ROLES:
                raise ValueError(f"unsupported message role: {role!r}")
            extra = {
                key: deepcopy(value)
                for key, value in raw.items()
                if key not in self._RESERVED_MESSAGE_KEYS
            }
            if source is not None and "source" not in extra:
                extra["source"] = source
            session.add_message(role, deepcopy(raw["content"]), **extra)

        if save:
            self._loop.sessions.save(session)
        return snapshot_from_session(session)

    def get(self, session_key: str) -> SessionSnapshot | None:
        """Return a display-safe snapshot without creating a new session on disk."""
        cached = self._loop.sessions._cache.get(session_key)
        if cached is not None:
            return snapshot_from_session(cached)
        payload = self._loop.sessions.read_session_file(session_key)
        if payload is None:
            return None
        return snapshot_from_payload(payload)

    def list(self) -> list[SessionInfo]:
        """List persisted sessions."""
        return [
            SessionInfo(
                key=str(row.get("key") or ""),
                created_at=row.get("created_at"),
                updated_at=row.get("updated_at"),
                title=str(row.get("title") or ""),
                preview=str(row.get("preview") or ""),
                path=row.get("path"),
            )
            for row in self._loop.sessions.list_sessions()
        ]

    def export(self, session_key: str) -> SessionSnapshot | None:
        """Return a trusted full snapshot, including model-only runtime context."""
        cached = self._loop.sessions._cache.get(session_key)
        if cached is not None:
            return snapshot_from_session(cached, include_runtime_context=True)
        payload = self._loop.sessions.read_session_file(session_key)
        if payload is None:
            return None
        return snapshot_from_payload(payload, include_runtime_context=True)

    async def restore(
        self,
        snapshot: SessionSnapshot,
        *,
        session_key: str | None = None,
        save: bool = True,
    ) -> SessionSnapshot:
        """Restore a trusted snapshot into an empty session."""
        key = session_key or snapshot.key
        if not key:
            raise ValueError("restored snapshots must include a session key")
        session = self._loop.sessions.get_or_create(key)
        if session.messages:
            raise ValueError(f"restore target session is not empty: {key}")

        prepared: list[tuple[str, Any, dict[str, Any]]] = []
        for raw in snapshot.messages:
            if "role" not in raw or "content" not in raw:
                raise ValueError("restored messages must include role and content")
            role = str(raw["role"]).strip()
            if role not in self._VALID_ROLES:
                raise ValueError(f"unsupported message role: {role!r}")
            extra = {
                field: deepcopy(value)
                for field, value in raw.items()
                if field not in {"role", "content"}
            }
            prepared.append((role, deepcopy(raw["content"]), extra))

        session.metadata.update(deepcopy(snapshot.metadata))
        for role, content, extra in prepared:
            session.add_message(role, content, **extra)

        if save:
            self._loop.sessions.save(session)
        return snapshot_from_session(session)

    def clear(self, session_key: str) -> SessionSnapshot:
        """Clear one session and persist the empty session."""
        session = self._loop.sessions.get_or_create(session_key)
        session.clear()
        self._loop.sessions.save(session)
        return snapshot_from_session(session)

    def delete(self, session_key: str) -> bool:
        """Delete one session from disk and cache."""
        return self._loop.sessions.delete_session(session_key)

    def flush(self) -> int:
        """Flush cached sessions to durable storage."""
        return self._loop.sessions.flush_all()


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

    async def compact_session(self, session_key: str) -> SessionSnapshot:
        """Run token/replay-window consolidation for one session."""
        session = self._loop.sessions.get_or_create(session_key)
        runtime = self._loop.llm_runtime()
        await self._loop.consolidator.maybe_consolidate_by_tokens(
            session,
            runtime=runtime,
            replay_max_messages=replay_max_messages_for_context(
                runtime.context_window_tokens
            ),
        )
        return snapshot_from_session(self._loop.sessions.get_or_create(session_key))

    async def compact_idle_session(self, session_key: str, *, max_suffix: int = 8) -> str | None:
        """Run idle-session compaction for one session and return the summary."""
        runtime = self._loop.llm_runtime()
        return await self._loop.consolidator.compact_idle_session(
            session_key,
            runtime=runtime,
            max_suffix=max_suffix,
        )
