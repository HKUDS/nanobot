"""Dispatch in-process runtime control messages before turn admission."""

from collections.abc import Awaitable, Callable
from pathlib import Path

from nanobot.agent.tools import image_generation as image_generation_tools
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.bus.events import (
    INBOUND_META_RUNTIME_CONTROL,
    RUNTIME_CONTROL_SESSION_DISCARD,
    InboundMessage,
)


async def handle_runtime_control(
    msg: InboundMessage,
    *,
    workspace: Path,
    tools: ToolRegistry,
    discard_session: Callable[[str], Awaitable[None]],
) -> bool:
    if msg.metadata.get(INBOUND_META_RUNTIME_CONTROL) == RUNTIME_CONTROL_SESSION_DISCARD:
        await discard_session(msg.session_key)
        return True
    return await image_generation_tools.handle_runtime_control(msg, workspace, tools)
