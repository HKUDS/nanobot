"""Memory consolidation orchestration.

``ConsolidationOrchestrator`` manages the lifecycle of memory consolidation:

- **Locking** — per-session asyncio locks prevent concurrent consolidation.
- **Delegation** — calls ``MemoryStore.consolidate()`` for AI-based merging.
- **Fallback** — plain-text archival when AI consolidation fails.

Extracted from ``AgentLoop`` per ADR-002 to keep the main loop focused
on message processing.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from nanobot.agent.memory.store import MemoryStore
    from nanobot.providers.base import LLMProvider
    from nanobot.session.manager import Session


class ConsolidationOrchestrator:
    """Manages memory consolidation locking, execution, and fallback archival."""

    def __init__(self, memory_store: MemoryStore) -> None:
        self._memory = memory_store
        self._locks: dict[str, asyncio.Lock] = {}

    def get_lock(self, session_key: str) -> asyncio.Lock:
        """Get or create a per-session consolidation lock."""
        lock = self._locks.get(session_key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[session_key] = lock
        return lock

    def prune_lock(self, session_key: str, lock: asyncio.Lock) -> None:
        """Drop lock entry if no longer in use."""
        if not lock.locked():
            self._locks.pop(session_key, None)

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
        """Delegate to ``MemoryStore.consolidate()``. Returns True on success."""
        return await self._memory.consolidate(
            session,
            provider,
            model,
            archive_all=archive_all,
            memory_window=memory_window,
            enable_contradiction_check=enable_contradiction_check,
        )

    def fallback_archive_snapshot(self, snapshot: list[dict]) -> bool:
        """Fallback archival used by ``/new`` when AI consolidation fails."""
        try:
            lines: list[str] = []
            for m in snapshot:
                content = m.get("content")
                if not content:
                    continue
                tools = (
                    f" [tools: {', '.join(m['tools_used'])}]" if m.get("tools_used") else ""
                )
                timestamp = str(m.get("timestamp", "?"))[:16]
                role = str(m.get("role", "unknown")).upper()
                lines.append(f"[{timestamp}] {role}{tools}: {content}")

            if not lines:
                return True

            header = (
                f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] "
                f"Fallback archive from /new ({len(lines)} messages)"
            )
            entry = header + "\n" + "\n".join(lines)
            self._memory.append_history(entry)
            logger.warning("/new used fallback archival: {} messages", len(lines))
            return True
        except Exception:  # crash-barrier: memory subsystem archival
            logger.exception("Fallback archival failed")
            return False
