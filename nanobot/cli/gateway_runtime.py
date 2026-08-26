"""Foreground gateway runtime and lifecycle helpers."""

import asyncio
import signal
from collections.abc import Awaitable, Callable, Coroutine, Iterable
from contextlib import suppress
from pathlib import Path
from typing import Any, cast

import typer
from loguru import logger
from rich.console import Console

from nanobot import __logo__, __version__
from nanobot.agent.hook import AgentHook, AgentRunHookContext
from nanobot.agent.hooks import create_file_edit_activity_hook
from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.mcp import MCPProvider
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.cli import terminal as cli_terminal
from nanobot.cli.runtime_config import _migrate_cron_store
from nanobot.cli.webui_support import (
    _gateway_health_bind_note,
    _gateway_health_url,
    _host_for_local_browser,
    _launch_browser,
    _prepare_webui_bundle_for_gateway,
    _print_foreground_port_conflict,
    _tcp_endpoint_reachable,
    _webui_browser_url,
    _webui_channel_enabled,
    _webui_display_url,
    _webui_endpoint_reachable,
)
from nanobot.config.paths import is_default_workspace
from nanobot.config.schema import Config
from nanobot.gateway.runtime import GatewayInstance
from nanobot.security.network import is_loopback_host
from nanobot.session.keys import UNIFIED_SESSION_KEY, last_channel_from_metadata
from nanobot.utils.evaluator import evaluate_response, resolve_evaluator_prompt
from nanobot.utils.helpers import sync_workspace_templates
from nanobot.webui.build import BuildMode
from nanobot.webui.dev import WebUIDevError, WebUIDevServer
from nanobot.webui.sidebar_state import read_webui_sidebar_state

__all__ = ["_run_gateway"]

console = Console()


class _MCPReadinessHook(AgentHook):
    """Retry application-owned MCP connections before the runner reads tools."""

    def __init__(self, provider: MCPProvider) -> None:
        super().__init__()
        self._provider = provider

    async def before_run(self, context: AgentRunHookContext) -> None:
        await self._provider.connect()


def _http_endpoint_responding(url: str, *, timeout_s: float = 0.25) -> bool:
    """Return whether an HTTP endpoint responds, including with an auth error."""
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(url, timeout=timeout_s):
            return True
    except urllib.error.HTTPError:
        return True
    except (OSError, urllib.error.URLError, TimeoutError, ValueError):
        return False


async def _watch_webui_dev_server(
    server: WebUIDevServer,
    shutdown_event: asyncio.Event,
    *,
    poll_interval_s: float = 0.2,
) -> None:
    """Fail the foreground gateway when its owned Vite sidecar exits."""
    while not shutdown_event.is_set():
        await asyncio.sleep(poll_interval_s)
        if shutdown_event.is_set():
            return
        server.ensure_running()


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
    """Install foreground gateway signal handlers and return a restore callback."""
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

    for signum in (signal.SIGINT, signal.SIGTERM):
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


def _advance_dream_cursor_if_behind(memory: Any) -> None:
    latest = memory.get_latest_cursor()
    if memory.get_last_dream_cursor() < latest:
        memory.set_last_dream_cursor(latest)


def _commit_dream_changes(memory: Any) -> str | None:
    """Commit durable Dream edits, without entering the commit path for a no-op run."""
    if not memory.git.is_initialized():
        return None
    diff_body = memory.dream_content_diff()
    if not diff_body:
        return None
    message = memory.build_dream_commit_message(
        "dream: periodic memory consolidation",
        diff_body,
    )
    return memory.git.auto_commit(message)


_HEARTBEAT_PREAMBLE = (
    "[Your response will be delivered directly to the user's messaging app. "
    "Output ONLY the final user-facing message. Never reference internal "
    "files (HEARTBEAT.md, AWARENESS.md, etc.), your instructions, or your "
    "decision process. If nothing needs reporting, respond with just "
    "'All clear.' and nothing else.]\n\n"
)


def _heartbeat_has_active_tasks(content: str) -> bool:
    """True if HEARTBEAT.md has task lines, ignoring headers, blanks and comments."""
    in_comment = False
    in_active_section: bool = False
    for line in content.splitlines():
        stripped = line.strip()
        if in_comment:
            if "-->" in stripped:
                in_comment = False
            continue
        if not stripped or stripped.startswith("#"):
            if stripped.startswith("##") and not stripped.startswith("###"):
                heading = stripped.lstrip("#").strip().lower()
                in_active_section = heading.startswith("active tasks")
            continue
        if stripped.startswith("<!--"):
            if "-->" not in stripped[4:]:
                in_comment = True
            continue
        if in_active_section is False:
            continue
        return True
    return False


