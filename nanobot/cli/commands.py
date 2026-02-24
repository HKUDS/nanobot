"""CLI commands for nanobot."""

import asyncio
import os
import signal
from pathlib import Path
import select
import sys

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table
from rich.text import Text

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.patch_stdout import patch_stdout

from nanobot import __version__, __logo__
from nanobot.config.schema import Config

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

    history_file = Path.home() / ".nanobot" / "history" / "cli_history"
    history_file.parent.mkdir(parents=True, exist_ok=True)

    _PROMPT_SESSION = PromptSession(
        history=FileHistory(str(history_file)),
        enable_open_in_editor=False,
        multiline=False,   # Enter submits (single line mode)
    )


def _print_agent_response(response: str, render_markdown: bool) -> None:
    """Render assistant response with consistent terminal styling."""
    content = response or ""
    body = Markdown(content) if render_markdown else Text(content)
    console.print()
    console.print(f"[cyan]{__logo__} nanobot[/cyan]")
    console.print(body)
    console.print()


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
    from nanobot.config.schema import Config
    from nanobot.utils.helpers import get_workspace_path
    
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
            save_config(config)
            console.print(f"[green]✓[/green] Config refreshed at {config_path} (existing values preserved)")
    else:
        save_config(Config())
        console.print(f"[green]✓[/green] Created config at {config_path}")
    
    # Create workspace
    workspace = get_workspace_path()
    
    if not workspace.exists():
        workspace.mkdir(parents=True, exist_ok=True)
        console.print(f"[green]✓[/green] Created workspace at {workspace}")
    
    # Create default bootstrap files
    _create_workspace_templates(workspace)
    
    console.print(f"\n{__logo__} nanobot is ready!")
    console.print("\nNext steps:")
    console.print("  1. Add your API key to [cyan]~/.nanobot/config.json[/cyan]")
    console.print("     Get one at: https://openrouter.ai/keys")
    console.print("  2. Chat: [cyan]nanobot agent -m \"Hello!\"[/cyan]")
    console.print("\n[dim]Want Telegram/WhatsApp? See: https://github.com/HKUDS/nanobot#-chat-apps[/dim]")




def _create_workspace_templates(workspace: Path):
    """Create default workspace template files from bundled templates."""
    from importlib.resources import files as pkg_files

    templates_dir = pkg_files("nanobot") / "templates"

    for item in templates_dir.iterdir():
        if not item.name.endswith(".md"):
            continue
        dest = workspace / item.name
        if not dest.exists():
            dest.write_text(item.read_text(encoding="utf-8"), encoding="utf-8")
            console.print(f"  [dim]Created {item.name}[/dim]")

    memory_dir = workspace / "memory"
    memory_dir.mkdir(exist_ok=True)

    memory_template = templates_dir / "memory" / "MEMORY.md"
    memory_file = memory_dir / "MEMORY.md"
    if not memory_file.exists():
        memory_file.write_text(memory_template.read_text(encoding="utf-8"), encoding="utf-8")
        console.print("  [dim]Created memory/MEMORY.md[/dim]")

    history_file = memory_dir / "HISTORY.md"
    if not history_file.exists():
        history_file.write_text("", encoding="utf-8")
        console.print("  [dim]Created memory/HISTORY.md[/dim]")

    events_file = memory_dir / "events.jsonl"
    if not events_file.exists():
        events_file.write_text("", encoding="utf-8")
        console.print("  [dim]Created memory/events.jsonl[/dim]")

    profile_file = memory_dir / "profile.json"
    if not profile_file.exists():
        profile_file.write_text("{}", encoding="utf-8")
        console.print("  [dim]Created memory/profile.json[/dim]")

    metrics_file = memory_dir / "metrics.json"
    if not metrics_file.exists():
        metrics_file.write_text("{}", encoding="utf-8")
        console.print("  [dim]Created memory/metrics.json[/dim]")

    (workspace / "skills").mkdir(exist_ok=True)


def _make_provider(config: Config):
    """Create the appropriate LLM provider from config."""
    from nanobot.providers.litellm_provider import LiteLLMProvider
    from nanobot.providers.openai_codex_provider import OpenAICodexProvider
    from nanobot.providers.custom_provider import CustomProvider

    model = config.agents.defaults.model
    provider_name = config.get_provider_name(model)
    p = config.get_provider(model)

    # OpenAI Codex (OAuth)
    if provider_name == "openai_codex" or model.startswith("openai-codex/"):
        return OpenAICodexProvider(default_model=model)

    # Custom: direct OpenAI-compatible endpoint, bypasses LiteLLM
    if provider_name == "custom":
        return CustomProvider(
            api_key=p.api_key if p else "no-key",
            api_base=config.get_api_base(model) or "http://localhost:8000/v1",
            default_model=model,
        )

    from nanobot.providers.registry import find_by_name
    spec = find_by_name(provider_name)
    if not model.startswith("bedrock/") and not (p and p.api_key) and not (spec and spec.is_oauth):
        console.print("[red]Error: No API key configured.[/red]")
        console.print("Set one in ~/.nanobot/config.json under providers section")
        raise typer.Exit(1)

    return LiteLLMProvider(
        api_key=p.api_key if p else None,
        api_base=config.get_api_base(model),
        default_model=model,
        extra_headers=p.extra_headers if p else None,
        provider_name=provider_name,
    )


