"""CLI commands for nanobot."""

import asyncio
import json
import os
import signal
from pathlib import Path
import select
import sys
from typing import Any

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
    
    sync_workspace_templates(workspace)
    
    console.print(f"\n{__logo__} nanobot is ready!")
    console.print("\nNext steps:")
    console.print("  1. Add your API key to [cyan]~/.nanobot/config.json[/cyan]")
    console.print("     Get one at: https://openrouter.ai/keys")
    console.print("  2. Chat: [cyan]nanobot agent -m \"Hello!\"[/cyan]")
    console.print("\n[dim]Want Telegram/WhatsApp? See: https://github.com/HKUDS/nanobot#-chat-apps[/dim]")





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
    sync_workspace_templates(config.workspace_path)
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
        reasoning_effort=config.agents.defaults.reasoning_effort,
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
    sync_workspace_templates(config.workspace_path)
    
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
        reasoning_effort=config.agents.defaults.reasoning_effort,
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
        reasoning_effort=config.agents.defaults.reasoning_effort,
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
# Mobile Testing Commands
# ============================================================================

mobile_app = typer.Typer(help="Manage mobile app automation setup")
app.add_typer(mobile_app, name="mobile")


def _mobile_layout(workspace: Path) -> dict[str, Path]:
    """Return canonical workspace paths for mobile automation."""
    mobile_root = workspace / "mobile"
    reports_root = workspace / "reports" / "mobile"
    return {
        "mobile_root": mobile_root,
        "apps_dir": mobile_root / "apps",
        "flows_dir": mobile_root / "flows",
        "artifacts_dir": reports_root / "artifacts",
        "runs_dir": reports_root / "runs",
        "summary_file": reports_root / "summary-latest.json",
        "sample_flow": mobile_root / "flows" / "smoke.yaml",
    }


def _write_if_missing(path: Path, content: str) -> bool:
    """Create a file only when absent. Returns True if created."""
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def _mobile_slug(name: str) -> str:
    """Build a safe filename token from a flow name."""
    cleaned = "".join(ch if (ch.isalnum() or ch in "-_.") else "-" for ch in name)
    cleaned = cleaned.strip("-._")
    return cleaned or "flow"


def _resolve_mobile_flows(
    workspace: Path,
    flows_dir: Path,
    selected_flows: list[str] | None,
    pattern: str,
) -> list[Path]:
    """Resolve flow file paths from explicit args or glob pattern."""
    candidates: list[Path] = []
    if selected_flows:
        for raw in selected_flows:
            p = Path(raw).expanduser()
            if not p.is_absolute():
                p = workspace / p
            candidates.append(p.resolve())
    else:
        patterns = [p.strip() for p in pattern.split(",") if p.strip()]
        if not patterns:
            patterns = ["*.yaml", "*.yml"]
        for pat in patterns:
            candidates.extend(sorted(flows_dir.glob(pat)))
    seen: set[Path] = set()
    flows: list[Path] = []
    for p in candidates:
        rp = p.resolve()
        if rp not in seen:
            seen.add(rp)
            flows.append(rp)
    return flows


def _mobile_mcp_run_tool_name(tool_names: list[str], server_name: str) -> str | None:
    """Pick preferred Maestro MCP run tool from registered names."""
    preferred = (
        f"mcp_{server_name}_run_flow_files",
        f"mcp_{server_name}_run_flow",
    )
    for name in preferred:
        if name in tool_names:
            return name
    return None