def _pick_heartbeat_target_from_sessions(
    *,
    enabled_channels: Iterable[str],
    sessions: Iterable[dict[str, Any]],
    archived_keys: Iterable[str],
    unified_session_metadata: dict[str, Any] | None = None,
) -> tuple[str, str]:
    enabled = set(enabled_channels)
    archived = set(archived_keys)
    for item in sessions:
        key = item.get("key") or ""
        if key in archived:
            continue
        if key == UNIFIED_SESSION_KEY:
            route = last_channel_from_metadata(unified_session_metadata)
            if route is not None:
                channel, chat_id = route
                if channel not in {"cli", "system"} and channel in enabled:
                    return channel, chat_id
            continue
        if ":" not in key:
            continue
        channel, chat_id = key.split(":", 1)
        if channel in {"cli", "system"}:
            continue
        if channel in enabled and chat_id:
            return channel, chat_id
    return "cli", "direct"


_GATEWAY_HEALTH_MAX_CONNECTIONS = 64
_GATEWAY_HEALTH_READ_TIMEOUT_SECONDS = 2.0


def _print_gateway_health_endpoint(host: str, port: int) -> None:
    """Print a usable health URL and make non-loopback binds explicit."""
    console.print(
        f"[green]✓[/green] Health endpoint: {_gateway_health_url(host, port)}"
        f"{_gateway_health_bind_note(host)}"
    )
    if is_loopback_host(host):
        return

    console.print(
        "[yellow]Warning: the unauthenticated health endpoint is listening beyond loopback "
        "and may be reachable from other devices. "
        f"Keep port {port} private or protect it with a firewall or reverse proxy.[/yellow]"
    )


def _gateway_readiness_payload(channels: Any) -> tuple[bool, dict[str, object]]:
    """Describe process liveness separately from required WebSocket readiness."""
    channel_status: dict[str, Any] = {}
    get_status = getattr(channels, "get_status", None)
    if callable(get_status):
        try:
            raw_status = get_status()
            if isinstance(raw_status, dict):
                channel_status = cast(dict[str, Any], raw_status)
        except Exception:
            logger.exception("Gateway readiness could not read channel status")

    websocket = channel_status.get("websocket")
    websocket_required = websocket is not None or "websocket" in getattr(
        channels,
        "enabled_channels",
        (),
    )
    if not websocket_required:
        websocket_state = "disabled"
        ready = True
    elif isinstance(websocket, dict):
        websocket_status = cast(dict[str, Any], websocket)
        ready = websocket_status.get("running") is True
        state = websocket_status.get("state")
        websocket_state = str(state) if isinstance(state, str) else "unavailable"
    else:
        ready = False
        websocket_state = "unavailable"

    return ready, {
        "status": "ok" if ready else "degraded",
        "process": "alive",
        "ready": ready,
        "websocket": websocket_state,
    }


