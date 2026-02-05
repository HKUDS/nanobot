"""CLI commands for nanobot."""

import asyncio
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from nanobot import __logo__, __version__

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
    version: bool = typer.Option(None, "--version", "-v", callback=version_callback, is_eager=True),
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
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus
    from nanobot.channels.manager import ChannelManager
    from nanobot.config.loader import get_data_dir, load_config
    from nanobot.cron.service import CronService
    from nanobot.cron.types import CronJob
    from nanobot.heartbeat.service import HeartbeatService
    from nanobot.providers.litellm_provider import LiteLLMProvider

    if verbose:
        import logging

        logging.basicConfig(level=logging.DEBUG)

    console.print(f"{__logo__} Starting nanobot gateway on port {port}...")

    config = load_config()

    # Create components
    bus = MessageBus()

    # Resolve main provider credentials
    from nanobot.providers.resolver import ProviderResolver

    resolver = ProviderResolver(config.providers, config.agents.defaults.provider)
    api_key, api_base = resolver.resolve()
    model = config.agents.defaults.model
    is_bedrock = model.startswith("bedrock/")

    if not api_key and not is_bedrock:
        console.print("[red]Error: No API key configured.[/red]")
        console.print("Set one in ~/.nanobot/config.json under providers.openrouter.apiKey")
        raise typer.Exit(1)

    provider = LiteLLMProvider(
        api_key=api_key, api_base=api_base, default_model=config.agents.defaults.model
    )

    # Create channel manager first (needed for agent tools)
    channels = ChannelManager(config, bus)

    # Create cron service first (without callback - set after agent is created)
    cron_store_path = get_data_dir() / "cron" / "jobs.json"
    cron = CronService(cron_store_path, on_job=None)

    # Create agent with channel manager and cron service
    agent = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        model=config.agents.defaults.model,
        max_iterations=config.agents.defaults.max_tool_iterations,
        brave_api_key=config.tools.web.search.api_key or None,
        exec_config=config.tools.exec,
        channel_manager=channels,
        cron_service=cron,
        mcp_config=config.tools.mcp,
        context_config=config.agents.defaults.context,
        compaction_config=config.agents.defaults.compaction,
        memory_config=config.agents.defaults.memory,
        provider_resolver=resolver,
    )

    # Set the cron callback using agent's process_direct
    async def on_cron_job(job: CronJob) -> str | None:
        """Execute a cron job through the agent."""
        response = await agent.process_direct(job.payload.message, session_key=f"cron:{job.id}")
        # Optionally deliver to channel
        if job.payload.deliver and job.payload.to:
            from nanobot.bus.events import OutboundMessage

            await bus.publish_outbound(
                OutboundMessage(
                    channel=job.payload.channel or "whatsapp",
                    chat_id=job.payload.to,
                    content=response or "",
                )
            )
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
        enabled=True,
    )

    if channels.enabled_channels:
        console.print(f"[green]✓[/green] Channels enabled: {', '.join(channels.enabled_channels)}")
    else:
        console.print("[yellow]Warning: No channels enabled[/yellow]")

    cron_status = cron.status()
    if cron_status["jobs"] > 0:
        console.print(f"[green]✓[/green] Cron: {cron_status['jobs']} scheduled jobs")

    console.print("[green]✓[/green] Heartbeat: every 30m")

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
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus
    from nanobot.config.loader import load_config
    from nanobot.providers.litellm_provider import LiteLLMProvider

    config = load_config()

    from nanobot.providers.resolver import ProviderResolver

    resolver = ProviderResolver(config.providers, config.agents.defaults.provider)
    api_key, api_base = resolver.resolve()
    model = config.agents.defaults.model
    is_bedrock = model.startswith("bedrock/")

    if not api_key and not is_bedrock:
        console.print("[red]Error: No API key configured.[/red]")
        raise typer.Exit(1)

    bus = MessageBus()
    provider = LiteLLMProvider(
        api_key=api_key, api_base=api_base, default_model=config.agents.defaults.model
    )

    agent_loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        brave_api_key=config.tools.web.search.api_key or None,
        exec_config=config.tools.exec,
        context_config=config.agents.defaults.context,
        compaction_config=config.agents.defaults.compaction,
        memory_config=config.agents.defaults.memory,
        provider_resolver=resolver,
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
    table.add_row("WhatsApp", "✓" if wa.enabled else "✗", wa.bridge_url)

    # Telegram
    tg = config.channels.telegram
    tg_config = f"token: {tg.token[:10]}..." if tg.token else "[dim]not configured[/dim]"
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
    cron_expr: str = typer.Option(None, "--cron", "-c", help="Cron expression (e.g. '0 9 * * *')"),
    at: str = typer.Option(None, "--at", help="Run once at time (ISO format)"),
    deliver: bool = typer.Option(False, "--deliver", "-d", help="Deliver response to channel"),
    to: str = typer.Option(None, "--to", help="Recipient for delivery"),
    channel: str = typer.Option(
        None, "--channel", help="Channel for delivery (e.g. 'telegram', 'whatsapp')"
    ),
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
        console.print("[green]✓[/green] Job executed")
    else:
        console.print(f"[red]Failed to run job {job_id}[/red]")


