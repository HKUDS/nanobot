"""Session-worker completion helpers for integration tests."""

import asyncio

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage


async def run_session(loop: AgentLoop, msg: InboundMessage) -> None:
    """Submit input and wait for its session worker to finish."""
    loop._enqueue_session_message(msg)
    await asyncio.gather(*loop._active_tasks[loop._effective_session_key(msg)])
