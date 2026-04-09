"""Factory for assembling and running the nanobot gateway."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Callable, Coroutine

from loguru import logger

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.channels.manager import ChannelManager
from nanobot.cron.service import CronService
from nanobot.cron.types import CronPayload
from nanobot.heartbeat.service import HeartbeatService
from nanobot.session.manager import SessionManager

@dataclass(frozen=True)
class GatewayComponentClasses:
    """Injectable implementation classes for the gateway assembly."""

    message_bus_cls: type[MessageBus] = MessageBus
    session_manager_cls: type[SessionManager] = SessionManager
    agent_loop_cls: type[AgentLoop] = AgentLoop
    channel_manager_cls: type[ChannelManager] = ChannelManager
    cron_service_cls: type[CronService] = CronService
    heartbeat_service_cls: type[HeartbeatService] = HeartbeatService


@dataclass(frozen=True)
class GatewayRuntime:
    """Resolved gateway configuration and async entrypoint."""

    port: int
    run: Callable[[], Coroutine[Any, Any, None]]


def create_gateway_runtime(
    *,
    port: int | None = None,
    workspace: str | None = None,
    config_path: str | None = None,
    verbose: bool = False,
    components: GatewayComponentClasses | None = None,
) -> GatewayRuntime:
    """Load config, wire agent/cron/heartbeat/channels, return runnable gateway.

    Pass ``components`` to substitute core classes (``MessageBus``, ``SessionManager``,
    ``AgentLoop``, ``ChannelManager``, ``CronService``, ``HeartbeatService``) with
    subclasses for custom behavior.
    """
    from nanobot import __logo__, __version__
    from nanobot.cli.commands import (
        _load_runtime_config,
        _make_provider,
        _migrate_cron_store,
        console,
        sync_workspace_templates,
    )
    from nanobot.config.paths import is_default_workspace
    from nanobot.cron.types import CronJob

    if verbose:
        import logging

        logging.basicConfig(level=logging.DEBUG)

    config = _load_runtime_config(config_path, workspace)
    resolved_port = port if port is not None else config.gateway.port

    console.print(
        f"{__logo__} Starting nanobot gateway version {__version__} on port {resolved_port}..."
    )
    sync_workspace_templates(config.workspace_path)

    component_classes = components or GatewayComponentClasses()

    bus = component_classes.message_bus_cls()
    provider = _make_provider(config)
    session_manager = component_classes.session_manager_cls(config.workspace_path)

    if is_default_workspace(config.workspace_path):
        _migrate_cron_store(config)

    cron_store_path = config.workspace_path / "cron" / "jobs.json"
    cron = component_classes.cron_service_cls(cron_store_path)

    agent = component_classes.agent_loop_cls(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        model=config.agents.defaults.model,
        max_iterations=config.agents.defaults.max_tool_iterations,
        context_window_tokens=config.agents.defaults.context_window_tokens,
        web_config=config.tools.web,
        context_block_limit=config.agents.defaults.context_block_limit,
        max_tool_result_chars=config.agents.defaults.max_tool_result_chars,
        provider_retry_mode=config.agents.defaults.provider_retry_mode,
        exec_config=config.tools.exec,
        cron_service=cron,
        restrict_to_workspace=config.tools.restrict_to_workspace,
        session_manager=session_manager,
        mcp_servers=config.tools.mcp_servers,
        channels_config=config.channels,
        timezone=config.agents.defaults.timezone,
    )

    async def on_cron_job(job: CronJob) -> str | None:
        if job.name == "dream":
            try:
                await agent.dream.run()
                logger.info("Dream cron job completed")
            except Exception:
                logger.exception("Dream cron job failed")
            return None

        from nanobot.agent.tools.cron import CronTool
        from nanobot.agent.tools.message import MessageTool
        from nanobot.bus.events import OutboundMessage
        from nanobot.utils.evaluator import evaluate_response

        reminder_note = (
            "[Scheduled Task] Timer finished.\n\n"
            f"Task '{job.name}' has been triggered.\n"
            f"Scheduled instruction: {job.payload.message}"
        )

        cron_tool = agent.tools.get("cron")
        cron_token = None
        if isinstance(cron_tool, CronTool):
            cron_token = cron_tool.set_cron_context(True)
        try:
            resp = await agent.process_direct(
                reminder_note,
                session_key=f"cron:{job.id}",
                channel=job.payload.channel or "cli",
                chat_id=job.payload.to or "direct",
            )
        finally:
            if isinstance(cron_tool, CronTool) and cron_token is not None:
                cron_tool.reset_cron_context(cron_token)

        response = resp.content if resp else ""

        message_tool = agent.tools.get("message")
        if isinstance(message_tool, MessageTool) and message_tool._sent_in_turn:
            return response

        if job.payload.deliver and job.payload.to and response:
            should_notify = await evaluate_response(
                response,
                reminder_note,
                provider,
                agent.model,
            )
            if should_notify:
                await bus.publish_outbound(
                    OutboundMessage(
                        channel=job.payload.channel or "cli",
                        chat_id=job.payload.to,
                        content=response,
                    )
                )
        return response

    cron.on_job = on_cron_job

    channels = component_classes.channel_manager_cls(config, bus)

    def _pick_heartbeat_target() -> tuple[str, str]:
        enabled = set(channels.enabled_channels)
        for item in session_manager.list_sessions():
            key = item.get("key") or ""
            if ":" not in key:
                continue
            channel, chat_id = key.split(":", 1)
            if channel in {"cli", "system"}:
                continue
            if channel in enabled and chat_id:
                return channel, chat_id
        return "cli", "direct"

    heartbeat_config = config.gateway.heartbeat

    async def on_heartbeat_execute(tasks: str) -> str:
        channel, chat_id = _pick_heartbeat_target()

        async def _silent(*_args, **_kwargs):
            pass

        resp = await agent.process_direct(
            tasks,
            session_key="heartbeat",
            channel=channel,
            chat_id=chat_id,
            on_progress=_silent,
        )

        session = agent.sessions.get_or_create("heartbeat")
        session.retain_recent_legal_suffix(heartbeat_config.keep_recent_messages)
        agent.sessions.save(session)

        return resp.content if resp else ""

    async def on_heartbeat_notify(response: str) -> None:
        from nanobot.bus.events import OutboundMessage

        channel, chat_id = _pick_heartbeat_target()
        if channel == "cli":
            return
        await bus.publish_outbound(
            OutboundMessage(channel=channel, chat_id=chat_id, content=response)
        )

    heartbeat = component_classes.heartbeat_service_cls(
        workspace=config.workspace_path,
        provider=provider,
        model=agent.model,
        on_execute=on_heartbeat_execute,
        on_notify=on_heartbeat_notify,
        interval_s=heartbeat_config.interval_s,
        enabled=heartbeat_config.enabled,
        timezone=config.agents.defaults.timezone,
    )

    if channels.enabled_channels:
        console.print(
            f"[green]✓[/green] Channels enabled: {', '.join(channels.enabled_channels)}"
        )
    else:
        console.print("[yellow]Warning: No channels enabled[/yellow]")

    cron_status = cron.status()
    if cron_status["jobs"] > 0:
        console.print(f"[green]✓[/green] Cron: {cron_status['jobs']} scheduled jobs")

    console.print(f"[green]✓[/green] Heartbeat: every {heartbeat_config.interval_s}s")

    dream_cfg = config.agents.defaults.dream
    if dream_cfg.model_override:
        agent.dream.model = dream_cfg.model_override
    agent.dream.max_batch_size = dream_cfg.max_batch_size
    agent.dream.max_iterations = dream_cfg.max_iterations
    cron.register_system_job(
        CronJob(
            id="dream",
            name="dream",
            schedule=dream_cfg.build_schedule(config.agents.defaults.timezone),
            payload=CronPayload(kind="system_event"),
        )
    )
    console.print(f"[green]✓[/green] Dream: {dream_cfg.describe_schedule()}")

    async def run() -> None:
        try:
            await cron.start()
            await heartbeat.start()
            await asyncio.gather(
                agent.run(),
                channels.start_all(),
            )
        except KeyboardInterrupt:
            console.print("\nShutting down...")
        except Exception:
            import traceback

            console.print("\n[red]Error: Gateway crashed unexpectedly[/red]")
            console.print(traceback.format_exc())
        finally:
            await agent.close_mcp()
            heartbeat.stop()
            cron.stop()
            agent.stop()
            await channels.stop_all()

    return GatewayRuntime(port=resolved_port, run=run)
