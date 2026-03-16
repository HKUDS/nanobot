"""CLI commands for nanobot."""

import asyncio
import os
import select
import signal
import sys
from pathlib import Path
from typing import Any

from loguru import logger

# Force UTF-8 encoding for Windows console
if sys.platform == "win32":
    if sys.stdout.encoding != "utf-8":
        os.environ["PYTHONIOENCODING"] = "utf-8"
        # Re-open stdout/stderr with UTF-8 encoding
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

import typer
from prompt_toolkit import print_formatted_text
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import ANSI, HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.application import run_in_terminal
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table
from rich.text import Text

from nanobot import __logo__, __version__
from nanobot.config.paths import get_workspace_path
from nanobot.config.schema import Config
from nanobot.utils.helpers import sync_workspace_templates

app = typer.Typer(
    name="nanobot",
    help=f"{__logo__} nanobot - Personal AI Assistant",
    no_args_is_help=True,
)

console = Console()
EXIT_COMMANDS = {"exit", "quit", "/exit", "/quit", ":q"}

# ---------------------------------------------------------------------------
# CLI input: prompt_toolkit for editing, paste, history, and display
# ---------------------------------------------------------------------------

_PROMPT_SESSION: PromptSession | None = None
_SAVED_TERM_ATTRS = None  # original termios settings, restored on exit


def _flush_pending_tty_input() -> None:
    """Drop unread keypresses typed while the model was generating output."""
    try:
        fd = sys.stdin.fileno()
        if not os.isatty(fd):
            return
    except Exception:
        return

    try:
        import termios
        termios.tcflush(fd, termios.TCIFLUSH)
        return
    except Exception:
        pass

    try:
        while True:
            ready, _, _ = select.select([fd], [], [], 0)
            if not ready:
                break
            if not os.read(fd, 4096):
                break
    except Exception:
        return


def _restore_terminal() -> None:
    """Restore terminal to its original state (echo, line buffering, etc.)."""
    if _SAVED_TERM_ATTRS is None:
        return
    try:
        import termios
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, _SAVED_TERM_ATTRS)
    except Exception:
        pass


def _init_prompt_session() -> None:
    """Create the prompt_toolkit session with persistent file history."""
    global _PROMPT_SESSION, _SAVED_TERM_ATTRS

    # Save terminal state so we can restore it on exit
    try:
        import termios
        _SAVED_TERM_ATTRS = termios.tcgetattr(sys.stdin.fileno())
    except Exception:
        pass

    from nanobot.config.paths import get_cli_history_path

    history_file = get_cli_history_path()
    history_file.parent.mkdir(parents=True, exist_ok=True)

    _PROMPT_SESSION = PromptSession(
        history=FileHistory(str(history_file)),
        enable_open_in_editor=False,
        multiline=False,   # Enter submits (single line mode)
    )


def _make_console() -> Console:
    return Console(file=sys.stdout)


def _render_interactive_ansi(render_fn) -> str:
    """Render Rich output to ANSI so prompt_toolkit can print it safely."""
    ansi_console = Console(
        force_terminal=True,
        color_system=console.color_system or "standard",
        width=console.width,
    )
    with ansi_console.capture() as capture:
        render_fn(ansi_console)
    return capture.get()


def _print_agent_response(response: str, render_markdown: bool) -> None:
    """Render assistant response with consistent terminal styling."""
    console = _make_console()
    content = response or ""
    body = Markdown(content) if render_markdown else Text(content)
    console.print()
    console.print(f"[cyan]{__logo__} nanobot[/cyan]")
    console.print(body)
    console.print()


async def _print_interactive_line(text: str) -> None:
    """Print async interactive updates with prompt_toolkit-safe Rich styling."""
    def _write() -> None:
        ansi = _render_interactive_ansi(
            lambda c: c.print(f"  [dim]↳ {text}[/dim]")
        )
        print_formatted_text(ANSI(ansi), end="")

    await run_in_terminal(_write)


async def _print_interactive_response(response: str, render_markdown: bool) -> None:
    """Print async interactive replies with prompt_toolkit-safe Rich styling."""
    def _write() -> None:
        content = response or ""
        ansi = _render_interactive_ansi(
            lambda c: (
                c.print(),
                c.print(f"[cyan]{__logo__} nanobot[/cyan]"),
                c.print(Markdown(content) if render_markdown else Text(content)),
                c.print(),
            )
        )
        print_formatted_text(ANSI(ansi), end="")

    await run_in_terminal(_write)


def _is_exit_command(command: str) -> bool:
    """Return True when input should end interactive chat."""
    return command.lower() in EXIT_COMMANDS


async def _read_interactive_input_async() -> str:
    """Read user input using prompt_toolkit (handles paste, history, display).

    prompt_toolkit natively handles:
    - Multiline paste (bracketed paste mode)
    - History navigation (up/down arrows)
    - Clean display (no ghost characters or artifacts)
    """
    if _PROMPT_SESSION is None:
        raise RuntimeError("Call _init_prompt_session() first")
    try:
        with patch_stdout():
            return await _PROMPT_SESSION.prompt_async(
                HTML("<b fg='ansiblue'>You:</b> "),
            )
    except EOFError as exc:
        raise KeyboardInterrupt from exc