# ============================================================================
# Memory Commands
# ============================================================================

memory_app = typer.Typer(help="Manage memory")
app.add_typer(memory_app, name="memory")


def _get_memory_components() -> (
    tuple["VectorStore", "EmbeddingService"]  # noqa: F821
):
    """Load config and create vector store + embedding service."""
    from nanobot.config.loader import load_config
    from nanobot.llm.embeddings import EmbeddingService
    from nanobot.memory.vectors import VectorStore
    from nanobot.providers.resolver import ProviderResolver

    config = load_config()
    mem = config.agents.defaults.memory

    if not mem.enabled:
        console.print("[red]Memory is disabled in config.[/red]")
        raise typer.Exit(1)

    resolver = ProviderResolver(config.providers, config.agents.defaults.provider)
    embed_key, embed_base = resolver.resolve(mem.embedding_provider)

    embedding_service = EmbeddingService(
        model=mem.embedding_model,
        api_key=embed_key,
        api_base=embed_base,
    )
    vector_store = VectorStore(
        db_path=mem.db_path,
        embedding_service=embedding_service,
    )
    return vector_store, embedding_service


@memory_app.command("search")
def memory_search(
    query: str = typer.Argument(..., help="Search query"),
    limit: int = typer.Option(5, "--limit", "-n", help="Max results"),
):
    """Search memory for matching entries."""
    vector_store, _ = _get_memory_components()

    async def _search():
        return await vector_store.search(query=query, top_k=limit)

    results = asyncio.run(_search())

    if not results:
        console.print(f"No memories matching: {query}")
        return

    table = Table(title=f"Memory Search: {query}")
    table.add_column("Score", style="cyan", width=6)
    table.add_column("Type", width=12)
    table.add_column("Date", width=12)
    table.add_column("Content")

    for r in results:
        score = f"{r.get('similarity', 0):.2f}"
        meta = r.get("metadata", {})
        entry_type = meta.get("type", "?")
        date = r.get("created_at", "")[:10]
        text = r.get("text", "")[:120]
        table.add_row(score, entry_type, date, text)

    console.print(table)


@memory_app.command("list")
def memory_list(
    type_filter: str = typer.Option(
        None,
        "--type",
        "-t",
        help="Filter by type (fact/conversation)",
    ),
    limit: int = typer.Option(20, "--limit", "-n", help="Max entries"),
    after: str = typer.Option(
        None,
        "--after",
        help="Only entries after date (YYYY-MM-DD)",
    ),
):
    """List recent memory entries."""
    import json
    import sqlite3

    vector_store, _ = _get_memory_components()

    with sqlite3.connect(vector_store.db_path) as conn:
        sql = "SELECT id, text, metadata, created_at FROM vectors ORDER BY created_at DESC"
        rows = conn.execute(sql).fetchall()

    entries = []
    for row in rows:
        entry_id, text, meta_json, created_at = row
        meta = json.loads(meta_json) if meta_json else {}
        entry_type = meta.get("type", "unknown")

        if type_filter and entry_type != type_filter:
            continue
        if after and created_at < after:
            continue

        entries.append((entry_id, entry_type, created_at, text))
        if len(entries) >= limit:
            break

    if not entries:
        console.print("No matching entries found.")
        return

    table = Table(title="Memory Entries")
    table.add_column("ID", style="cyan", width=6)
    table.add_column("Type", width=12)
    table.add_column("Date", width=12)
    table.add_column("Content")

    for entry_id, entry_type, created_at, text in entries:
        date = created_at[:10] if created_at else ""
        table.add_row(
            str(entry_id),
            entry_type,
            date,
            text[:100],
        )

    console.print(table)


