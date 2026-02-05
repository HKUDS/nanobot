"""CLI commands for nanobot."""

import asyncio
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
    console.print("  1. Configure a provider:")
    console.print("     • [cyan]nanobot config setup-provider[/cyan] - Interactive provider setup")
    console.print("     • Or edit [cyan]~/.nanobot/config.json[/cyan] manually")
    console.print("  2. Chat: [cyan]nanobot agent -m \"Hello!\"[/cyan]")
    console.print("\n[dim]Optional: Configure web search, usage alerts, or chat apps[/dim]")
    console.print("[dim]Run 'nanobot config --help' for more options[/dim]")




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
        memory_file.write_text("""# Long-term Memory

This file stores important information that should persist across sessions.

## User Information

(Important facts about the user)

## Preferences

(User preferences learned over time)

## Important Notes

(Things to remember)
""")
        console.print("  [dim]Created memory/MEMORY.md[/dim]")


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
    from nanobot.providers.litellm_provider import LiteLLMProvider
    from nanobot.agent.loop import AgentLoop
    from nanobot.channels.manager import ChannelManager
    from nanobot.cron.service import CronService
    from nanobot.cron.types import CronJob
    from nanobot.heartbeat.service import HeartbeatService
    
    if verbose:
        import logging
        logging.basicConfig(level=logging.DEBUG)
    
    console.print(f"{__logo__} Starting nanobot gateway on port {port}...")
    
    config = load_config()
    
    # Create components
    bus = MessageBus()
    
    # Determine which provider to use
    # Priority: explicit config -> available API keys
    provider = None
    api_key = config.get_api_key()
    api_base = config.get_api_base()
    model = config.agents.defaults.model
    is_bedrock = model.startswith("bedrock/")
    if config.providers.ollama.enabled:
        # Use Ollama provider
        from nanobot.providers.ollama_provider import OllamaProvider
        provider = OllamaProvider(
            mode=config.providers.ollama.mode,
            api_key=config.providers.ollama.api_key,
            base_url=config.providers.ollama.base_url,
            default_model=config.agents.defaults.model or config.providers.ollama.default_model,
        )
        console.print(f"[green]✓[/green] Using Ollama provider ({config.providers.ollama.mode} mode)")
    else:
        # Use LiteLLM provider (default)
        from nanobot.providers.litellm_provider import LiteLLMProvider
        
        if not api_key and not is_bedrock:
            console.print("[red]Error: No API key configured.[/red]")
            console.print("Set one in ~/.nanobot/config.json under providers.openrouter.apiKey")
            raise typer.Exit(1)
        
        provider = LiteLLMProvider(
            api_key=api_key,
            api_base=api_base,
            default_model=model
        )
    
    # Create agent
    agent = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        model=config.agents.defaults.model,
        max_iterations=config.agents.defaults.max_tool_iterations,
        brave_api_key=config.tools.web.search.api_key or None,
        ollama_web_search_key=config.tools.web.ollama_search.api_key if config.tools.web.ollama_search.enabled else None,
        ollama_web_search_base_url=config.tools.web.ollama_search.base_url if config.tools.web.ollama_search.enabled else None,
        exec_config=config.tools.exec,
        usage_alert_config=config.usage_alert,
    )
    
    # Create cron service
    async def on_cron_job(job: CronJob) -> str | None:
        """Execute a cron job through the agent."""
        response = await agent.process_direct(
            job.payload.message,
            session_key=f"cron:{job.id}"
        )
        # Optionally deliver to channel
        if job.payload.deliver and job.payload.to:
            from nanobot.bus.events import OutboundMessage
            await bus.publish_outbound(OutboundMessage(
                channel=job.payload.channel or "whatsapp",
                chat_id=job.payload.to,
                content=response or ""
            ))
        return response
    
    cron_store_path = get_data_dir() / "cron" / "jobs.json"
    cron = CronService(cron_store_path, on_job=on_cron_job)
    
    # Create heartbeat service
    async def on_heartbeat(prompt: str) -> str:
        """Execute heartbeat through the agent."""
        return await agent.process_direct(prompt, session_key="heartbeat")
    
    heartbeat = HeartbeatService(
        workspace=config.workspace_path,
        on_heartbeat=on_heartbeat,
        interval_s=30 * 60,  # 30 minutes
        enabled=True
    )
    
    # Create channel manager
    channels = ChannelManager(config, bus)
    
    if channels.enabled_channels:
        console.print(f"[green]✓[/green] Channels enabled: {', '.join(channels.enabled_channels)}")
    else:
        console.print("[yellow]Warning: No channels enabled[/yellow]")
    
    cron_status = cron.status()
    if cron_status["jobs"] > 0:
        console.print(f"[green]✓[/green] Cron: {cron_status['jobs']} scheduled jobs")
    
    console.print(f"[green]✓[/green] Heartbeat: every 30m")
    
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
    session_id: str = typer.Option("cli:default", "--session", "-s", help="Session ID"),
):
    """Interact with the agent directly."""
    from nanobot.config.loader import load_config
    from nanobot.bus.queue import MessageBus
    from nanobot.providers.litellm_provider import LiteLLMProvider
    from nanobot.agent.loop import AgentLoop
    
    config = load_config()
    
    # Determine provider
    if config.providers.ollama.enabled:
        from nanobot.providers.ollama_provider import OllamaProvider
        provider = OllamaProvider(
            mode=config.providers.ollama.mode,
            api_key=config.providers.ollama.api_key,
            base_url=config.providers.ollama.base_url,
            default_model=config.agents.defaults.model,
        )
    else:
        from nanobot.providers.litellm_provider import LiteLLMProvider
        api_key = config.get_api_key()
        api_base = config.get_api_base()
        model = config.agents.defaults.model
        is_bedrock = model.startswith("bedrock/")

        if not api_key and not is_bedrock:
            console.print("[red]Error: No API key configured.[/red]")
            raise typer.Exit(1)

        provider = LiteLLMProvider(
            api_key=api_key,
            api_base=api_base,
            default_model=config.agents.defaults.model
        )

    bus = MessageBus()
    
    agent_loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        brave_api_key=config.tools.web.search.api_key or None,
        ollama_web_search_key=config.tools.web.ollama_search.api_key if config.tools.web.ollama_search.enabled else None,
        ollama_web_search_base_url=config.tools.web.ollama_search.base_url if config.tools.web.ollama_search.enabled else None,
        exec_config=config.tools.exec,
        usage_alert_config=config.usage_alert,
    )
    
    if message:
        # Single message mode
        async def run_once():
            response = await agent_loop.process_direct(message, session_id)
            console.print(f"\n{__logo__} {response}")
        
        asyncio.run(run_once())
    else:
        # Interactive mode
        console.print(f"{__logo__} Interactive mode (Ctrl+C to exit)\n")
        
        async def run_interactive():
            while True:
                try:
                    user_input = console.input("[bold blue]You:[/bold blue] ")
                    if not user_input.strip():
                        continue
                    
                    response = await agent_loop.process_direct(user_input, session_id)
                    console.print(f"\n{__logo__} {response}\n")
                except KeyboardInterrupt:
                    console.print("\nGoodbye!")
                    break
        
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

    # Telegram
    tg = config.channels.telegram
    tg_config = f"token: {tg.token[:10]}..." if tg.token else "[dim]not configured[/dim]"
    table.add_row(
        "Telegram",
        "✓" if tg.enabled else "✗",
        tg_config
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
            next_time = time.strftime("%Y-%m-%d %H:%M", time.localtime(job.state.next_run_at_ms / 1000))
            next_run = next_time
        
        status = "[green]enabled[/green]" if job.enabled else "[dim]disabled[/dim]"
        
        table.add_row(job.id, job.name, sched, status, next_run)
    
    console.print(table)


@cron_app.command("add")
def cron_add(
    name: str = typer.Option(..., "--name", "-n", help="Job name"),
    message: str = typer.Option(..., "--message", "-m", help="Message for agent"),
    every: int = typer.Option(None, "--every", "-e", help="Run every N seconds"),
    cron_expr: str = typer.Option(None, "--cron", "-c", help="Cron expression (e.g. '0 9 * * *')"),
    at: str = typer.Option(None, "--at", help="Run once at time (ISO format)"),
    deliver: bool = typer.Option(False, "--deliver", "-d", help="Deliver response to channel"),
    to: str = typer.Option(None, "--to", help="Recipient for delivery"),
    channel: str = typer.Option(None, "--channel", help="Channel for delivery (e.g. 'telegram', 'whatsapp')"),
):
    """Add a scheduled job."""
    from nanobot.config.loader import get_data_dir
    from nanobot.cron.service import CronService
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
    
    store_path = get_data_dir() / "cron" / "jobs.json"
    service = CronService(store_path)
    
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
    from nanobot.config.loader import get_data_dir
    from nanobot.cron.service import CronService
    
    store_path = get_data_dir() / "cron" / "jobs.json"
    service = CronService(store_path)
    
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
        console.print(f"Model: {config.agents.defaults.model}")
        
        # Check API keys
        has_openrouter = bool(config.providers.openrouter.api_key)
        has_anthropic = bool(config.providers.anthropic.api_key)
        has_openai = bool(config.providers.openai.api_key)
        has_gemini = bool(config.providers.gemini.api_key)
        has_ollama = config.providers.ollama.enabled
        has_vllm = bool(config.providers.vllm.api_base)
        
        console.print(f"OpenRouter API: {'[green]✓[/green]' if has_openrouter else '[dim]not set[/dim]'}")
        console.print(f"Anthropic API: {'[green]✓[/green]' if has_anthropic else '[dim]not set[/dim]'}")
        console.print(f"OpenAI API: {'[green]✓[/green]' if has_openai else '[dim]not set[/dim]'}")
        console.print(f"Gemini API: {'[green]✓[/green]' if has_gemini else '[dim]not set[/dim]'}")
        
        # Ollama status with mode indication
        if has_ollama:
            if config.providers.ollama.mode == "cloud":
                ollama_status = "[green]✓ cloud (ollama.com)[/green]"
            else:
                ollama_base = config.providers.ollama.base_url or "http://localhost:11434"
                ollama_status = f"[green]✓ local ({ollama_base})[/green]"
        else:
            ollama_status = "[dim]not set[/dim]"
        console.print(f"Ollama: {ollama_status}")
        
        vllm_status = f"[green]✓ {config.providers.vllm.api_base}[/green]" if has_vllm else "[dim]not set[/dim]"
        console.print(f"vLLM/Local: {vllm_status}")
        
        # Show usage alerts status
        if config.usage_alert.enabled:
            console.print(f"Usage Alerts: [green]✓ enabled[/green] (daily: {config.usage_alert.daily_limit:,}, session: {config.usage_alert.session_limit:,})")
        
        console.print(f"\n[dim]Run 'nanobot config show' for detailed configuration[/dim]")


# ============================================================================
# Config Commands
# ============================================================================

config_app = typer.Typer(help="Manage nanobot configuration")
app.add_typer(config_app, name="config")


@config_app.command("show")
def config_show():
    """Display current configuration."""
    from nanobot.config.loader import load_config, get_config_path
    import json
    
    config = load_config()
    config_path = get_config_path()
    
    console.print(f"[bold]Configuration:[/bold] {config_path}\n")
    
    # Show key settings
    console.print("[bold cyan]Providers:[/bold cyan]")
    providers = {
        "OpenRouter": bool(config.providers.openrouter.api_key),
        "Anthropic": bool(config.providers.anthropic.api_key),
        "OpenAI": bool(config.providers.openai.api_key),
        "Groq": bool(config.providers.groq.api_key),
        "Gemini": bool(config.providers.gemini.api_key),
        "Ollama": bool(config.providers.ollama.enabled),
        "vLLM": bool(config.providers.vllm.api_base),
    }
    for name, configured in providers.items():
        status = "[green]✓ configured[/green]" if configured else "[dim]not set[/dim]"
        console.print(f"  {name}: {status}")
    
    console.print(f"\n[bold cyan]Default Model:[/bold cyan] {config.agents.defaults.model}")
    
    console.print("\n[bold cyan]Web Search:[/bold cyan]")
    console.print(f"  Brave Search: {'[green]✓[/green]' if config.tools.web.search.api_key else '[dim]not set[/dim]'}")
    console.print(f"  Ollama Search: {'[green]✓ enabled[/green]' if config.tools.web.ollama_search.enabled else '[dim]disabled[/dim]'}")
    
    console.print("\n[bold cyan]Usage Alerts:[/bold cyan]")
    if config.usage_alert.enabled:
        console.print(f"  [green]✓ Enabled[/green]")
        console.print(f"  Daily limit: {config.usage_alert.daily_limit:,} tokens")
        console.print(f"  Session limit: {config.usage_alert.session_limit:,} tokens")
    else:
        console.print("  [dim]Disabled[/dim]")
    
    console.print(f"\n[dim]Full config: {config_path}[/dim]")


@config_app.command("setup-provider")
def config_setup_provider():
    """Interactive provider setup wizard."""
    from nanobot.config.loader import load_config, save_config
    
    console.print("[bold]LLM Provider Setup[/bold]\n")
    console.print("Choose a provider to configure:\n")
    console.print("  1. OpenRouter (recommended - access to all models)")
    console.print("  2. Ollama (local models or cloud)")
    console.print("  3. Anthropic (Claude)")
    console.print("  4. OpenAI (GPT)")
    console.print("  5. Groq (fast inference)")
    console.print("  6. Other providers (manual edit)")
    
    choice = console.input("\n[bold cyan]Select provider [1-6]:[/bold cyan] ").strip()
    
    config = load_config()
    
    if choice == "1":
        # OpenRouter
        console.print("\n[bold]OpenRouter Configuration[/bold]")
        console.print("Get your API key at: https://openrouter.ai/keys\n")
        api_key = console.input("API Key: ").strip()
        if api_key:
            config.providers.openrouter.api_key = api_key
            console.print("[green]✓[/green] OpenRouter configured")
    
    elif choice == "2":
        # Ollama
        console.print("\n[bold]Ollama Configuration[/bold]")
        console.print("\nChoose mode:")
        console.print("  1. Local - Run models on your machine (requires Ollama installed)")
        console.print("  2. Cloud - Use Ollama cloud service (requires API key)")
        
        mode_choice = console.input("\n[bold cyan]Select mode [1/2]:[/bold cyan] ").strip()
        
        if mode_choice == "2":
            # Cloud mode
            console.print("\n[cyan]Cloud Mode Configuration[/cyan]")
            console.print("Get your API key at: https://ollama.com/settings/keys\n")
            
            api_key = console.input("Ollama Cloud API Key: ").strip()
            if not api_key:
                console.print("[red]Error: API key required for cloud mode[/red]")
                return
            
            config.providers.ollama.enabled = True
            config.providers.ollama.mode = "cloud"
            config.providers.ollama.api_key = api_key
            
            model = console.input("Default model [qwen3-coder:480b]: ").strip() or "qwen3-coder:480b"
            config.providers.ollama.default_model = model
            config.agents.defaults.model = model
            
            console.print("[green]✓[/green] Ollama cloud mode configured")
            
            # Offer to enable Ollama Web Search
            if typer.confirm("\nEnable Ollama Web Search tool?", default=True):
                config.tools.web.ollama_search.enabled = True
                config.tools.web.ollama_search.api_key = api_key
                config.tools.web.ollama_search.base_url = "https://ollama.com"
                console.print("[green]✓[/green] Ollama Web Search enabled")
        else:
            # Local mode (default)
            console.print("\n[cyan]Local Mode Configuration[/cyan]")
            
            base_url = console.input("Base URL [http://localhost:11434]: ").strip() or "http://localhost:11434"
            config.providers.ollama.enabled = True
            config.providers.ollama.mode = "local"
            config.providers.ollama.base_url = base_url
            
            model = console.input("Default model [qwen3:4b]: ").strip() or "qwen3:4b"
            config.providers.ollama.default_model = model
            config.agents.defaults.model = model
            
            console.print("[green]✓[/green] Ollama local mode configured")
    
    elif choice == "3":
        # Anthropic
        console.print("\n[bold]Anthropic Configuration[/bold]")
        console.print("Get your API key at: https://console.anthropic.com\n")
        api_key = console.input("API Key: ").strip()
        if api_key:
            config.providers.anthropic.api_key = api_key
            console.print("[green]✓[/green] Anthropic configured")
    
    elif choice == "4":
        # OpenAI
        console.print("\n[bold]OpenAI Configuration[/bold]")
        console.print("Get your API key at: https://platform.openai.com\n")
        api_key = console.input("API Key: ").strip()
        if api_key:
            config.providers.openai.api_key = api_key
            console.print("[green]✓[/green] OpenAI configured")
    
    elif choice == "5":
        # Groq
        console.print("\n[bold]Groq Configuration[/bold]")
        console.print("Get your API key at: https://console.groq.com\n")
        api_key = console.input("API Key: ").strip()
        if api_key:
            config.providers.groq.api_key = api_key
            console.print("[green]✓[/green] Groq configured")
    
    else:
        console.print("[yellow]For other providers, edit config file: nanobot config edit[/yellow]")
        return
    
    save_config(config)
    console.print("\n[green]✓[/green] Provider configuration saved!")


@config_app.command("setup-alerts")
def config_setup_alerts(
    enable: bool = typer.Option(None, "--enable/--disable", help="Enable or disable alerts"),
    daily_limit: int = typer.Option(None, "--daily", help="Daily token limit"),
    session_limit: int = typer.Option(None, "--session", help="Per-session token limit"),
):
    """Configure usage alerts."""
    from nanobot.config.loader import load_config, save_config
    
    config = load_config()
    
    if enable is not None:
        config.usage_alert.enabled = enable
        console.print(f"[green]✓[/green] Usage alerts {'enabled' if enable else 'disabled'}")
    
    if daily_limit:
        config.usage_alert.daily_limit = daily_limit
        console.print(f"[green]✓[/green] Daily limit: {daily_limit:,} tokens")
    
    if session_limit:
        config.usage_alert.session_limit = session_limit
        console.print(f"[green]✓[/green] Session limit: {session_limit:,} tokens")
    
    if not any([enable is not None, daily_limit, session_limit]):
        # Interactive mode
        console.print("[bold]Usage Alerts Configuration[/bold]\n")
        
        if typer.confirm("Enable usage alerts?", default=False):
            config.usage_alert.enabled = True
            
            daily = console.input("Daily token limit [1000000]: ").strip()
            config.usage_alert.daily_limit = int(daily) if daily else 1000000
            
            session = console.input("Per-session token limit [100000]: ").strip()
            config.usage_alert.session_limit = int(session) if session else 100000
            
            console.print("[green]✓[/green] Usage alerts configured!")
        else:
            config.usage_alert.enabled = False
    
    save_config(config)


@config_app.command("setup-web-search")
def config_setup_web_search():
    """Configure web search tools for the agent."""
    from nanobot.config.loader import load_config, save_config
    
    console.print("[bold]Web Search Tools Configuration[/bold]\n")
    console.print("Configure search tools that the agent can use:\n")
    
    config = load_config()
    
    # Brave Search
    console.print("[cyan]1. Brave Search[/cyan] - Independent search service")
    if typer.confirm("   Configure Brave Search?", default=True):
        console.print("\n   Get API key at: https://brave.com/search/api/\n")
        api_key = console.input("   Brave API Key: ").strip()
        if api_key:
            config.tools.web.search.api_key = api_key
            console.print("   [green]✓[/green] Brave Search configured\n")
    
    # Ollama Search
    console.print("[cyan]2. Ollama Web Search[/cyan] - Requires Ollama Cloud")
    if typer.confirm("   Configure Ollama Web Search?", default=False):
        # Check if Ollama provider is configured in cloud mode
        if config.providers.ollama.enabled and config.providers.ollama.mode == "cloud" and config.providers.ollama.api_key:
            console.print(f"\n   [dim]Ollama cloud mode detected - API key available[/dim]")
            if typer.confirm("   Use the same API key as Ollama provider?", default=True):
                config.tools.web.ollama_search.enabled = True
                config.tools.web.ollama_search.api_key = config.providers.ollama.api_key
                config.tools.web.ollama_search.base_url = "https://ollama.com"
                console.print("   [green]✓[/green] Ollama Web Search configured (using provider API key)\n")
            else:
                console.print("\n   Enter a different API key for Ollama Web Search:\n")
                api_key = console.input("   Ollama API Key: ").strip()
                if api_key:
                    config.tools.web.ollama_search.enabled = True
                    config.tools.web.ollama_search.api_key = api_key
                    config.tools.web.ollama_search.base_url = "https://ollama.com"
                    console.print("   [green]✓[/green] Ollama Web Search configured\n")
        else:
            console.print("\n   [yellow]Note:[/yellow] Ollama Web Search requires Ollama cloud mode")
            console.print("   Get API key at: https://ollama.com/settings/keys\n")
            if typer.confirm("   Do you have an Ollama Cloud API key?", default=False):
                api_key = console.input("   Ollama API Key: ").strip()
                if api_key:
                    config.tools.web.ollama_search.enabled = True
                    config.tools.web.ollama_search.api_key = api_key
                    config.tools.web.ollama_search.base_url = "https://ollama.com"
                    console.print("   [green]✓[/green] Ollama Web Search configured\n")
            else:
                console.print("   [yellow]Tip:[/yellow] Run 'nanobot config setup-provider' and choose Ollama cloud mode\n")
    
    save_config(config)
    console.print("[green]✓[/green] Web search tools configuration saved!")


@config_app.command("edit")
def config_edit():
    """Open config file in default editor."""
    from nanobot.config.loader import get_config_path
    import subprocess
    import sys
    
    config_path = get_config_path()
    
    console.print(f"Opening: {config_path}")
    
    if sys.platform == "win32":
        subprocess.run(["notepad", str(config_path)])
    elif sys.platform == "darwin":
        subprocess.run(["open", str(config_path)])
    else:
        subprocess.run(["xdg-open", str(config_path)])


# ============================================================================
# Usage Commands
# ============================================================================

usage_app = typer.Typer(help="View token usage statistics")
app.add_typer(usage_app, name="usage")


@usage_app.callback(invoke_without_command=True)
def usage_main(
    ctx: typer.Context,
    session: str = typer.Option(None, "--session", "-s", help="Show usage for specific session"),
    today: bool = typer.Option(False, "--today", help="Show today's usage"),
    week: bool = typer.Option(False, "--week", help="Show this week's usage"),
    export: str = typer.Option(None, "--export", "-e", help="Export all data to JSON file"),
    clear: bool = typer.Option(False, "--clear", help="Clear all usage data"),
):
    """View token usage statistics."""
    from nanobot.usage.tracker import UsageTracker
    import json
    
    tracker = UsageTracker()
    
    # Clear data
    if clear:
        if typer.confirm("⚠️  Clear all usage data? This cannot be undone."):
            tracker.clear()
            console.print("[green]✓[/green] Usage data cleared")
        return
    
    # Export data
    if export:
        data = tracker.export()
        with open(export, "w") as f:
            json.dump(data, f, indent=2)
        console.print(f"[green]✓[/green] Exported usage data to {export}")
        return
    
    # Show specific session
    if session:
        usage = tracker.get_session(session)
        if not usage:
            console.print(f"[yellow]No usage data for session: {session}[/yellow]")
            return
        
        console.print(f"\n[bold]Session: {session}[/bold]")
        _print_usage_stats(usage)
        return
    
    # Show today's usage
    if today:
        usage = tracker.get_daily()
        if not usage:
            console.print("[yellow]No usage data for today[/yellow]")
            return
        
        from datetime import date
        console.print(f"\n[bold]Usage for {date.today().isoformat()}[/bold]")
        _print_usage_stats(usage)
        return
    
    # Show week's usage
    if week:
        usage = tracker.get_week()
        console.print("\n[bold]Usage for This Week[/bold]")
        _print_usage_stats(usage)
        return
    
    # If no command specified, show total usage (default)
    if ctx.invoked_subcommand is None:
        usage = tracker.get_total()
        console.print("\n[bold]Total Token Usage[/bold]")
        _print_usage_stats(usage)
        
        # Show top sessions
        all_sessions = tracker.get_all_sessions()
        if all_sessions:
            console.print("\n[bold]Top Sessions[/bold]")
            sorted_sessions = sorted(
                all_sessions.items(),
                key=lambda x: x[1].get("total_tokens", 0),
                reverse=True
            )[:5]
            
            table = Table()
            table.add_column("Session", style="cyan")
            table.add_column("Total Tokens", justify="right")
            table.add_column("Calls", justify="right")
            
            for session_key, stats in sorted_sessions:
                table.add_row(
                    session_key,
                    f"{stats.get('total_tokens', 0):,}",
                    str(stats.get('call_count', 0))
                )
            
            console.print(table)


@usage_app.command("sessions")
def usage_sessions():
    """List all sessions with usage data."""
    from nanobot.usage.tracker import UsageTracker
    
    tracker = UsageTracker()
    all_sessions = tracker.get_all_sessions()
    
    if not all_sessions:
        console.print("[yellow]No session data available[/yellow]")
        return
    
    sorted_sessions = sorted(
        all_sessions.items(),
        key=lambda x: x[1].get("total_tokens", 0),
        reverse=True
    )
    
    table = Table(title="All Sessions")
    table.add_column("Session", style="cyan")
    table.add_column("Prompt Tokens", justify="right")
    table.add_column("Completion Tokens", justify="right")
    table.add_column("Total Tokens", justify="right")
    table.add_column("Calls", justify="right")
    
    for session_key, stats in sorted_sessions:
        table.add_row(
            session_key,
            f"{stats.get('prompt_tokens', 0):,}",
            f"{stats.get('completion_tokens', 0):,}",
            f"{stats.get('total_tokens', 0):,}",
            str(stats.get('call_count', 0))
        )
    
    console.print(table)


def _print_usage_stats(usage: dict[str, int]) -> None:
    """Helper to print usage statistics."""
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold")
    table.add_column(justify="right")
    
    table.add_row("Prompt Tokens:", f"{usage.get('prompt_tokens', 0):,}")
    table.add_row("Completion Tokens:", f"{usage.get('completion_tokens', 0):,}")
    table.add_row("Total Tokens:", f"[bold]{usage.get('total_tokens', 0):,}[/bold]")
    table.add_row("API Calls:", str(usage.get('call_count', 0)))
    
    console.print(table)


if __name__ == "__main__":
    app()
