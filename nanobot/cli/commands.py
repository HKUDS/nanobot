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


def _create_provider(config):
    """Create the appropriate provider based on configuration."""
    api_key = config.get_api_key()
    
    # Check if Ollama is enabled and should be used
    if api_key == "ollama" and config.ollama.enabled:
        from nanobot.providers.ollama_provider import OllamaProvider
        from nanobot.usage import UsageTracker
        
        tracker = UsageTracker()
        provider = OllamaProvider(
            api_base=config.ollama.api_base,
            default_model=config.ollama.model,
            timeout=config.ollama.timeout,
            usage_tracker=tracker
        )
        return provider
    
    # Default to LiteLLM for cloud providers
    if not api_key or api_key == "ollama":
        console.print("[red]Error: No API key configured and Ollama not enabled.[/red]")
        console.print("Set an API key in ~/.nanobot/config.json under providers.*.apiKey")
        console.print("Or enable Ollama: set ollama.enabled to true")
        raise typer.Exit(1)
    
    from nanobot.providers.litellm_provider import LiteLLMProvider
    from nanobot.usage import UsageTracker
    
    api_base = config.get_api_base()
    tracker = UsageTracker()
    
    provider = LiteLLMProvider(
        api_key=api_key,
        api_base=api_base,
        default_model=config.agents.defaults.model,
        usage_tracker=tracker
    )
    return provider


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
    console.print("  2. Chat: [cyan]nanobot agent -m \"Hello!\"[/cyan]")
    console.print("\n[dim]Want Telegram/WhatsApp? See: https://github.com/HKUDS/nanobot#-chat-apps[/dim]")




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
    
    # Create provider (supports Ollama, OpenRouter, Anthropic, OpenAI)
    provider = _create_provider(config)
    # Create provider (supports OpenRouter, Anthropic, OpenAI, Bedrock)
    api_key = config.get_api_key()
    api_base = config.get_api_base()
    model = config.agents.defaults.model
    is_bedrock = model.startswith("bedrock/")

    if not api_key and not is_bedrock:
        console.print("[red]Error: No API key configured.[/red]")
        console.print("Set one in ~/.nanobot/config.json under providers.openrouter.apiKey")
        raise typer.Exit(1)
    
    provider = LiteLLMProvider(
        api_key=api_key,
        api_base=api_base,
        default_model=config.agents.defaults.model
    )
    
    # Create cron service first (callback set after agent creation)
    cron_store_path = get_data_dir() / "cron" / "jobs.json"
    cron = CronService(cron_store_path)
    
    # Create agent with cron service
    agent = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        model=config.agents.defaults.model,
        max_iterations=config.agents.defaults.max_tool_iterations,
        brave_api_key=config.tools.web.search.api_key or None,
        exec_config=config.tools.exec,
        cron_service=cron,
        restrict_to_workspace=config.tools.restrict_to_workspace,
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
    
    # Create provider (supports Ollama, OpenRouter, Anthropic, OpenAI)
    provider = _create_provider(config)
    
    api_key = config.get_api_key()
    api_base = config.get_api_base()
    model = config.agents.defaults.model
    is_bedrock = model.startswith("bedrock/")

    # Check if NVIDIA provider should be used
    is_nvidia = model.startswith("moonshotai/") or config.providers.nvidia.api_key

    if not api_key and not is_bedrock and not is_nvidia:
        console.print("[red]Error: No API key configured.[/red]")
        raise typer.Exit(1)

    if is_nvidia and config.providers.nvidia.api_key:
        from nanobot.providers.nvidia_provider import NvidiaProvider
        provider = NvidiaProvider(
            api_key=config.providers.nvidia.api_key,
            default_model=config.agents.defaults.model
        )
    else:
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
        exec_config=config.tools.exec,
        restrict_to_workspace=config.tools.restrict_to_workspace,
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
    
    # WhatsApp channel

    # WhatsApp
    wa = config.channels.whatsapp
    table.add_row(
        "WhatsApp",
        "✓" if wa.enabled else "✗",
        wa.bridge_url
    )
    
    # Telegram channel
    tg = config.channels.telegram
    token_display = f"{tg.token[:10]}..." if tg.token else "not configured"
    table.add_row(
        "Telegram",
        "✓" if tg.enabled else "✗",
        token_display
    )
    

    dc = config.channels.discord
    table.add_row(
        "Discord",
        "✓" if dc.enabled else "✗",
        dc.gateway_url
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
    import subprocess  # nosec B404 - subprocess necessário para build do bridge
    
    # User's bridge location
    user_bridge = Path.home() / ".nanobot" / "bridge"
    
    # Check if already built
    if (user_bridge / "dist" / "index.js").exists():
        return user_bridge
    
    # Obter caminho completo do npm para segurança (B607)
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
    
    # Install and build usando caminho completo do npm
    try:
        console.print("  Installing dependencies...")
        subprocess.run([npm_path, "install"], cwd=user_bridge, check=True, capture_output=True)  # nosec B603
        
        console.print("  Building...")
        subprocess.run([npm_path, "run", "build"], cwd=user_bridge, check=True, capture_output=True)  # nosec B603
        
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
    import subprocess  # nosec B404
    
    bridge_dir = _get_bridge_dir()
    
    # Obter caminho completo do npm para segurança (B607)
    npm_path = shutil.which("npm")
    if not npm_path:
        console.print("[red]npm not found. Please install Node.js.[/red]")
        raise typer.Exit(1)
    
    console.print(f"{__logo__} Starting bridge...")
    console.print("Scan the QR code to connect.\n")
    
    try:
        subprocess.run([npm_path, "start"], cwd=bridge_dir, check=True)  # nosec B603
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Bridge failed: {e}[/red]")


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
# Usage Commands
# ============================================================================


@app.command()
def usage(
    period: str = typer.Option("month", "--period", "-p", help="Time period: today, week, month"),
    model: str = typer.Option(None, "--model", "-m", help="Filter by specific model"),
    channel: str = typer.Option(None, "--channel", "-c", help="Filter by specific channel"),
    budget: bool = typer.Option(False, "--budget", "-b", help="Show budget status only"),
    alerts: bool = typer.Option(False, "--alerts", "-a", help="Show budget alerts only"),
):
    """Show token usage statistics and budget information."""
    from nanobot.usage import UsageTracker, UsageMonitor, UsageConfig
    from nanobot.config.loader import load_config

    config = load_config()
    usage_config = config.usage
    tracker = UsageTracker()
    monitor = UsageMonitor(tracker, usage_config)

    # Handle special modes
    if budget:
        self._display_budget_status(monitor)
        return

    if alerts:
        self._display_alerts(monitor)
        return

    # Validate period and get summary
    days, period_name = self._validate_period_and_get_days(period)
    summary = tracker.get_usage_summary(
        days=days,
        model_filter=model,
        channel_filter=channel
    )

    # Display usage information
    self._display_usage_summary(summary, period_name, model, channel)
    self._display_model_breakdown(summary)
    self._display_channel_breakdown(summary)
    self._display_budget_and_alerts(monitor)


def _validate_period_and_get_days(self, period):
    # Determine days based on period
    if period == "today":
        days = 1
        period_name = "today"
    elif period == "week":
        days = 7
        period_name = "this week"
    elif period == "month":
        days = 30
        period_name = "this month"
    else:
        console.print(f"[red]Error: Invalid period '{period}'. Use: today, week, month[/red]")
        raise typer.Exit(1)
    return days, period_name


def _display_usage_summary(self, summary, period_name, model, channel):
    console.print(f"[bold]Usage Summary ({period_name})[/bold]\n")

    if model or channel:
        filters = []
        if model:
            filters.append(f"model: {model}")
        if channel:
            filters.append(f"channel: {channel}")
        console.print(f"[dim]Filtered by: {', '.join(filters)}[/dim]\n")

    console.print(f"Total Tokens: [green]{summary['total_tokens']:,}[/green]")
    console.print(f"Total Cost: [yellow]${summary['total_cost_usd']:.4f}[/yellow]")
    console.print(f"API Calls: [cyan]{summary['record_count']}[/cyan]\n")


def _display_model_breakdown(self, summary):
    # Model breakdown
    if summary['model_breakdown']:
        table = Table(title="Model Usage")
        table.add_column("Model", style="cyan")
        table.add_column("Tokens", style="green", justify="right")
        table.add_column("Percentage", style="yellow", justify="right")

        for model_name, tokens in sorted(summary['model_breakdown'].items(), key=lambda x: x[1], reverse=True):
            percentage = (tokens / summary['total_tokens'] * 100) if summary['total_tokens'] > 0 else 0
            table.add_row(model_name, f"{tokens:,}", f"{percentage:.1f}%")

        console.print(table)
        console.print()


def _display_channel_breakdown(self, summary):
    # Channel breakdown
    if summary['channel_breakdown']:
        table = Table(title="Channel Usage")
        table.add_column("Channel", style="cyan")
        table.add_column("Tokens", style="green", justify="right")
        table.add_column("Percentage", style="yellow", justify="right")

        for channel_name, tokens in sorted(summary['channel_breakdown'].items(), key=lambda x: x[1], reverse=True):
            percentage = (tokens / summary['total_tokens'] * 100) if summary['total_tokens'] > 0 else 0
            table.add_row(channel_name, f"{tokens:,}", f"{percentage:.1f}%")

        console.print(table)
        console.print()


def _display_budget_status(self, monitor):
    # Show budget status only
    status = monitor.get_budget_status()
    console.print(f"[bold]Monthly Budget Status[/bold]\n")
    console.print(f"Budget: [green]${status.monthly_budget_usd:.2f}[/green]")
    console.print(f"Current Spend: [yellow]${status.current_spend_usd:.2f}[/yellow]")
    console.print(f"Remaining: [cyan]${status.remaining_budget_usd:.2f}[/cyan]")
    console.print(f"Utilization: [magenta]{status.utilization_percentage:.1f}%[/magenta]")


def _display_alerts(self, monitor):
    # Show alerts only
    alerts_list = monitor.get_budget_alerts()
    if not alerts_list:
        console.print("[green] No budget alerts at this time[/green]")
    else:
        console.print("[bold red]Budget Alerts:[/bold red]")
        for alert in alerts_list:
            console.print(f"  {alert}")


def _display_budget_and_alerts(self, monitor):
    # Budget status
    status = monitor.get_budget_status()
    console.print(f"[bold]Budget Status[/bold]")
    console.print(f"Monthly Budget: [green]${status.monthly_budget_usd:.2f}[/green]")
    console.print(f"Current Spend: [yellow]${status.current_spend_usd:.2f}[/yellow]")
    console.print(f"Remaining: [cyan]${status.remaining_budget_usd:.2f}[/cyan]")
    console.print(f"Utilization: [magenta]{status.utilization_percentage:.1f}%[/magenta]")

    # Show alerts if any
    if status.alerts:
        console.print("\n[bold red]Alerts:[/bold red]")
        for alert in status.alerts:
            console.print(f"  {alert}")


ollama_app = typer.Typer(help="Manage Ollama local models")
app.add_typer(ollama_app, name="ollama")


@ollama_app.command("status")
def ollama_status():
    """Check Ollama service status and available models."""
    from nanobot.config.loader import load_config
    from nanobot.providers.ollama_provider import OllamaProvider
    
    config = load_config()
    
    if not config.ollama.enabled:
        console.print("[yellow]Ollama is not enabled in config.[/yellow]")
        console.print("Enable it by setting 'ollama.enabled: true' in ~/.nanobot/config.json")
        return
    
    console.print(f"{__logo__} Checking Ollama status...")
    
    provider = OllamaProvider(
        api_base=config.ollama.api_base,
        default_model=config.ollama.model,
        timeout=config.ollama.timeout
    )
    
    async def check_status():
        status = await provider.check_status()
        await provider.close()
        return status
    
    import asyncio
    status = asyncio.run(check_status())
    
    if status["available"]:
        console.print("[green]✓[/green] Ollama service is running")
        console.print(f"  Version: {status['version']}")
        console.print(f"  Endpoint: {status['endpoint']}")
        
        if status["models"]:
            console.print(f"  Available models: {len(status['models'])}")
            for model in status["models"][:5]:  # Show first 5
                console.print(f"    • {model}")
            if len(status["models"]) > 5:
                console.print(f"    ... and {len(status['models']) - 5} more")
        else:
            console.print("  [yellow]No models installed[/yellow]")
            console.print("  Install models with: ollama pull <model_name>")
    else:
        console.print("[red]✗[/red] Ollama service is not available")
        console.print(f"  Error: {status['error']}")
        console.print("\nTroubleshooting:")
        console.print("  1. Install Ollama: https://ollama.ai/download")
        console.print("  2. Start Ollama: ollama serve")
        console.print("  3. Pull a model: ollama pull llama3.2")


@ollama_app.command("list")
def ollama_list():
    """List installed Ollama models."""
    from nanobot.config.loader import load_config
    from nanobot.providers.ollama_provider import OllamaProvider
    
    config = load_config()
    
    if not config.ollama.enabled:
        console.print("[yellow]Ollama is not enabled in config.[/yellow]")
        return
    
    console.print(f"{__logo__} Listing Ollama models...")
    
    provider = OllamaProvider(
        api_base=config.ollama.api_base,
        timeout=config.ollama.timeout
    )
    
    async def list_models():
        models = await provider.list_models()
        await provider.close()
        return models
    
    import asyncio
    models = asyncio.run(list_models())
    
    if models:
        table = Table(title="Installed Ollama Models")
        table.add_column("Model Name", style="cyan")
        table.add_column("Status", style="green")
        
        for model in sorted(models):
            status = "[green]installed[/green]"
            if model == config.ollama.model:
                status = "[blue]default[/blue]"
            table.add_row(model, status)
        
        console.print(table)
    else:
        console.print("[yellow]No models found.[/yellow]")
        console.print("Install models with: ollama pull <model_name>")


@ollama_app.command("pull")
def ollama_pull(
    model: str = typer.Argument(..., help="Model name to pull (e.g., 'llama3.2', 'mistral')"),
):
    """Pull (download) an Ollama model."""
    import re
    import shutil
    import subprocess  # nosec B404
    
    # Validação de entrada: nome do modelo deve conter apenas caracteres seguros
    if not re.match(r'^[a-zA-Z0-9._:-]+$', model):
        console.print("[red]Nome de modelo inválido. Use apenas letras, números, '.', '_', ':' e '-'[/red]")
        raise typer.Exit(1)
    
    # Obter caminho completo do ollama para segurança (B607)
    ollama_path = shutil.which("ollama")
    if not ollama_path:
        console.print("[red]ollama command not found.[/red]")
        console.print("Install Ollama from: https://ollama.ai/download")
        raise typer.Exit(1)
    
    console.print(f"{__logo__} Pulling Ollama model: {model}")
    console.print("This may take several minutes depending on model size...\n")
    
    try:
        # Run ollama pull command com caminho completo e entrada validada
        result = subprocess.run(
            [ollama_path, "pull", model],
            capture_output=True,
            text=True,
            check=True
        )  # nosec B603
        
        console.print(f"[green]✓[/green] Successfully pulled model: {model}")
        
        if result.stdout:
            console.print(f"[dim]{result.stdout.strip()}[/dim]")
            
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Failed to pull model: {model}[/red]")
        if e.stderr:
            console.print(f"[dim]{e.stderr.strip()}[/dim]")
        console.print("\nMake sure Ollama is installed and running.")


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
        has_nvidia = bool(config.providers.nvidia.api_key)
        has_vllm = bool(config.providers.vllm.api_base)
        
        console.print(f"OpenRouter API: {'[green]✓[/green]' if has_openrouter else '[dim]not set[/dim]'}")
        console.print(f"Anthropic API: {'[green]✓[/green]' if has_anthropic else '[dim]not set[/dim]'}")
        console.print(f"OpenAI API: {'[green]✓[/green]' if has_openai else '[dim]not set[/dim]'}")
        console.print(f"Gemini API: {'[green]✓[/green]' if has_gemini else '[dim]not set[/dim]'}")
        console.print(f"NVIDIA API: {'[green]✓[/green]' if has_nvidia else '[dim]not set[/dim]'}")
        vllm_status = f"[green]✓ {config.providers.vllm.api_base}[/green]" if has_vllm else "[dim]not set[/dim]"
        console.print(f"vLLM/Local: {vllm_status}")
        
        # Ollama status
        if config.ollama.enabled:
            console.print(f"Ollama: [green]✓ enabled[/green] ({config.ollama.model})")
        else:
            console.print("Ollama: [dim]disabled[/dim]")

# ============================================================================
# Alarm Commands
# ============================================================================

alarm_app = typer.Typer(help="Manage alarms and reminders")
app.add_typer(alarm_app, name="alarm")


@alarm_app.command("set")
def alarm_set(
    message: str = typer.Argument(..., help="Alarm message"),
    in_time: str = typer.Option(None, "--in", help="Time from now (e.g., '2m', '1h30m', '30s')"),
    at_time: str = typer.Option(None, "--at", help="Specific time (HH:MM)"),
    channel: str = typer.Option("telegram", "--channel", help="Notification channel: telegram, console, all"),
):
    """Set a new alarm."""
    from nanobot.alarm import AlarmService, AlarmStorage, parse_time_string, AlarmChannel
    from datetime import datetime, timedelta
    import re
    
    storage = AlarmStorage()
    service = AlarmService(storage)
    
    # Validate channel
    if channel not in [c.value for c in AlarmChannel]:
        console.print(f"[red]Invalid channel: {channel}. Use: telegram, console, all[/red]")
        raise typer.Exit(1)
    
    # Parse time
    if in_time:
        try:
            delay_seconds = parse_time_string(in_time)
            trigger_at = datetime.now() + timedelta(seconds=delay_seconds)
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1)
    elif at_time:
        # Parse HH:MM format
        try:
            match = re.match(r'^(\d{1,2}):(\d{2})$', at_time)
            if not match:
                raise ValueError("Invalid time format. Use HH:MM")
            hour, minute = int(match.group(1)), int(match.group(2))
            trigger_at = datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0)
            if trigger_at < datetime.now():
                trigger_at += timedelta(days=1)  # Next day
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1)
    else:
        console.print("[red]Specify time with --in or --at[/red]")
        raise typer.Exit(1)
    
    # Create alarm
    alarm = asyncio.run(service.create_alarm_at(
        user_id="cli_user",  # Will be enhanced when integrated with user system
        message=message,
        trigger_at=trigger_at,
        channel=channel,
    ))
    
    time_str = trigger_at.strftime("%H:%M:%S")
    console.print(f"[green]✓[/green] Alarm set: {message}")
    console.print(f"   ID: {alarm.id}")
    console.print(f"   Triggers at: {time_str}")
    console.print(f"   Channel: {channel}")


