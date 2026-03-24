"""Gateway and Web UI CLI commands.

Extracted from ``commands.py`` — plain functions registered by the Typer app
in the main command module.
"""

from __future__ import annotations

import asyncio
import errno
import os
from pathlib import Path
from typing import Any

import typer

from nanobot import __logo__
from nanobot.cli._shared import (
    _configure_log_sink,
    _make_agent_config,
    _make_provider,
    console,
)


def gateway(
    port: int = typer.Option(18790, "--port", "-p", help="Gateway port"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
) -> None:
    """Start the nanobot gateway."""
    from nanobot.agent.agent_factory import build_agent
    from nanobot.bus.queue import MessageBus
    from nanobot.channels.manager import ChannelManager
    from nanobot.config.loader import get_data_dir, load_config
    from nanobot.cron.service import CronService
    from nanobot.cron.types import CronJob
    from nanobot.heartbeat.service import HeartbeatService
    from nanobot.session.manager import SessionManager

    if verbose:
        import logging

        logging.basicConfig(level=logging.DEBUG)
        from loguru import logger as _gw_logger

        _gw_logger.enable("nanobot")

    console.print(f"{__logo__} Starting nanobot gateway on port {port}...")

    config = load_config()

    # Initialize langfuse observability (auto-instruments litellm via OTEL)
    from nanobot.observability.langfuse import init_langfuse
    from nanobot.observability.langfuse import shutdown as shutdown_langfuse

    init_langfuse(config.langfuse)

    # Apply structured logging config
    from loguru import logger as _gw_logger2

    _configure_log_sink(config, _gw_logger2)

    bus = MessageBus()
    provider = _make_provider(config)
    session_manager = SessionManager(config.workspace_path)

    # Create cron service first (callback set after agent creation)
    cron_store_path = get_data_dir() / "cron" / "jobs.json"
    cron = CronService(cron_store_path)

    # Create agent with cron service
    agent = build_agent(
        bus=bus,
        provider=provider,
        config=_make_agent_config(config),
        brave_api_key=config.tools.web.search.api_key or None,
        exec_config=config.tools.exec,
        cron_service=cron,
        session_manager=session_manager,
        mcp_servers=config.tools.mcp_servers,
        channels_config=config.channels,
        routing_config=config.agents.routing,
    )

    # Set cron callback (needs agent)
    async def on_cron_job(job: CronJob) -> str | None:
        """Execute a cron job through the agent."""
        response = await agent.process_direct(
            job.payload.message,
            session_key=f"cron:{job.id}",
            channel=job.payload.channel or "cli",
            chat_id=job.payload.to or "direct",
        )
        if job.payload.deliver and job.payload.to:
            from nanobot.bus.events import OutboundMessage

            await bus.publish_outbound(
                OutboundMessage(
                    channel=job.payload.channel or "cli",
                    chat_id=job.payload.to,
                    content=response or "",
                )
            )
        return response

    cron.on_job = on_cron_job

    # Create channel manager
    channels = ChannelManager(config, bus)

    # Wire honest delivery: MessageTool gets synchronous feedback via deliver()
    agent.set_deliver_callback(channels.deliver)

    # Wire contacts provider: agent refreshes known contacts each turn
    agent.set_contacts_provider(channels.get_email_contacts)
    agent.context.set_contacts_context(channels.get_email_contacts())

    # Wire email fetch so check_email tool can read the mailbox on demand
    if config.channels.email.enabled:
        agent.set_email_fetch(channels.fetch_emails, channels.fetch_unread_emails)

    def _pick_heartbeat_target() -> tuple[str, str]:
        """Pick a routable channel/chat target for heartbeat-triggered messages."""
        enabled = set(channels.enabled_channels)
        # Prefer the most recently updated non-internal session on an enabled channel.
        for item in session_manager.list_sessions():
            key = item.get("key") or ""
            if ":" not in key:
                continue
            channel, chat_id = key.split(":", 1)
            if channel in {"cli", "system"}:
                continue
            if channel in enabled and chat_id:
                return channel, chat_id
        # Fallback keeps prior behavior but remains explicit.
        return "cli", "direct"

    # Create heartbeat service
    async def on_heartbeat_execute(tasks: str) -> str:
        """Phase 2: execute heartbeat tasks through the full agent loop."""
        from nanobot.agent.callbacks import ProgressEvent

        channel, chat_id = _pick_heartbeat_target()

        async def _silent(event: ProgressEvent) -> None:  # noqa: ARG001
            pass

        return await agent.process_direct(
            tasks,
            session_key="heartbeat",
            channel=channel,
            chat_id=chat_id,
            on_progress=_silent,
        )

    async def on_heartbeat_notify(response: str) -> None:
        """Deliver a heartbeat response to the user's channel."""
        from nanobot.bus.events import OutboundMessage

        channel, chat_id = _pick_heartbeat_target()
        if channel == "cli":
            return  # No external channel available to deliver to
        await bus.publish_outbound(
            OutboundMessage(channel=channel, chat_id=chat_id, content=response)
        )

    hb_cfg = config.gateway.heartbeat
    heartbeat = HeartbeatService(
        workspace=config.workspace_path,
        provider=provider,
        model=hb_cfg.model or agent.model,
        on_execute=on_heartbeat_execute,
        on_notify=on_heartbeat_notify,
        on_health_refresh=agent._capabilities.refresh_health,
        interval_s=hb_cfg.interval_s,
        enabled=hb_cfg.enabled,
    )

    if channels.enabled_channels:
        console.print(f"[green]✓[/green] Channels enabled: {', '.join(channels.enabled_channels)}")
    else:
        console.print("[yellow]Warning: No channels enabled[/yellow]")

    cron_status = cron.status()
    if cron_status["jobs"] > 0:
        console.print(f"[green]✓[/green] Cron: {cron_status['jobs']} scheduled jobs")

    console.print(f"[green]✓[/green] Heartbeat: every {hb_cfg.interval_s}s")

    # Resolve web UI parameters if enabled
    web_cfg = config.channels.web
    web_app = None
    if web_cfg.enabled:
        from pathlib import Path as _Path

        from nanobot.channels.web import WebChannel
        from nanobot.web.app import create_app

        web_channel = channels.get_channel("web")
        assert isinstance(web_channel, WebChannel)
        frontend_dist = _Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
        web_app = create_app(
            agent,
            session_manager,
            web_channel,
            static_dir=frontend_dist if frontend_dist.is_dir() else None,
            api_key=web_cfg.api_key,
            rate_limit_per_minute=web_cfg.rate_limit_per_minute,
        )
        if frontend_dist.is_dir():
            console.print(f"[green]✓[/green] Web UI: http://{web_cfg.host}:{web_cfg.port}")
        else:
            console.print(
                f"[green]✓[/green] Web API: http://{web_cfg.host}:{web_cfg.port} (no frontend)"
            )

    async def run() -> None:
        health_server: asyncio.Server | None = None
        uvi_server = None
        try:
            if web_app is not None:
                # Web channel enabled: FastAPI serves health + web UI
                import uvicorn

                uvi_config = uvicorn.Config(
                    web_app,
                    host=web_cfg.host,
                    port=web_cfg.port,
                    log_level="warning",
                )
                uvi_server = uvicorn.Server(uvi_config)
                # Also start bare health server on the gateway port for Docker HEALTHCHECK
                from nanobot.web.health import start_health_server

                try:
                    health_server = await start_health_server(agent, port=port)
                except OSError as exc:
                    if exc.errno != errno.EADDRINUSE:
                        raise
                    console.print(
                        "[yellow]Warning:[/yellow] Gateway health port "
                        f"{port} is already in use; continuing because the web UI "
                        f"still exposes /health on http://{web_cfg.host}:{web_cfg.port}"
                    )
            else:
                # No web channel: lightweight health endpoint only
                from nanobot.web.health import start_health_server

                try:
                    health_server = await start_health_server(agent, port=port)
                except OSError as exc:
                    if exc.errno == errno.EADDRINUSE:
                        console.print(
                            "[red]Error:[/red] Gateway health port "
                            f"{port} is already in use. Stop the other process or "
                            "start nanobot with a different --port."
                        )
                    raise

            await cron.start()
            await heartbeat.start()

            coros: list[Any] = [agent.run(), channels.start_all()]
            if uvi_server is not None:
                coros.append(uvi_server.serve())
            await asyncio.gather(*coros)
        except KeyboardInterrupt:
            console.print("\nShutting down...")
        finally:
            if health_server:
                health_server.close()
                await health_server.wait_closed()
            await agent.close_mcp()
            heartbeat.stop()
            cron.stop()
            agent.stop()
            await channels.stop_all()
            shutdown_langfuse()

    asyncio.run(run())


def ui(
    port: int = typer.Option(8000, "--port", "-p", help="Web UI port"),
    host: str = typer.Option("127.0.0.1", "--host", help="Bind address"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
) -> None:
    """Start the nanobot web UI (FastAPI + assistant-ui)."""
    try:
        import uvicorn  # noqa: F401
    except ImportError:
        console.print(
            "[red]Error: Web UI requires extra dependencies.[/red]\n"
            "Install with: pip install nanobot-ai[web]"
        )
        raise typer.Exit(1) from None

    from nanobot.agent.agent_factory import build_agent
    from nanobot.bus.queue import MessageBus
    from nanobot.channels.web import WebChannel
    from nanobot.config.loader import get_data_dir, load_config
    from nanobot.cron.service import CronService
    from nanobot.observability.langfuse import init_langfuse
    from nanobot.observability.langfuse import shutdown as shutdown_langfuse
    from nanobot.session.manager import SessionManager
    from nanobot.web.app import create_app

    if verbose:
        import logging

        logging.basicConfig(level=logging.DEBUG)

    console.print(f"{__logo__} Starting nanobot web UI on http://{host}:{port}")

    config = load_config()

    # Observability
    init_langfuse(config.langfuse)

    bus = MessageBus()
    provider = _make_provider(config)
    session_manager = SessionManager(config.workspace_path)

    cron_store_path = get_data_dir() / "cron" / "jobs.json"
    cron = CronService(cron_store_path)

    agent_loop = build_agent(
        bus=bus,
        provider=provider,
        config=_make_agent_config(config),
        brave_api_key=config.tools.web.search.api_key or None,
        exec_config=config.tools.exec,
        cron_service=cron,
        session_manager=session_manager,
        mcp_servers=config.tools.mcp_servers,
        channels_config=config.channels,
        routing_config=config.agents.routing,
    )

    web_channel = WebChannel(config=None, bus=bus)

    # Check for built frontend static files
    frontend_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"

    app = create_app(
        agent_loop,
        session_manager,
        web_channel,
        static_dir=frontend_dist if frontend_dist.is_dir() else None,
        owns_lifecycle=True,
        api_key=os.environ.get("NANOBOT_WEB_API_KEY", ""),
    )

    console.print(f"[green]✓[/green] Agent initialized (model: {agent_loop.model})")
    if frontend_dist.is_dir():
        console.print(f"[green]✓[/green] Serving frontend from {frontend_dist}")
    else:
        console.print("[yellow]ℹ[/yellow] No built frontend found — API-only mode")
        console.print("  Run frontend dev server: cd frontend && npm run dev")

    import uvicorn

    async def _run() -> None:
        uvi_config = uvicorn.Config(
            app,
            host=host,
            port=port,
            log_level="info" if verbose else "warning",
        )
        server = uvicorn.Server(uvi_config)

        await web_channel.start()
        try:
            await asyncio.gather(
                agent_loop.run(),
                server.serve(),
            )
        except KeyboardInterrupt:
            console.print("\nShutting down...")
        finally:
            await web_channel.stop()
            await agent_loop.close_mcp()
            agent_loop.stop()
            shutdown_langfuse()

    asyncio.run(_run())