# ============================================================================
# Gateway / Server
# ============================================================================


@app.command()
def gateway(
    port: int = typer.Option(18790, "--port", "-p", help="Gateway port"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
):
    """Start the nanobot gateway."""
    from nanobot.config.loader import load_config, get_data_dir
    from nanobot.bus.queue import MessageBus
    from nanobot.agent.loop import AgentLoop
    from nanobot.channels.manager import ChannelManager
    from nanobot.session.manager import SessionManager
    from nanobot.cron.service import CronService
    from nanobot.cron.types import CronJob
    from nanobot.heartbeat.service import HeartbeatService
    
    if verbose:
        import logging
        logging.basicConfig(level=logging.DEBUG)
    
    console.print(f"{__logo__} Starting nanobot gateway on port {port}...")
    
    config = load_config()
    bus = MessageBus()
    provider = _make_provider(config)
    session_manager = SessionManager(config.workspace_path)
    
    # Create cron service first (callback set after agent creation)
    cron_store_path = get_data_dir() / "cron" / "jobs.json"
    cron = CronService(cron_store_path)
    
    # Create agent with cron service
    agent = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        model=config.agents.defaults.model,
        temperature=config.agents.defaults.temperature,
        max_tokens=config.agents.defaults.max_tokens,
        max_iterations=config.agents.defaults.max_tool_iterations,
        memory_window=config.agents.defaults.memory_window,
        memory_mode=config.agents.defaults.memory_mode,
        memory_retrieval_k=config.agents.defaults.memory_retrieval_k,
        memory_token_budget=config.agents.defaults.memory_token_budget,
        memory_recency_half_life_days=config.agents.defaults.memory_recency_half_life_days,
        memory_enable_contradiction_check=config.agents.defaults.memory_enable_contradiction_check,
        memory_embedding_provider=config.agents.defaults.memory_embedding_provider,
        memory_vector_backend=config.agents.defaults.memory_vector_backend,
        brave_api_key=config.tools.web.search.api_key or None,
        exec_config=config.tools.exec,
        cron_service=cron,
        restrict_to_workspace=config.tools.restrict_to_workspace,
        session_manager=session_manager,
        mcp_servers=config.tools.mcp_servers,
        channels_config=config.channels,
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
            await bus.publish_outbound(OutboundMessage(
                channel=job.payload.channel or "cli",
                chat_id=job.payload.to,
                content=response or ""
            ))
        return response
    cron.on_job = on_cron_job
    
    # Create channel manager
    channels = ChannelManager(config, bus)

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
        channel, chat_id = _pick_heartbeat_target()

        async def _silent(*_args, **_kwargs):
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
        await bus.publish_outbound(OutboundMessage(channel=channel, chat_id=chat_id, content=response))

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
    
    if channels.enabled_channels:
        console.print(f"[green]✓[/green] Channels enabled: {', '.join(channels.enabled_channels)}")
    else:
        console.print("[yellow]Warning: No channels enabled[/yellow]")
    
    cron_status = cron.status()
    if cron_status["jobs"] > 0:
        console.print(f"[green]✓[/green] Cron: {cron_status['jobs']} scheduled jobs")
    
    console.print(f"[green]✓[/green] Heartbeat: every {hb_cfg.interval_s}s")
    
    async def run():
        try:
            await cron.start()
            await heartbeat.start()
            await asyncio.gather(
                agent.run(),
                channels.start_all(),
            )
        except KeyboardInterrupt:
            console.print("\nShutting down...")
        finally:
            await agent.close_mcp()
            heartbeat.stop()
            cron.stop()
            agent.stop()
            await channels.stop_all()
    
    asyncio.run(run())




# ============================================================================
# Agent Commands
# ============================================================================


@app.command()
def agent(
    message: str = typer.Option(None, "--message", "-m", help="Message to send to the agent"),
    session_id: str = typer.Option("cli:direct", "--session", "-s", help="Session ID"),
    markdown: bool = typer.Option(True, "--markdown/--no-markdown", help="Render assistant output as Markdown"),
    logs: bool = typer.Option(False, "--logs/--no-logs", help="Show nanobot runtime logs during chat"),
):
    """Interact with the agent directly."""
    from nanobot.config.loader import load_config, get_data_dir
    from nanobot.bus.queue import MessageBus
    from nanobot.agent.loop import AgentLoop
    from nanobot.cron.service import CronService
    from loguru import logger
    
    config = load_config()
    
    bus = MessageBus()
    provider = _make_provider(config)

    # Create cron service for tool usage (no callback needed for CLI unless running)
    cron_store_path = get_data_dir() / "cron" / "jobs.json"
    cron = CronService(cron_store_path)

    if logs:
        logger.enable("nanobot")
    else:
        logger.disable("nanobot")
    
    agent_loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        model=config.agents.defaults.model,
        temperature=config.agents.defaults.temperature,
        max_tokens=config.agents.defaults.max_tokens,
        max_iterations=config.agents.defaults.max_tool_iterations,
        memory_window=config.agents.defaults.memory_window,
        memory_mode=config.agents.defaults.memory_mode,
        memory_retrieval_k=config.agents.defaults.memory_retrieval_k,
        memory_token_budget=config.agents.defaults.memory_token_budget,
        memory_recency_half_life_days=config.agents.defaults.memory_recency_half_life_days,
        memory_enable_contradiction_check=config.agents.defaults.memory_enable_contradiction_check,
        memory_embedding_provider=config.agents.defaults.memory_embedding_provider,
        memory_vector_backend=config.agents.defaults.memory_vector_backend,
        brave_api_key=config.tools.web.search.api_key or None,
        exec_config=config.tools.exec,
        cron_service=cron,
        restrict_to_workspace=config.tools.restrict_to_workspace,
        mcp_servers=config.tools.mcp_servers,
        channels_config=config.channels,
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

        def _exit_on_sigint(signum, frame):
            _restore_terminal()
            console.print("\nGoodbye!")
            os._exit(0)

        signal.signal(signal.SIGINT, _exit_on_sigint)

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
                                console.print(f"  [dim]↳ {msg.content}[/dim]")
                        elif not turn_done.is_set():
                            if msg.content:
                                turn_response.append(msg.content)
                            turn_done.set()
                        elif msg.content:
                            console.print()
                            _print_agent_response(msg.content, render_markdown=markdown)
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
    from nanobot.config.loader import load_config

    config = load_config()

    table = Table(title="Channel Status")
    table.add_column("Channel", style="cyan")
    table.add_column("Enabled", style="green")
    table.add_column("Configuration", style="yellow")

    # WhatsApp
    wa = config.channels.whatsapp
    table.add_row(
        "WhatsApp",
        "✓" if wa.enabled else "✗",
        wa.bridge_url
    )

    dc = config.channels.discord
    table.add_row(
        "Discord",
        "✓" if dc.enabled else "✗",
        dc.gateway_url
    )

    # Feishu
    fs = config.channels.feishu
    fs_config = f"app_id: {fs.app_id[:10]}..." if fs.app_id else "[dim]not configured[/dim]"
    table.add_row(
        "Feishu",
        "✓" if fs.enabled else "✗",
        fs_config
    )

    # Mochat
    mc = config.channels.mochat
    mc_base = mc.base_url or "[dim]not configured[/dim]"
    table.add_row(
        "Mochat",
        "✓" if mc.enabled else "✗",
        mc_base
    )
    
    # Telegram
    tg = config.channels.telegram
    tg_config = f"token: {tg.token[:10]}..." if tg.token else "[dim]not configured[/dim]"
    table.add_row(
        "Telegram",
        "✓" if tg.enabled else "✗",
        tg_config
    )

    # Slack
    slack = config.channels.slack
    slack_config = "socket" if slack.app_token and slack.bot_token else "[dim]not configured[/dim]"
    table.add_row(
        "Slack",
        "✓" if slack.enabled else "✗",
        slack_config
    )

    # DingTalk
    dt = config.channels.dingtalk
    dt_config = f"client_id: {dt.client_id[:10]}..." if dt.client_id else "[dim]not configured[/dim]"
    table.add_row(
        "DingTalk",
        "✓" if dt.enabled else "✗",
        dt_config
    )

    # QQ
    qq = config.channels.qq
    qq_config = f"app_id: {qq.app_id[:10]}..." if qq.app_id else "[dim]not configured[/dim]"
    table.add_row(
        "QQ",
        "✓" if qq.enabled else "✗",
        qq_config
    )

    # Email
    em = config.channels.email
    em_config = em.imap_host if em.imap_host else "[dim]not configured[/dim]"
    table.add_row(
        "Email",
        "✓" if em.enabled else "✗",
        em_config
    )

    console.print(table)


def _get_bridge_dir() -> Path:
    """Get the bridge directory, setting it up if needed."""
    import shutil
    import subprocess
    
    # User's bridge location
    user_bridge = Path.home() / ".nanobot" / "bridge"
    
    # Check if already built
    if (user_bridge / "dist" / "index.js").exists():
        return user_bridge
    
    # Check for npm
    if not shutil.which("npm"):
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
        subprocess.run(["npm", "install"], cwd=user_bridge, check=True, capture_output=True)
        
        console.print("  Building...")
        subprocess.run(["npm", "run", "build"], cwd=user_bridge, check=True, capture_output=True)
        
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
    import subprocess
    from nanobot.config.loader import load_config
    
    config = load_config()
    bridge_dir = _get_bridge_dir()
    
    console.print(f"{__logo__} Starting bridge...")
    console.print("Scan the QR code to connect.\n")
    
    env = {**os.environ}
    if config.channels.whatsapp.bridge_token:
        env["BRIDGE_TOKEN"] = config.channels.whatsapp.bridge_token
    
    try:
        subprocess.run(["npm", "start"], cwd=bridge_dir, check=True, env=env)
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Bridge failed: {e}[/red]")
    except FileNotFoundError:
        console.print("[red]npm not found. Please install Node.js.[/red]")


# ============================================================================
# Cron Commands
# ============================================================================

cron_app = typer.Typer(help="Manage scheduled tasks")
app.add_typer(cron_app, name="cron")


@cron_app.command("list")
def cron_list(
    all: bool = typer.Option(False, "--all", "-a", help="Include disabled jobs"),
):
    """List scheduled jobs."""
    from nanobot.config.loader import get_data_dir
    from nanobot.cron.service import CronService
    
    store_path = get_data_dir() / "cron" / "jobs.json"
    service = CronService(store_path)
    
    jobs = service.list_jobs(include_disabled=all)
    
    if not jobs:
        console.print("No scheduled jobs.")
        return
    
    table = Table(title="Scheduled Jobs")
    table.add_column("ID", style="cyan")
    table.add_column("Name")
    table.add_column("Schedule")
    table.add_column("Status")
    table.add_column("Next Run")
    
    import time
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo
    for job in jobs:
        # Format schedule
        if job.schedule.kind == "every":
            sched = f"every {(job.schedule.every_ms or 0) // 1000}s"
        elif job.schedule.kind == "cron":
            sched = f"{job.schedule.expr or ''} ({job.schedule.tz})" if job.schedule.tz else (job.schedule.expr or "")
        else:
            sched = "one-time"
        
        # Format next run
        next_run = ""
        if job.state.next_run_at_ms:
            ts = job.state.next_run_at_ms / 1000
            try:
                tz = ZoneInfo(job.schedule.tz) if job.schedule.tz else None
                next_run = _dt.fromtimestamp(ts, tz).strftime("%Y-%m-%d %H:%M")
            except Exception:
                next_run = time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
        
        status = "[green]enabled[/green]" if job.enabled else "[dim]disabled[/dim]"
        
        table.add_row(job.id, job.name, sched, status, next_run)
    
    console.print(table)


@cron_app.command("add")
def cron_add(
    name: str = typer.Option(..., "--name", "-n", help="Job name"),
    message: str = typer.Option(..., "--message", "-m", help="Message for agent"),
    every: int = typer.Option(None, "--every", "-e", help="Run every N seconds"),
    cron_expr: str = typer.Option(None, "--cron", "-c", help="Cron expression (e.g. '0 9 * * *')"),
    tz: str | None = typer.Option(None, "--tz", help="IANA timezone for cron (e.g. 'America/Vancouver')"),
    at: str = typer.Option(None, "--at", help="Run once at time (ISO format)"),
    deliver: bool = typer.Option(False, "--deliver", "-d", help="Deliver response to channel"),
    to: str = typer.Option(None, "--to", help="Recipient for delivery"),
    channel: str = typer.Option(None, "--channel", help="Channel for delivery (e.g. 'telegram', 'whatsapp')"),
):
    """Add a scheduled job."""
    from nanobot.config.loader import get_data_dir
    from nanobot.cron.service import CronService
    from nanobot.cron.types import CronSchedule
    
    if tz and not cron_expr:
        console.print("[red]Error: --tz can only be used with --cron[/red]")
        raise typer.Exit(1)

    # Determine schedule type
    if every:
        schedule = CronSchedule(kind="every", every_ms=every * 1000)
    elif cron_expr:
        schedule = CronSchedule(kind="cron", expr=cron_expr, tz=tz)
    elif at:
        import datetime
        dt = datetime.datetime.fromisoformat(at)
        schedule = CronSchedule(kind="at", at_ms=int(dt.timestamp() * 1000))
    else:
        console.print("[red]Error: Must specify --every, --cron, or --at[/red]")
        raise typer.Exit(1)
    
    store_path = get_data_dir() / "cron" / "jobs.json"
    service = CronService(store_path)
    
    try:
        job = service.add_job(
            name=name,
            schedule=schedule,
            message=message,
            deliver=deliver,
            to=to,
            channel=channel,
        )
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from e

    console.print(f"[green]✓[/green] Added job '{job.name}' ({job.id})")


@cron_app.command("remove")
def cron_remove(
    job_id: str = typer.Argument(..., help="Job ID to remove"),
):
    """Remove a scheduled job."""
    from nanobot.config.loader import get_data_dir
    from nanobot.cron.service import CronService
    
    store_path = get_data_dir() / "cron" / "jobs.json"
    service = CronService(store_path)
    
    if service.remove_job(job_id):
        console.print(f"[green]✓[/green] Removed job {job_id}")
    else:
        console.print(f"[red]Job {job_id} not found[/red]")


@cron_app.command("enable")
def cron_enable(
    job_id: str = typer.Argument(..., help="Job ID"),
    disable: bool = typer.Option(False, "--disable", help="Disable instead of enable"),
):
    """Enable or disable a job."""
    from nanobot.config.loader import get_data_dir
    from nanobot.cron.service import CronService
    
    store_path = get_data_dir() / "cron" / "jobs.json"
    service = CronService(store_path)
    
    job = service.enable_job(job_id, enabled=not disable)
    if job:
        status = "disabled" if disable else "enabled"
        console.print(f"[green]✓[/green] Job '{job.name}' {status}")
    else:
        console.print(f"[red]Job {job_id} not found[/red]")


@cron_app.command("run")
def cron_run(
    job_id: str = typer.Argument(..., help="Job ID to run"),
    force: bool = typer.Option(False, "--force", "-f", help="Run even if disabled"),
):
    """Manually run a job."""
    from loguru import logger
    from nanobot.config.loader import load_config, get_data_dir
    from nanobot.cron.service import CronService
    from nanobot.cron.types import CronJob
    from nanobot.bus.queue import MessageBus
    from nanobot.agent.loop import AgentLoop
    logger.disable("nanobot")

    config = load_config()
    provider = _make_provider(config)
    bus = MessageBus()
    agent_loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        model=config.agents.defaults.model,
        temperature=config.agents.defaults.temperature,
        max_tokens=config.agents.defaults.max_tokens,
        max_iterations=config.agents.defaults.max_tool_iterations,
        memory_window=config.agents.defaults.memory_window,
        memory_mode=config.agents.defaults.memory_mode,
        memory_retrieval_k=config.agents.defaults.memory_retrieval_k,
        memory_token_budget=config.agents.defaults.memory_token_budget,
        memory_recency_half_life_days=config.agents.defaults.memory_recency_half_life_days,
        memory_enable_contradiction_check=config.agents.defaults.memory_enable_contradiction_check,
        memory_embedding_provider=config.agents.defaults.memory_embedding_provider,
        brave_api_key=config.tools.web.search.api_key or None,
        exec_config=config.tools.exec,
        restrict_to_workspace=config.tools.restrict_to_workspace,
        mcp_servers=config.tools.mcp_servers,
        channels_config=config.channels,
    )

    store_path = get_data_dir() / "cron" / "jobs.json"
    service = CronService(store_path)

    result_holder = []

    async def on_job(job: CronJob) -> str | None:
        response = await agent_loop.process_direct(
            job.payload.message,
            session_key=f"cron:{job.id}",
            channel=job.payload.channel or "cli",
            chat_id=job.payload.to or "direct",
        )
        result_holder.append(response)
        return response

    service.on_job = on_job

    async def run():
        return await service.run_job(job_id, force=force)

    if asyncio.run(run()):
        console.print("[green]✓[/green] Job executed")
        if result_holder:
            _print_agent_response(result_holder[0], render_markdown=True)
    else:
        console.print(f"[red]Failed to run job {job_id}[/red]")