def version_callback(value: bool):
    if value:
        console.print(f"{__logo__} nanobot v{__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        None, "--version", "-v", callback=version_callback, is_eager=True
    ),
):
    """nanobot - Personal AI Assistant."""
    pass


# ============================================================================
# Onboard / Setup
# ============================================================================


@app.command()
def onboard():
    """Initialize nanobot configuration and workspace."""
    from nanobot.config.loader import get_config_path, load_config, save_config
    from nanobot.config.schema import AgentDefaults, Config

    config_path = get_config_path()

    if config_path.exists():
        console.print(f"[yellow]Config already exists at {config_path}[/yellow]")
        console.print("  [bold]y[/bold] = overwrite with defaults (existing values will be lost)")
        console.print("  [bold]N[/bold] = refresh config, keeping existing values and adding new fields")
        if typer.confirm("Overwrite?"):
            config = Config()
            save_config(config)
            console.print(f"[green]✓[/green] Config reset to defaults at {config_path}")
        else:
            config = load_config()
            # Ensure defaults has the workspace set after refresh
            if not config.agents.defaults.workspace:
                config.agents.defaults.workspace = get_workspace_path()
            save_config(config)
            console.print(f"[green]✓[/green] Config refreshed at {config_path} (existing values preserved)")
    else:
        config = Config()
        save_config(config)
        console.print(f"[green]✓[/green] Created config at {config_path}")

    console.print("[dim]Config template now uses `maxTokens` + `contextWindowTokens`; `memoryWindow` is no longer a runtime setting.[/dim]")

    _onboard_plugins(config_path)

    agent_config = config.agents.defaults
    
    # Create workspace
    workspace_path = Path(agent_config.workspace) if agent_config.workspace else config.workspace_path
    
    if not workspace_path.exists():
        workspace_path.mkdir(parents=True, exist_ok=True)
        console.print(f"[green]✓[/green] Created workspace at {workspace_path}")

    sync_workspace_templates(workspace_path)

    console.print(f"\n{__logo__} nanobot is ready!")
    console.print("\nNext steps:")
    console.print("  1. Add your API key to [cyan]~/.nanobot/config.json[/cyan]")
    console.print("     Get one at: https://openrouter.ai/keys")
    console.print("  2. Chat: [cyan]nanobot agent -m \"Hello!\"[/cyan]")
    console.print("  3. New agent: [cyan]nanobot agent-create <name>[/cyan]")
    console.print("\n[dim]Want Telegram/WhatsApp? See: https://github.com/HKUDS/nanobot#-chat-apps[/dim]")


def _merge_missing_defaults(existing: Any, defaults: Any) -> Any:
    """Recursively fill in missing values from defaults without overwriting user config."""
    if not isinstance(existing, dict) or not isinstance(defaults, dict):
        return existing

    merged = dict(existing)
    for key, value in defaults.items():
        if key not in merged:
            merged[key] = value
        else:
            merged[key] = _merge_missing_defaults(merged[key], value)
    return merged


def _onboard_plugins(config_path: Path) -> None:
    """Inject default config for all discovered channels (built-in + plugins)."""
    import json

    from nanobot.channels.registry import discover_all

    all_channels = discover_all()
    if not all_channels:
        return

    with open(config_path, encoding="utf-8") as f:
        data = json.load(f)

    channels = data.setdefault("channels", {})
    for name, cls in all_channels.items():
        if name not in channels:
            channels[name] = cls.default_config()
        else:
            channels[name] = _merge_missing_defaults(channels[name], cls.default_config())

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)



