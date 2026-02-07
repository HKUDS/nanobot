"""CLI commands for nanobot."""

import asyncio
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from nanobot import __version__, __logo__

app = typer.Typer(
    name="nanobot",
    help=f"{__logo__} nanobot - Personal AI Assistant",
    no_args_is_help=True,
)

console = Console()


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
# Shared helpers (DRY)
# ============================================================================


def _validate_api_key(config):
    """Ensure config has an API key. Exits with rich error if not."""
    p = config.get_provider()
    model = config.agents.defaults.model
    if not (p and p.api_key) and not model.startswith("bedrock/"):
        console.print("[red]Error: No API key configured.[/red]")
        console.print("Set one in ~/.nanobot/config.json under providers section")
        raise typer.Exit(1)


async def _boot_agent(config):
    """Init Pulsing, spawn ProviderActor + AgentActor. Returns agent ref."""
    import pulsing as pul
    from nanobot.actor.agent import AgentActor
    from nanobot.actor.provider import ProviderActor

    await pul.init()

    _validate_api_key(config)
    await ProviderActor.spawn(config=config, name="provider")
    return await AgentActor.spawn(config=config, name="agent")


async def _print_stream(agent_actor, channel: str, chat_id: str, content: str):
    """Send a message to the agent and print the streaming response."""
    prefix_printed = False
    async for chunk in agent_actor.process_stream(
        channel=channel,
        sender_id="user",
        chat_id=chat_id,
        content=content,
    ):
        if chunk.kind == "token":
            if not prefix_printed:
                console.print(f"\n{__logo__} ", end="")
                prefix_printed = True
            sys.stdout.write(chunk.text)
            sys.stdout.flush()
        elif chunk.kind == "tool_call":
            console.print(f"  [dim]⚙ {chunk.tool_name}...[/dim]", end="")
        elif chunk.kind == "tool_result":
            console.print(f" [dim]✓[/dim]")
    sys.stdout.write("\n")


# ============================================================================
# Onboard / Setup
# ============================================================================


@app.command()
def onboard():
    """Initialize nanobot configuration and workspace."""
    from nanobot.config.loader import get_config_path, save_config
    from nanobot.config.schema import Config
    from nanobot.utils.helpers import get_workspace_path

    config_path = get_config_path()

    if config_path.exists():
        console.print(f"[yellow]Config already exists at {config_path}[/yellow]")
        if not typer.confirm("Overwrite?"):
            raise typer.Exit()

    # Create default config
    config = Config()
    save_config(config)
    console.print(f"[green]✓[/green] Created config at {config_path}")

    # Create workspace
    workspace = get_workspace_path()
    console.print(f"[green]✓[/green] Created workspace at {workspace}")

    # Create default bootstrap files
    _create_workspace_templates(workspace)

    console.print(f"\n{__logo__} nanobot is ready!")
    console.print("\nNext steps:")
    console.print("  1. Add your API key to [cyan]~/.nanobot/config.json[/cyan]")
    console.print("     Get one at: https://openrouter.ai/keys")
    console.print('  2. Chat: [cyan]nanobot agent -m "Hello!"[/cyan]')
    console.print(
        "\n[dim]Want Telegram/WhatsApp? See: https://github.com/HKUDS/nanobot#-chat-apps[/dim]"
    )


def _create_workspace_templates(workspace: Path):
    """Create default workspace template files."""
    templates = {
        "AGENTS.md": """# Agent Instructions

You are a helpful AI assistant. Be concise, accurate, and friendly.

## Guidelines

- Always explain what you're doing before taking actions
- Ask for clarification when the request is ambiguous
- Use tools to help accomplish tasks
- Remember important information in your memory files
""",
        "SOUL.md": """# Soul

I am nanobot, a lightweight AI assistant.

## Personality

- Helpful and friendly
- Concise and to the point
- Curious and eager to learn

## Values

- Accuracy over speed
- User privacy and safety
- Transparency in actions
""",
        "USER.md": """# User

Information about the user goes here.

## Preferences

- Communication style: (casual/formal)
- Timezone: (your timezone)
- Language: (your preferred language)
""",
    }

    for filename, content in templates.items():
        file_path = workspace / filename
        if not file_path.exists():
            file_path.write_text(content)
            console.print(f"  [dim]Created {filename}[/dim]")

    # Create memory directory and MEMORY.md
    memory_dir = workspace / "memory"
    memory_dir.mkdir(exist_ok=True)
    memory_file = memory_dir / "MEMORY.md"
    if not memory_file.exists():
        memory_file.write_text(
            """# Long-term Memory

This file stores important information that should persist across sessions.

## User Information

(Important facts about the user)

## Preferences

(User preferences learned over time)

## Important Notes

(Things to remember)
"""
        )
        console.print("  [dim]Created memory/MEMORY.md[/dim]")