async def _close_gateway_runtime(
    agent: AgentLoop,
    mcp_provider: MCPProvider,
    channels: Any,
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
    pending: set[asyncio.Task[Any]] = set()
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


def _run_gateway(
    config: Config,
    *,
    port: int | None = None,
    open_browser_url: str | None = None,
    open_browser_ready_url: str | None = None,
    webui_static_dist: bool = True,
    webui_bundle_mode: BuildMode = "warn",
    webui_runtime_surface: str = "browser",
    webui_runtime_capabilities: dict[str, Any] | None = None,
    health_server_enabled: bool = True,
    unconfigured_provider_error: str | None = None,
    webui_dev_server: WebUIDevServer | None = None,
    gateway_instance: GatewayInstance | None = None,
) -> None:
    """Shared gateway runtime; ``open_browser_url`` opens a tab once channels are up."""
    from nanobot.agent.model_presets import load_model_preset_catalog
    from nanobot.agent.tools.message import MessageTool
    from nanobot.agent.turn_delivery import TurnDeliveryFactory
    from nanobot.bus.queue import MessageBus
    from nanobot.bus.runtime_events import RuntimeEventBus
    from nanobot.channels.manager import ChannelManager
    from nanobot.config.watcher import watch_config_file
    from nanobot.cron.bound_runner import run_bound_cron_job
    from nanobot.cron.service import CronJobSkippedError, CronService
    from nanobot.cron.session_turns import is_bound_cron_job
    from nanobot.cron.types import CronJob
    from nanobot.llm_usage import record_llm_call
    from nanobot.llm_usage.context import llm_usage_source
    from nanobot.providers.factory import (
        ProviderSnapshot,
        build_provider_snapshot,
        build_unconfigured_provider_snapshot,
        load_provider_snapshot,
    )
    from nanobot.providers.fallback_provider import FallbackProvider
    from nanobot.providers.image_generation import image_gen_provider_configs
    from nanobot.session.manager import SessionManager
    from nanobot.session.recovery import RecoveryCoordinator
    from nanobot.session.webui_turns import (
        WebuiTurnCoordinator,
        WebuiTurnRoutePolicy,
        build_webui_fallback_model_observer,
    )
    from nanobot.triggers.local_runner import run_local_trigger_queue
    from nanobot.triggers.local_store import LocalTriggerStore

    port = port if port is not None else config.gateway.port
    webui_url = _webui_browser_url(config)
    gateway_host_for_browser = _host_for_local_browser(config.gateway.host)
    if health_server_enabled and _tcp_endpoint_reachable(gateway_host_for_browser, port):
        _print_foreground_port_conflict(
            webui_url=webui_url,
            gateway_host=config.gateway.host,
            gateway_port=port,
        )
        raise typer.Exit(1)
    if _webui_channel_enabled(config) and _webui_endpoint_reachable(webui_url):
        _print_foreground_port_conflict(
            webui_url=webui_url,
            gateway_host=config.gateway.host,
            gateway_port=port,
        )
        raise typer.Exit(1)

    console.print(f"{__logo__} Starting nanobot gateway version {__version__} on port {port}...")
    _prepare_webui_bundle_for_gateway(
        config,
        mode=webui_bundle_mode,
        webui_static_dist=webui_static_dist,
    )
    sync_workspace_templates(config.workspace_path)
    bus = MessageBus()
    runtime_events = RuntimeEventBus()
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
            raise typer.Exit(1) from exc
    session_manager = SessionManager(config.workspace_path)

    # Use the same runtime identity for foreground and managed gateway processes.
    from nanobot.config.loader import get_config_path
    from nanobot.gateway.runtime import (
        GatewayClientLease,
        GatewayRuntime,
        monitor_gateway_clients,
    )

    instance = gateway_instance or GatewayInstance.resolve(
        config_path=get_config_path(),
    )
    config_path = str(instance.config_path)
    gateway_runtime = GatewayRuntime(paths=instance.paths)
    gateway_start_options = instance.start_options(port=port)

    # Preserve existing single-workspace installs, but keep custom workspaces clean.
    if is_default_workspace(config.workspace_path):
        _migrate_cron_store(config)

    # Create cron service with workspace-scoped store
    cron_store_path = config.workspace_path / "cron" / "jobs.json"
    cron = CronService(cron_store_path)
    trigger_store = LocalTriggerStore(config.workspace_path)

    turn_delivery_factory = TurnDeliveryFactory(
        bus,
        runtime_events,
        route_policy=WebuiTurnRoutePolicy(session_manager),
    )

    tools = ToolRegistry()
    mcp_provider = MCPProvider.from_config(config, tools)

    recovery = RecoveryCoordinator(
        sessions=session_manager,
        bus=bus,
        unified_session=config.agents.defaults.unified_session,
    )

    # Create agent with cron service
    agent = AgentLoop.from_config(
        config, bus,
        provider=provider_snapshot.provider,
        model=provider_snapshot.model,
        context_window_tokens=provider_snapshot.context_window_tokens,
        cron_service=cron,
        session_manager=session_manager,
        image_generation_provider_configs=image_gen_provider_configs(config),
        provider_snapshot_loader=_load_gateway_provider_snapshot,
        preset_catalog_loader=load_model_preset_catalog,
        runtime_events=runtime_events,
        turn_delivery_factory=turn_delivery_factory,
        provider_signature=provider_snapshot.signature,
        local_trigger_store=trigger_store,
        hooks=[_MCPReadinessHook(mcp_provider)],
        hook_factories=[create_file_edit_activity_hook],
        tool_registry=tools,
        recovery_admission=recovery,
    )
    def _schedule_webui_background(awaitable: Awaitable[None]) -> None:
        agent.schedule_background(cast(Coroutine[Any, Any, None], awaitable))

    webui_turn_coordinator = WebuiTurnCoordinator(
        bus=bus,
        sessions=session_manager,
        schedule_background=_schedule_webui_background,
        recovery=recovery,
    )
    webui_turn_coordinator.subscribe(runtime_events)
    from nanobot.bus.events import OutboundMessage
    from nanobot.session.keys import session_key_for_channel

    def _channel_session_key(channel: str, chat_id: str) -> str:
        return session_key_for_channel(
            channel,
            chat_id,
            unified_session=config.agents.defaults.unified_session,
        )

    async def _deliver_to_channel(
        msg: OutboundMessage, *, record: bool = False, session_key: str | None = None,
    ) -> None:
        """Publish a user-visible message and mirror it into that channel's session."""
        metadata = dict(msg.metadata or {})
        record = record or bool(metadata.pop("_record_channel_delivery", False))
        if metadata != (msg.metadata or {}):
            msg = OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=msg.content,
                reply_to=msg.reply_to,
                media=msg.media,
                metadata=metadata,
                buttons=msg.buttons,
            )
        if (
            record
            and msg.channel != "cli"
            and msg.content.strip()
            and hasattr(session_manager, "get_or_create")
            and hasattr(session_manager, "save")
        ):
            key = session_key or _channel_session_key(msg.channel, msg.chat_id)
            session = session_manager.get_or_create(key)
            extra: dict[str, Any] = {"_channel_delivery": True}
            if msg.media:
                extra["media"] = list(msg.media)
            session.add_message("assistant", msg.content, **extra)
            session_manager.save(session)
        await bus.publish_outbound(msg)

    message_tool = agent.tools.get("message")
    if isinstance(message_tool, MessageTool):
        message_tool.set_send_callback(_deliver_to_channel)

    # Set cron callback (needs agent)
    async def on_cron_job(job: CronJob) -> str | None:
        """Execute a cron job through the agent."""
        async def _silent(*_args: Any, **_kwargs: Any) -> None:
            pass

        # Dream is an internal job — run directly, not through the agent loop.
        if job.name == "dream":
            from nanobot.agent.memory import MemoryStore

            dream_session_key = MemoryStore.dream_session_key
            prune_dream_sessions = MemoryStore.prune_dream_sessions

            store = agent.context.memory
            resp = None
            diff_body = ""
            try:
                result = store.build_dream_prompt()
                if result is None:
                    logger.info("Dream: nothing to process")
                    return None
                prompt, last_cursor = result
                key = dream_session_key()
                dream_runtime = agent.dream_runtime()
                await mcp_provider.connect()
                resp = await agent.process_direct(
                    prompt,
                    session_key=key,
                    ephemeral=True,
                    tools=store.build_dream_tools(),
                    on_progress=_silent,
                    runtime=dream_runtime,
                )
                # The real file delta grounds the audit record; normal completion
                # decides whether this history batch has finished processing.
                diff_body = store.dream_content_diff()
                completed = MemoryStore.dream_run_completed(resp)
                if completed:
                    store.set_last_dream_cursor(last_cursor)
                    if diff_body:
                        logger.info(
                            "Dream cron job completed, cursor advanced to {}",
                            last_cursor,
                        )
                    else:
                        logger.info(
                            "Dream cron job completed with no memory changes; "
                            "cursor advanced to {}",
                            last_cursor,
                        )
                else:
                    logger.warning(
                        "Dream cron job did not complete ({}); cursor remains at {}",
                        MemoryStore.dream_incompletion_reason(resp),
                        store.get_last_dream_cursor(),
                    )
            except Exception:
                logger.exception("Dream cron job failed")
            finally:
                sha = _commit_dream_changes(store)
                if sha:
                    logger.info("Dream commit: {}", sha)
                store.compact_history()
                prune_dream_sessions(agent.sessions)
            return None

        # Heartbeat is a system job that checks HEARTBEAT.md for active tasks.
        if job.name == "heartbeat":
            heartbeat_file = config.workspace_path / "HEARTBEAT.md"
            try:
                content = heartbeat_file.read_text(encoding="utf-8")
            except OSError:
                logger.debug("Heartbeat: HEARTBEAT.md missing")
                return None
            if not _heartbeat_has_active_tasks(content):
                logger.debug("Heartbeat: HEARTBEAT.md has no active tasks")
                return None

            channel, chat_id = _pick_heartbeat_target()
            if channel == "cli":
                return None

            prompt = (
                _HEARTBEAT_PREAMBLE
                + f"You are executing periodic heartbeat tasks. Read the active tasks below, perform each one, and report what you did:\n\n{content}"
            )

            # Internal check: funnel all output through the post-run gate so the
            # turn can't deliver directly via the message tool and skip it.
            suppress_token = None
            if isinstance(message_tool, MessageTool):
                suppress_token = message_tool.set_suppress_delivery(True)
            try:
                await mcp_provider.connect()
                resp = await agent.process_direct(
                    prompt,
                    session_key="heartbeat",
                    channel=channel,
                    chat_id=chat_id,
                    on_progress=_silent,
                )
            finally:
                if isinstance(message_tool, MessageTool) and suppress_token is not None:
                    message_tool.reset_suppress_delivery(suppress_token)

            # Keep a small tail of heartbeat history so the loop stays bounded.
            session = agent.sessions.get_or_create("heartbeat")
            session.retain_recent_legal_suffix(hb_cfg.keep_recent_messages)
            agent.sessions.save(session)

            if not resp or not resp.content:
                return

            response = resp.content

            evaluator_prompt = resolve_evaluator_prompt(config.workspace_path)

            # Fail closed: stay silent on evaluator failure instead of notifying.
            with llm_usage_source("cron"):
                should_notify = await evaluate_response(
                    response=response,
                    task_context=prompt,
                    provider=agent.provider,
                    model=agent.model,
                    evaluator_prompt=evaluator_prompt,
                    default_notify=False,
                )

            if should_notify:
                logger.info("Heartbeat: completed, delivering response")
                await _deliver_to_channel(
                    OutboundMessage(channel=channel, chat_id=chat_id, content=response),
                    record=True,
                )
            else:
                logger.info("Heartbeat: silenced by post-run evaluation")
            return response

        if is_bound_cron_job(job):
            return await run_bound_cron_job(job, agent=agent, cron=cron)

        reason = "unbound agent cron job must be recreated from a chat session"
        logger.warning(
            "Cron: skipped unbound agent job '{}' ({}): {}",
            job.name,
            job.id,
            reason,
        )
        raise CronJobSkippedError(reason)

    cron.on_job = on_cron_job

    def _webui_runtime_model_name() -> str | None:
        return agent.model.strip() or None

    def _webui_refresh_runtime_config() -> None:
        agent.refresh_runtime_config()

    def _webui_skill_state_action(disabled_skills: set[str]) -> None:
        config.agents.defaults.disabled_skills = sorted(disabled_skills)
        agent.context.skills.disabled_skills = set(disabled_skills)
        agent.subagents.disabled_skills = set(disabled_skills)

    # Create channel manager (forwards SessionManager so the WebSocket channel
    # can serve the embedded webui's REST surface).
    channels = ChannelManager(
        config,
        bus,
        session_manager=session_manager,
        cron_service=cron,
        local_trigger_store=trigger_store,
        webui_runtime_model_name=_webui_runtime_model_name,
        webui_refresh_runtime_config=_webui_refresh_runtime_config,
        webui_cron_pending_job_ids=agent.pending_cron_job_ids_for_session,
        webui_local_trigger_pending_ids=agent.pending_local_trigger_ids_for_session,
        webui_static_dist=webui_static_dist,
        webui_runtime_surface=webui_runtime_surface,
        webui_runtime_capabilities=webui_runtime_capabilities,
        webui_mcp_runtime_status=mcp_provider.runtime_status,
        webui_mcp_reload=mcp_provider.reload,
        webui_skill_state_action=_webui_skill_state_action,
        webui_recovery_action=recovery.handle_action,
        config_path=Path(config_path),
    )

    def _pick_heartbeat_target() -> tuple[str, str]:
        """Pick a routable channel/chat target for heartbeat-triggered messages."""
        sidebar_state = read_webui_sidebar_state()
        unified_metadata = None
        if config.agents.defaults.unified_session:
            record = session_manager.read_session_metadata(UNIFIED_SESSION_KEY)
            if isinstance(record, dict) and isinstance(record.get("metadata"), dict):
                unified_metadata = record["metadata"]
        return _pick_heartbeat_target_from_sessions(
            enabled_channels=channels.enabled_channels,
            sessions=session_manager.list_sessions(),
            archived_keys=sidebar_state.get("archived_keys", []),
            unified_session_metadata=unified_metadata,
        )

    if channels.enabled_channels:
        console.print(f"[green]✓[/green] Channels enabled: {', '.join(channels.enabled_channels)}")
    else:
        console.print("[yellow]Warning: No channels enabled[/yellow]")

    hb_cfg = config.gateway.heartbeat
    if hb_cfg.enabled:
        console.print(f"[green]✓[/green] Heartbeat: every {hb_cfg.interval_s}s")
    else:
        console.print("[yellow]✗[/yellow] Heartbeat: disabled")

    async def _health_server(host: str, health_port: int) -> None:
        """Lightweight HTTP health endpoint on the gateway port."""
        import json as _json

        connection_slots = asyncio.Semaphore(_GATEWAY_HEALTH_MAX_CONNECTIONS)

        async def handle(
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            if connection_slots.locked():
                writer.close()
                return

            async with connection_slots:
                try:
                    data = await asyncio.wait_for(
                        reader.read(4096),
                        timeout=_GATEWAY_HEALTH_READ_TIMEOUT_SECONDS,
                    )
                    request_line = data.split(b"\r\n", 1)[0].decode(
                        "utf-8", errors="replace",
                    )
                    method, path = "", ""
                    parts = request_line.split(" ")
                    if len(parts) >= 2:
                        method, path = parts[0], parts[1]

                    if method == "GET" and path == "/health":
                        ready, payload = _gateway_readiness_payload(channels)
                        body = _json.dumps(payload)
                        status = "200 OK" if ready else "503 Service Unavailable"
                        content_type = "application/json"
                    else:
                        body = "Not Found"
                        status = "404 Not Found"
                        content_type = "text/plain"

                    resp = (
                        f"HTTP/1.0 {status}\r\n"
                        f"Content-Type: {content_type}\r\n"
                        f"Content-Length: {len(body)}\r\n"
                        "Connection: close\r\n"
                        f"\r\n{body}"
                    )
                    writer.write(resp.encode())
                    await writer.drain()
                except (asyncio.TimeoutError, ConnectionError):
                    pass
                finally:
                    writer.close()

        server = await asyncio.start_server(handle, host, health_port)
        _print_gateway_health_endpoint(host, health_port)
        async with server:
            await server.serve_forever()
    # Register Dream system job (idempotent on restart)
    from nanobot.cron.types import CronJob, CronPayload, CronSchedule
    dream_cfg = config.agents.defaults.dream
    if dream_cfg.enabled:
        cron.register_system_job(CronJob(
            id="dream",
            name="dream",
            schedule=dream_cfg.build_schedule(config.agents.defaults.timezone),
            payload=CronPayload(kind="system_event"),
        ))
        console.print(f"[green]✓[/green] Dream: {dream_cfg.describe_schedule()}")
    else:
        console.print("[yellow]○[/yellow] Dream: disabled")
        # Cursor repair must not depend on a healthy cron store.
        _advance_dream_cursor_if_behind(agent.context.memory)
        cron.remove_system_job("dream")

    # Register Heartbeat system job (idempotent on restart)
    if hb_cfg.enabled:
        cron.register_system_job(CronJob(
            id="heartbeat",
            name="heartbeat",
            schedule=CronSchedule(
                kind="every",
                every_ms=hb_cfg.interval_s * 1000,
                tz=config.agents.defaults.timezone,
            ),
            payload=CronPayload(kind="system_event"),
        ))
    else:
        cron.remove_system_job("heartbeat")

    cron_status = cron.status()
    cron_job_count = cast(int, cron_status["jobs"])
    if cron_job_count > 0:
        console.print(f"[green]✓[/green] Cron: {cron_job_count} scheduled jobs")

    async def _open_browser_when_ready() -> None:
        """Wait for the gateway to bind, then point the user's browser at the webui."""
        if not open_browser_url:
            return
        from urllib.parse import urlparse

        # Channels start asynchronously. When the caller supplies a backend
        # readiness route, wait for an actual HTTP response rather than probing
        # the WebSocket listener with an incomplete TCP connection.
        if open_browser_ready_url:
            for _ in range(40):  # ~4s max per listener
                if await asyncio.to_thread(
                    _http_endpoint_responding,
                    open_browser_ready_url,
                ):
                    break
                await asyncio.sleep(0.1)

        parsed = urlparse(open_browser_url)
        target_host = parsed.hostname or config.gateway.host or "127.0.0.1"
        target_port = parsed.port or port
        for _ in range(40):  # ~4s max
            try:
                _reader, writer = await asyncio.open_connection(
                    target_host,
                    target_port,
                )
                writer.close()
                with suppress(Exception):
                    await writer.wait_closed()
                break
            except OSError:
                await asyncio.sleep(0.1)
        display_url = _webui_display_url(open_browser_url)
        try:
            if _launch_browser(open_browser_url):
                console.print(f"[green]✓[/green] Opened browser at {display_url}")
            else:
                console.print(f"[yellow]Could not open browser; visit {display_url}[/yellow]")
        except Exception as e:
            console.print(f"[yellow]Could not open browser ({e}); visit {display_url}[/yellow]")

    async def run() -> None:
        tasks: list[asyncio.Task[Any]] = []
        shutdown_task: asyncio.Task[Any] | None = None
        runtime_tasks: asyncio.Future[list[Any]] | None = None
        startup_complete = False
        shutdown_event = asyncio.Event()
        cli_terminal._ensure_interactive_tty_mode()
        restore_shutdown_handlers = _install_gateway_shutdown_handlers(
            asyncio.get_running_loop(),
            shutdown_event,
            tasks,
            console.print,
        )
        try:
            await cron.start()
            # Re-read once on first admission to close the watcher subscription window.
            agent.runtime_resolver.invalidate()
            # Recovery must finish before WebSocket and other channels begin
            # accepting new input.  That makes a new user message reliably
            # supersede an old recoverable turn instead of racing its queue.
            await recovery.scan()
            async def _run_agent() -> None:
                try:
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

            tasks = [
                asyncio.create_task(
                    watch_config_file(
                        Path(config_path),
                        lambda: agent.invalidate_runtime_config(),
                    ),
                    name="nanobot-config-watcher",
                ),
                asyncio.create_task(_run_agent(), name="nanobot-agent-loop"),
                asyncio.create_task(channels.start_all(), name="nanobot-channels"),
                asyncio.create_task(
                    run_local_trigger_queue(
                        store=trigger_store,
                        submit_turn=agent.submit_local_trigger_turn,
                        is_channel_enabled=lambda name: channels.get_channel(name) is not None,
                    ),
                    name="nanobot-local-triggers",
                ),
                asyncio.create_task(
                    _monitor_local_clients(),
                    name="nanobot-gateway-client-monitor",
                ),
            ]
            if health_server_enabled:
                tasks.append(asyncio.create_task(
                    _health_server(config.gateway.host, port),
                    name="nanobot-health-server",
                ))
            if open_browser_url:
                tasks.append(asyncio.create_task(
                    _open_browser_when_ready(),
                    name="nanobot-open-browser",
                ))
            if webui_dev_server is not None:
                tasks.append(asyncio.create_task(
                    _watch_webui_dev_server(webui_dev_server, shutdown_event),
                    name="nanobot-webui-dev-server",
                ))
            runtime_tasks = asyncio.gather(*tasks)
            startup_complete = True
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
        except WebUIDevError:
            raise
        except Exception:
            import traceback

            console.print("\n[red]Error: Gateway crashed unexpectedly[/red]")
            console.print(traceback.format_exc())
            if not startup_complete:
                # Do not report a successful gateway command when startup
                # failed before any runtime task or listener was created.
                raise typer.Exit(1)
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
                # Flush all cached sessions to durable storage before exit.
                # This prevents data loss on filesystems with write-back
                # caching (rclone VFS, NFS, FUSE mounts, etc.).
                flushed = agent.sessions.flush_all()
                if flushed:
                    logger.info("Shutdown: flushed {} session(s) to disk", flushed)
            finally:
                restore_shutdown_handlers()

    with gateway_runtime.foreground_instance(gateway_start_options):
        if health_server_enabled:
            gateway_runtime.publish_health_host(config.gateway.host)
        asyncio.run(run())