@alarm_app.command("list")
def alarm_list(
    all_status: bool = typer.Option(False, "--all", "-a", help="Show all alarms including triggered/cancelled"),
):
    """List active alarms."""
    from nanobot.alarm import AlarmService, AlarmStorage, AlarmStatus
    
    storage = AlarmStorage()
    service = AlarmService(storage)
    
    if all_status:
        alarms = service.list_alarms()
    else:
        alarms = service.list_alarms(status=AlarmStatus.PENDING)
    
    if not alarms:
        console.print("No alarms found.")
        return
    
    table = Table(title="Alarms")
    table.add_column("ID", style="cyan")
    table.add_column("Message", style="green")
    table.add_column("Time", style="yellow")
    table.add_column("Status", style="magenta")
    table.add_column("Channel", style="blue")
    
    for alarm in alarms:
        time_str = alarm.trigger_at.strftime("%Y-%m-%d %H:%M")
        status_icon = {
            AlarmStatus.PENDING.value: "⏳",
            AlarmStatus.TRIGGERED.value: "✅",
            AlarmStatus.CANCELLED.value: "❌",
        }.get(alarm.status.value, "?")
        
        table.add_row(
            alarm.id,
            alarm.message[:30] + "..." if len(alarm.message) > 30 else alarm.message,
            time_str,
            f"{status_icon} {alarm.status.value}",
            alarm.channel,
        )
    
    console.print(table)