def _make_provider(config: Config, agent_config: Any = None):
    """Create the appropriate LLM provider from config."""
    from nanobot.providers.base import GenerationSettings
    from nanobot.providers.openai_codex_provider import OpenAICodexProvider
    from nanobot.providers.azure_openai_provider import AzureOpenAIProvider

    if agent_config is None:
        agent_config = config.agents.defaults

    model = agent_config.model
    provider_name = config.get_provider_name(model)
    p = config.get_provider(model)

    # OpenAI Codex (OAuth)
    if provider_name == "openai_codex" or model.startswith("openai-codex/"):
        provider = OpenAICodexProvider(default_model=model)
    # Custom: direct OpenAI-compatible endpoint, bypasses LiteLLM
    elif provider_name == "custom":
        from nanobot.providers.custom_provider import CustomProvider
        provider = CustomProvider(
            api_key=p.api_key if p else "no-key",
            api_base=config.get_api_base(model) or "http://localhost:8000/v1",
            default_model=model,
        )
    # Azure OpenAI: direct Azure OpenAI endpoint with deployment name
    elif provider_name == "azure_openai":
        if not p or not p.api_key or not p.api_base:
            console.print("[red]Error: Azure OpenAI requires api_key and api_base.[/red]")
            console.print("Set them in ~/.nanobot/config.json under providers.azure_openai section")
            console.print("Use the model field to specify the deployment name.")
            raise typer.Exit(1)
        provider = AzureOpenAIProvider(
            api_key=p.api_key,
            api_base=p.api_base,
            default_model=model,
        )
    else:
        from nanobot.providers.litellm_provider import LiteLLMProvider
        from nanobot.providers.registry import find_by_name
        spec = find_by_name(provider_name)
        if not model.startswith("bedrock/") and not (p and p.api_key) and not (spec and (spec.is_oauth or spec.is_local)):
            console.print("[red]Error: No API key configured.[/red]")
            console.print("Set one in ~/.nanobot/config.json under providers section")
            raise typer.Exit(1)
        provider = LiteLLMProvider(
            api_key=p.api_key if p else None,
            api_base=config.get_api_base(model),
            default_model=model,
            extra_headers=p.extra_headers if p else None,
            provider_name=provider_name,
        )

    provider.generation = GenerationSettings(
        temperature=agent_config.temperature,
        max_tokens=agent_config.max_tokens,
        reasoning_effort=agent_config.reasoning_effort,
    )
    return provider


def _load_runtime_config(config: str | None = None, workspace: str | None = None) -> Config:
    """Load config and optionally override the active workspace."""
    from nanobot.config.loader import load_config, set_config_path

    config_path = None
    if config:
        config_path = Path(config).expanduser().resolve()
        if not config_path.exists():
            console.print(f"[red]Error: Config file not found: {config_path}[/red]")
            raise typer.Exit(1)
        set_config_path(config_path)
        console.print(f"[dim]Using config: {config_path}[/dim]")

    loaded = load_config(config_path)
    if workspace:
        loaded.agents.defaults.workspace = workspace
    return loaded


def _print_deprecated_memory_window_notice(config: Config) -> None:
    """Warn when running with old memoryWindow-only config."""
    if config.agents.defaults.should_warn_deprecated_memory_window:
        console.print(
            "[yellow]Hint:[/yellow] Detected deprecated `memoryWindow` without "
            "`contextWindowTokens`. `memoryWindow` is ignored; run "
            "[cyan]nanobot onboard[/cyan] to refresh your config template."
        )


# ============================================================================
# Gateway / Server
# ============================================================================


