"""Assemble and run one claimed Gateway, including protected updater startup."""

from __future__ import annotations

import asyncio
import signal
from collections.abc import Awaitable, Callable, Coroutine
from contextlib import ExitStack, suppress
from dataclasses import dataclass, replace
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from loguru import logger
from rich.console import Console

from nanobot import __logo__, __version__
from nanobot.agent.hook import AgentHook, AgentRunHookContext
from nanobot.agent.hooks import create_file_edit_activity_hook
from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.image_generation import (
    register_image_generation_tool,
    reload_image_generation_tool,
)
from nanobot.agent.tools.mcp import MCPProvider
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.bus.events import OutboundMessage
from nanobot.config.paths import get_data_dir, is_default_workspace
from nanobot.config.schema import Config
from nanobot.cron.migration import migrate_legacy_cron_store
from nanobot.gateway.health import serve_health
from nanobot.gateway.runtime import GatewayInstance, GatewayRuntime
from nanobot.installation_lock import installation_access
from nanobot.utils.helpers import sync_workspace_templates
from nanobot.utils.token_encoding import warmup_token_encoding
from nanobot.webui.context_source_hook import create_context_source_hook

if TYPE_CHECKING:
    from nanobot.bus.queue import MessageBus
    from nanobot.channels.manager import ChannelManager
    from nanobot.session.manager import SessionManager
    from nanobot.update_profiles import ProfileReceipt
    from nanobot.update_restart import GatewayStartup

console = Console()


class GatewayRunError(Exception):
    """The runtime has already reported an error; the launcher supplies its exit status."""


@dataclass(frozen=True, slots=True)
class GatewayPresentation:
    """Launcher actions; task scheduling, activation and shutdown stay in the Gateway."""

    check_ports: Callable[[int], None]
    prepare_webui: Callable[[], None]
    prepare_terminal: Callable[[], None]
    report_health: Callable[[str, int], None]
    watch_dock: Callable[[Path, asyncio.Event], Coroutine[Any, Any, None] | None]


async def _deliver_to_channel(
    msg: OutboundMessage,
    *,
    bus: MessageBus,
    session_manager: SessionManager,
    record: bool = False,
    session_key: str | None = None,
    session_generation: str | None = None,
) -> None:
    metadata = dict(msg.metadata or {})
    record = record or bool(metadata.pop("_record_channel_delivery", False))
    raw_key = metadata.pop("_session_key", None)
    raw_generation = metadata.pop("_session_generation", None)
    expected_generation = (
        session_generation
        if session_generation is not None
        else raw_generation if isinstance(raw_generation, str) else None
    )
    key = session_key or (raw_key if isinstance(raw_key, str) else None)
    if key is None:
        key = f"{msg.channel}:{msg.chat_id}"
    if msg.channel == "websocket":
        from nanobot.agent.turn_delivery import TurnRoute
        from nanobot.session.display_history import HISTORY_GENERATION_METADATA_KEY
        from nanobot.session.webui_turns import WebuiTurnRoutePolicy
        from nanobot.webui.session_identity import webui_session_key

        route = await WebuiTurnRoutePolicy(session_manager).admit(
            TurnRoute(msg.channel, msg.chat_id, metadata), key, expected_generation,
        )
        metadata = route.metadata
        if key == webui_session_key(msg.chat_id):
            expected_generation = cast(str, metadata[HISTORY_GENERATION_METADATA_KEY])
    if metadata != (msg.metadata or {}):
        msg = replace(msg, metadata=metadata)
    if record and msg.channel != "cli" and msg.content.strip():
        if expected_generation is None:
            # Cross-target sends admit their target before recording; subsequent
            # deletion or reset must still revoke this delivery's generation.
            target = await session_manager.state.get_header(key)
            expected_generation = target.generation
        extra: dict[str, Any] = {"_channel_delivery": True}
        if msg.media:
            extra["media"] = list(msg.media)
        await session_manager.state.record_delivery(
            key, msg.content, extra, expected_generation=expected_generation,
        )
    await bus.publish_outbound(msg)


class _MCPReadinessHook(AgentHook):
    """Retry application-owned MCP connections before the runner reads tools."""

    def __init__(self, provider: MCPProvider) -> None:
        super().__init__()
        self._provider = provider

    async def before_run(self, context: AgentRunHookContext) -> None:
        await self._provider.connect()


def _signal_name(signum: int) -> str:
    with suppress(ValueError):
        return signal.Signals(signum).name
    return f"signal {signum}"