def _mobile_build_mcp_payload_candidates(
    schema: dict[str, Any],
    flow_path: Path,
    flow_output_dir: Path,
    suite: str,
    platform: str,
) -> list[dict[str, Any]]:
    """Build multiple payload candidates to tolerate MCP schema variants."""
    props = schema.get("properties", {}) if isinstance(schema, dict) else {}
    required = schema.get("required", []) if isinstance(schema, dict) else []
    flow = str(flow_path)
    out_dir = str(flow_output_dir)
    candidates: list[dict[str, Any]] = []

    def _append(payload: dict[str, Any]) -> None:
        if payload not in candidates:
            candidates.append(payload)

    # 1) Schema-driven required payload (best effort)
    auto_payload: dict[str, Any] = {}
    unresolved = False
    for key in required if isinstance(required, list) else []:
        key_lower = str(key).lower()
        key_schema = props.get(key, {}) if isinstance(props, dict) else {}
        key_type = key_schema.get("type") if isinstance(key_schema, dict) else None

        if any(token in key_lower for token in ("flow", "file", "path")):
            auto_payload[key] = [flow] if key_type == "array" else flow
        elif any(token in key_lower for token in ("output", "artifact", "report")):
            auto_payload[key] = out_dir
        elif "suite" in key_lower and suite:
            auto_payload[key] = suite
        elif "platform" in key_lower and platform:
            auto_payload[key] = platform
        else:
            unresolved = True
            break

    if not unresolved:
        _append(auto_payload)

    # 2) Common cross-version payload names
    fallback_payloads = [
        {"flow_files": [flow], "test_output_dir": out_dir},
        {"flowFiles": [flow], "testOutputDir": out_dir},
        {"flows": [flow], "test_output_dir": out_dir},
        {"files": [flow], "output_dir": out_dir},
        {"flow": flow, "test_output_dir": out_dir},
        {"flowFile": flow, "testOutputDir": out_dir},
        {"file": flow, "outputDir": out_dir},
        {"path": flow, "output_dir": out_dir},
    ]

    for payload in fallback_payloads:
        if suite:
            payload.setdefault("suite", suite)
            payload.setdefault("test_suite", suite)
        if platform:
            payload.setdefault("platform", platform)
        _append(payload)

    return candidates


async def _mobile_run_with_mcp(
    config: Config,
    server_name: str,
    flows: list[Path],
    artifacts_dir: Path,
    run_dir: Path,
    suite: str,
    platform: str,
    continue_on_fail: bool,
) -> tuple[list[dict[str, Any]], list[Path], list[Path], str]:
    """Run flows via Maestro MCP tool wrappers."""
    from contextlib import AsyncExitStack
    from nanobot.agent.tools.mcp import connect_mcp_servers
    from nanobot.agent.tools.registry import ToolRegistry

    mcp_cfg = config.tools.mcp_servers.get(server_name)
    if not mcp_cfg:
        raise RuntimeError(f"MCP server '{server_name}' not configured")

    registry = ToolRegistry()
    async with AsyncExitStack() as stack:
        await connect_mcp_servers({server_name: mcp_cfg}, registry, stack)
        run_tool = _mobile_mcp_run_tool_name(registry.tool_names, server_name)
        if not run_tool:
            raise RuntimeError(
                f"No runnable mobile test tool found on MCP server '{server_name}'. "
                f"Expected one of: run_flow_files, run_flow"
            )

        tool = registry.get(run_tool)
        schema = tool.parameters if tool else {}
        results: list[dict[str, Any]] = []
        logs: list[Path] = []
        output_dirs: list[Path] = []

        for idx, flow_path in enumerate(flows, 1):
            label = _mobile_slug(flow_path.stem)
            flow_output_dir = artifacts_dir / f"{idx:02d}-{label}"
            flow_output_dir.mkdir(parents=True, exist_ok=True)
            output_dirs.append(flow_output_dir)
            log_file = run_dir / f"{idx:02d}-{label}.log"

            candidates = _mobile_build_mcp_payload_candidates(
                schema=schema,
                flow_path=flow_path,
                flow_output_dir=flow_output_dir,
                suite=suite,
                platform=platform,
            )

            selected_payload: dict[str, Any] = {}
            selected_result = "Error: no MCP payload candidates were generated"
            success = False
            for payload in candidates:
                out = await registry.execute(run_tool, payload)
                selected_payload = payload
                selected_result = out
                if not (isinstance(out, str) and out.startswith("Error")):
                    success = True
                    break

            log_file.write_text(
                (
                    f"Tool: {run_tool}\n"
                    f"Flow: {flow_path}\n"
                    f"Payload: {json.dumps(selected_payload, ensure_ascii=False)}\n\n"
                    f"Result:\n{selected_result}\n"
                ),
                encoding="utf-8",
            )
            logs.append(log_file)
            results.append(
                {
                    "flow": str(flow_path),
                    "status": "passed" if success else "failed",
                    "exitCode": 0 if success else 1,
                    "logFile": str(log_file),
                    "artifactDir": str(flow_output_dir),
                }
            )

            if not success and not continue_on_fail:
                break

        return results, logs, output_dirs, run_tool