@app.command()
def gateway(
    port: int | None = typer.Option(None, "--port", "-p", help="Gateway port"),
    workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
    config: str | None = typer.Option(None, "--config", "-c", help="Path to config file"),
):
    """Start the nanobot gateway."""
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus
    from nanobot.channels.manager import ChannelManager
    from nanobot.config.paths import get_cron_dir
    from nanobot.cron.service import CronService
    from nanobot.cron.types import CronJob
    from nanobot.heartbeat.service import HeartbeatService
    from nanobot.session.manager import SessionManager

    if verbose:
        import logging
        logging.basicConfig(level=logging.DEBUG)

    config = _load_runtime_config(config, workspace)
    _print_deprecated_memory_window_notice(config)
    port = port if port is not None else config.gateway.port

    console.print(f"{__logo__} Starting nanobot gateway on port {port}...")
    
    instances = config.agents

    main_bus = MessageBus()
    
    agents = []
    crons = []
    heartbeats = []
    forward_coros = []
    
    channels = ChannelManager(config, main_bus)
    
    # Pre-allocate message buses and parse profiles for all instances
    # Profile is auto-derived from <workspace>/PROFILE.md (convention over config)
    all_buses = {}
    peer_profiles = {}
    for idx, (instance_name, cfg) in enumerate(instances.items()):
        is_primary = (instance_name == "defaults")
        all_buses[instance_name] = main_bus if is_primary else MessageBus()
        profile_path = Path(cfg.workspace) / "PROFILE.md"
        if profile_path.exists():
            peer_profiles[instance_name] = profile_path.read_text(encoding="utf-8")
        else:
            peer_profiles[instance_name] = "No description available."

    for instance_name, agent_config in instances.items():
        bus = all_buses[instance_name]
        is_primary = bus is main_bus
        peer_buses = {k: v for k, v in all_buses.items() if k != instance_name}
        peer_profiles_filtered = {k: v for k, v in peer_profiles.items() if k != instance_name}

        instance_workspace = Path(agent_config.workspace)
        sync_workspace_templates(instance_workspace)
        session_manager = SessionManager(instance_workspace)
        
        provider = _make_provider(config, agent_config)
        
        if not is_primary:
            # "system" is an internal pseudo-channel used for peer-to-peer delegation.
            # Outbound messages targeting it from secondary agents are internal artifacts
            # (e.g. from the message tool echoing back during a delegated task) and
            # should be silently dropped - the real result is routed via delegated_from.
            _INTERNAL_CHANNELS = {"system"}
            def _make_forward(b, name):
                async def _forward():
                    while True:
                        try:
                            msg = await b.consume_outbound()
                            if msg.metadata and msg.metadata.get("delegated_from"):
                                caller = msg.metadata["delegated_from"]
                                task_id = msg.metadata.get("delegate_task_id")
                                is_final = bool(msg.metadata.get("is_final"))
                                
                                # Find the calling agent to resolve the future directly,
                                # bypassing the message bus to avoid deadlocks.
                                resolved = False
                                if task_id:
                                    # agents exists in the outer scope (defined at line ~420 below, but we need access to it)
                                    # We can capture it by accessing the global `agents` list created in `main()`.
                                    for a in agents:
                                        if a.self_agent_name == caller:
                                            # Found the delegating agent, try to resolve the tool
                                            delegate_tool = a.tools.get("agent_delegate")
                                            if delegate_tool and hasattr(delegate_tool, "resolve_task"):
                                                await delegate_tool.resolve_task(task_id, is_final, msg.content)
                                                resolved = True
                                                break
                                
                                if not resolved:
                                    logger.warning(f"Could not resolve delegated task {task_id} for {caller}")
                                    
                            elif msg.channel not in _INTERNAL_CHANNELS:
                                # Forward proactive notifications to main outbound (real channels only)
                                msg.content = f"[{name}] {msg.content}"
                                await main_bus.publish_outbound(msg)
                            # else: silently drop internal pseudo-channel messages
                        except asyncio.CancelledError:
                            break
                        except Exception:
                            await asyncio.sleep(1)
                return _forward
            forward_coros.append(_make_forward(bus, instance_name))
            
        cron_store_path = get_cron_dir(agent_config.workspace) / "jobs.json"
        cron_store_path.parent.mkdir(parents=True, exist_ok=True)
        cron = CronService(cron_store_path, agent_name=instance_name)
        
        agent = AgentLoop(
            bus=bus,
            provider=provider,
            workspace=instance_workspace,
            model=agent_config.model,
            max_iterations=agent_config.max_tool_iterations,
            context_window_tokens=agent_config.context_window_tokens,
            web_search_config=config.tools.web.search,
            web_proxy=config.tools.web.proxy or None,
            exec_config=config.tools.exec,
            cron_service=cron,
            restrict_to_workspace=config.tools.restrict_to_workspace,
            session_manager=session_manager,
            mcp_servers=config.tools.mcp_servers,
            channels_config=config.channels,
            peer_buses=peer_buses,
            peer_profiles=peer_profiles_filtered,
            allowed_agent_delegates=agent_config.allowed_agent_delegates,
            self_agent_name=instance_name,
        )
        
        def _make_cron_callback(a: AgentLoop, c: CronService, p):
            async def on_cron_job(job: CronJob) -> str | None:
                from nanobot.agent.tools.cron import CronTool
                from nanobot.agent.tools.message import MessageTool
                from nanobot.utils.evaluator import evaluate_response
                reminder_note = (
                    "[Scheduled Task] Timer finished.\n\n"
                    f"Task '{job.name}' has been triggered.\n"
                    f"Scheduled instruction: {job.payload.message}"
                )
                cron_tool = a.tools.get("cron")
                cron_token = None
                if isinstance(cron_tool, CronTool):
                    cron_token = cron_tool.set_cron_context(True)
                try:
                    response = await a.process_direct(
                        reminder_note,
                        session_key=f"cron:{job.id}",
                        channel=job.payload.channel or "cli",
                        chat_id=job.payload.to or "direct",
                    )
                finally:
                    if isinstance(cron_tool, CronTool) and cron_token is not None:
                        cron_tool.reset_cron_context(cron_token)

                message_tool = a.tools.get("message")
                if isinstance(message_tool, MessageTool) and message_tool._sent_in_turn:
                    return response

                if job.payload.deliver and job.payload.to and response:
                    should_notify = await evaluate_response(
                        response, job.payload.message, p, a.model,
                    )
                    if should_notify:
                        from nanobot.bus.events import OutboundMessage
                        await main_bus.publish_outbound(OutboundMessage(
                            channel=job.payload.channel or "cli",
                            chat_id=job.payload.to,
                            content=response
                    ))
                return response
            return on_cron_job
            
        cron.on_job = _make_cron_callback(agent, cron, provider)
        
        def _make_heartbeat_callbacks(a: AgentLoop, sm: SessionManager):
            def _pick_heartbeat_target() -> tuple[str, str]:
                """Pick a routable channel/chat target for heartbeat-triggered messages."""
                enabled = set(channels.enabled_channels)
                # Prefer the most recently updated non-internal session on an enabled channel.
                for item in sm.list_sessions():
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

            async def on_heartbeat_execute(tasks: str) -> str:
                """Phase 2: execute heartbeat tasks through the full agent loop."""
                channel, chat_id = _pick_heartbeat_target()
                
                async def _silent(*_args, **_kwargs): 
                    pass
                
                return await a.process_direct(
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
                await main_bus.publish_outbound(OutboundMessage(channel=channel, chat_id=chat_id, content=response))
            
            return on_heartbeat_execute, on_heartbeat_notify
            
        on_hb_exec, on_hb_notify = _make_heartbeat_callbacks(agent, session_manager)
            
        hb_cfg = config.gateway.heartbeat
        heartbeat = HeartbeatService(
            workspace=instance_workspace,
            provider=provider,
            model=agent.model,
            on_execute=on_hb_exec,
            on_notify=on_hb_notify,
            interval_s=hb_cfg.interval_s,
            enabled=hb_cfg.enabled,
            agent_name=instance_name,
        )
        
        agents.append(agent)
        crons.append(cron)
        heartbeats.append(heartbeat)

    if channels.enabled_channels:
        console.print(f"[green]✓[/green] Channels enabled: {', '.join(channels.enabled_channels)}")
    else:
        console.print("[yellow]Warning: No channels enabled[/yellow]")

    total_cron_jobs = sum(c.status()["jobs"] for c in crons)
    if total_cron_jobs > 0:
        console.print(f"[green]✓[/green] Cron: {total_cron_jobs} scheduled jobs across {len(crons)} agents")

    console.print(f"[green]✓[/green] Heartbeat: every {config.gateway.heartbeat.interval_s}s for {len(heartbeats)} agents")

    async def run():
        tasks = []
        try:
            for c in crons:
                await c.start()
            for h in heartbeats:
                await h.start()
                
            coroutines = [a.run() for a in agents] + [channels.start_all()] + [f() for f in forward_coros]
            gather_task = asyncio.gather(*coroutines)
            tasks.append(gather_task)
            await gather_task
        except KeyboardInterrupt:
            console.print("\nShutting down...")
        except Exception:
            import traceback
            console.print("\n[red]Error: Gateway crashed unexpectedly[/red]")
            console.print(traceback.format_exc())
        finally:
            for t in tasks:
                t.cancel()
            for a in agents:
                await a.close_mcp()
            for h in heartbeats:
                h.stop()
            for c in crons:
                c.stop()
            for a in agents:
                a.stop()
            await channels.stop_all()

    asyncio.run(run())




# ============================================================================
# Agent Commands
# ============================================================================


@app.command()
def agent(
    message: str = typer.Option(None, "--message", "-m", help="Message to send to the agent"),
    session_id: str = typer.Option("cli:direct", "--session", "-s", help="Session ID"),
    workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
    config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
    markdown: bool = typer.Option(True, "--markdown/--no-markdown", help="Render assistant output as Markdown"),
    logs: bool = typer.Option(False, "--logs/--no-logs", help="Show nanobot runtime logs during chat"),
):
    """Interact with the agent directly."""
    from loguru import logger

    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus
    from nanobot.config.paths import get_cron_dir
    from nanobot.cron.service import CronService

    config = _load_runtime_config(config, workspace)
    
    agent_config = config.agents.defaults
    instance_workspace = Path(agent_config.workspace) if agent_config.workspace else config.workspace_path
    
    _print_deprecated_memory_window_notice(config)
    sync_workspace_templates(instance_workspace)

    bus = MessageBus()
    provider = _make_provider(config, agent_config)

    # Create cron service for tool usage (no callback needed for CLI unless running)
    cron_store_path = get_cron_dir() / "jobs.json"
    cron = CronService(cron_store_path)

    if logs:
        logger.enable("nanobot")
    else:
        logger.disable("nanobot")

    agent_loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=instance_workspace,
        model=agent_config.model,
        max_iterations=agent_config.max_tool_iterations,
        context_window_tokens=agent_config.context_window_tokens,
        web_search_config=config.tools.web.search,
        web_proxy=config.tools.web.proxy or None,
        exec_config=config.tools.exec,
        cron_service=cron,
        restrict_to_workspace=config.tools.restrict_to_workspace,
        mcp_servers=config.tools.mcp_servers,
        channels_config=config.channels,
        allowed_agent_delegates=getattr(agent_config, "allowed_agent_delegates", []),
        self_agent_name="main",
    )

    # Show spinner when logs are off (no output to miss); skip when logs are on
    def _thinking_ctx():
        if logs:
            from contextlib import nullcontext
            return nullcontext()
        # Animated spinner is safe to use with prompt_toolkit input handling
        return console.status("[dim]nanobot is thinking...[/dim]", spinner="dots")

    async def _cli_progress(content: str, *, tool_hint: bool = False) -> None:
        ch = agent_loop.channels_config
        if ch and tool_hint and not ch.send_tool_hints:
            return
        if ch and not tool_hint and not ch.send_progress:
            return
        console.print(f"  [dim]↳ {content}[/dim]")

    if message:
        # Single message mode — direct call, no bus needed
        async def run_once():
            with _thinking_ctx():
                response = await agent_loop.process_direct(message, session_id, on_progress=_cli_progress)
            _print_agent_response(response, render_markdown=markdown)
            await agent_loop.close_mcp()

        asyncio.run(run_once())
    else:
        # Interactive mode — route through bus like other channels
        from nanobot.bus.events import InboundMessage
        _init_prompt_session()
        console.print(f"{__logo__} Interactive mode (type [bold]exit[/bold] or [bold]Ctrl+C[/bold] to quit)\n")

        if ":" in session_id:
            cli_channel, cli_chat_id = session_id.split(":", 1)
        else:
            cli_channel, cli_chat_id = "cli", session_id

        def _handle_signal(signum, frame):
            sig_name = signal.Signals(signum).name
            _restore_terminal()
            console.print(f"\nReceived {sig_name}, goodbye!")
            sys.exit(0)

        signal.signal(signal.SIGINT, _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)
        # SIGHUP is not available on Windows
        if hasattr(signal, 'SIGHUP'):
            signal.signal(signal.SIGHUP, _handle_signal)
        # Ignore SIGPIPE to prevent silent process termination when writing to closed pipes
        # SIGPIPE is not available on Windows
        if hasattr(signal, 'SIGPIPE'):
            signal.signal(signal.SIGPIPE, signal.SIG_IGN)

        async def run_interactive():
            bus_task = asyncio.create_task(agent_loop.run())
            turn_done = asyncio.Event()
            turn_done.set()
            turn_response: list[str] = []

            async def _consume_outbound():
                while True:
                    try:
                        msg = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
                        if msg.metadata.get("_progress"):
                            is_tool_hint = msg.metadata.get("_tool_hint", False)
                            ch = agent_loop.channels_config
                            if ch and is_tool_hint and not ch.send_tool_hints:
                                pass
                            elif ch and not is_tool_hint and not ch.send_progress:
                                pass
                            else:
                                await _print_interactive_line(msg.content)

                        elif not turn_done.is_set():
                            if msg.content:
                                turn_response.append(msg.content)
                            turn_done.set()
                        elif msg.content:
                            await _print_interactive_response(msg.content, render_markdown=markdown)

                    except asyncio.TimeoutError:
                        continue
                    except asyncio.CancelledError:
                        break

            outbound_task = asyncio.create_task(_consume_outbound())

            try:
                while True:
                    try:
                        _flush_pending_tty_input()
                        user_input = await _read_interactive_input_async()
                        command = user_input.strip()
                        if not command:
                            continue

                        if _is_exit_command(command):
                            _restore_terminal()
                            console.print("\nGoodbye!")
                            break

                        turn_done.clear()
                        turn_response.clear()

                        await bus.publish_inbound(InboundMessage(
                            channel=cli_channel,
                            sender_id="user",
                            chat_id=cli_chat_id,
                            content=user_input,
                        ))

                        with _thinking_ctx():
                            await turn_done.wait()

                        if turn_response:
                            _print_agent_response(turn_response[0], render_markdown=markdown)
                    except KeyboardInterrupt:
                        _restore_terminal()
                        console.print("\nGoodbye!")
                        break
                    except EOFError:
                        _restore_terminal()
                        console.print("\nGoodbye!")
                        break
            finally:
                agent_loop.stop()
                outbound_task.cancel()
                await asyncio.gather(bus_task, outbound_task, return_exceptions=True)
                await agent_loop.close_mcp()

        asyncio.run(run_interactive())


