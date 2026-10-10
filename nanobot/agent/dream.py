"""Shared execution and finalization for Dream memory consolidation."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from nanobot.agent.memory import MemoryStore

if TYPE_CHECKING:
    from nanobot.agent.loop import AgentLoop


@dataclass
class DreamResult:
    status: Literal["empty", "completed", "incomplete", "failed"] = "empty"
    elapsed: float = 0.0
    content_diff: str = ""
    cursor: int | None = None
    reason: str = ""
    error: Exception | None = None
    commit_sha: str | None = None


async def run_dream(
    loop: AgentLoop,
    *,
    kind: Literal["manual", "scheduled"],
    before_run: Callable[[], Awaitable[None]] | None = None,
) -> DreamResult:
    """Serialize a batch through execution, cursor advancement, and cleanup.

    Manual runs commit cursor-only progress; scheduled runs commit only durable
    content changes. Cancellation propagates after finalization, leaving the
    unfinished batch pending for the next trigger.
    """
    async def _silent(*_args: Any, **_kwargs: Any) -> None:
        pass

    store = loop.context.memory
    async with store.dream_lock:
        result = DreamResult()
        started = time.monotonic()
        try:
            batch = store.build_dream_prompt()
            if batch is None:
                return result
            prompt, last_cursor = batch
            key = MemoryStore.dream_session_key()
            runtime = loop.dream_runtime()
            if before_run is not None:
                await before_run()
            response = await loop.process_direct(
                prompt,
                session_key=key,
                ephemeral=True,
                tools=store.build_dream_tools(),
                on_progress=_silent,
                runtime=runtime,
            )
            result.content_diff = store.dream_content_diff()
            if MemoryStore.dream_run_completed(response):
                store.set_last_dream_cursor(last_cursor)
                result.status = "completed"
                result.cursor = last_cursor
            else:
                result.status = "incomplete"
                result.reason = MemoryStore.dream_incompletion_reason(response)
                result.cursor = store.get_last_dream_cursor()
        except Exception as exc:
            result.status = "failed"
            result.error = exc
        finally:
            result.elapsed = time.monotonic() - started
            if store.git.is_initialized():
                diff_body = (
                    store.dream_content_diff() if kind == "scheduled"
                    else result.content_diff
                )
                if kind == "manual" or diff_body:
                    prefix = (
                        "dream: manual run" if kind == "manual"
                        else "dream: periodic memory consolidation"
                    )
                    result.commit_sha = store.git.auto_commit(
                        MemoryStore.build_dream_commit_message(prefix, diff_body),
                    )
            store.compact_history()
            MemoryStore.prune_dream_sessions(loop.sessions)
        return result
