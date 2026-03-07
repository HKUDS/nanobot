"""OpenFaaS handler for Nanobot A2A channel.

Deploy as a function that exposes the A2A ASGI app with full agent capabilities
including cron scheduling and heartbeat checks.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
import traceback
from typing import Any

from starlette.responses import JSONResponse

# Configure logging to stderr so OpenFaaS watchdog captures it
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("openfaas_handler")

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.channels.manager import ChannelManager
from nanobot.channels.a2a import A2AChannel
from nanobot.config.loader import load_config
from nanobot.cron.service import CronService
from nanobot.dashboard import get_dashboard_app
from nanobot.heartbeat.service import HeartbeatService
from nanobot.providers.custom_provider import CustomProvider
from nanobot.providers.litellm_provider import LiteLLMProvider
from nanobot.session.manager import SessionManager

_state: dict[str, Any] | None = None
_state_lock: asyncio.Lock | None = None


def _get_state_lock() -> asyncio.Lock:
    """Return (creating if needed) the module-level init lock.

    We defer creation to first use so the lock is created inside the running
    event loop, avoiding the 'no current event loop' error on import.
    """
    global _state_lock
    if _state_lock is None:
        _state_lock = asyncio.Lock()
    return _state_lock


async def get_state() -> dict[str, Any]:
    """Lazy-initialize Nanobot components (safe against concurrent first calls)."""
    global _state
    if _state is not None:
        return _state
    async with _get_state_lock():
        if _state is not None:  # re-check after acquiring lock
            return _state
        logger.info("Initializing Nanobot components...")
        config = load_config()
        logger.info("Config loaded. Workspace: %s", config.workspace_path)
        bus = MessageBus()

        session_manager = SessionManager(config.workspace_path)

        # Create channel manager — handles A2A channel creation, outbound
        # dispatch, and progress-message filtering (send_tool_hints /
        # send_progress config flags).  This replaces the manual A2AChannel
        # instantiation and custom _dispatch_outbound() that previously
        # duplicated logic from ChannelManager._dispatch_outbound().
        channels = ChannelManager(config, bus)
        a2a_channel = channels.get_channel("a2a")
        if not isinstance(a2a_channel, A2AChannel):
            raise RuntimeError("A2A channel not initialised — is channels.a2a.enabled set?")

        # Create provider and agent (mirror _make_provider logic from cli/commands.py)
        model = config.agents.defaults.model
        provider_name = config.get_provider_name(model)
        provider_config = config.get_provider(model)

        if provider_name == "custom":
            provider = CustomProvider(
                api_key=provider_config.api_key if provider_config else "no-key",
                api_base=config.get_api_base(model) or "http://localhost:8000/v1",
                default_model=model,
            )
        else:
            provider = LiteLLMProvider(
                api_key=provider_config.api_key if provider_config else None,
                api_base=config.get_api_base(model),
                default_model=model,
                extra_headers=provider_config.extra_headers if provider_config else None,
                provider_name=provider_name,
            )
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
            suppress_builtin_skills=config.agents.defaults.suppress_builtin_skills or None,
            mcp_servers=config.tools.mcp_servers,
        )

        # Create cron service
        cron_store_path = config.workspace_path / "cron.db"
        cron = CronService(cron_store_path)

        async def on_cron_job(job: Any) -> str:
            """Execute cron job through the agent."""
            response = await agent.process_direct(
                job.payload.message,
                session_key=f"cron:{job.id}",
                channel=job.payload.channel or "a2a",
                chat_id=job.payload.to or "cron",
            )
            if job.payload.deliver and job.payload.to:
                from nanobot.bus.events import OutboundMessage

                await bus.publish_outbound(
                    OutboundMessage(
                        channel=job.payload.channel or "a2a",
                        chat_id=job.payload.to,
                        content=response or "",
                    )
                )
            return response

        cron.on_job = on_cron_job

        # Create heartbeat service
        async def on_heartbeat_execute(tasks: str) -> str:
            """Execute heartbeat tasks through the agent."""
            return await agent.process_direct(
                tasks,
                session_key="heartbeat",
                channel="a2a",
                chat_id="heartbeat",
            )

        async def on_heartbeat_notify(response: str) -> None:
            """Deliver heartbeat response."""
            from nanobot.bus.events import OutboundMessage

            await bus.publish_outbound(
                OutboundMessage(
                    channel="a2a",
                    chat_id="heartbeat",
                    content=response,
                )
            )

        hb_cfg = config.gateway.heartbeat
        heartbeat = HeartbeatService(
            workspace=config.workspace_path,
            provider=provider,
            model=agent.model,
            on_execute=on_heartbeat_execute,
            on_notify=on_heartbeat_notify,
            interval_s=hb_cfg.interval_s,
            enabled=hb_cfg.enabled,
        )

        # Unregister tools not needed in this deployment
        agent.tools.unregister("web_search")

        # Start all services — ChannelManager.start_all() launches the
        # outbound dispatcher (with proper progress filtering) and starts
        # every enabled channel.  It awaits internally via asyncio.gather,
        # so we wrap it in a task to avoid blocking initialisation.
        await cron.start()
        await heartbeat.start()
        asyncio.create_task(agent.run())

        def _log_task_error(task: asyncio.Task) -> None:
            if not task.cancelled() and (exc := task.exception()):
                logger.error("channels.start_all failed: {}", exc)

        asyncio.create_task(channels.start_all()).add_done_callback(_log_task_error)

        _state = {
            "channels": channels,
            "bus": bus,
            "agent": agent,
            "cron": cron,
            "heartbeat": heartbeat,
            "sessions": session_manager,
            "config": config,
            "start_time": time.monotonic(),
        }

    return _state


_cached_asgi_app = None
_cached_dashboard_app = None


async def _a2a_handler(scope: dict, receive: callable, send: callable) -> None:
    """Forward request to the A2A Starlette app (lazy-init on first call)."""
    global _cached_asgi_app
    path = scope.get("path", "?")
    method = scope.get("method", "?")
    try:
        state = await get_state()
        if _cached_asgi_app is None:
            channel = state["channels"].get_channel("a2a")
            _cached_asgi_app = channel.get_asgi_app()
            logger.info("A2A ASGI app built and cached")
        await _cached_asgi_app(scope, receive, send)
    except Exception as e:
        logger.error(
            "Error handling %s %s: [%s] %s",
            method,
            path,
            type(e).__name__,
            e,
        )
        logger.error("Traceback:\n%s", traceback.format_exc())
        if scope.get("type") == "http":
            response = JSONResponse(
                {"error": str(e), "type": type(e).__name__},
                status_code=500,
            )
            await response(scope, receive, send)


async def _dashboard_handler(scope: dict, receive: callable, send: callable) -> None:
    """Route dashboard requests (lazy-init on first call)."""
    global _cached_dashboard_app
    if _cached_dashboard_app is None:
        _cached_dashboard_app = get_dashboard_app(lambda: _state)
        logger.info("Dashboard app built and cached")
    await _cached_dashboard_app(scope, receive, send)


# A2A protocol path prefixes (all methods).  Note: the A2A JSON-RPC endpoint
# is POST /, so we use the HTTP method to disambiguate the root path.
_A2A_PATH_PREFIXES = (
    "/.well-known/",
    "/agent/",  # authenticated extended card: /agent/authenticatedExtendedCard
)


def _is_a2a_request(method: str, path: str) -> bool:
    """Return True if this request belongs to the A2A SDK, not the dashboard."""
    # POST / is the A2A JSON-RPC endpoint (DEFAULT_RPC_URL = "/")
    if method == "POST" and path == "/":
        return True
    return any(path.startswith(p) for p in _A2A_PATH_PREFIXES)


async def handle(scope: dict, receive: callable, send: callable) -> None:
    """OpenFaaS ASGI entrypoint — dashboard at /, A2A protocol on its own paths."""
    if scope["type"] == "lifespan":
        # Handle ASGI lifespan protocol directly so uvicorn startup/shutdown
        # succeeds even before the heavy A2A state is initialised.
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                logger.info("ASGI lifespan startup")
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                logger.info("ASGI lifespan shutdown")
                await send({"type": "lifespan.shutdown.complete"})
                return
            else:
                return

    if scope["type"] == "http":
        path = scope.get("path", "")
        method = scope.get("method", "GET")
        logger.debug("Incoming request: %s %s", method, path)

        if _is_a2a_request(method, path):
            await _a2a_handler(scope, receive, send)
        else:
            # Dashboard handles GET /, /health, /api/*, /static/*
            await _dashboard_handler(scope, receive, send)
        return

    # WebSocket or other — pass to A2A
    await _a2a_handler(scope, receive, send)


if __name__ == "__main__":
    import uvicorn

    # For local development: run the handle function as ASGI app
    uvicorn.run(
        "a2a_openfaas_handler:handle",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        reload=False,
    )
