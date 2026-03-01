"""OpenFaaS handler for Nanobot A2A channel.

Deploy as a function that exposes the A2A ASGI app.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from nanobot.config.loader import load_config
from nanobot.bus.queue import MessageBus
from nanobot.channels.a2a import A2AChannel
from nanobot.agent.loop import AgentLoop
from nanobot.session.manager import SessionManager
from nanobot.providers.litellm_provider import LiteLLMProvider

_state: dict[str, Any] | None = None


async def get_state() -> dict[str, Any]:
    """Lazy-initialize Nanobot components."""
    global _state
    if _state is None:
        config = load_config()
        bus = MessageBus()

        session_manager = SessionManager(config.workspace_path)

        a2a_channel = A2AChannel(config.channels.a2a, bus, session_manager=session_manager)
        await a2a_channel.start()

        provider = LiteLLMProvider(config)
        agent = AgentLoop(
            bus=bus,
            provider=provider,
            workspace=config.workspace_path,
            model=config.agents.defaults.model,
            max_iterations=config.agents.defaults.max_tool_iterations,
            temperature=config.agents.defaults.temperature,
            max_tokens=config.agents.defaults.max_tokens,
            memory_window=config.agents.defaults.memory_window,
            reasoning_effort=config.agents.defaults.reasoning_effort,
            session_manager=session_manager,
            channels_config=config.channels,
        )
        asyncio.create_task(agent.run())

        _state = {
            "channel": a2a_channel,
            "bus": bus,
            "agent": agent,
        }

    return _state


async def handle(scope: dict, receive: callable, send: callable) -> None:
    """OpenFaaS ASGI entrypoint - routes all requests to A2A app."""
    state = await get_state()
    channel = state["channel"]
    app = channel.get_asgi_app()
    await app(scope, receive, send)


async def health(request: Any) -> JSONResponse:
    """Health check endpoint."""
    return JSONResponse({"status": "healthy"})


# OpenFaaS expects a 'handle' function at module level
# This is the main ASGI entrypoint
async def main_app(scope: dict, receive: callable, send: callable) -> None:
    """Main ASGI app that routes to health or A2A handler."""
    if scope["type"] == "http":
        path = scope.get("path", "")
        if path == "/health":
            response = JSONResponse({"status": "healthy"})
            await response(scope, receive, send)
            return
    # All other requests go to A2A handler
    await handle(scope, receive, send)


# For OpenFaaS, export 'handle' as the entrypoint
handle = main_app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
