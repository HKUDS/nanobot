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
    changed: bool = False
    error: str | None = None
    commit_sha: str | None = None


async def run_dream(loop: AgentLoop, *, commit_prefix: str) -> DreamResult:
    """Run one Dream over the pending journal range, serializing writers."""
    store = loop.context.memory
    result = DreamResult()

    async def silent(*_args: Any, **_kwargs: Any) -> None:
        pass

    async with store.dream_lock:
        try:
            history = store.build_dream_prompt()
            if history is not None:
                result.had_input = True
                prompt, last_cursor = history
                response = await loop.process_direct(
                    prompt,
                    session_key=MemoryStore.dream_session_key(),
                    ephemeral=True,
                    tools=store.build_dream_tools(),
                    on_progress=silent,
                    runtime=loop.dream_runtime(),
                )
                if MemoryStore.dream_run_completed(response):
                    store.set_last_dream_cursor(last_cursor)
                else:
                    result.error = MemoryStore.dream_incompletion_reason(response)
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
