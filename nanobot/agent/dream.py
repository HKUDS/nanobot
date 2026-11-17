"""Shared manual and scheduled Dream execution over a bounded history snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.agent.memory import MemoryStore

if TYPE_CHECKING:
    from nanobot.agent.loop import AgentLoop


@dataclass
class DreamResult:
    had_input: bool = False
    completed_batches: int = 0
    changed: bool = False
    error: str | None = None
    commit_sha: str | None = None


async def run_dream(loop: AgentLoop, *, commit_prefix: str) -> DreamResult:
    """Drain the pending journal at admission, serializing Dream writers."""
    store = loop.context.memory
    result = DreamResult()

    async def silent(*_args: Any, **_kwargs: Any) -> None:
        pass

    async with store.dream_lock:
        try:
            through_cursor = store.get_latest_cursor()
            batch = store.build_dream_prompt(through_cursor=through_cursor)
            if batch is not None:
                result.had_input = True
                runtime = loop.dream_runtime()
                while batch is not None:
                    prompt, last_cursor = batch
                    response = await loop.process_direct(
                        prompt,
                        session_key=MemoryStore.dream_session_key(),
                        ephemeral=True,
                        tools=store.build_dream_tools(),
                        on_progress=silent,
                        runtime=runtime,
                    )
                    if not MemoryStore.dream_run_completed(response):
                        result.error = MemoryStore.dream_incompletion_reason(response)
                        break
                    store.set_last_dream_cursor(last_cursor)
                    result.completed_batches += 1
                    batch = store.build_dream_prompt(through_cursor=through_cursor)
        except Exception as exc:
            result.error = str(exc)
            logger.exception("Dream failed")
        finally:
            try:
                diff = store.dream_content_diff()
                result.changed = bool(diff)
                if diff and store.git.is_initialized():
                    result.commit_sha = store.git.auto_commit(
                        MemoryStore.build_dream_commit_message(commit_prefix, diff),
                    )
                store.compact_history()
            except Exception as exc:
                failure = f"Memory finalization failed: {exc}"
                result.error = f"{result.error}; {failure}" if result.error else failure
                logger.exception("Dream memory finalization failed")
            await loop.sessions.state.prune_dream_sessions()
    return result
