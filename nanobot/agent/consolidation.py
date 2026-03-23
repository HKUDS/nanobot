"""Memory consolidation orchestration with structured concurrency.

``ConsolidationOrchestrator`` manages the lifecycle of memory consolidation:

- **Lifecycle** -- async context-manager; ``async with orchestrator:`` enters it.
- **Background** -- ``submit()`` schedules fire-and-forget tasks.
- **Blocking** -- ``consolidate_and_wait()`` runs consolidation inline (used by /new).
- **Archival** -- ``archive_fn`` closure called on failure; decoupled from MemoryPersistence.

Compatible with Python 3.10+ (does not use asyncio.TaskGroup which requires 3.11).
"""

from __future__ import annotations

import asyncio
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
        *,
        memory: MemoryStore,
        archive_fn: Callable[[list[dict[str, Any]]], None] | None = None,
        max_concurrent: int = 3,
        memory_window: int = 50,
        enable_contradiction_check: bool = True,
    ) -> None:
        self._memory: MemoryStore = memory
        self._archive_fn = archive_fn
        self._max_concurrent = max_concurrent
        self._memory_window = memory_window
        self._enable_contradiction_check = enable_contradiction_check
        self._locks: dict[str, asyncio.Lock] = {}
        self._in_progress: set[str] = set()
        self._sem: asyncio.Semaphore | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        self._active = False

    async def __aenter__(self) -> ConsolidationOrchestrator:
        self._sem = asyncio.Semaphore(self._max_concurrent)
        self._tasks = set()
        self._active = True
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        self._active = False
        # Drain all pending background tasks before exiting.
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

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
        if not self._active:
            logger.warning("submit() called before entering context manager; skipping")
            return
        if session_key in self._in_progress:
            return
        self._in_progress.add(session_key)
        task = asyncio.create_task(self._run(session_key, session, provider, model))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

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
        async with lock:
            return await self._memory.consolidate(
                session,
                provider,
                model,
                memory_window=self._memory_window,
                enable_contradiction_check=self._enable_contradiction_check,
                archive_all=archive_all,
            )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_or_create_lock(self, session_key: str) -> asyncio.Lock:
        lock = self._locks.get(session_key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[session_key] = lock
        return lock

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
