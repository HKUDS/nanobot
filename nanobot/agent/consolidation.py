"""Memory consolidation orchestration (rewritten with asyncio.TaskGroup).

``ConsolidationOrchestrator`` manages the lifecycle of memory consolidation:

- **Lifecycle** -- async context-manager; ``async with orchestrator:`` enters it.
- **Background** -- ``submit()`` schedules fire-and-forget tasks via ``asyncio.TaskGroup``.
- **Blocking** -- ``consolidate_and_wait()`` runs consolidation inline (used by /new).
- **Archival** -- ``archive_fn`` closure called on failure; decoupled from MemoryPersistence.

Backward-compatible shims (``get_lock``, ``prune_lock``, ``consolidate``,
``fallback_archive_snapshot``) are retained so existing callers that construct
with ``ConsolidationOrchestrator(memory_store)`` continue to work.
"""

from __future__ import annotations

import asyncio
import weakref
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable

from loguru import logger

if TYPE_CHECKING:
    from nanobot.agent.memory.store import MemoryStore
    from nanobot.providers.base import LLMProvider
    from nanobot.session.manager import Session


class ConsolidationOrchestrator:
    """Manages memory consolidation with structured concurrency."""

    def __init__(
        self,
        memory_store: MemoryStore | None = None,
        *,
        memory: MemoryStore | None = None,
        archive_fn: Callable[[list[dict[str, Any]]], None] | None = None,
        max_concurrent: int = 3,
        memory_window: int = 50,
        enable_contradiction_check: bool = True,
    ) -> None:
        # Support both old positional API and new keyword API
        resolved = memory or memory_store
        assert resolved is not None, "either memory_store or memory= must be provided"
        self._memory: MemoryStore = resolved
        self._archive_fn = archive_fn
        self._max_concurrent = max_concurrent
        self._memory_window = memory_window
        self._enable_contradiction_check = enable_contradiction_check
        self._locks: dict[str, asyncio.Lock] | weakref.WeakValueDictionary[str, asyncio.Lock] = {}
        self._in_progress: set[str] = set()
        self._sem: asyncio.Semaphore | None = None
        self._tg: Any = None  # asyncio.TaskGroup (typed as Any for mypy compat)

        # Backward compatibility: when constructed with old positional API,
        # use WeakValueDictionary for locks (matches old behaviour).
        if memory_store is not None and memory is None:
            self._locks = weakref.WeakValueDictionary()

    async def __aenter__(self) -> ConsolidationOrchestrator:
        self._sem = asyncio.Semaphore(self._max_concurrent)
        self._tg = asyncio.TaskGroup()  # type: ignore[attr-defined]
        await self._tg.__aenter__()
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: Any
    ) -> None:  # noqa: E501
        if self._tg is not None:
            await self._tg.__aexit__(exc_type, exc_val, exc_tb)

    # ------------------------------------------------------------------
    # New public API
    # ------------------------------------------------------------------

    def submit(
        self,
        session_key: str,
        session: Session,
        provider: LLMProvider,
        model: str,
    ) -> None:
        """Schedule a background consolidation task. Returns immediately.

        Silently skips if a consolidation for this session is already
        in progress (preserves the deduplication from _consolidating guard).
        """
        assert self._tg is not None, "must be used as async context manager"
        if session_key in self._in_progress:
            return
        self._in_progress.add(session_key)
        self._tg.create_task(self._run(session_key, session, provider, model))

    async def consolidate_and_wait(
        self,
        session_key: str,
        session: Session,
        provider: LLMProvider,
        model: str,
        *,
        archive_all: bool = False,
    ) -> bool:
        """Run consolidation inline (awaitable). Returns True on success.

        Used by _consolidate_memory for the archive_all=True path (/new command).
        """
        lock = self._get_or_create_lock(session_key)
        try:
            async with lock:
                return await self._memory.consolidate(
                    session,
                    provider,
                    model,
                    memory_window=self._memory_window,
                    enable_contradiction_check=self._enable_contradiction_check,
                    archive_all=archive_all,
                )
        finally:
            self._prune_lock_if_idle(session_key)

    # ------------------------------------------------------------------
    # Backward-compatible API (retained for existing callers)
    # ------------------------------------------------------------------

    def get_lock(self, session_key: str) -> asyncio.Lock:
        """Get or create a per-session consolidation lock.

        .. deprecated:: Use ``submit()`` or ``consolidate_and_wait()`` instead.
        """
        return self._get_or_create_lock(session_key)

    def prune_lock(self, session_key: str, lock: asyncio.Lock) -> None:
        """Remove the lock entry for a session key when it is no longer in use.

        .. deprecated:: Use ``submit()`` or ``consolidate_and_wait()`` instead.
        """
        existing = self._locks.get(session_key)
        if existing is lock and not lock.locked():
            try:
                del self._locks[session_key]
            except KeyError:
                pass

    async def consolidate(
        self,
        session: Session,
        provider: LLMProvider,
        model: str,
        *,
        memory_window: int,
        enable_contradiction_check: bool,
        archive_all: bool = False,
    ) -> bool:
        """Delegate to ``MemoryStore.consolidate()``. Returns True on success.

        .. deprecated:: Use ``submit()`` or ``consolidate_and_wait()`` instead.
        """
        return await self._memory.consolidate(
            session,
            provider,
            model,
            archive_all=archive_all,
            memory_window=memory_window,
            enable_contradiction_check=enable_contradiction_check,
        )

    def fallback_archive_snapshot(self, snapshot: list[dict]) -> bool:
        """Fallback archival used by ``/new`` when AI consolidation fails.

        .. deprecated:: Inject ``archive_fn`` at construction instead.
        """
        try:
            lines: list[str] = []
            for m in snapshot:
                content = m.get("content")
                if not content:
                    continue
                tools = f" [tools: {', '.join(m['tools_used'])}]" if m.get("tools_used") else ""
                timestamp = str(m.get("timestamp", "?"))[:16]
                role = str(m.get("role", "unknown")).upper()
                lines.append(f"[{timestamp}] {role}{tools}: {content}")

            if not lines:
                return True

            header = (
                f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}] "
                f"Fallback archive from /new ({len(lines)} messages)"
            )
            entry = header + "\n" + "\n".join(lines)
            self._memory.persistence.append_text(self._memory.history_file, entry.rstrip() + "\n\n")
            logger.warning("/new used fallback archival: {} messages", len(lines))
            return True
        except Exception:  # crash-barrier: memory subsystem archival
            logger.exception("Fallback archival failed")
            return False

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_or_create_lock(self, session_key: str) -> asyncio.Lock:
        lock = self._locks.get(session_key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[session_key] = lock
        return lock

    def _prune_lock_if_idle(self, session_key: str) -> None:
        entry = self._locks.get(session_key)
        if entry is not None and not entry.locked():
            try:
                del self._locks[session_key]
            except KeyError:
                pass

    async def _run(
        self,
        session_key: str,
        session: Session,
        provider: LLMProvider,
        model: str,
    ) -> None:
        assert self._sem is not None
        try:
            async with self._sem:
                lock = self._get_or_create_lock(session_key)
                async with lock:
                    try:
                        await self._memory.consolidate(
                            session,
                            provider,
                            model,
                            memory_window=self._memory_window,
                            enable_contradiction_check=self._enable_contradiction_check,
                        )
                    except Exception:  # crash-barrier: consolidation failure
                        logger.exception("Consolidation failed for {}; archiving", session_key)
                        if self._archive_fn is not None:
                            self._archive_fn(list(session.messages))
        finally:
            self._in_progress.discard(session_key)
            self._prune_lock_if_idle(session_key)