# ============================================================================
# Status Commands
# ============================================================================


memory_app = typer.Typer(help="Manage memory system")
app.add_typer(memory_app, name="memory")


@memory_app.command("inspect")
def memory_inspect(
    query: str = typer.Option("", "--query", "-q", help="Optional retrieval query"),
    top_k: int = typer.Option(6, "--top-k", "-k", help="Top-k memories to display"),
):
    """Inspect memory profile, metrics, and retrieval results."""
    from nanobot.config.loader import load_config
    from nanobot.agent.memory import MemoryStore

    config = load_config()
    store = MemoryStore(
        config.workspace_path,
        embedding_provider=config.agents.defaults.memory_embedding_provider,
        vector_backend=config.agents.defaults.memory_vector_backend,
    )

    observability = store.get_observability_report()
    metrics = observability.get("metrics", {})
    kpis = observability.get("kpis", {})
    profile = store.read_profile()
    report = store.verify_memory()
    events = store.read_events()

    console.print(f"{__logo__} Memory Inspect\n")
    console.print(f"Mode: [cyan]{config.agents.defaults.memory_mode}[/cyan]")
    console.print(f"Vector backend: [cyan]{store.retriever.active_backend}[/cyan]")
    console.print(f"Events: [green]{len(events)}[/green]")
    console.print(f"Profile items: [green]{report['profile_items']}[/green]")
    console.print(f"Open conflicts: [yellow]{report['open_conflicts']}[/yellow]")
    console.print(f"Stale events: [yellow]{report['stale_events']}[/yellow]\n")

    table = Table(title="Memory Metrics")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    for key in (
        "consolidations",
        "messages_processed",
        "user_messages_processed",
        "user_corrections",
        "events_extracted",
        "event_dedup_merges",
        "profile_updates_applied",
        "retrieval_queries",
        "retrieval_hits",
        "conflicts_detected",
        "memory_context_calls",
        "memory_context_tokens_total",
        "memory_context_tokens_max",
        "last_updated",
    ):
        table.add_row(key, str(metrics.get(key, 0)))
    console.print(table)

    kpi_table = Table(title="Memory KPIs")
    kpi_table.add_column("KPI", style="cyan")
    kpi_table.add_column("Value", style="green")
    kpi_table.add_row("retrieval_hit_rate", str(kpis.get("retrieval_hit_rate", 0.0)))
    kpi_table.add_row("contradiction_rate_per_100_messages", str(kpis.get("contradiction_rate_per_100_messages", 0.0)))
    kpi_table.add_row("user_correction_rate_per_100_user_messages", str(kpis.get("user_correction_rate_per_100_user_messages", 0.0)))
    kpi_table.add_row("avg_memory_context_tokens", str(kpis.get("avg_memory_context_tokens", 0.0)))
    kpi_table.add_row("max_memory_context_tokens", str(kpis.get("max_memory_context_tokens", 0)))
    console.print(kpi_table)

    if query.strip():
        retrieved = store.retrieve(
            query,
            top_k=top_k,
            recency_half_life_days=config.agents.defaults.memory_recency_half_life_days,
            embedding_provider=config.agents.defaults.memory_embedding_provider,
        )
        if not retrieved:
            console.print("\n[dim]No memory retrieved for query.[/dim]")
            return
        out = Table(title=f"Top Memories for: {query}")
        out.add_column("When", style="cyan")
        out.add_column("Type", style="magenta")
        out.add_column("Score", style="green")
        out.add_column("Summary")
        for item in retrieved:
            out.add_row(
                str(item.get("timestamp", ""))[:16],
                str(item.get("type", "fact")),
                f"{float(item.get('score', 0.0)):.3f}",
                str(item.get("summary", "")),
            )
        console.print()
        console.print(out)

    pref_count = len(profile.get("preferences", [])) if isinstance(profile.get("preferences"), list) else 0
    fact_count = len(profile.get("stable_facts", [])) if isinstance(profile.get("stable_facts"), list) else 0
    console.print(f"\nProfile breakdown: preferences={pref_count}, stable_facts={fact_count}")