@memory_app.command("stats")
def memory_stats():
    """Show memory system statistics."""
    import json
    import sqlite3
    from pathlib import Path

    vector_store, _ = _get_memory_components()
    db_path = Path(vector_store.db_path)

    total = vector_store.count()
    db_size = db_path.stat().st_size if db_path.exists() else 0

    # Count by type
    facts = 0
    conversations = 0
    oldest = None
    newest = None

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT metadata, created_at FROM vectors").fetchall()

    for meta_json, created_at in rows:
        meta = json.loads(meta_json) if meta_json else {}
        t = meta.get("type", "")
        if t == "fact":
            facts += 1
        elif t == "conversation":
            conversations += 1

        if created_at:
            if oldest is None or created_at < oldest:
                oldest = created_at
            if newest is None or created_at > newest:
                newest = created_at

    console.print(f"Total entries: [cyan]{total}[/cyan]")
    console.print(f"  Facts: {facts}")
    console.print(f"  Conversations: {conversations}")
    console.print(f"  Other: {total - facts - conversations}")
    if oldest:
        console.print(f"Oldest: {oldest[:10]}")
    if newest:
        console.print(f"Newest: {newest[:10]}")

    if db_size > 1024 * 1024:
        size_str = f"{db_size / (1024 * 1024):.1f} MB"
    elif db_size > 1024:
        size_str = f"{db_size / 1024:.1f} KB"
    else:
        size_str = f"{db_size} B"
    console.print(f"DB size: {size_str}")

    # Entity count (if available)
    from nanobot.config.loader import load_config

    config = load_config()
    entities_path = Path(config.agents.defaults.memory.entities_db_path).expanduser()
    if entities_path.exists():
        try:
            with sqlite3.connect(entities_path) as conn:
                entity_count = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
            console.print(f"Entities: {entity_count}")
        except Exception:
            pass


@memory_app.command("delete")
def memory_delete(
    entry_id: int = typer.Argument(..., help="Entry ID to delete"),
):
    """Delete a specific memory entry by ID."""
    import sqlite3

    vector_store, _ = _get_memory_components()

    # Look up entry first
    with sqlite3.connect(vector_store.db_path) as conn:
        row = conn.execute("SELECT text FROM vectors WHERE id = ?", (entry_id,)).fetchone()

    if not row:
        console.print(f"[red]Entry {entry_id} not found.[/red]")
        raise typer.Exit(1)

    console.print(f"Content: {row[0][:200]}")
    if not typer.confirm("Delete this entry?"):
        raise typer.Exit()

    with sqlite3.connect(vector_store.db_path) as conn:
        conn.execute("DELETE FROM vectors WHERE id = ?", (entry_id,))
        conn.commit()

    console.print(f"[green]Deleted entry {entry_id}.[/green]")


@memory_app.command("prune")
def memory_prune(
    older_than: int = typer.Option(
        180,
        "--days",
        help="Remove unaccessed memories older than N days",
    ),
    dry_run: bool = typer.Option(
        True,
        "--dry-run/--execute",
        help="Preview only (default: dry run)",
    ),
):
    """Remove old, never-accessed memories."""
    from nanobot.config.loader import load_config
    from nanobot.memory.consolidation import MemoryConsolidator
    from nanobot.providers.litellm_provider import LiteLLMProvider
    from nanobot.providers.resolver import ProviderResolver

    config = load_config()
    vector_store, _ = _get_memory_components()

    # Consolidation follows compaction provider
    mem = config.agents.defaults.memory
    comp = config.agents.defaults.compaction
    resolver = ProviderResolver(config.providers, config.agents.defaults.provider)
    api_key, api_base = resolver.resolve(mem.consolidation_provider or comp.provider)
    provider = LiteLLMProvider(
        api_key=api_key,
        api_base=api_base,
        default_model=config.agents.defaults.model,
    )

    consolidator = MemoryConsolidator(
        vector_store=vector_store,
        provider=provider,
    )

    async def _prune():
        return await consolidator.prune_old(
            max_age_days=older_than,
            dry_run=dry_run,
        )

    stats = asyncio.run(_prune())
    pruned = stats.get("pruned_count", 0)

    if dry_run:
        console.print(f"Would prune {pruned} memories older than {older_than} days")
    else:
        console.print(f"[green]Pruned {pruned} memories.[/green]")