# ============================================================================
# Channel Commands
# ============================================================================


channels_app = typer.Typer(help="Manage channels")
app.add_typer(channels_app, name="channels")


@channels_app.command("status")
def channels_status():
    """Show channel status."""
    from nanobot.channels.registry import discover_all
    from nanobot.config.loader import load_config

    config = load_config()

    table = Table(title="Channel Status")
    table.add_column("Channel", style="cyan")
    table.add_column("Enabled", style="green")

    for name, cls in sorted(discover_all().items()):
        section = getattr(config.channels, name, None)
        if section is None:
            enabled = False
        elif isinstance(section, dict):
            enabled = section.get("enabled", False)
        else:
            enabled = getattr(section, "enabled", False)
        table.add_row(
            cls.display_name,
            "[green]\u2713[/green]" if enabled else "[dim]\u2717[/dim]",
        )

    console.print(table)


def _get_bridge_dir() -> Path:
    """Get the bridge directory, setting it up if needed."""
    import shutil
    import subprocess

    # User's bridge location
    from nanobot.config.paths import get_bridge_install_dir

    user_bridge = get_bridge_install_dir()

    # Check if already built
    if (user_bridge / "dist" / "index.js").exists():
        return user_bridge

    # Check for npm
    npm_path = shutil.which("npm")
    if not npm_path:
        console.print("[red]npm not found. Please install Node.js >= 18.[/red]")
        raise typer.Exit(1)

    # Find source bridge: first check package data, then source dir
    pkg_bridge = Path(__file__).parent.parent / "bridge"  # nanobot/bridge (installed)
    src_bridge = Path(__file__).parent.parent.parent / "bridge"  # repo root/bridge (dev)

    source = None
    if (pkg_bridge / "package.json").exists():
        source = pkg_bridge
    elif (src_bridge / "package.json").exists():
        source = src_bridge

    if not source:
        console.print("[red]Bridge source not found.[/red]")
        console.print("Try reinstalling: pip install --force-reinstall nanobot")
        raise typer.Exit(1)

    console.print(f"{__logo__} Setting up bridge...")

    # Copy to user directory
    user_bridge.parent.mkdir(parents=True, exist_ok=True)
    if user_bridge.exists():
        shutil.rmtree(user_bridge)
    shutil.copytree(source, user_bridge, ignore=shutil.ignore_patterns("node_modules", "dist"))

    # Install and build
    try:
        console.print("  Installing dependencies...")
        subprocess.run([npm_path, "install"], cwd=user_bridge, check=True, capture_output=True)

        console.print("  Building...")
        subprocess.run([npm_path, "run", "build"], cwd=user_bridge, check=True, capture_output=True)

        console.print("[green]✓[/green] Bridge ready\n")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Build failed: {e}[/red]")
        if e.stderr:
            console.print(f"[dim]{e.stderr.decode()[:500]}[/dim]")
        raise typer.Exit(1)

    return user_bridge