@mobile_app.command("setup")
def mobile_setup(
    maestro_command: str = typer.Option(
        "maestro",
        "--maestro-command",
        help="Maestro CLI executable name or absolute path",
    ),
    tool_timeout: int = typer.Option(
        180,
        "--tool-timeout",
        min=10,
        help="MCP tool timeout in seconds",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Overwrite existing maestro MCP config if present",
    ),
):
    """Initialize workspace layout and Maestro MCP config for mobile automation."""
    import shutil
    from nanobot.config.loader import load_config, save_config
    from nanobot.config.schema import MCPServerConfig

    config = load_config()
    workspace = config.workspace_path
    sync_workspace_templates(workspace)

    layout = _mobile_layout(workspace)
    created_dirs: list[Path] = []
    for key in ("apps_dir", "flows_dir", "artifacts_dir", "runs_dir"):
        path = layout[key]
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
            created_dirs.append(path)

    sample_flow_created = _write_if_missing(
        layout["sample_flow"],
        """appId: com.example.app
---
- launchApp
- assertVisible: "Home"
""",
    )

    summary_created = _write_if_missing(
        layout["summary_file"],
        """{
  "runId": "",
  "status": "not-started",
  "platform": "",
  "suite": "",
  "startedAt": "",
  "finishedAt": "",
  "artifacts": []
}
""",
    )

    existing = config.tools.mcp_servers.get("maestro")
    updated_mcp = False

    if existing and not force:
        console.print("[yellow]maestro MCP config already exists. Use --force to overwrite.[/yellow]")
    else:
        env = existing.env if existing else {}
        config.tools.mcp_servers["maestro"] = MCPServerConfig(
            command=maestro_command,
            args=["mcp"],
            env=env,
            tool_timeout=tool_timeout,
        )
        save_config(config)
        updated_mcp = True

    console.print(f"{__logo__} Mobile automation setup complete\n")
    console.print(f"Workspace: [cyan]{workspace}[/cyan]")

    if created_dirs:
        for path in created_dirs:
            console.print(f"  [green]✓[/green] Created dir: {path}")
    else:
        console.print("  [dim]No new directories created[/dim]")

    console.print(
        f"  {'[green]✓[/green]' if sample_flow_created else '[dim]•[/dim]'} "
        f"Sample flow: {layout['sample_flow']}"
    )
    console.print(
        f"  {'[green]✓[/green]' if summary_created else '[dim]•[/dim]'} "
        f"Summary file: {layout['summary_file']}"
    )

    if updated_mcp:
        console.print(
            f"  [green]✓[/green] Configured MCP server 'maestro' => "
            f"`{maestro_command} mcp` (toolTimeout={tool_timeout}s)"
        )
    else:
        console.print("  [dim]• MCP config unchanged[/dim]")

    if shutil.which(maestro_command) is None:
        console.print("\n[yellow]Maestro CLI not found on PATH.[/yellow]")
        console.print("Install: [cyan]curl -fsSL \"https://get.maestro.mobile.dev\" | bash[/cyan]")
        console.print("or: [cyan]brew tap mobile-dev-inc/tap && brew install maestro[/cyan]")

    console.print("\nNext steps:")
    console.print("  1. Start simulator/emulator (or run: [cyan]maestro start-device --platform android[/cyan])")
    console.print("  2. Adjust appId and assertions in [cyan]mobile/flows/smoke.yaml[/cyan]")
    console.print("  3. Run locally: [cyan]maestro test mobile/flows/smoke.yaml[/cyan]")
    console.print("  4. Ask agent to run MCP tools after launching [cyan]nanobot agent[/cyan] or [cyan]nanobot gateway[/cyan]")


