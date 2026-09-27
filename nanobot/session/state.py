"""Ordered session operations with detached reads and durable acknowledgements."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import fields, replace
from datetime import datetime
from typing import Any, TypeVar, cast

from nanobot.bus.events import InboundMessage
from nanobot.session.keys import is_dream_session
from nanobot.session.manager import Session, SessionPolicy, fork_session
from nanobot.session.sqlite_store import SessionConflictError, SqliteSessionStore
from nanobot.utils.cancellation import shield_and_drain

_T = TypeVar("_T")
_PENDING_KEY = "pending_user_turn"
_CHECKPOINT_KEY = "runtime_checkpoint"
_RESERVED_KEYS = frozenset({_PENDING_KEY, _CHECKPOINT_KEY, "pending_user_followups"})


class SessionState:
    """Own session mutations and their storage boundary.

    Operations load and change private state under the store transaction lock.
    Only detached reads leave this boundary. Model calls, tool execution, and
    event publication must happen outside these short operations.
    """

    def __init__(
        self, store: SqliteSessionStore, *, capacity: int = 32,
        on_delete: Callable[[str], None] | None = None,
    ) -> None:
        if capacity < 1:
            raise ValueError("session operation capacity must be positive")
        self._store = store
        self._transaction = store.transaction
        self._on_delete = on_delete
        self._snapshots: dict[str, Session] = {}
        self._transients: dict[str, Session] = {}
        self._policies: dict[str, SessionPolicy] = {}
        self._slots = asyncio.Semaphore(capacity)
        self._pending: set[asyncio.Task[Any]] = set()
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="session-store")
        self._closed = False
        self._close_task: asyncio.Task[None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def _bind_loop(self) -> None:
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        elif self._loop is not loop:
            raise RuntimeError("session state belongs to a different event loop")

    async def _execute(self, key: str, operation: Callable[[], _T]) -> _T:
        self._bind_loop()
        if self._closed:
            raise RuntimeError("session state is closed")
        await self._slots.acquire()
        if self._closed:
            self._slots.release()
            raise RuntimeError("session state is closed")

        async def run() -> _T:
            def work() -> _T:
                self._store.retain_worker_connection()
                return operation()
            try:
                return await asyncio.get_running_loop().run_in_executor(self._worker, work)
            finally:
                self._slots.release()

        task = asyncio.create_task(run())
        self._pending.add(task)
        try:
            return await shield_and_drain(task)
        finally:
            self._pending.discard(task)

    async def aclose(self) -> None:
        """Reject new operations and wait for all accepted operations to settle."""
        self._bind_loop()
        self._closed = True

        async def close() -> None:
            try:
                if self._pending:
                    await asyncio.gather(*self._pending, return_exceptions=True)
                await asyncio.get_running_loop().run_in_executor(
                    self._worker, self._store.close_worker_connection,
                )
            finally:
                self._worker.shutdown(wait=False)

        if self._close_task is None:
            self._close_task = asyncio.create_task(close())
        await shield_and_drain(self._close_task)

    def _change(
        self, key: str, change: Callable[[Session], _T], *, history: bool = True,
    ) -> _T:
        # Hold the cross-process lock across read/modify/write, not just the write.
        # No live cache can expose uncommitted changes if validation or I/O fails.
        with self._transaction():
            session = self._load(key, history=history) or Session(key=key)
            before = list(session.messages)
            result = change(session)
            if not history and session.persisted and session.policy.persist:
                self._store.replace_metadata(key, session.metadata, updated_at=session.updated_at)
                session.revision += 1
            else:
                self._commit(session, message_start=self._changed_start(before, session.messages))
                history = True
        self._publish(session, history=history)
        if isinstance(result, Session):
            # Only import returns a session; it must not expose the committed records.
            return cast(_T, self._draft(result))
        return result

    @staticmethod
    def _working(session: Session) -> Session:
        """Copy mutable headers and the list, sharing only owner-private message records."""
        return replace(session, _baseline=None, messages=list(session.messages),
                       metadata=deepcopy(session.metadata), provider_state=deepcopy(session.provider_state))

    def _load(self, key: str, *, history: bool = True) -> Session | None:
        transient = self._transients.get(key)
        if transient is not None:
            return self._working(transient)
        with self._transaction(write=False):
            session = self._store.load(key, history=False)
            if session is not None and history:
                cached = self._snapshots.get(key)
                if cached is not None and (cached.revision, cached.generation) == (session.revision, session.generation):
                    session = replace(session, messages=list(cached.messages))
                else:
                    session = self._store.load(key)
        if session is not None and key in self._policies:
            session.policy = self._policies[key]
        return session

    @staticmethod
    def _changed_start(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> int:
        return next((i for i, (old, new) in enumerate(zip(before, after)) if old != new),
                    min(len(before), len(after)))

    @staticmethod
    def _copy_changed_messages(
        source: list[dict[str, Any]], owned: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Reuse this owner's unchanged records and detach replacements from the source."""
        return [owned[i] if i < len(owned) and message == owned[i] else deepcopy(message)
                for i, message in enumerate(source)]

    def _commit(self, session: Session, *, message_start: int = 0) -> None:
        raw = replace(session, _baseline=None)
        if session.policy.persist:
            self._store.save(raw, message_start=message_start)
            session.revision = raw.revision
            session.persisted = raw.persisted
        else:
            self._transients[session.key] = self._working(raw)

    def _publish(self, session: Session, *, history: bool = True) -> None:
        """Publish owner-private records only after the enclosing transaction committed."""
        if not history:
            cached = self._snapshots.get(session.key)
            if cached is None or (cached.revision + 1, cached.generation) != (session.revision, session.generation):
                self._snapshots.pop(session.key, None)
                return
            session = replace(session, messages=cached.messages)
        self._snapshots[session.key] = self._working(session)
        if len(self._snapshots) > 128:
            self._snapshots.pop(next(iter(self._snapshots)))

    @staticmethod
    def _draft(
        session: Session, *, present: bool = True, previous: Session | None = None,
    ) -> Session:
        raw = replace(session, _baseline=None)
        if previous is None:
            draft = deepcopy(raw)
        else:
            # Retain records already owned by this caller; copy only merged changes.
            messages = SessionState._copy_changed_messages(raw.messages, previous.messages)
            draft = replace(raw, messages=messages, metadata=deepcopy(raw.metadata),
                            provider_state=deepcopy(raw.provider_state))
        draft._baseline = raw  # pyright: ignore[reportPrivateUsage]
        draft.persisted = present
        return draft

    def peek(self, key: str) -> Session | None:
        """Return a detached committed view without storage I/O."""
        session = self._transients.get(key) or self._snapshots.get(key)
        return self._draft(session) if session is not None else None

    async def set_policy(self, key: str, policy: SessionPolicy) -> None:
        """Configure runtime privacy and tools for an existing durable session."""
        if not policy.persist:
            raise ValueError("use register_transient for non-persistent sessions")

        def configure() -> None:
            session = self._load(key)
            if session is None or not session.policy.persist:
                raise ValueError("policy requires an existing durable session")
            self._policies[key] = policy
            session.policy = policy
            self._publish(session)

        await self._execute(key, configure)

    def register_transient(
        self, key: str, *, disabled_tools: frozenset[str] = frozenset(),
    ) -> Session:
        """Create an owner-held non-persistent session for a temporary conversation."""
        session = Session(key=key, policy=SessionPolicy(
            persist=False, log_content=False, disabled_tools=disabled_tools,
        ))
        self._transients[key] = session
        return self._draft(session)

    async def read(self, key: str) -> Session | None:
        """Return a detached view of committed state; edits do not write through."""
        def read() -> Session | None:
            session = self._load(key)
            if session is None:
                return None
            self._publish(session)
            return self._draft(session)
        return await self._execute(key, read)

    async def get(self, key: str) -> Session:
        def get() -> Session:
            with self._transaction():
                session = self._load(key)
                if session is None:
                    session = Session(key=key)
                    self._commit(session)
            self._publish(session)
            return self._draft(session)
        return await self._execute(key, get)

    @staticmethod
    def _refresh(draft: Session, fresh: Session) -> None:
        for item in fields(Session):
            setattr(draft, item.name, getattr(fresh, item.name))

    def _apply_turn(self, draft: Session) -> tuple[Session, int]:
        baseline = draft._baseline  # pyright: ignore[reportPrivateUsage]
        if baseline is None:
            raise ValueError("session changes require an owner-issued draft")
        loaded = self._load(draft.key)
        if (draft.persisted or not draft.policy.persist) and loaded is None:
            raise SessionConflictError("session was deleted")
        current = loaded or Session(key=draft.key, created_at=baseline.created_at, generation=baseline.generation)
        before_messages = current.messages
        if loaded is not None and (
            current.generation != baseline.generation
        ):
            raise SessionConflictError("session was reset")
        for key in baseline.metadata.keys() | draft.metadata.keys():
            missing = object()
            before = baseline.metadata.get(key, missing)
            after = draft.metadata.get(key, missing)
            if before == after:
                continue
            existing = current.metadata.get(key, missing)
            if key == "pending_user_followups":
                old_records = cast(list[dict[str, Any]], before) if isinstance(before, list) else []
                new_records = cast(list[dict[str, Any]], after) if isinstance(after, list) else []
                removed_ids = {item["id"] for item in old_records} - {item["id"] for item in new_records}
                from nanobot.session.recovery import acknowledge_pending_followups

                acknowledge_pending_followups(current, removed_ids)
                continue
            if existing != before and existing != after:
                raise SessionConflictError(f"turn metadata changed: {key}")
            if after is missing:
                current.metadata.pop(key, None)
            else:
                current.metadata[key] = deepcopy(after)
        if draft.messages != baseline.messages:
            if current.messages == baseline.messages:
                current.messages = self._copy_changed_messages(draft.messages, before_messages)
            elif (
                draft.messages[:len(baseline.messages)] == baseline.messages
                and current.messages[:len(baseline.messages)] == baseline.messages
            ):
                current.messages = current.messages + deepcopy(draft.messages[len(baseline.messages):])
            else:
                raise SessionConflictError("session history changed")
        for name in ("last_consolidated", "provider_state"):
            before, after = getattr(baseline, name), getattr(draft, name)
            if before != after:
                existing = getattr(current, name)
                if existing != before and existing != after:
                    raise SessionConflictError(f"session {name} changed")
                setattr(current, name, deepcopy(after))
        current.policy = draft.policy
        current.updated_at = max(current.updated_at, draft.updated_at)
        return current, self._changed_start(before_messages, current.messages)

    async def _submit_draft(self, draft: Session) -> None:
        def commit() -> Session:
            # The caller owns this draft and awaits settlement before using it again.
            with self._transaction():
                current, message_start = self._apply_turn(draft)
                self._commit(current, message_start=message_start)
            self._publish(current)
            return self._draft(current, previous=draft)
        fresh = await self._execute(draft.key, commit)
        self._refresh(draft, fresh)

    async def mutate_metadata(
        self, key: str, change: Callable[[dict[str, Any]], _T],
        *, expected_generation: str | None = None,
    ) -> tuple[_T, dict[str, Any]]:
        """Run a synchronous metadata command inside one short transaction."""
        def commit() -> tuple[_T, dict[str, Any]]:
            with self._transaction():
                session = self._load(key, history=False) or Session(key=key)
                if expected_generation is not None and session.generation != expected_generation:
                    raise SessionConflictError("metadata command belongs to a replaced session")
                result = change(session.metadata)
                header_only = session.policy.persist and session.persisted
                if header_only:
                    self._store.replace_metadata(key, session.metadata)
                    session.revision += 1
                else:
                    self._commit(session)
            self._publish(session, history=not header_only)
            return deepcopy(result), deepcopy(session.metadata)
        return await self._execute(key, commit)

    async def prepare_input(self, session: Session) -> None:
        """Commit the prepared input and recovery baseline before external execution."""
        await self._submit_draft(session)

    async def finish_turn(self, session: Session) -> None:
        """Commit the assembled transcript and clear its recovery markers."""
        session.metadata.pop(_PENDING_KEY, None)
        session.metadata.pop(_CHECKPOINT_KEY, None)
        await self._submit_draft(session)

    async def restore_interruption(self, session: Session) -> None:
        """Commit a recovery decision against the version it classified."""
        await self._submit_draft(session)

    async def checkpoint_view(self, draft: Session, payload: Mapping[str, Any]) -> None:
        """Store a turn's recovery boundary without publishing unrelated draft edits."""
        baseline = draft._baseline  # pyright: ignore[reportPrivateUsage]
        generation = baseline.generation if baseline is not None else None
        def commit() -> Session:
            request = deepcopy(dict(payload))
            provider = deepcopy(draft.provider_state)
            with self._transaction():
                current = self._load(draft.key, history=False)
                if current is None:
                    raise SessionConflictError("checkpoint requires accepted input")
                if current.generation != generation:
                    raise SessionConflictError("checkpoint belongs to a replaced session")
                current.metadata[_CHECKPOINT_KEY] = request
                current.provider_state = provider
                if not current.policy.persist:
                    self._commit(current)
                else:
                    self._store.save_runtime_checkpoint(current)
            self._publish(current, history=not current.policy.persist)
            return current
        committed = await self._execute(draft.key, commit)
        # Only the checkpoint fields have committed; preserve other local changes.
        draft.metadata[_CHECKPOINT_KEY] = dict(payload)
        if baseline is not None:
            metadata = {**baseline.metadata, _CHECKPOINT_KEY: committed.metadata[_CHECKPOINT_KEY]}
            draft._baseline = replace(baseline, metadata=metadata, provider_state=committed.provider_state)  # pyright: ignore[reportPrivateUsage]

    async def record_delivery(self, key: str, content: str, extra: Mapping[str, Any]) -> None:
        values = deepcopy(dict(extra))
        def change(session: Session) -> None:
            session.add_message("assistant", content, **values)
        await self._execute(key, lambda: self._change(key, change))

    async def queue_followup(self, key: str, message: InboundMessage) -> str | None:
        if message.channel != "websocket":
            return None

        from nanobot.session.recovery import record_pending_followup

        payload = deepcopy(message)
        return await self._execute(key, lambda: self._change(
            key, lambda session: record_pending_followup(session, payload), history=False,
        ))

    async def acknowledge_followups(self, key: str, identifiers: Sequence[str]) -> None:
        from nanobot.session.recovery import acknowledge_pending_followups

        values = tuple(identifiers)
        await self._execute(key, lambda: self._change(
            key, lambda session: acknowledge_pending_followups(session, values), history=False,
        ))

    async def commit_summary(
        self, source: Session, summary: str, *, archive_end: int,
    ) -> None:
        prefix = deepcopy(source.messages[:archive_end])
        def change(session: Session) -> None:
            if session.generation != source.generation or session.messages[:archive_end] != prefix:
                raise SessionConflictError("summarized history was replaced")
            session.commit_summary_checkpoint(
                summary, insert_at=archive_end, last_active=source.updated_at,
            )
            session.provider_state = None
        await self._execute(source.key, lambda: self._change(source.key, change))

    async def read_metadata(self, key: str) -> dict[str, Any] | None:
        def read() -> dict[str, Any] | None:
            transient = self._transients.get(key)
            if transient is not None:
                return {"key": key, "metadata": deepcopy(transient.metadata)}
            return cast(dict[str, Any] | None, self._store.read_metadata(key))
        return await self._execute(key, read)

    async def list_sessions(self) -> list[dict[str, Any]]:
        return await self._execute("", lambda: cast(list[dict[str, Any]], self._store.list_sessions()))

    async def prune_dream_sessions(self, *, keep: int = 10) -> int:
        """Delete older Dream conversations in one transaction on the owner worker."""
        def prune() -> int:
            with self._transaction():
                rows = [row for row in self._store.list_sessions() if is_dream_session(row["key"])]
                removed = [row["key"] for row in rows[max(0, keep):]]
                for key in removed:
                    self._store.delete(key)
            for key in removed:
                self.forget_transient(key)
                self._policies.pop(key, None)
                if self._on_delete is not None:
                    self._on_delete(key)
            return len(removed)
        return await self._execute("", prune)

    def forget_transient(self, key: str) -> None:
        self._transients.pop(key, None)
        self._snapshots.pop(key, None)

    async def discard(self, key: str) -> None:
        def discard() -> None:
            self._transients.pop(key, None)
            self._snapshots.pop(key, None)
        await self._execute(key, discard)

    async def fork(
        self, source_key: str, target_key: str, before_user_index: int,
        *, title: str | None = None,
    ) -> Session | None:
        def commit() -> Session | None:
            with self._transaction():
                source = self._load(source_key)
                if source is None:
                    return None
                target = fork_session(source, target_key, before_user_index)
                if target is None:
                    return None
                if title:
                    target.metadata["title"] = title
                self._commit(target)
            self._publish(target)
            return self._draft(target)
        return await self._execute(source_key, commit)

    async def delete(self, key: str) -> bool:
        def delete() -> bool:
            with self._transaction():
                deleted = self._store.delete(key)
                self._transients.pop(key, None)
                self._snapshots.pop(key, None)
                self._policies.pop(key, None)
                if self._on_delete is not None:
                    self._on_delete(key)
                return deleted
        return await self._execute(key, delete)

    async def update_metadata(
        self, key: str, updates: Mapping[str, Any], *, remove: Sequence[str] = (),
    ) -> None:
        """Commit metadata changes without granting access to the live transcript."""
        values = deepcopy(dict(updates))
        removed = tuple(remove)
        if _RESERVED_KEYS.intersection(values) or _RESERVED_KEYS.intersection(removed):
            raise ValueError("turn state must be changed through turn operations")

        def change(metadata: dict[str, Any]) -> None:
            for name in removed:
                metadata.pop(name, None)
            metadata.update(values)

        await self.mutate_metadata(key, change)

    async def import_messages(
        self,
        key: str,
        messages: Sequence[Mapping[str, Any]],
        *,
        metadata: Mapping[str, Any] | None = None,
        require_empty: bool = False,
    ) -> Session:
        """Validate and commit an import as one operation, or leave state unchanged."""
        records = deepcopy([dict(message) for message in messages])
        values = deepcopy(dict(metadata or {}))
        if _RESERVED_KEYS.intersection(values):
            raise ValueError("cannot import active turn state as metadata")
        for record in records:
            if record.get("role") not in {"user", "assistant", "tool", "system"}:
                raise ValueError("unsupported message role")
            if "content" not in record:
                raise ValueError("messages must include content")

        def change(session: Session) -> Session:
            if session.metadata.get(_PENDING_KEY):
                raise SessionConflictError("cannot import into an active or interrupted session")
            if require_empty and session.messages:
                raise SessionConflictError("restore target is not empty")
            session.messages.extend(records)
            session.metadata.update(values)
            session.updated_at = datetime.now()
            return session

        return await self._execute(key, lambda: self._change(key, change))

    async def reset(self, key: str) -> None:
        """Clear the transcript and revoke any old turn in one commit."""
        def reset() -> None:
            with self._transaction():
                old = self._load(key, history=False)
                session = Session(key=key)
                if old is not None:
                    session.policy = old.policy
                    session.metadata = deepcopy(old.metadata)
                for name in (*_RESERVED_KEYS, "webui_recovery", "_last_summary"):
                    session.metadata.pop(name, None)
                if session.policy.persist:
                    self._store.delete(key)
                self._commit(session)
            self._publish(session)
        await self._execute(key, reset)