@channels_app.command("login")
def channels_login():
    """Link device via QR code."""
    import shutil
    import subprocess

    from nanobot.config.loader import load_config
    from nanobot.config.paths import get_runtime_subdir

    config = load_config()
    bridge_dir = _get_bridge_dir()

    console.print(f"{__logo__} Starting bridge...")
    console.print("Scan the QR code to connect.\n")

    env = {**os.environ}
    wa_cfg = getattr(config.channels, "whatsapp", None) or {}
    bridge_token = wa_cfg.get("bridgeToken", "") if isinstance(wa_cfg, dict) else getattr(wa_cfg, "bridge_token", "")
    if bridge_token:
        env["BRIDGE_TOKEN"] = bridge_token
    env["AUTH_DIR"] = str(get_runtime_subdir("whatsapp-auth"))

    npm_path = shutil.which("npm")
    if not npm_path:
        console.print("[red]npm not found. Please install Node.js.[/red]")
        raise typer.Exit(1)

    try:
        subprocess.run([npm_path, "start"], cwd=bridge_dir, check=True, env=env)
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Bridge failed: {e}[/red]")


# ============================================================================
# Plugin Commands
# ============================================================================

plugins_app = typer.Typer(help="Manage channel plugins")
app.add_typer(plugins_app, name="plugins")