@mobile_app.command("run")
def mobile_run(
    flow: list[str] | None = typer.Option(
        None,
        "--flow",
        "-f",
        help="Specific flow files to run (repeatable, relative to workspace or absolute).",
    ),
    pattern: str = typer.Option(
        "*.yaml,*.yml",
        "--pattern",
        help="Glob pattern(s) under mobile/flows when --flow is not provided. Comma-separated supported.",
    ),
    suite: str = typer.Option(
        "default",
        "--suite",
        help="Suite label written into run summary.",
    ),
    platform: str = typer.Option(
        "",
        "--platform",
        help="Optional platform label for summary (android/ios).",
    ),
    continue_on_fail: bool = typer.Option(
        True,
        "--continue-on-fail/--fail-fast",
        help="Continue running remaining flows after a failure.",
    ),
    mode: str = typer.Option(
        "auto",
        "--mode",
        help="Execution mode: auto, local, or mcp.",
    ),
    mcp_server: str = typer.Option(
        "maestro",
        "--mcp-server",
        help="MCP server name from tools.mcpServers (used in mcp/auto mode).",
    ),
    maestro_command: str = typer.Option(
        "maestro",
        "--maestro-command",
        help="Maestro CLI executable name or absolute path.",
    ),
):
    """Run mobile flow files and persist summary/report artifacts."""
    import shutil
    import subprocess
    import uuid
    from datetime import datetime
    from nanobot.config.loader import load_config

    config = load_config()
    workspace = config.workspace_path
    layout = _mobile_layout(workspace)
    flows = _resolve_mobile_flows(workspace, layout["flows_dir"], flow, pattern)
    mode = mode.lower().strip()

    if not flows:
        console.print(f"[red]No flow files found.[/red] pattern={pattern}, flows_dir={layout['flows_dir']}")
        raise typer.Exit(1)

    missing = [str(p) for p in flows if not p.exists()]
    if missing:
        console.print(f"[red]Flow file not found:[/red] {missing[0]}")
        raise typer.Exit(1)

    if mode not in {"auto", "local", "mcp"}:
        console.print(f"[red]Invalid mode:[/red] {mode}. Use auto/local/mcp.")
        raise typer.Exit(1)

    has_mcp = mcp_server in config.tools.mcp_servers
    use_mcp = mode == "mcp" or (mode == "auto" and has_mcp)

    if mode == "mcp" and not has_mcp:
        console.print(f"[red]MCP server not configured:[/red] {mcp_server}")
        console.print("Configure it in ~/.nanobot/config.json under tools.mcpServers")
        raise typer.Exit(1)

    if not use_mcp and shutil.which(maestro_command) is None:
        console.print(f"[red]Maestro CLI not found:[/red] {maestro_command}")
        console.print('Install: [cyan]curl -fsSL "https://get.maestro.mobile.dev" | bash[/cyan]')
        raise typer.Exit(1)

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    started_at = datetime.now().astimezone().isoformat(timespec="seconds")
    run_dir = layout["runs_dir"] / run_id
    artifacts_dir = layout["artifacts_dir"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    def _rel(path: Path) -> str:
        try:
            return str(path.relative_to(workspace))
        except ValueError:
            return str(path)

    results: list[dict[str, object]] = []
    logs: list[Path] = []
    output_dirs: list[Path] = []
    exec_mode = "mcp" if use_mcp else "local"
    console.print(f"Execution mode: [cyan]{exec_mode}[/cyan]")

    if use_mcp:
        try:
            raw_results, logs, output_dirs, run_tool = asyncio.run(
                _mobile_run_with_mcp(
                    config=config,
                    server_name=mcp_server,
                    flows=flows,
                    artifacts_dir=artifacts_dir,
                    run_dir=run_dir,
                    suite=suite,
                    platform=platform,
                    continue_on_fail=continue_on_fail,
                )
            )
            console.print(f"MCP tool: [cyan]{run_tool}[/cyan]")
            for item in raw_results:
                status = str(item.get("status", "failed"))
                symbol = "[green]✓[/green]" if status == "passed" else "[red]✗[/red]"
                flow_name = Path(str(item.get("flow", ""))).name
                console.print(f"{symbol} {flow_name} ({status})")
                results.append(
                    {
                        "flow": _rel(Path(str(item.get("flow", "")))),
                        "status": status,
                        "exitCode": int(item.get("exitCode", 1)),
                        "logFile": _rel(Path(str(item.get("logFile", "")))),
                        "artifactDir": _rel(Path(str(item.get("artifactDir", "")))),
                    }
                )
        except Exception as e:
            if mode == "auto":
                console.print(f"[yellow]MCP execution failed in auto mode, fallback to local: {e}[/yellow]")
                use_mcp = False
            else:
                console.print(f"[red]MCP execution failed:[/red] {e}")
                raise typer.Exit(1)

    if not use_mcp:
        for idx, flow_path in enumerate(flows, 1):
            label = _mobile_slug(flow_path.stem)
            log_file = run_dir / f"{idx:02d}-{label}.log"
            flow_output_dir = artifacts_dir / f"{idx:02d}-{label}"
            flow_output_dir.mkdir(parents=True, exist_ok=True)
            cmd = [maestro_command, "test", str(flow_path), "--test-output-dir", str(flow_output_dir)]
            proc = subprocess.run(
                cmd,
                cwd=workspace,
                capture_output=True,
                text=True,
            )
            log_file.write_text(
                f"$ {' '.join(cmd)}\n\nSTDOUT:\n{proc.stdout or ''}\n\nSTDERR:\n{proc.stderr or ''}\n",
                encoding="utf-8",
            )
            logs.append(log_file)
            output_dirs.append(flow_output_dir)
            status = "passed" if proc.returncode == 0 else "failed"
            results.append(
                {
                    "flow": _rel(flow_path),
                    "status": status,
                    "exitCode": proc.returncode,
                    "logFile": _rel(log_file),
                    "artifactDir": _rel(flow_output_dir),
                }
            )

            symbol = "[green]✓[/green]" if status == "passed" else "[red]✗[/red]"
            console.print(f"{symbol} {flow_path.name} ({status}) -> {log_file.name}")
            if proc.returncode != 0 and not continue_on_fail:
                console.print("[yellow]Fail-fast enabled; stopping remaining flows.[/yellow]")
                break

    passed = sum(1 for item in results if item["status"] == "passed")
    failed = len(results) - passed
    finished_at = datetime.now().astimezone().isoformat(timespec="seconds")
    summary = {
        "runId": run_id,
        "status": "passed" if failed == 0 else "failed",
        "platform": platform,
        "suite": suite,
        "startedAt": started_at,
        "finishedAt": finished_at,
        "requestedFlows": len(flows),
        "executedFlows": len(results),
        "passedFlows": passed,
        "failedFlows": failed,
        "executionMode": "mcp" if use_mcp else "local",
        "mcpServer": mcp_server if use_mcp else "",
        "flows": results,
        "artifacts": (
            [{"type": "log", "path": _rel(p)} for p in logs]
            + [{"type": "maestro-output-dir", "path": _rel(p)} for p in output_dirs]
        ),
    }

    run_summary = run_dir / "summary.json"
    run_summary.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    layout["summary_file"].parent.mkdir(parents=True, exist_ok=True)
    layout["summary_file"].write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    table = Table(title=f"Mobile Run Summary ({run_id})")
    table.add_column("Suite", style="cyan")
    table.add_column("Requested")
    table.add_column("Executed")
    table.add_column("Passed", style="green")
    table.add_column("Failed", style="red")
    table.add_row(suite, str(len(flows)), str(len(results)), str(passed), str(failed))
    console.print()
    console.print(table)
    console.print(f"Summary: [cyan]{layout['summary_file']}[/cyan]")
    console.print(f"Run dir: [cyan]{run_dir}[/cyan]")

    if failed > 0:
        raise typer.Exit(1)


@mobile_app.command("status")
def mobile_status():
    """Show mobile automation workspace and maestro MCP status."""
    from nanobot.config.loader import load_config, get_config_path

    config_path = get_config_path()
    config = load_config()
    workspace = config.workspace_path
    layout = _mobile_layout(workspace)
    maestro = config.tools.mcp_servers.get("maestro")
    cwd = Path.cwd()

    table = Table(title="Mobile Automation Status")
    table.add_column("Item", style="cyan")
    table.add_column("Value", style="yellow")

    table.add_row("Config", str(config_path))
    table.add_row("Workspace", str(workspace))
    if not str(workspace).startswith(str(cwd)):
        table.add_row("Workspace scope", f"outside current cwd ({cwd})")
    table.add_row("Flows dir", str(layout["flows_dir"]))
    table.add_row("Apps dir", str(layout["apps_dir"]))
    table.add_row("Reports dir", str(layout["runs_dir"].parent))
    table.add_row("Sample flow exists", "✓" if layout["sample_flow"].exists() else "✗")

    if maestro:
        cmd = " ".join([maestro.command, *maestro.args]).strip()
        table.add_row("MCP maestro", f"✓ {cmd}")
        table.add_row("MCP toolTimeout", f"{maestro.tool_timeout}s")
    else:
        table.add_row("MCP maestro", "✗ not configured")

    console.print(table)


# ============================================================================
# Status Commands
# ============================================================================


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
