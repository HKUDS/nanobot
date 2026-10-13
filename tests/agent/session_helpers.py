"""Session-worker completion helpers for integration tests."""

import asyncio
import time

from nanobot.agent.loop import AgentLoop
from nanobot.agent.subagent_status import SubagentStatus
from nanobot.bus.events import InboundMessage
from nanobot.runtime_context import (
    RUNTIME_CONTEXT_HISTORY_META,
    RUNTIME_CONTEXT_MESSAGE_META,
    public_history_message,
)


def visible_message(message: dict) -> dict:
    """Project raw runner or persisted messages without model-only context."""
    marker = message.get("_meta", {}).get(RUNTIME_CONTEXT_MESSAGE_META)
    if marker is not None:
        message = {**message, RUNTIME_CONTEXT_HISTORY_META: marker}
    return public_history_message(message)


def save_completed_subagent(loop: AgentLoop, task_id: str, owner: str) -> None:
    """Persist the child that owns a synthetic completion notification."""
    assert loop.subagents.sessions is not None
    now = time.monotonic()
    loop.subagents.sessions.create(SubagentStatus(
        task_id=task_id, label=task_id, task_description="Background work",
        owner=owner, started_at=now, finished_at=now, completed_at=time.time(),
        state="done", phase="done",
    ))


async def run_session(loop: AgentLoop, msg: InboundMessage) -> None:
    """Submit input and wait for its session worker to finish."""
    loop._enqueue_session_message(msg)
    await asyncio.gather(*loop._active_tasks[loop._effective_session_key(msg)])
