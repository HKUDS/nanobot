"""Session-worker completion helpers for integration tests."""

import asyncio
import faulthandler
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


async def save_completed_subagent(loop: AgentLoop, task_id: str, owner: str) -> None:
    """Persist the child that owns a synthetic completion notification."""
    assert loop.subagents.sessions is not None
    now = time.monotonic()
    await loop.subagents.sessions.create(SubagentStatus(
        task_id=task_id, label=task_id, task_description="Background work",
        owner=owner, started_at=now, finished_at=now, completed_at=time.time(),
        state="done", phase="done",
    ))


async def run_session(loop: AgentLoop, msg: InboundMessage) -> None:
    """Submit input and wait for its session worker to finish."""
    (await loop._enqueue_session_message(msg))
    await asyncio.gather(*loop._active_tasks[loop._effective_session_key(msg)])


async def stop_loop(loop: AgentLoop, worker: asyncio.Task[None], *, timeout: float) -> None:
    """Stop an integration loop, retaining native shutdown stacks on timeout."""
    loop.stop()
    try:
        await asyncio.wait_for(worker, timeout=timeout)
    except TimeoutError:
        close_task = loop.sessions.state._close_task
        if close_task is not None:
            close_task.print_stack()
        faulthandler.dump_traceback()
        raise


def mock_session_manager(*_args, **_kwargs):
    """Model the asynchronous state boundary in scheduler-only unit tests."""
    from unittest.mock import AsyncMock, MagicMock

    from nanobot.session.manager import Session, SessionManager
    from nanobot.session.state import SessionState

    manager = MagicMock(spec=SessionManager)
    manager.get_or_create.side_effect = lambda key: Session(key=key)
    manager.state = MagicMock(spec=SessionState)
    manager.state.get = AsyncMock(side_effect=lambda key: manager.get_or_create(key))
    manager.state.read = AsyncMock(return_value=None)
    manager.state.read_metadata = AsyncMock(return_value=None)
    manager.state.list_sessions = AsyncMock(return_value=[])
    manager.state.peek.return_value = None
    return manager