def _install_gateway_shutdown_handlers(
    loop: asyncio.AbstractEventLoop,
    shutdown_event: asyncio.Event,
    tasks: list[asyncio.Task[Any]],
    print_status: Callable[[str], None],
) -> Callable[[], None]:
    loop_signals: list[int] = []
    previous_handlers: list[tuple[int, Any]] = []
    shutdown_requested = False

    def request_shutdown(signum: int) -> None:
        nonlocal shutdown_requested
        sig_name = _signal_name(signum)
        if shutdown_requested:
            logger.warning("Forcing gateway shutdown after repeated {}", sig_name)
            for task in tasks:
                if not task.done():
                    task.cancel()
            return
        shutdown_requested = True
        logger.info("Gateway shutdown requested by {}", sig_name)
        print_status("\nShutting down... Press Ctrl+C again to force.")
        shutdown_event.set()

    shutdown_signals = [signal.SIGINT, signal.SIGTERM]
    if sigbreak := getattr(signal, "SIGBREAK", None):
        shutdown_signals.append(sigbreak)

    for signum in shutdown_signals:
        try:
            loop.add_signal_handler(signum, request_shutdown, signum)
        except (NotImplementedError, RuntimeError, ValueError):
            try:
                previous = signal.getsignal(signum)
                signal.signal(signum, lambda sig, _frame: request_shutdown(sig))
            except (RuntimeError, ValueError):
                logger.debug("Could not install gateway handler for {}", _signal_name(signum))
                continue
            previous_handlers.append((signum, previous))
        else:
            loop_signals.append(signum)

    def restore() -> None:
        for signum in loop_signals:
            with suppress(NotImplementedError, RuntimeError, ValueError):
                loop.remove_signal_handler(signum)
        for signum, handler in previous_handlers:
            with suppress(RuntimeError, ValueError):
                signal.signal(signum, handler)

    return restore




async def _close_gateway_runtime(
    agent: AgentLoop,
    mcp_provider: MCPProvider,
    channels: ChannelManager,
    tasks: list[asyncio.Task[Any]],
    runtime_tasks: asyncio.Future[list[Any]] | None,
    *,
    task_wait_timeout: float = 15.0,
    close_timeout: float = 15.0,
) -> None:
    """Cancel runtime tasks, then deterministically close application resources.

    Order matters: runtime tasks (including the agent loop and any in-flight
    turn) are cancelled and awaited -- bounded -- before the loop-owned resources
    and the application-owned MCP provider are torn down. The final close is
    bounded and idempotent, so it also covers a cancelled or incomplete loop
    cleanup without leaving subprocess transports alive past ``loop.close()``.
    """
    # Some SDKs swallow task cancellation while attempting to reconnect.
    # Close channel transports before waiting for their runners to exit.
    await channels.stop_all()
    for task in tasks:
        if not task.done():
            task.cancel()
    if tasks:
        # Bounded: a coroutine that swallows cancellation (e.g. an SDK reconnect
        # loop) must not hold the stop open until systemd's timeout kills the
        # cgroup. Anything still pending is abandoned and closed underneath.
        _done, pending = await asyncio.wait(tasks, timeout=task_wait_timeout)
        # A task can swallow the first cancellation while unwinding. Re-cancel
        # timed-out tasks so an agent loop stuck draining background work reaches
        # its resource-cleanup phase before the explicit final close below.
        for task in pending:
            task.cancel()
    if runtime_tasks is not None and not runtime_tasks.done():
        runtime_tasks.cancel()
    for label, close in (
        ("agent", agent.aclose),
        ("MCP provider", mcp_provider.aclose),
    ):
        try:
            await asyncio.wait_for(close(), timeout=close_timeout)
        except BaseException as exc:  # noqa: BLE001 - shutdown must proceed
            logger.warning("Gateway shutdown: {} cleanup incomplete: {}", label, exc)
    # Retrieving an already-finished gather prevents noisy unhandled exceptions,
    # but never wait for it here: its children were bounded individually above.
    if runtime_tasks is not None and runtime_tasks.done():
        with suppress(asyncio.CancelledError, Exception):
            await runtime_tasks


