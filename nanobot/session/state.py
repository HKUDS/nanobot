"""Ordered session operations with detached reads and durable acknowledgements."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import fields, replace
from datetime import datetime
from typing import Any, TypeVar, cast

from nanobot.bus.events import InboundMessage
from nanobot.session.keys import is_dream_session
from nanobot.session.manager import Session, SessionPolicy, fork_session
from nanobot.session.model_selection import SESSION_MODEL_PRESET_METADATA_KEY
from nanobot.session.sqlite_store import SessionConflictError, SqliteSessionStore
from nanobot.session.types import PARENT_SESSION_KEY, SessionTypes
from nanobot.utils.cancellation import shield_and_drain

_T = TypeVar("_T")
_PENDING_KEY = "pending_user_turn"
_CHECKPOINT_KEY = "runtime_checkpoint"
_RESERVED_KEYS = frozenset({_PENDING_KEY, _CHECKPOINT_KEY, "pending_user_followups"})
_DEFAULT_CAPACITY = 64
_DEFAULT_WORKERS = 4


class SessionOperationQueueFullError(RuntimeError):
    """The bounded session owner cannot admit another operation."""


class SessionState:
    """Own session mutations and their storage boundary.

    Operations load and change private state under the store transaction lock.
    Only detached reads leave this boundary. Model calls, tool execution, and
    event publication must happen outside these short operations.
    """

    def __init__(
        self, store: SqliteSessionStore, *, capacity: int = _DEFAULT_CAPACITY,
        workers: int = _DEFAULT_WORKERS,
        on_delete: Callable[[str], None] | None = None,
        types: SessionTypes | None = None,
    ) -> None:
        if capacity < 1:
            raise ValueError("session operation capacity must be positive")
        if workers < 1:
            raise ValueError("session operation worker count must be positive")
        self._types = types if types is not None else SessionTypes()
        self._store = store
        self._on_delete = on_delete
        self._snapshots: dict[str, Session] = {}
        self._transients: dict[str, Session] = {}
        self._policies: dict[str, SessionPolicy] = {}
        # Process-local deletion tombstones reject late key-only mutations. An
        # explicit create/get/reset/import starts a new generation and clears it.
        self._retired: set[str] = set()
        self._cache_lock = threading.RLock()
        self._capacity = capacity
        self._admitted = 0
        self._key_tails: dict[str, asyncio.Task[Any]] = {}
        self._global_tail: asyncio.Task[Any] | None = None
        self._pending: set[asyncio.Task[Any]] = set()
        self._worker = ThreadPoolExecutor(
            max_workers=min(workers, capacity),
            thread_name_prefix="session-store",
        )
        self._closed = False
        self._close_task: asyncio.Task[None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def is_bound(self) -> bool:
        """Whether runtime operations have claimed this state owner."""
        return self._loop is not None

    @property
    def bound_loop(self) -> asyncio.AbstractEventLoop | None:
        return self._loop

    def _bind_loop(self) -> None:
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        elif self._loop is not loop:
            raise RuntimeError("session state belongs to a different event loop")

    async def _execute(
        self,
        key: str | Sequence[str] | None,
        operation: Callable[[], _T],
        *,
        operation_name: str | None = None,
    ) -> _T:
        """Admit bounded work with FIFO key affinity or a global barrier."""
        self._bind_loop()
        name = operation_name or getattr(operation, "__name__", "session operation")
        if key is None:
            keys: tuple[str, ...] = ()
            session_label = "<all>"
        elif isinstance(key, str):
            keys = (key,)
            session_label = key
        else:
            keys = tuple(sorted(set(key)))
            if not keys:
                raise ValueError("session operation requires at least one key")
            session_label = ",".join(keys)
        if self._closed:
            raise RuntimeError(
                f"session state is closed: operation={name} session={session_label!r}"
            )
        if self._admitted >= self._capacity:
            raise SessionOperationQueueFullError(
                f"session operation queue is full: operation={name} "
                f"session={session_label!r} capacity={self._capacity}"
            )

        self._admitted += 1
        if key is None:
            predecessors = tuple(self._pending)
        else:
            ordered = [self._key_tails[item] for item in keys if item in self._key_tails]
            if self._global_tail is not None:
                ordered.append(self._global_tail)
            predecessors = tuple(dict.fromkeys(ordered))

        async def run() -> _T:
            try:
                if predecessors:
                    await asyncio.gather(
                        *(asyncio.shield(predecessor) for predecessor in predecessors),
                        return_exceptions=True,
                    )
                return await asyncio.get_running_loop().run_in_executor(
                    self._worker,
                    operation,
                )
            finally:
                self._admitted -= 1
                for item in keys:
                    if self._key_tails.get(item) is task:
                        self._key_tails.pop(item, None)
                if self._global_tail is task:
                    self._global_tail = None

        task = asyncio.create_task(run())
        if key is None:
            self._global_tail = task
        else:
            for item in keys:
                self._key_tails[item] = task
        self._pending.add(task)
        try:
            return await shield_and_drain(task)
        finally:
            self._pending.discard(task)

    async def aclose(self) -> None:
        """Reject new operations and drain accepted work without swallowing caller cancellation."""
        self._bind_loop()
        self._closed = True

        async def close() -> None:
            if self._pending:
                await asyncio.gather(*tuple(self._pending), return_exceptions=True)
            await asyncio.to_thread(self._worker.shutdown, wait=True)

        if self._close_task is None:
            self._close_task = asyncio.create_task(close())
        # A timeout may stop waiting for shutdown, but it must not cancel the
        # drain itself. Unlike an admitted mutation, close has no commit result
        # that must delay cancellation of its caller.
        await asyncio.shield(self._close_task)

    def _change(
        self,
        key: str,
        change: Callable[[Session], _T],
        *,
        history: bool = True,
        create_if_missing: bool = False,
    ) -> _T:
        # Hold the cross-process lock across read/modify/write, not just the write.
        # No live cache can expose uncommitted changes if validation or I/O fails.
        def commit() -> tuple[Session, _T, bool]:
            session = self._load(key, history=history)
            if session is None:
                if not create_if_missing:
                    raise SessionConflictError("session does not exist")
                with self._cache_lock:
                    self._retired.discard(key)
                session = Session(key=key)
            before = list(session.messages)
            result = change(session)
            publish_history = history
            if not history and session.persisted and session.policy.persist:
                self._store.replace_metadata(key, session.metadata, updated_at=session.updated_at)
                session.revision += 1
            else:
                self._commit(session, message_start=self._changed_start(before, session.messages))
                publish_history = True
            return session, result, publish_history

        session, result, publish_history = self._store.run_write(commit)
        self._publish(session, history=publish_history)
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
        with self._cache_lock:
            transient = self._transients.get(key)
            if transient is not None:
                return self._working(transient)
        def load() -> Session | None:
            session = self._store.load(key, history=False)
            if session is not None and history:
                with self._cache_lock:
                    cached = self._snapshots.get(key)
                    if cached is not None and (cached.revision, cached.generation) == (
                        session.revision,
                        session.generation,
                    ):
                        return replace(session, messages=list(cached.messages))
                return self._store.load(key)
            return session

        session = self._store.run_read(load)
        with self._cache_lock:
            policy = self._policies.get(key)
        if session is not None and policy is not None:
            session.policy = policy
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
            with self._cache_lock:
                self._transients[session.key] = self._working(raw)

    def _publish(self, session: Session, *, history: bool = True) -> None:
        """Publish owner-private records only after the enclosing transaction committed."""
        with self._cache_lock:
            if not history:
                cached = self._snapshots.get(session.key)
                if cached is None or (cached.revision + 1, cached.generation) != (
                    session.revision,
                    session.generation,
                ):
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
        with self._cache_lock:
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
            with self._cache_lock:
                self._policies[key] = policy
            session.policy = policy
            self._publish(session)

        await self._execute(key, configure)

    async def register_transient(
        self, key: str, *, disabled_tools: frozenset[str] = frozenset(),
    ) -> Session:
        """Create an owner-held non-persistent session for a temporary conversation."""
        def register() -> Session:
            session = Session(key=key, policy=SessionPolicy(
                persist=False, log_content=False, disabled_tools=disabled_tools,
            ))
            with self._cache_lock:
                if key in self._transients:
                    raise SessionConflictError("transient session already exists")
                self._retired.discard(key)
                self._transients[key] = session
            return self._draft(session)

        return await self._execute(key, register, operation_name="register_transient")

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
            def commit() -> Session:
                session = self._load(key)
                if session is None:
                    with self._cache_lock:
                        self._retired.discard(key)
                    session = Session(key=key)
                    self._commit(session)
                return session

            session = self._store.run_write(commit)
            self._publish(session)
            return self._draft(session)
        return await self._execute(key, get)

    async def create_child(
        self, parent_key: str, key: str, *, metadata: Mapping[str, Any],
        content: str, policy: SessionPolicy,
    ) -> Session:
        """Establish a child and its parent before execution leaves the owner."""
        values = deepcopy(dict(metadata))

        def create() -> Session:
            def write() -> Session:
                parent = self._load(parent_key, history=False)
                if parent is None:
                    with self._cache_lock:
                        if parent_key in self._retired:
                            raise SessionConflictError("parent session was deleted")
                    parent = Session(key=parent_key, policy=policy)
                    self._commit(parent)
                effective = SessionPolicy(
                    persist=parent.policy.persist and policy.persist,
                    log_content=parent.policy.log_content and policy.log_content,
                    disabled_tools=parent.policy.disabled_tools | policy.disabled_tools,
                )
                child = Session(key=key, policy=effective, metadata=values)
                child.metadata[PARENT_SESSION_KEY] = parent_key
                child.add_message("user", content)
                self._commit(child)
                return child

            child = self._store.run_write(write)
            self._publish(child)
            return self._draft(child)

        return await self._execute((parent_key, key), create, operation_name="create_child")

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
            def write() -> Session:
                current, message_start = self._apply_turn(draft)
                self._commit(current, message_start=message_start)
                return current

            current = self._store.run_write(write)
            self._publish(current)
            return self._draft(current, previous=draft)
        fresh = await self._execute(draft.key, commit)
        self._refresh(draft, fresh)

    async def mutate_metadata(
        self,
        key: str,
        change: Callable[[dict[str, Any]], _T],
        *,
        expected_generation: str | None = None,
        create_if_missing: bool = False,
    ) -> tuple[_T, dict[str, Any]]:
        """Run a synchronous metadata command inside one short transaction."""
        def commit() -> tuple[_T, dict[str, Any]]:
            def write() -> tuple[Session, _T, bool]:
                session = self._load(key, history=False)
                if session is None:
                    with self._cache_lock:
                        retired = key in self._retired
                    if retired or not create_if_missing:
                        raise SessionConflictError("session does not exist")
                    session = Session(key=key)
                if expected_generation is not None and session.generation != expected_generation:
                    raise SessionConflictError("metadata command belongs to a replaced session")
                result = change(session.metadata)
                header_only = session.policy.persist and session.persisted
                if header_only:
                    self._store.replace_metadata(key, session.metadata)
                    session.revision += 1
                else:
                    self._commit(session)
                return session, result, header_only

            session, result, header_only = self._store.run_write(write)
            self._publish(session, history=not header_only)
            return deepcopy(result), deepcopy(session.metadata)
        return await self._execute(key, commit)

    async def open_with_metadata(
        self,
        key: str,
        updates: Mapping[str, Any],
        *,
        expected_generation: str | None = None,
    ) -> tuple[str, bool]:
        """Open one generation and atomically attach admission metadata."""
        values = deepcopy(dict(updates))
        if _RESERVED_KEYS.intersection(values):
            raise ValueError("turn state must be changed through turn operations")

        def open_session() -> tuple[str, bool]:
            def write() -> tuple[Session, bool, bool]:
                session = self._load(key, history=False)
                created = session is None
                if created:
                    if expected_generation is not None:
                        raise SessionConflictError("session does not exist")
                    with self._cache_lock:
                        self._retired.discard(key)
                    session = Session(key=key)
                elif (
                    expected_generation is not None
                    and session.generation != expected_generation
                ):
                    raise SessionConflictError("session admission belongs to a replaced session")
                session.metadata.update(values)
                header_only = session.policy.persist and session.persisted
                if header_only:
                    self._store.replace_metadata(key, session.metadata)
                    session.revision += 1
                else:
                    self._commit(session)
                return session, created, header_only

            session, created, header_only = self._store.run_write(write)
            self._publish(session, history=not header_only)
            return session.generation, created

        return await self._execute(key, open_session, operation_name="open_with_metadata")

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

            def write() -> Session:
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
                return current

            current = self._store.run_write(write)
            self._publish(current, history=not current.policy.persist)
            return current
        committed = await self._execute(draft.key, commit)
        # Only the checkpoint fields have committed; preserve other local changes.
        draft.metadata[_CHECKPOINT_KEY] = dict(payload)
        if baseline is not None:
            metadata = {**baseline.metadata, _CHECKPOINT_KEY: committed.metadata[_CHECKPOINT_KEY]}
            draft._baseline = replace(baseline, metadata=metadata, provider_state=committed.provider_state)  # pyright: ignore[reportPrivateUsage]

    async def record_delivery(
        self,
        key: str,
        content: str,
        extra: Mapping[str, Any],
        *,
        expected_generation: str,
    ) -> None:
        """Append a delivery only to the existing generation it belongs to."""
        if not expected_generation:
            raise ValueError("delivery requires a session generation")
        values = deepcopy(dict(extra))

        def change(session: Session) -> None:
            if session.generation != expected_generation:
                raise SessionConflictError("delivery belongs to a replaced session")
            session.add_message("assistant", content, **values)

        await self._execute(
            key,
            lambda: self._change(key, change),
            operation_name="record_delivery",
        )

    async def queue_followup(self, key: str, message: InboundMessage) -> str | None:
        if message.channel != "websocket":
            return None

        from nanobot.session.recovery import record_pending_followup

        payload = deepcopy(message)

        def commit() -> str | None:
            def write() -> tuple[Session, str | None, bool]:
                session = self._load(key, history=False)
                if session is None:
                    with self._cache_lock:
                        retired = key in self._retired
                    if retired or payload.require_existing_session or payload.session_generation is not None:
                        raise SessionConflictError("follow-up requires an existing session")
                    # The inbox can accept a second input before the first turn
                    # has loaded its session. Journal that input, but never revive
                    # a deleted generation or a discarded Temporary Chat.
                    session = Session(key=key)
                if payload.session_generation is not None and session.generation != payload.session_generation:
                    raise SessionConflictError("follow-up belongs to a replaced session")
                identifier = record_pending_followup(session, payload)
                header_only = session.policy.persist and session.persisted
                if header_only:
                    self._store.replace_metadata(key, session.metadata, updated_at=session.updated_at)
                    session.revision += 1
                else:
                    self._commit(session)
                return session, identifier, header_only

            session, identifier, header_only = self._store.run_write(write)
            self._publish(session, history=not header_only)
            return identifier

        return await self._execute(key, commit, operation_name="queue_followup")

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
            with self._cache_lock:
                transient = self._transients.get(key)
                if transient is not None:
                    return {"key": key, "metadata": deepcopy(transient.metadata)}
            return cast(dict[str, Any] | None, self._store.read_metadata(key))
        return await self._execute(key, read)

    async def list_sessions(self) -> list[dict[str, Any]]:
        return await self._execute(
            None,
            lambda: cast(list[dict[str, Any]], self._store.list_sessions()),
            operation_name="list_sessions",
        )

    async def rename_model_preset(self, old_name: str, new_name: str) -> int:
        """Rename persisted preset references in one owner-serialized transaction."""
        if old_name == new_name:
            return 0

        def rename() -> int:
            def write() -> list[str]:
                changed: list[str] = []
                for row in self._store.list_metadata():
                    if row["metadata"].get(SESSION_MODEL_PRESET_METADATA_KEY) == old_name:
                        if self._store.update_metadata(
                            row["key"],
                            {SESSION_MODEL_PRESET_METADATA_KEY: new_name},
                        ):
                            changed.append(row["key"])
                return changed

            changed = self._store.run_write(write)
            with self._cache_lock:
                for key in changed:
                    self._snapshots.pop(key, None)
            return len(changed)

        return await self._execute(None, rename, operation_name="rename_model_preset")

    async def ensure_session_handles(self) -> dict[str, str]:
        """Allocate stable public handles through the runtime mutation owner."""
        from nanobot.session.session_handles import (
            SESSION_HANDLE_METADATA_KEY,
            allocate_session_handles,
        )

        def ensure() -> dict[str, str]:
            changed: list[str] = []

            def write() -> dict[str, str]:
                names, updates = allocate_session_handles(self._store.list_metadata(), self._types)
                for key, name in updates.items():
                    if self._store.update_metadata(
                        key,
                        {SESSION_HANDLE_METADATA_KEY: name},
                    ):
                        changed.append(key)
                return names

            names = self._store.run_write(write)
            with self._cache_lock:
                for key in changed:
                    self._snapshots.pop(key, None)
            return names

        return await self._execute(None, ensure, operation_name="ensure_session_handles")

    async def prune_dream_sessions(self, *, keep: int = 10) -> int:
        """Delete older Dream conversations in one transaction on the owner worker."""
        def prune() -> list[str]:
            def write() -> list[str]:
                rows = [row for row in self._store.list_sessions() if is_dream_session(row["key"])]
                removed = [row["key"] for row in rows[max(0, keep):]]
                for key in removed:
                    self._store.delete(key)
                return removed

            removed = self._store.run_write(write)
            with self._cache_lock:
                for key in removed:
                    self._transients.pop(key, None)
                    self._snapshots.pop(key, None)
                    self._policies.pop(key, None)
                    self._retired.add(key)
            return removed

        removed = await self._execute(None, prune, operation_name="prune_dream_sessions")
        if self._on_delete is not None:
            for key in removed:
                self._on_delete(key)
        return len(removed)

    def forget_transient(self, key: str) -> None:
        """Drop process-local cache state; runtime disposal should use discard()."""
        with self._cache_lock:
            self._transients.pop(key, None)
            self._snapshots.pop(key, None)

    async def discard(self, key: str) -> None:
        def discard() -> None:
            with self._cache_lock:
                self._transients.pop(key, None)
                self._snapshots.pop(key, None)
                self._policies.pop(key, None)
                self._retired.add(key)
        await self._execute(key, discard, operation_name="discard")

    async def fork(
        self, source_key: str, target_key: str, before_user_index: int,
        *, title: str | None = None,
    ) -> Session | None:
        def commit() -> Session | None:
            def write() -> Session | None:
                source = self._load(source_key)
                if source is None:
                    return None
                target = fork_session(source, target_key, before_user_index)
                if target is None:
                    return None
                if title:
                    target.metadata["title"] = title
                self._commit(target)
                return target

            target = self._store.run_write(write)
            if target is None:
                return None
            self._publish(target)
            return self._draft(target)
        return await self._execute(
            (source_key, target_key),
            commit,
            operation_name="fork",
        )

    async def delete(
        self,
        key: str,
        *,
        expected_generation: str | None = None,
    ) -> bool:
        def delete() -> tuple[bool, set[str]]:
            def write() -> tuple[bool, set[str]]:
                session = self._load(key, history=False)
                if expected_generation is not None and (
                    session is None or session.generation != expected_generation
                ):
                    raise SessionConflictError("delete belongs to a replaced session")
                rows = self._store.list_metadata()
                with self._cache_lock:
                    rows.extend({"key": child.key, "metadata": child.metadata}
                                for child in self._transients.values())
                children: dict[str, list[str]] = {}
                for row in rows:
                    parent = row["metadata"].get(PARENT_SESSION_KEY)
                    if isinstance(parent, str):
                        children.setdefault(parent, []).append(row["key"])
                pending = [key]
                removed: set[str] = set()
                deleted = False
                while pending:
                    current = pending.pop()
                    if current in removed:
                        continue
                    removed.add(current)
                    pending.extend(children.get(current, ()))
                    deleted = self._store.delete(current) or deleted
                return deleted, removed

            deleted, removed = self._store.run_write(write)
            with self._cache_lock:
                for current in removed:
                    self._transients.pop(current, None)
                    self._snapshots.pop(current, None)
                    self._policies.pop(current, None)
                    self._retired.add(current)
            return deleted, removed

        deleted, removed = await self._execute(None, delete, operation_name="delete")
        if self._on_delete is not None:
            for current in removed:
                self._on_delete(current)
        return deleted

    async def update_metadata(
        self,
        key: str,
        updates: Mapping[str, Any],
        *,
        remove: Sequence[str] = (),
        expected_generation: str | None = None,
        create_if_missing: bool = False,
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

        await self.mutate_metadata(
            key,
            change,
            expected_generation=expected_generation,
            create_if_missing=create_if_missing,
        )

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

        return await self._execute(
            key,
            lambda: self._change(key, change, create_if_missing=True),
            operation_name="import_messages",
        )

    async def reset(self, key: str) -> None:
        """Clear the transcript and revoke any old turn in one commit."""
        def reset() -> None:
            def write() -> Session:
                old = self._load(key, history=False)
                with self._cache_lock:
                    self._retired.discard(key)
                session = Session(key=key)
                if old is not None:
                    session.policy = old.policy
                    session.metadata = deepcopy(old.metadata)
                for name in (*_RESERVED_KEYS, "webui_recovery", "_last_summary"):
                    session.metadata.pop(name, None)
                if session.policy.persist:
                    self._store.delete(key)
                self._commit(session)
                return session

            session = self._store.run_write(write)
            self._publish(session)
        await self._execute(key, reset)