@plugins_app.command("list")
def plugins_list():
    """List all discovered channels (built-in and plugins)."""
    from nanobot.channels.registry import discover_all, discover_channel_names
    from nanobot.config.loader import load_config

    config = load_config()
    builtin_names = set(discover_channel_names())
    all_channels = discover_all()

    table = Table(title="Channel Plugins")
    table.add_column("Name", style="cyan")
    table.add_column("Source", style="magenta")
    table.add_column("Enabled", style="green")

    for name in sorted(all_channels):
        cls = all_channels[name]
        source = "builtin" if name in builtin_names else "plugin"
        section = getattr(config.channels, name, None)
        if section is None:
            enabled = False
        elif isinstance(section, dict):
            enabled = section.get("enabled", False)
        else:
            enabled = getattr(section, "enabled", False)
        table.add_row(
            cls.display_name,
            source,
            "[green]yes[/green]" if enabled else "[dim]no[/dim]",
        )

    console.print(table)


# ============================================================================
# Status Commands
# ============================================================================


@app.command()
def status():
    """Show nanobot status."""
    from nanobot.config.loader import get_config_path, load_config

    config_path = get_config_path()
    config = load_config()
    
    agent_config = config.agents.instances.get("main") or config.agents.defaults
    workspace = Path(agent_config.workspace) if agent_config.workspace else config.workspace_path

    console.print(f"{__logo__} nanobot Status\n")

    console.print(f"Config: {config_path} {'[green]✓[/green]' if config_path.exists() else '[red]✗[/red]'}")
    console.print(f"Workspace: {workspace} {'[green]✓[/green]' if workspace.exists() else '[red]✗[/red]'}")

    if config_path.exists():
        from nanobot.providers.registry import PROVIDERS

        console.print(f"Model: {agent_config.model}")

        # Check API keys from registry
        for spec in PROVIDERS:
            p = getattr(config.providers, spec.name, None)
            if p is None:
                continue
            if spec.is_oauth:
                console.print(f"{spec.label}: [green]✓ (OAuth)[/green]")
            elif spec.is_local:
                # Local deployments show api_base instead of api_key
                if p.api_base:
                    console.print(f"{spec.label}: [green]✓ {p.api_base}[/green]")
                else:
                    console.print(f"{spec.label}: [dim]not set[/dim]")
            else:
                has_key = bool(p.api_key)
                console.print(f"{spec.label}: {'[green]✓[/green]' if has_key else '[dim]not set[/dim]'}")