def run_gateway(
    config: Config,
    *,
    port: int | None = None,
    verbose: bool = False,
    presentation: GatewayPresentation,
    unconfigured_provider_error: str | None = None,
    gateway_instance: GatewayInstance | None = None,
    update_startup: GatewayStartup | None = None,
) -> None:
    from nanobot.config.loader import get_config_path
    from nanobot.update_profiles import record_gateway_profile

    port = port if port is not None else config.gateway.port
    instance = gateway_instance or GatewayInstance.resolve(config_path=get_config_path())
    gateway_runtime = GatewayRuntime(paths=instance.paths)
    with installation_access(allow_incomplete=update_startup is not None):
        if update_startup is not None:
            update_startup.validate_installation()
        with (
            gateway_runtime.foreground_instance(instance.start_options(port=port, verbose=verbose)),
            record_gateway_profile(instance, gateway_runtime, data_dir=get_data_dir(),
                                   workspace=config.workspace_path, port=port, verbose=verbose,
                                   grant=update_startup.grant if update_startup else None,
                                   cooperative_stop=True) as profile,
        ):
            if update_startup is not None:
                update_startup.validate_profile(profile)
            _run_claimed_gateway(
                config, port=port, gateway_instance=instance, gateway_runtime=gateway_runtime,
                update_startup=update_startup, update_profile=profile, presentation=presentation,
                unconfigured_provider_error=unconfigured_provider_error,
            )