# ============================================================================
# Gateway / Server
# ============================================================================


@app.command()
def gateway(
    port: int = typer.Option(18790, "--port", "-p", help="Gateway port"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
):
    """Start the nanobot gateway (fully distributed actors)."""
    from nanobot.config.loader import load_config, get_data_dir
    from nanobot.actor.agent import AgentActor
    from nanobot.actor.scheduler import SchedulerActor
    from nanobot.actor.provider import ProviderActor
    from nanobot.channels.manager import create_channels, spawn_channel_actors

    if verbose:
        import logging

        logging.basicConfig(level=logging.DEBUG)

    console.print(f"{__logo__} Starting nanobot gateway on port {port}...")

    config = load_config()
    _validate_api_key(config)

    # Create channel instances (not yet actors)
    channels = create_channels(config, agent_name="agent")

    if channels:
        console.print(f"[green]✓[/green] Channels: {', '.join(channels.keys())}")
    else:
        console.print("[yellow]Warning: No channels enabled[/yellow]")

    console.print(f"[green]✓[/green] Scheduler: cron")

    async def run():
        import pulsing as pul

        await pul.init()

        channel_tasks = []
        try:
            cron_store_path = get_data_dir() / "cron" / "jobs.json"

            # 1) Spawn ProviderActor (takes config directly)
            await ProviderActor.spawn(config=config, name="provider")

            # 2) Spawn SchedulerActor -- auto-starts via on_start()
            await SchedulerActor.spawn(
                cron_store_path=cron_store_path,
                workspace=config.workspace_path,
                agent_name="agent",
                name="scheduler",
            )

            # 3) Spawn AgentActor -- resolves provider + scheduler by name
            await AgentActor.spawn(config=config, name="agent")

            # 4) Spawn each channel as ChannelActor
            channel_tasks = await spawn_channel_actors(channels)

            # Wait for all channel tasks (they run forever)
            if channel_tasks:
                await asyncio.gather(*channel_tasks, return_exceptions=True)
            else:
                # No channels -- just keep running for scheduler
                while True:
                    await asyncio.sleep(3600)

        except KeyboardInterrupt:
            console.print("\nShutting down...")
        finally:
            for t in channel_tasks:
                t.cancel()
            await pul.shutdown()

    asyncio.run(run())


# ============================================================================
# Agent Commands
# ============================================================================


@app.command()
def agent(
    message: str = typer.Option(
        None, "--message", "-m", help="Message to send to the agent"
    ),
    session_id: str = typer.Option("cli:default", "--session", "-s", help="Session ID"),
):
    """Interact with the agent directly."""
    from nanobot.config.loader import load_config

    config = load_config()

    # Parse session_id into channel:chat_id
    if ":" in session_id:
        parts = session_id.split(":", 1)
        cli_channel, cli_chat_id = parts[0], parts[1]
    else:
        cli_channel, cli_chat_id = "cli", session_id

    if message:
        # Single-message mode (streaming)
        async def run_once():
            import pulsing as pul

            try:
                agent_actor = await _boot_agent(config)
                await _print_stream(agent_actor, cli_channel, cli_chat_id, message)
            finally:
                await pul.shutdown()

        asyncio.run(run_once())
    else:
        # Interactive mode (streaming)
        console.print(f"{__logo__} Interactive mode (Ctrl+C to exit)\n")

        async def run_interactive():
            import pulsing as pul

            try:
                agent_actor = await _boot_agent(config)
                while True:
                    try:
                        user_input = console.input("[bold blue]You:[/bold blue] ")
                        if not user_input.strip():
                            continue
                        await _print_stream(
                            agent_actor, cli_channel, cli_chat_id, user_input
                        )
                        sys.stdout.write("\n")  # blank line between exchanges
                    except KeyboardInterrupt:
                        console.print("\nGoodbye!")
                        break
            finally:
                await pul.shutdown()

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
    table.add_row("WhatsApp", "✓" if wa.enabled else "✗", wa.bridge_url)

    dc = config.channels.discord
    table.add_row("Discord", "✓" if dc.enabled else "✗", dc.gateway_url)

    # Telegram
    tg = config.channels.telegram
    tg_config = (
        f"token: {tg.token[:10]}..." if tg.token else "[dim]not configured[/dim]"
    )
    table.add_row("Telegram", "✓" if tg.enabled else "✗", tg_config)

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
    src_bridge = (
        Path(__file__).parent.parent.parent / "bridge"
    )  # repo root/bridge (dev)

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
    shutil.copytree(
        source, user_bridge, ignore=shutil.ignore_patterns("node_modules", "dist")
    )

    # Install and build
    try:
        console.print("  Installing dependencies...")
        subprocess.run(
            ["npm", "install"], cwd=user_bridge, check=True, capture_output=True
        )

        console.print("  Building...")
        subprocess.run(
            ["npm", "run", "build"], cwd=user_bridge, check=True, capture_output=True
        )

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

    bridge_dir = _get_bridge_dir()

    console.print(f"{__logo__} Starting bridge...")
    console.print("Scan the QR code to connect.\n")

    try:
        subprocess.run(["npm", "start"], cwd=bridge_dir, check=True)
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Bridge failed: {e}[/red]")
    except FileNotFoundError:
        console.print("[red]npm not found. Please install Node.js.[/red]")


# ============================================================================
# Cron Commands
# ============================================================================

cron_app = typer.Typer(help="Manage scheduled tasks")
app.add_typer(cron_app, name="cron")


def _make_scheduler_offline():
    """Create a SchedulerActor for offline cron management (no agent, no start)."""
    from nanobot.config.loader import get_data_dir, load_config
    from nanobot.actor.scheduler import SchedulerActor

    config = load_config()
    store_path = get_data_dir() / "cron" / "jobs.json"
    # Create raw instance (not spawned as actor) for file-based cron management
    return SchedulerActor(
        cron_store_path=store_path,
        workspace=config.workspace_path,
    )


@cron_app.command("list")
def cron_list(
    all: bool = typer.Option(False, "--all", "-a", help="Include disabled jobs"),
):
    """List scheduled jobs."""
    service = _make_scheduler_offline()
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

    for job in jobs:
        # Format schedule
        if job.schedule.kind == "every":
            sched = f"every {(job.schedule.every_ms or 0) // 1000}s"
        elif job.schedule.kind == "cron":
            sched = job.schedule.expr or ""
        else:
            sched = "one-time"

        # Format next run
        next_run = ""
        if job.state.next_run_at_ms:
            next_time = time.strftime(
                "%Y-%m-%d %H:%M", time.localtime(job.state.next_run_at_ms / 1000)
            )
            next_run = next_time

        status = "[green]enabled[/green]" if job.enabled else "[dim]disabled[/dim]"

        table.add_row(job.id, job.name, sched, status, next_run)

    console.print(table)


@cron_app.command("add")
def cron_add(
    name: str = typer.Option(..., "--name", "-n", help="Job name"),
    message: str = typer.Option(..., "--message", "-m", help="Message for agent"),
    every: int = typer.Option(None, "--every", "-e", help="Run every N seconds"),
    cron_expr: str = typer.Option(
        None, "--cron", "-c", help="Cron expression (e.g. '0 9 * * *')"
    ),
    at: str = typer.Option(None, "--at", help="Run once at time (ISO format)"),
    deliver: bool = typer.Option(
        False, "--deliver", "-d", help="Deliver response to channel"
    ),
    to: str = typer.Option(None, "--to", help="Recipient for delivery"),
    channel: str = typer.Option(
        None, "--channel", help="Channel for delivery (e.g. 'telegram', 'whatsapp')"
    ),
):
    """Add a scheduled job."""
    from nanobot.cron.types import CronSchedule

    # Determine schedule type
    if every:
        schedule = CronSchedule(kind="every", every_ms=every * 1000)
    elif cron_expr:
        schedule = CronSchedule(kind="cron", expr=cron_expr)
    elif at:
        import datetime

        dt = datetime.datetime.fromisoformat(at)
        schedule = CronSchedule(kind="at", at_ms=int(dt.timestamp() * 1000))
    else:
        console.print("[red]Error: Must specify --every, --cron, or --at[/red]")
        raise typer.Exit(1)

    service = _make_scheduler_offline()

    job = service.add_job(
        name=name,
        schedule=schedule,
        message=message,
        deliver=deliver,
        to=to,
        channel=channel,
    )

    console.print(f"[green]✓[/green] Added job '{job.name}' ({job.id})")


@cron_app.command("remove")
def cron_remove(
    job_id: str = typer.Argument(..., help="Job ID to remove"),
):
    """Remove a scheduled job."""
    service = _make_scheduler_offline()

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
    service = _make_scheduler_offline()

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
    service = _make_scheduler_offline()

    async def run():
        return await service.run_job(job_id, force=force)

    if asyncio.run(run()):
        console.print(f"[green]✓[/green] Job executed")
    else:
        console.print(f"[red]Failed to run job {job_id}[/red]")


# ============================================================================
# Status Commands
# ============================================================================


@app.command()
def status(
    live: bool = typer.Option(
        False, "--live", "-l", help="Query running gateway for actor status"
    ),
):
    """Show nanobot status."""
    from nanobot.config.loader import load_config, get_config_path

    config_path = get_config_path()
    config = load_config()
    workspace = config.workspace_path

    console.print(f"{__logo__} nanobot Status\n")

    console.print(
        f"Config: {config_path} {'[green]✓[/green]' if config_path.exists() else '[red]✗[/red]'}"
    )
    console.print(
        f"Workspace: {workspace} {'[green]✓[/green]' if workspace.exists() else '[red]✗[/red]'}"
    )

    if config_path.exists():
        console.print(f"Model: {config.agents.defaults.model}")

        # Check configured API keys
        providers_info = {
            "OpenRouter": bool(config.providers.openrouter.api_key),
            "Anthropic": bool(config.providers.anthropic.api_key),
            "OpenAI": bool(config.providers.openai.api_key),
            "Gemini": bool(config.providers.gemini.api_key),
            "Zhipu AI": bool(config.providers.zhipu.api_key),
            "AiHubMix": bool(config.providers.aihubmix.api_key),
        }
        for name, has_key in providers_info.items():
            console.print(
                f"{name} API: {'[green]✓[/green]' if has_key else '[dim]not set[/dim]'}"
            )

        has_vllm = bool(config.providers.vllm.api_base)
        vllm_status = (
            f"[green]✓ {config.providers.vllm.api_base}[/green]"
            if has_vllm
            else "[dim]not set[/dim]"
        )
        console.print(f"vLLM/Local: {vllm_status}")

    # Live actor status from Pulsing admin API
    if live:
        console.print("\n[bold]Live Actor Status[/bold]")
        _show_live_actor_status()


def _show_live_actor_status():
    """Query the running Pulsing system for actor status."""

    async def _query():
        import pulsing as pul
        from pulsing.admin import list_actors, health_check

        try:
            system = await pul.init()
            health = await health_check(system)
            actors = await list_actors(system)

            console.print(f"  Health: [green]{health}[/green]")

            if actors:
                table = Table(title="Running Actors")
                table.add_column("Name", style="cyan")
                table.add_column("Type", style="yellow")
                table.add_column("Status", style="green")

                for actor in actors:
                    name = getattr(actor, "name", str(actor))
                    atype = getattr(actor, "type_name", "unknown")
                    table.add_row(name, atype, "running")

                console.print(table)
            else:
                console.print("  [dim]No actors running (gateway not started?)[/dim]")

            await pul.shutdown()
        except Exception as e:
            console.print(f"  [dim]Could not connect to Pulsing runtime: {e}[/dim]")
            console.print("  [dim]Start the gateway first: nanobot gateway[/dim]")

    asyncio.run(_query())


if __name__ == "__main__":
    app()
