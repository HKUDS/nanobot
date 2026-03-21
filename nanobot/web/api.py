"""REST API routes for the dashboard."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

if TYPE_CHECKING:
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus
    from nanobot.channels.manager import ChannelManager
    from nanobot.config.schema import Config


class SendMessageRequest(BaseModel):
    content: str
    agent: str = "main"  # "main" or named agent name
    session_key: str = "web:dashboard"


class _ApiState:
    """Holds references injected at startup."""

    agent_loop: AgentLoop | None = None
    channel_manager: ChannelManager | None = None
    bus: MessageBus | None = None
    config: Config | None = None
    start_time: float = 0.0


state = _ApiState()
router = APIRouter(prefix="/api")


def configure(
    agent_loop: "AgentLoop",
    channel_manager: "ChannelManager",
    bus: "MessageBus",
    config: "Config",
) -> None:
    state.agent_loop = agent_loop
    state.channel_manager = channel_manager
    state.bus = bus
    state.config = config
    state.start_time = time.time()


# ------------------------------------------------------------------
# System
# ------------------------------------------------------------------


@router.get("/status")
async def get_status() -> dict[str, Any]:
    uptime = int(time.time() - state.start_time) if state.start_time else 0
    return {
        "uptime_seconds": uptime,
        "model": state.agent_loop.model if state.agent_loop else None,
        "queue_inbound": state.bus.inbound_size if state.bus else 0,
        "queue_outbound": state.bus.outbound_size if state.bus else 0,
        "channels": state.channel_manager.enabled_channels if state.channel_manager else [],
        "agents_count": len(state.agent_loop.agent_registry.list_agents()) + 1 if state.agent_loop else 0,
    }


# ------------------------------------------------------------------
# Agents
# ------------------------------------------------------------------


@router.get("/agents")
async def list_agents() -> list[dict[str, Any]]:
    if not state.agent_loop:
        return []

    agents = [
        {
            "name": "main",
            "identity": "Main agent",
            "model": state.agent_loop.model,
            "aliases": [],
            "max_iterations": state.agent_loop.max_iterations,
        }
    ]

    for agent in state.agent_loop.agent_registry.list_agents():
        agents.append({
            "name": agent.name,
            "identity": agent.config.identity[:200] if agent.config.identity else "",
            "model": state.agent_loop.agent_registry.get_model(agent),
            "aliases": agent.config.aliases,
            "max_iterations": agent.config.max_iterations,
        })

    return agents


@router.get("/agents/{name}")
async def get_agent(name: str) -> dict[str, Any]:
    if not state.agent_loop:
        raise HTTPException(404, "Agent loop not initialized")

    if name == "main":
        return {
            "name": "main",
            "identity": "Main agent",
            "model": state.agent_loop.model,
            "aliases": [],
            "max_iterations": state.agent_loop.max_iterations,
            "tools": [t.name for t in state.agent_loop.tools._tools.values()],
        }

    agent = state.agent_loop.agent_registry.get(name)
    if not agent:
        raise HTTPException(404, f"Agent '{name}' not found")

    return {
        "name": agent.name,
        "identity": agent.config.identity,
        "model": state.agent_loop.agent_registry.get_model(agent),
        "aliases": agent.config.aliases,
        "max_iterations": agent.config.max_iterations,
        "tools": [t.name for t in agent.tools._tools.values()],
    }


# ------------------------------------------------------------------
# Sessions
# ------------------------------------------------------------------


@router.get("/sessions")
async def list_sessions() -> list[dict[str, Any]]:
    if not state.agent_loop:
        return []
    return state.agent_loop.sessions.list_sessions()


@router.get("/sessions/{key:path}")
async def get_session(key: str) -> dict[str, Any]:
    if not state.agent_loop:
        raise HTTPException(404, "Not initialized")

    session = state.agent_loop.sessions.get_or_create(key)
    messages = []
    for msg in session.messages[-200:]:  # Last 200 messages
        entry = {
            "role": msg.get("role", ""),
            "content": _truncate_content(msg.get("content", "")),
            "timestamp": msg.get("timestamp", ""),
        }
        if msg.get("tool_calls"):
            entry["tool_calls"] = [
                {"name": tc.get("function", {}).get("name", ""), "id": tc.get("id", "")}
                for tc in msg["tool_calls"]
            ]
        if msg.get("name"):
            entry["tool_name"] = msg["name"]
        messages.append(entry)

    return {
        "key": session.key,
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat(),
        "message_count": len(session.messages),
        "messages": messages,
    }


@router.delete("/sessions/{key:path}")
async def clear_session(key: str) -> dict[str, str]:
    if not state.agent_loop:
        raise HTTPException(404, "Not initialized")

    session = state.agent_loop.sessions.get_or_create(key)
    session.clear()
    state.agent_loop.sessions.save(session)
    return {"status": "cleared", "key": key}


# ------------------------------------------------------------------
# Channels
# ------------------------------------------------------------------


@router.get("/channels")
async def list_channels() -> dict[str, Any]:
    if not state.channel_manager:
        return {}
    return state.channel_manager.get_status()


# ------------------------------------------------------------------
# Send message
# ------------------------------------------------------------------


@router.post("/send")
async def send_message(req: SendMessageRequest) -> dict[str, str]:
    if not state.agent_loop or not state.bus:
        raise HTTPException(503, "Agent not ready")

    from nanobot.bus.events import InboundMessage

    msg = InboundMessage(
        channel="web",
        sender_id="dashboard",
        chat_id="dashboard",
        content=req.content,
        session_key_override=req.session_key,
    )
    await state.bus.publish_inbound(msg)
    return {"status": "sent", "session_key": req.session_key}


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _truncate_content(content: Any, max_len: int = 1000) -> Any:
    """Truncate content for API response."""
    if isinstance(content, str):
        return content[:max_len] + "..." if len(content) > max_len else content
    if isinstance(content, list):
        result = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text", "")
                result.append({**item, "text": text[:max_len]})
            else:
                result.append(item)
        return result
    return content