def _run_claimed_gateway(
    config: Config,
    *,
    port: int,
    gateway_instance: GatewayInstance,
    gateway_runtime: GatewayRuntime,
    presentation: GatewayPresentation,
    unconfigured_provider_error: str | None,
    update_startup: GatewayStartup | None,
    update_profile: ProfileReceipt,
) -> None:
    from nanobot.agent.model_presets import load_model_preset_catalog
    from nanobot.agent.tools.message import MessageTool
    from nanobot.agent.turn_delivery import TurnDeliveryFactory
    from nanobot.bus.queue import MessageBus
    from nanobot.channels.manager import ChannelManager
    from nanobot.config.watcher import watch_config_file
    from nanobot.cron.gateway_jobs import configure_gateway_jobs
    from nanobot.cron.service import CronService
    from nanobot.llm_usage import record_llm_call
    from nanobot.providers.factory import (
        ProviderSnapshot,
        build_provider_snapshot,
        build_unconfigured_provider_snapshot,
        load_provider_snapshot,
    )
    from nanobot.providers.fallback_provider import FallbackProvider
    from nanobot.session.manager import SessionManager
    from nanobot.session.webui_turns import (
        WebuiTurnCoordinator,
        WebuiTurnRoutePolicy,
        build_webui_fallback_model_observer,
    )
    from nanobot.triggers.local_runner import run_local_trigger_queue
    from nanobot.triggers.local_store import LocalTriggerStore
    from nanobot.update_stop import watch_gateway_stop
    from nanobot.webui.recovery import RecoveryCoordinator

    health_identity = update_profile.health_identity
    presentation.check_ports(port)

    console.print(f"{__logo__} Starting nanobot gateway version {__version__} on port {port}...")
    warmup_token_encoding()
    presentation.prepare_webui()
    sync_workspace_templates(config.workspace_path)
    bus = MessageBus()
    fallback_model_observer = build_webui_fallback_model_observer(bus)

    def _observe_provider(snapshot: ProviderSnapshot) -> ProviderSnapshot:
        snapshot.provider.set_llm_call_observer(record_llm_call)
        if isinstance(snapshot.provider, FallbackProvider):
            snapshot.provider.set_fallback_model_observer(fallback_model_observer)
        return snapshot

    def _load_gateway_provider_snapshot(
        *args: Any,
        **kwargs: Any,
    ) -> ProviderSnapshot:
        try:
            return _observe_provider(load_provider_snapshot(*args, **kwargs))
        except ValueError as exc:
            if unconfigured_provider_error is None:
                raise
            return _observe_provider(build_unconfigured_provider_snapshot(config, str(exc)))

    if unconfigured_provider_error is not None:
        provider_snapshot = _observe_provider(
            build_unconfigured_provider_snapshot(config, unconfigured_provider_error)
        )
    else:
        try:
            provider_snapshot = _observe_provider(build_provider_snapshot(config))
        except ValueError as exc:
            console.print(f"[red]Error: {exc}[/red]")
            raise GatewayRunError() from exc
    session_manager = SessionManager(config.workspace_path)

    # Use the same runtime identity for foreground and managed gateway processes.
    from nanobot.gateway.runtime import (
        GatewayClientLease,
        monitor_gateway_clients,
    )

    config_path = gateway_instance.config_path

    # Preserve existing single-workspace installs, but keep custom workspaces clean.
    if is_default_workspace(config.workspace_path):
        migrate_legacy_cron_store(config.workspace_path)

    cron_store_path = config.workspace_path / "cron" / "jobs.json"
    cron = CronService(cron_store_path, admission=bus.admission)
    trigger_store = LocalTriggerStore(config.workspace_path)

    webui_route_policy = WebuiTurnRoutePolicy(session_manager)
    turn_delivery_factory = TurnDeliveryFactory(
        bus,
        route_policy=webui_route_policy,
        route_admission=webui_route_policy.admit,
    )

    tools = ToolRegistry()
    register_image_generation_tool(config, tools, workspace=config.workspace_path)
    mcp_provider = MCPProvider.from_config(config, tools)

    recovery = RecoveryCoordinator(
        sessions=session_manager,
        bus=bus,
    )

    from nanobot.goal.assembly import install_goal

    agent = AgentLoop.from_config(
        config, bus,
        provider=provider_snapshot.provider,
        model=provider_snapshot.model,
        context_window_tokens=provider_snapshot.context_window_tokens,
        cron_service=cron,
        session_manager=session_manager,
        provider_snapshot_loader=_load_gateway_provider_snapshot,
        preset_catalog_loader=load_model_preset_catalog,
        turn_delivery_factory=turn_delivery_factory,
        provider_signature=provider_snapshot.signature,
        local_trigger_store=trigger_store,
        hooks=[_MCPReadinessHook(mcp_provider)],
        hook_factories=[create_file_edit_activity_hook, create_context_source_hook],
        tool_registry=tools,
        recovery_admission=recovery,
        builtin_assembly=install_goal,
    )

    def _schedule_webui_background(awaitable: Awaitable[None]) -> None:
        agent.schedule_background(cast(Coroutine[Any, Any, None], awaitable))

    webui_turn_coordinator = WebuiTurnCoordinator(
        bus=bus,
        sessions=session_manager,
        schedule_background=_schedule_webui_background,
        recovery=recovery,
    )
    deliver_to_channel = partial(
        _deliver_to_channel,
        bus=bus,
        session_manager=session_manager,
    )

    message_tool = agent.tools.get("message")
    if isinstance(message_tool, MessageTool):
        message_tool.set_send_callback(deliver_to_channel)

    def _webui_refresh_runtime_config() -> None:
        agent.refresh_runtime_config()

    def _webui_skill_state_action(disabled_skills: set[str]) -> None:
        config.agents.defaults.disabled_skills = sorted(disabled_skills)
        agent.context.skills.disabled_skills = set(disabled_skills)
        agent.subagents.disabled_skills = set(disabled_skills)

    async def _webui_image_generation_reload() -> dict[str, Any]:
        return await reload_image_generation_tool(
            config_path=config_path,
            workspace=agent.workspace,
            registry=tools,
        )

    channels = ChannelManager(
        config,
        bus,
        session_manager=session_manager,
        cron_service=cron,
        local_trigger_store=trigger_store,
        webui_runtime_model_name=lambda: agent.model.strip() or None,
        webui_refresh_runtime_config=_webui_refresh_runtime_config,
        webui_cron_pending_job_ids=agent.pending_cron_job_ids_for_session,
        webui_local_trigger_pending_ids=agent.pending_local_trigger_ids_for_session,
        webui_mcp_runtime_status=mcp_provider.runtime_status,
        webui_mcp_reload=mcp_provider.reload,
        webui_image_generation_reload=_webui_image_generation_reload,
        webui_skill_state_action=_webui_skill_state_action,
        webui_recovery_action=recovery.handle_action,
        webui_subagent_manager=agent.subagents,
        webui_discard_session=agent.discard_session,
        config_path=config_path,
    )


    if channels.enabled_channels:
        console.print(f"[green]✓[/green] Channels enabled: {', '.join(channels.enabled_channels)}")
    else:
        console.print("[yellow]Warning: No channels enabled[/yellow]")

    configure_gateway_jobs(
        cron, config=config, agent=agent, mcp_provider=mcp_provider, channels=channels,
        deliver=deliver_to_channel, console=console,
    )
    async def run() -> None:
        startup_gate = ExitStack()
        desktop_activated = asyncio.Event()
        tasks: list[asyncio.Task[Any]] = []
        shutdown_task: asyncio.Task[Any] | None = None
        runtime_tasks: asyncio.Future[list[Any]] | None = None
        shutdown_event = asyncio.Event()
        presentation.prepare_terminal()
        restore_shutdown_handlers = _install_gateway_shutdown_handlers(
            asyncio.get_running_loop(),
            shutdown_event,
            tasks,
            console.print,
        )
        try:
            await agent.subagents.recover_interrupted()
            # Re-read once on first admission to close the watcher subscription window.
            agent.runtime_resolver.invalidate()
            # Recovery must finish before WebSocket and other channels begin
            # accepting new input.  That makes a new user message reliably
            # supersede an old recoverable turn instead of racing its queue.
            await recovery.scan()
            if update_startup is not None:
                # Recovery may reconstruct queued work, but no consumer or
                # external listener has started. Keep that work parked too.
                startup_gate.enter_context(bus.admission.pause_before_start())
            await cron.start()
            async def _run_agent() -> None:
                try:
                    await bus.admission.wait_until_open()
                    await mcp_provider.connect()
                    await agent.run()
                finally:
                    await mcp_provider.aclose()

            async def _monitor_local_clients() -> None:
                orphaned = await monitor_gateway_clients(
                    GatewayClientLease(gateway_runtime, kind="gateway-monitor"),
                    shutdown_event,
                )
                if orphaned:
                    logger.info("Last local client disappeared; stopping on-demand gateway")

            tasks.extend([
                asyncio.create_task(
                    gateway_runtime.wait_for_shutdown_request(shutdown_event),
                    name="nanobot-gateway-stop-request",
                ),
                asyncio.create_task(
                    watch_config_file(config_path, lambda: agent.invalidate_runtime_config()),
                    name="nanobot-config-watcher",
                ),
                asyncio.create_task(_run_agent(), name="nanobot-agent-loop"),
                asyncio.create_task(channels.start_all(), name="nanobot-channels"),
                asyncio.create_task(
                    run_local_trigger_queue(
                        store=trigger_store,
                        submit_turn=agent.submit_local_trigger_turn,
                        is_channel_enabled=lambda name: channels.get_channel(name) is not None,
                        admission=bus.admission,
                    ),
                    name="nanobot-local-triggers",
                ),
                asyncio.create_task(
                    _monitor_local_clients(),
                    name="nanobot-gateway-client-monitor",
                ),
            ])
            if update_startup is not None:
                async def activate(startup: GatewayStartup) -> None:
                    await startup.wait_for_activation(health_identity)
                    startup_gate.close()
                    desktop_activated.set()

                tasks.append(asyncio.create_task(activate(update_startup), name="nanobot-update-activation"))
            else:
                desktop_activated.set()
            tasks.extend((
                asyncio.create_task(
                    watch_gateway_stop(update_profile, agent.maintenance, shutdown_event, startup_gate),
                    name="nanobot-update-stop",
                ),
                asyncio.create_task(
                    serve_health(
                        config.gateway.host, port, channels=channels, identity=health_identity,
                        admission=bus.admission, on_bound=presentation.report_health,
                    ),
                    name="nanobot-health-server",
                ),
            ))
            dock = presentation.watch_dock(gateway_instance.paths.state_path, desktop_activated)
            if dock is not None:
                tasks.append(asyncio.create_task(dock, name="nanobot-dock"))
            runtime_tasks = asyncio.gather(*tasks)
            shutdown_task = asyncio.create_task(
                shutdown_event.wait(),
                name="nanobot-gateway-shutdown",
            )
            done, _pending = await asyncio.wait(
                {runtime_tasks, shutdown_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if runtime_tasks in done:
                await runtime_tasks
            else:
                runtime_tasks.cancel()
        except KeyboardInterrupt:
            console.print("\nShutting down...")
        except Exception:
            import traceback

            console.print("\n[red]Error: Gateway crashed unexpectedly[/red]")
            console.print(traceback.format_exc())
            raise GatewayRunError()
        finally:
            try:
                if shutdown_task and not shutdown_task.done():
                    shutdown_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await shutdown_task
                cron.stop()
                # A gateway exit interrupts ownership of active turns; it is
                # not the same as the user stopping a turn.  Keep checkpoints
                # so the next gateway can offer an explicit Continue action.
                agent.preserve_inflight_turns_on_shutdown()
                agent.stop()
                # Cancel runtime tasks first, then deterministically close
                # exec/MCP resources while the event loop is still alive.
                await _close_gateway_runtime(
                    agent,
                    mcp_provider,
                    channels,
                    tasks,
                    runtime_tasks,
                )
                await bus.drain()
            finally:
                # On a failed/aborted startup, keep intake closed until all
                # runtime consumers have been cancelled and cleanup finished.
                startup_gate.close()
                restore_shutdown_handlers()

    with webui_turn_coordinator.connected():
        gateway_runtime.publish_health_host(config.gateway.host)
        asyncio.run(run())