@memory_app.command("rebuild")
def memory_rebuild(
    max_events: int = typer.Option(30, "--max-events", help="Max recent events for MEMORY.md snapshot"),
):
    """Rebuild memory/MEMORY.md from structured memory profile and events."""
    from nanobot.config.loader import load_config
    from nanobot.agent.memory import MemoryStore

    config = load_config()
    store = MemoryStore(
        config.workspace_path,
        embedding_provider=config.agents.defaults.memory_embedding_provider,
        vector_backend=config.agents.defaults.memory_vector_backend,
    )
    snapshot = store.rebuild_memory_snapshot(max_events=max_events, write=True)
    line_count = len(snapshot.splitlines())
    console.print(f"[green]✓[/green] Rebuilt MEMORY.md with {line_count} lines")


@memory_app.command("verify")
def memory_verify(
    stale_days: int = typer.Option(90, "--stale-days", help="Age threshold for stale events without TTL"),
):
    """Verify memory consistency and freshness."""
    from nanobot.config.loader import load_config
    from nanobot.agent.memory import MemoryStore

    config = load_config()
    store = MemoryStore(
        config.workspace_path,
        embedding_provider=config.agents.defaults.memory_embedding_provider,
        vector_backend=config.agents.defaults.memory_vector_backend,
    )
    report = store.verify_memory(stale_days=stale_days, update_profile=True)

    table = Table(title="Memory Verification")
    table.add_column("Check", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("events", str(report["events"]))
    table.add_row("profile_items", str(report["profile_items"]))
    table.add_row("open_conflicts", str(report["open_conflicts"]))
    table.add_row("stale_events", str(report["stale_events"]))
    table.add_row("stale_profile_items", str(report["stale_profile_items"]))
    table.add_row("ttl_tracked_events", str(report["ttl_tracked_events"]))
    table.add_row("last_verified_at", str(report["last_verified_at"]))
    console.print(table)

    if report["open_conflicts"] > 0:
        raise typer.Exit(2)


@memory_app.command("eval")
def memory_eval(
    cases_file: str = typer.Option("", "--cases-file", help="Path to JSON benchmark cases file"),
    top_k: int = typer.Option(6, "--top-k", "-k", help="Default top-k when case does not specify it"),
    export: bool = typer.Option(False, "--export", help="Save evaluation report JSON under memory/reports/"),
    output_file: str = typer.Option("", "--output-file", help="Optional JSON output path (implies --export)"),
):
    """Evaluate memory retrieval quality (Recall@k, Precision@k) plus runtime KPIs."""
    import json

    from nanobot.config.loader import load_config
    from nanobot.agent.memory import MemoryStore

    config = load_config()
    store = MemoryStore(
        config.workspace_path,
        embedding_provider=config.agents.defaults.memory_embedding_provider,
        vector_backend=config.agents.defaults.memory_vector_backend,
    )

    path = Path(cases_file) if cases_file else (config.workspace_path / "memory" / "eval_cases.json")
    if not path.exists():
        template = {
            "cases": [
                {
                    "query": "oauth2 authentication",
                    "expected_any": ["oauth2", "authentication"],
                    "top_k": 6,
                }
            ]
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8")
        console.print(f"[yellow]Created template benchmark file:[/yellow] {path}")
        console.print("[dim]Edit it and run `nanobot memory eval` again.[/dim]")
        raise typer.Exit(1)

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        console.print(f"[red]Failed to parse benchmark file:[/red] {exc}")
        raise typer.Exit(1)

    raw_cases = payload.get("cases") if isinstance(payload, dict) else payload
    if not isinstance(raw_cases, list):
        console.print("[red]Benchmark file must contain a JSON array or {'cases': [...]}[/red]")
        raise typer.Exit(1)

    evaluation = store.evaluate_retrieval_cases(
        raw_cases,
        default_top_k=top_k,
        recency_half_life_days=config.agents.defaults.memory_recency_half_life_days,
        embedding_provider=config.agents.defaults.memory_embedding_provider,
    )
    obs = store.get_observability_report()
    eval_summary = evaluation.get("summary", {})
    kpis = obs.get("kpis", {})

    table = Table(title="Memory Evaluation")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("cases", str(evaluation.get("cases", 0)))
    table.add_row("recall_at_k", str(eval_summary.get("recall_at_k", 0.0)))
    table.add_row("precision_at_k", str(eval_summary.get("precision_at_k", 0.0)))
    table.add_row("retrieval_hit_rate", str(kpis.get("retrieval_hit_rate", 0.0)))
    table.add_row("contradiction_rate_per_100_messages", str(kpis.get("contradiction_rate_per_100_messages", 0.0)))
    table.add_row("user_correction_rate_per_100_user_messages", str(kpis.get("user_correction_rate_per_100_user_messages", 0.0)))
    table.add_row("avg_memory_context_tokens", str(kpis.get("avg_memory_context_tokens", 0.0)))
    console.print(table)

    details = evaluation.get("evaluated", [])
    if details:
        detail_table = Table(title="Case Breakdown")
        detail_table.add_column("Query", style="cyan")
        detail_table.add_column("TopK")
        detail_table.add_column("Expected")
        detail_table.add_column("Hits", style="green")
        detail_table.add_column("Recall@k", style="green")
        detail_table.add_column("Precision@k", style="green")
        for item in details[:20]:
            detail_table.add_row(
                str(item.get("query", ""))[:60],
                str(item.get("top_k", "")),
                str(item.get("expected", "")),
                str(item.get("hits", "")),
                str(item.get("case_recall_at_k", "")),
                str(item.get("case_precision_at_k", "")),
            )
        console.print(detail_table)

    if export or output_file:
        saved = store.save_evaluation_report(
            evaluation,
            obs,
            output_file=output_file or None,
        )
        console.print(f"[green]✓[/green] Saved report: {saved}")


@memory_app.command("conflicts")
def memory_conflicts(
    all: bool = typer.Option(False, "--all", help="Include resolved conflicts"),
):
    """List memory conflicts for manual review."""
    from nanobot.config.loader import load_config
    from nanobot.agent.memory import MemoryStore

    config = load_config()
    store = MemoryStore(
        config.workspace_path,
        embedding_provider=config.agents.defaults.memory_embedding_provider,
        vector_backend=config.agents.defaults.memory_vector_backend,
    )
    rows = store.list_conflicts(include_closed=all)
    if not rows:
        console.print("No conflicts found.")
        return

    table = Table(title="Memory Conflicts")
    table.add_column("Index", style="cyan")
    table.add_column("Field")
    table.add_column("Old")
    table.add_column("New")
    table.add_column("Status", style="yellow")
    for item in rows:
        table.add_row(
            str(item.get("index", "")),
            str(item.get("field", "")),
            str(item.get("old", ""))[:70],
            str(item.get("new", ""))[:70],
            str(item.get("status", "")),
        )
    console.print(table)


@memory_app.command("resolve")
def memory_resolve(
    index: int = typer.Option(..., "--index", help="Conflict index from `nanobot memory conflicts`"),
    action: str = typer.Option(..., "--action", help="Resolution: keep_old | keep_new | dismiss"),
):
    """Resolve a single memory conflict."""
    from nanobot.config.loader import load_config
    from nanobot.agent.memory import MemoryStore

    config = load_config()
    store = MemoryStore(
        config.workspace_path,
        embedding_provider=config.agents.defaults.memory_embedding_provider,
        vector_backend=config.agents.defaults.memory_vector_backend,
    )
    ok = store.resolve_conflict(index=index, action=action)
    if not ok:
        console.print("[red]Failed to resolve conflict. Check index/action.[/red]")
        raise typer.Exit(1)
    console.print(f"[green]✓[/green] Conflict {index} resolved with action '{action}'")


@memory_app.command("pin")
def memory_pin(
    field: str = typer.Option(..., "--field", help="Profile field (preferences|stable_facts|active_projects|relationships|constraints)"),
    text: str = typer.Option(..., "--text", help="Memory text to pin"),
):
    """Pin a memory item so it is prioritized in snapshots and context."""
    from nanobot.config.loader import load_config
    from nanobot.agent.memory import MemoryStore

    config = load_config()
    store = MemoryStore(
        config.workspace_path,
        embedding_provider=config.agents.defaults.memory_embedding_provider,
        vector_backend=config.agents.defaults.memory_vector_backend,
    )
    try:
        ok = store.set_item_pin(field, text, pinned=True)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    if not ok:
        raise typer.Exit(1)
    console.print(f"[green]✓[/green] Pinned memory item in '{field}'")


@memory_app.command("unpin")
def memory_unpin(
    field: str = typer.Option(..., "--field", help="Profile field"),
    text: str = typer.Option(..., "--text", help="Memory text to unpin"),
):
    """Unpin a memory item."""
    from nanobot.config.loader import load_config
    from nanobot.agent.memory import MemoryStore

    config = load_config()
    store = MemoryStore(
        config.workspace_path,
        embedding_provider=config.agents.defaults.memory_embedding_provider,
        vector_backend=config.agents.defaults.memory_vector_backend,
    )
    try:
        ok = store.set_item_pin(field, text, pinned=False)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    if not ok:
        raise typer.Exit(1)
    console.print(f"[green]✓[/green] Unpinned memory item in '{field}'")


@memory_app.command("outdated")
def memory_outdated(
    field: str = typer.Option(..., "--field", help="Profile field"),
    text: str = typer.Option(..., "--text", help="Memory text to mark outdated"),
):
    """Mark a memory item as outdated (stale)."""
    from nanobot.config.loader import load_config
    from nanobot.agent.memory import MemoryStore

    config = load_config()
    store = MemoryStore(
        config.workspace_path,
        embedding_provider=config.agents.defaults.memory_embedding_provider,
        vector_backend=config.agents.defaults.memory_vector_backend,
    )
    try:
        ok = store.mark_item_outdated(field, text)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    if not ok:
        console.print("[red]Memory item not found.[/red]")
        raise typer.Exit(1)
    console.print(f"[green]✓[/green] Marked memory item as outdated in '{field}'")


@app.command()
def status():
    """Show nanobot status."""
    from nanobot.config.loader import load_config, get_config_path

    config_path = get_config_path()
    config = load_config()
    workspace = config.workspace_path

    console.print(f"{__logo__} nanobot Status\n")

    console.print(f"Config: {config_path} {'[green]✓[/green]' if config_path.exists() else '[red]✗[/red]'}")
    console.print(f"Workspace: {workspace} {'[green]✓[/green]' if workspace.exists() else '[red]✗[/red]'}")

    if config_path.exists():
        from nanobot.providers.registry import PROVIDERS

        console.print(f"Model: {config.agents.defaults.model}")
        
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


if __name__ == "__main__":
    app()