@memory_app.command("consolidate")
def memory_consolidate(
    dry_run: bool = typer.Option(
        True,
        "--dry-run/--execute",
        help="Preview only (default: dry run)",
    ),
):
    """Consolidate similar memories."""
    from nanobot.config.loader import load_config
    from nanobot.memory.consolidation import MemoryConsolidator
    from nanobot.providers.litellm_provider import LiteLLMProvider
    from nanobot.providers.resolver import ProviderResolver

    config = load_config()
    vector_store, _ = _get_memory_components()

    # Consolidation follows compaction provider
    mem = config.agents.defaults.memory
    comp = config.agents.defaults.compaction
    resolver = ProviderResolver(config.providers, config.agents.defaults.provider)
    api_key, api_base = resolver.resolve(mem.consolidation_provider or comp.provider)
    provider = LiteLLMProvider(
        api_key=api_key,
        api_base=api_base,
        default_model=config.agents.defaults.model,
    )

    consolidator = MemoryConsolidator(
        vector_store=vector_store,
        provider=provider,
    )

    async def _consolidate():
        return await consolidator.consolidate(dry_run=dry_run)

    stats = asyncio.run(_consolidate())

    clusters = stats.get("clusters_found", 0)
    merged = stats.get("entries_merged", 0)
    created = stats.get("entries_created", 0)

    if dry_run:
        console.print(
            f"Would merge {merged} entries in {clusters} clusters "
            f"into {created} consolidated entries"
        )
    else:
        console.print(
            f"[green]Merged {merged} entries into {created} consolidated entries.[/green]"
        )


@memory_app.command("export")
def memory_export(
    output: str = typer.Option(
        "memories.json",
        "--output",
        "-o",
        help="Output file path",
    ),
):
    """Export all memories to JSON."""
    import json
    import sqlite3

    vector_store, _ = _get_memory_components()

    entries = []
    with sqlite3.connect(vector_store.db_path) as conn:
        rows = conn.execute(
            "SELECT id, text, metadata, created_at FROM vectors ORDER BY created_at"
        ).fetchall()

    for row in rows:
        entry_id, text, meta_json, created_at = row
        meta = json.loads(meta_json) if meta_json else {}
        entries.append(
            {
                "id": entry_id,
                "text": text,
                "metadata": meta,
                "created_at": created_at,
            }
        )

    Path(output).write_text(
        json.dumps(entries, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    console.print(f"[green]Exported {len(entries)} entries to {output}[/green]")


# ============================================================================
# Status Commands
# ============================================================================


@app.command()
def status():
    """Show nanobot status."""
    from nanobot.config.loader import get_config_path, load_config

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

        # Check API keys
        has_openrouter = bool(config.providers.openrouter.api_key)
        has_anthropic = bool(config.providers.anthropic.api_key)
        has_openai = bool(config.providers.openai.api_key)
        has_gemini = bool(config.providers.gemini.api_key)
        has_vllm = bool(config.providers.vllm.api_base)

        console.print(
            f"OpenRouter API: {'[green]✓[/green]' if has_openrouter else '[dim]not set[/dim]'}"
        )
        console.print(
            f"Anthropic API: {'[green]✓[/green]' if has_anthropic else '[dim]not set[/dim]'}"
        )
        console.print(f"OpenAI API: {'[green]✓[/green]' if has_openai else '[dim]not set[/dim]'}")
        console.print(f"Gemini API: {'[green]✓[/green]' if has_gemini else '[dim]not set[/dim]'}")
        vllm_status = (
            f"[green]✓ {config.providers.vllm.api_base}[/green]"
            if has_vllm
            else "[dim]not set[/dim]"
        )
        console.print(f"vLLM/Local: {vllm_status}")


if __name__ == "__main__":
    app()