# ============================================================================
# OAuth Login
# ============================================================================

provider_app = typer.Typer(help="Manage providers")
app.add_typer(provider_app, name="provider")


_LOGIN_HANDLERS: dict[str, callable] = {}


def _register_login(name: str):
    def decorator(fn):
        _LOGIN_HANDLERS[name] = fn
        return fn
    return decorator


@provider_app.command("login")
def provider_login(
    provider: str = typer.Argument(..., help="OAuth provider (e.g. 'openai-codex', 'github-copilot')"),
):
    """Authenticate with an OAuth provider."""
    from nanobot.providers.registry import PROVIDERS

    key = provider.replace("-", "_")
    spec = next((s for s in PROVIDERS if s.name == key and s.is_oauth), None)
    if not spec:
        names = ", ".join(s.name.replace("_", "-") for s in PROVIDERS if s.is_oauth)
        console.print(f"[red]Unknown OAuth provider: {provider}[/red]  Supported: {names}")
        raise typer.Exit(1)

    handler = _LOGIN_HANDLERS.get(spec.name)
    if not handler:
        console.print(f"[red]Login not implemented for {spec.label}[/red]")
        raise typer.Exit(1)

    console.print(f"{__logo__} OAuth Login - {spec.label}\n")
    handler()


@_register_login("openai_codex")
def _login_openai_codex() -> None:
    try:
        from oauth_cli_kit import get_token, login_oauth_interactive
        token = None
        try:
            token = get_token()
        except Exception:
            pass
        if not (token and token.access):
            console.print("[cyan]Starting interactive OAuth login...[/cyan]\n")
            token = login_oauth_interactive(
                print_fn=lambda s: console.print(s),
                prompt_fn=lambda s: typer.prompt(s),
            )
        if not (token and token.access):
            console.print("[red]✗ Authentication failed[/red]")
            raise typer.Exit(1)
        console.print(f"[green]✓ Authenticated with OpenAI Codex[/green]  [dim]{token.account_id}[/dim]")
    except ImportError:
        console.print("[red]oauth_cli_kit not installed. Run: pip install oauth-cli-kit[/red]")
        raise typer.Exit(1)


@_register_login("github_copilot")
def _login_github_copilot() -> None:
    import asyncio

    console.print("[cyan]Starting GitHub Copilot device flow...[/cyan]\n")

    async def _trigger():
        from litellm import acompletion
        await acompletion(model="github_copilot/gpt-4o", messages=[{"role": "user", "content": "hi"}], max_tokens=1)

    try:
        asyncio.run(_trigger())
        console.print("[green]✓ Authenticated with GitHub Copilot[/green]")
    except Exception as e:
        console.print(f"[red]Authentication error: {e}[/red]")
        raise typer.Exit(1)


# ============================================================================
# Agent Management Commands
# ============================================================================
@app.command("agent-create")
def agent_create(
    name: str = typer.Argument(..., help="Name of the new agent (e.g. 'coder', 'researcher')"),
    config_path: str | None = typer.Option(None, "--config", "-c", help="Path to config file"),
):
    """Create a new agent, initialize its workspace, and register it in config.json."""
    from nanobot.config.loader import get_config_path, load_config, save_config
    from nanobot.config.schema import AgentDefaults

    cfg_path = Path(config_path) if config_path else get_config_path()
    config = load_config(cfg_path) if cfg_path.exists() else None

    if config is None:
        console.print("[red]Config not found. Run [bold]nanobot onboard[/bold] first.[/red]")
        raise typer.Exit(1)

    if name in config.agents:
        console.print(f"[yellow]Agent [bold]{name}[/bold] already exists in config.[/yellow]")
        raise typer.Exit(1)

    agent_workspace = Path.home() / ".nanobot" / "workspace" / name
    agent_profile = agent_workspace / "PROFILE.md"

    config.agents[name] = AgentDefaults(
        workspace=str(agent_workspace),
    )
    save_config(config)
    console.print(f"[green]✓[/green] Registered agent [bold]{name}[/bold] in config")

    agent_workspace.mkdir(parents=True, exist_ok=True)
    sync_workspace_templates(agent_workspace)
    console.print(f"[green]✓[/green] Initialized workspace at {agent_workspace}")

    console.print(f"\n[bold]{__logo__} Agent [cyan]{name}[/cyan] is ready![/bold]")
    console.print("\nNext steps:")
    console.print(f"  1. Edit [cyan]{agent_workspace / 'PROFILE.md'}[/cyan] to describe the agent's capabilities")
    console.print(f"  2. Set [cyan]allowed_agent_delegates[/cyan] in config.json to control which agents can call [bold]{name}[/bold]")
    console.print("  3. Restart [cyan]nanobot gateway[/cyan] to activate the new agent")


if __name__ == "__main__":
    app()