@alarm_app.command("cancel")
def alarm_cancel(
    alarm_id: str = typer.Argument(..., help="Alarm ID to cancel"),
):
    """Cancel an alarm."""
    from nanobot.alarm import AlarmService, AlarmStorage
    
    storage = AlarmStorage()
    service = AlarmService(storage)
    
    success = service.cancel_alarm(alarm_id)
    
    if success:
        console.print(f"[green]✓[/green] Alarm {alarm_id} cancelled")
    else:
        console.print(f"[red]✗[/red] Alarm {alarm_id} not found or already triggered")
        raise typer.Exit(1)


@alarm_app.command("test")
def alarm_test(
    message: str = typer.Argument("Test alarm!", help="Test message"),
    delay: int = typer.Option(3, "--delay", help="Seconds to wait"),
):
    """Test alarm system - sends notification after delay."""
    from nanobot.alarm import AlarmService, AlarmStorage
    
    storage = AlarmStorage()
    service = AlarmService(storage)
    
    console.print(f"Setting test alarm for {delay} seconds...")
    
    alarm = asyncio.run(service.create_alarm(
        user_id="cli_user",
        message=message,
        delay_seconds=delay,
        channel="console",
    ))
    
    console.print(f"Alarm {alarm.id} created. Waiting...")
    
    # Simple wait and trigger for testing
    import time
    time.sleep(delay)
    
    asyncio.run(service.trigger_alarm(alarm))
    console.print("[green]Test alarm triggered![/green]")


if __name__ == "__main__":
    app()
