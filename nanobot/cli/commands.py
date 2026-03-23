"""CLI commands for nanobot."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

import typer
from rich.table import Table

from nanobot import __logo__
from nanobot.cli._shared import (
    _configure_log_sink,
    _make_agent_config,
    _make_provider,
    _print_agent_response,
    console,
    version_callback,
)
from nanobot.cli._shared import (
    onboard as _onboard_impl,
)
from nanobot.cli._shared import (
    status as _status_impl,
)
from nanobot.cli.agent import agent as _agent_impl
from nanobot.cli.gateway import gateway as _gateway_impl
from nanobot.cli.gateway import ui as _ui_impl
from nanobot.config.schema import Config

app = typer.Typer(
    name="nanobot",
    help=f"{__logo__} nanobot - Personal AI Assistant",
    no_args_is_help=True,
)

# On Windows the default console encoding (cp1252) cannot render many Unicode
# characters the LLM emits (↳, →, — etc.).  Reconfigure stdout to UTF-8 so
# Rich can write them without a UnicodeEncodeError.
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # crash-barrier: non-standard stdout (e.g. pytest capture)
        pass


@app.callback()
def main(
    version: bool = typer.Option(None, "--version", "-v", callback=version_callback, is_eager=True),
) -> None:
    """nanobot - Personal AI Assistant."""
    pass


# ============================================================================
# Onboard / Setup
# ============================================================================


@app.command()
def onboard() -> None:
    """Initialize nanobot configuration and workspace."""
    _onboard_impl()


# ============================================================================
# Gateway / Server / UI / Agent — delegated to extracted modules
# ============================================================================

app.command()(_gateway_impl)
app.command()(_ui_impl)
app.command()(_agent_impl)


# ============================================================================
# Channel Commands
# ============================================================================


channels_app = typer.Typer(help="Manage channels")
app.add_typer(channels_app, name="channels")


@channels_app.command("status")
def channels_status() -> None:
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
    tg_config = f"token: {tg.token[:10]}..." if tg.token else "[dim]not configured[/dim]"
    table.add_row("Telegram", "✓" if tg.enabled else "✗", tg_config)

    # Slack
    slack = config.channels.slack
    slack_config = "socket" if slack.app_token and slack.bot_token else "[dim]not configured[/dim]"
    table.add_row("Slack", "✓" if slack.enabled else "✗", slack_config)

    # Email
    em = config.channels.email
    em_config = em.imap_host if em.imap_host else "[dim]not configured[/dim]"
    table.add_row("Email", "✓" if em.enabled else "✗", em_config)

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
        raise typer.Exit(1) from None

    return user_bridge


@channels_app.command("login")
def channels_login() -> None:
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
) -> None:
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
            sched = (
                f"{job.schedule.expr or ''} ({job.schedule.tz})"
                if job.schedule.tz
                else (job.schedule.expr or "")
            )
        else:
            sched = "one-time"

        # Format next run
        next_run = ""
        if job.state.next_run_at_ms:
            ts = job.state.next_run_at_ms / 1000
            try:
                tz = ZoneInfo(job.schedule.tz) if job.schedule.tz else None
                next_run = _dt.fromtimestamp(ts, tz).strftime("%Y-%m-%d %H:%M")
            except (ValueError, OSError, TypeError):
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
    tz: str | None = typer.Option(
        None, "--tz", help="IANA timezone for cron (e.g. 'America/Vancouver')"
    ),
    at: str = typer.Option(None, "--at", help="Run once at time (ISO format)"),
    deliver: bool = typer.Option(False, "--deliver", "-d", help="Deliver response to channel"),
    to: str = typer.Option(None, "--to", help="Recipient for delivery"),
    channel: str = typer.Option(
        None, "--channel", help="Channel for delivery (e.g. 'telegram', 'whatsapp')"
    ),
) -> None:
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
) -> None:
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
) -> None:
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
) -> None:
    """Manually run a job."""
    from loguru import logger

    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus
    from nanobot.config.loader import get_data_dir, load_config
    from nanobot.cron.service import CronService
    from nanobot.cron.types import CronJob

    logger.disable("nanobot")

    config = load_config()

    # Initialize langfuse observability (auto-instruments litellm via OTEL)
    from nanobot.agent.observability import init_langfuse
    from nanobot.agent.observability import shutdown as shutdown_langfuse

    init_langfuse(config.langfuse)

    provider = _make_provider(config)
    bus = MessageBus()
    agent_loop = AgentLoop(
        bus=bus,
        provider=provider,
        config=_make_agent_config(config),
        brave_api_key=config.tools.web.search.api_key or None,
        exec_config=config.tools.exec,
        mcp_servers=config.tools.mcp_servers,
        channels_config=config.channels,
        routing_config=config.agents.routing,
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

    async def run() -> bool:
        return await service.run_job(job_id, force=force)

    try:
        success = asyncio.run(run())
    finally:
        shutdown_langfuse()
    if success:
        console.print("[green]✓[/green] Job executed")
        if result_holder:
            _print_agent_response(result_holder[0], render_markdown=True)
    else:
        console.print(f"[red]Failed to run job {job_id}[/red]")


# ============================================================================
# Routing Commands
# ============================================================================

routing_app = typer.Typer(help="Multi-agent routing diagnostics")
app.add_typer(routing_app, name="routing")


@routing_app.command("trace")
def routing_trace(
    last: int = typer.Option(20, "--last", "-n", help="Number of recent trace entries to show"),
) -> None:
    """Show the last N routing decisions from the trace log.

    Routing traces are now captured by Langfuse.  Use the Langfuse dashboard
    for full trace exploration.  This command reads any legacy JSONL trace
    file that may still exist on disk.
    """
    import json

    from nanobot.config.loader import load_config

    config = load_config()
    trace_path = config.workspace_path / "memory" / "routing_trace.jsonl"
    if not trace_path.exists():
        console.print(
            "[dim]No legacy routing trace found.[/dim]\n"
            "[dim]Routing traces are now captured by Langfuse — "
            "check the Langfuse dashboard.[/dim]"
        )
        raise typer.Exit(0)

    entries: list[dict] = []
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    if not entries:
        console.print("[dim]Trace file is empty.[/dim]")
        raise typer.Exit(0)

    recent = entries[-last:]
    table = Table(title=f"Routing Trace (last {len(recent)} of {len(entries)}) [legacy]")
    table.add_column("Time", style="dim", max_width=19)
    table.add_column("Event", style="cyan")
    table.add_column("Role", style="green")
    table.add_column("Conf", style="yellow", justify="right")
    table.add_column("Latency", style="magenta", justify="right")
    table.add_column("From", style="blue")
    table.add_column("Message", max_width=40)

    for e in recent:
        ts = str(e.get("timestamp", ""))[:19]
        conf = f"{e.get('confidence', 0.0):.2f}" if e.get("confidence") else ""
        lat = f"{e.get('latency_ms', 0.0):.0f}ms" if e.get("latency_ms") else ""
        ok = "" if e.get("success", True) else " [red]FAIL[/red]"
        table.add_row(
            ts,
            str(e.get("event", "")) + ok,
            str(e.get("role", "")),
            conf,
            lat,
            str(e.get("from_role", "")),
            str(e.get("message", ""))[:40],
        )
    console.print(table)
    console.print(
        "\n[dim]Note: New routing traces are captured by Langfuse. "
        "This shows legacy on-disk data only.[/dim]"
    )


@routing_app.command("metrics")
def routing_metrics_cmd() -> None:
    """Show routing metrics (classifications, delegations, latencies).

    Routing metrics are now captured by Langfuse.  Use the Langfuse dashboard
    for real-time metrics.  This command reads any legacy metrics JSON file
    that may still exist on disk.
    """
    import json

    from nanobot.config.loader import load_config

    config = load_config()
    metrics_path = config.workspace_path / "memory" / "routing_metrics.json"
    if not metrics_path.exists():
        console.print(
            "[dim]No legacy routing metrics found.[/dim]\n"
            "[dim]Routing metrics are now captured by Langfuse — "
            "check the Langfuse dashboard.[/dim]"
        )
        raise typer.Exit(0)

    try:
        data = json.loads(metrics_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, FileNotFoundError, UnicodeDecodeError) as exc:
        console.print(f"[red]Failed to read metrics:[/red] {exc}")
        raise typer.Exit(1) from None

    table = Table(title="Routing Metrics [legacy]")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green", justify="right")

    # Core counters
    for key in (
        "routing_classifications",
        "routing_delegations",
        "routing_cycles_blocked",
    ):
        table.add_row(key, str(data.get(key, 0)))

    # Latency stats
    cls_count = int(data.get("routing_classifications", 0) or 0)
    cls_sum = float(data.get("routing_classify_latency_sum_ms", 0) or 0)
    cls_max = float(data.get("routing_classify_latency_max_ms", 0) or 0)
    del_count = int(data.get("routing_delegations", 0) or 0)
    del_sum = float(data.get("delegation_latency_sum_ms", 0) or 0)
    del_max = float(data.get("delegation_latency_max_ms", 0) or 0)

    table.add_row("classify_latency_avg_ms", f"{cls_sum / cls_count:.0f}" if cls_count else "—")
    table.add_row("classify_latency_max_ms", f"{cls_max:.0f}" if cls_max else "—")
    table.add_row("delegation_latency_avg_ms", f"{del_sum / del_count:.0f}" if del_count else "—")
    table.add_row("delegation_latency_max_ms", f"{del_max:.0f}" if del_max else "—")

    console.print(table)

    # Per-role breakdown
    role_keys = sorted(k for k in data if k.startswith("role_invocations:"))
    if role_keys:
        role_table = Table(title="Per-Role Stats")
        role_table.add_column("Role", style="cyan")
        role_table.add_column("Invocations", style="green", justify="right")
        role_table.add_column("Tool Calls", style="yellow", justify="right")
        for k in role_keys:
            role_name = k.split(":", 1)[1]
            invocations = data.get(k, 0)
            tool_calls = data.get(f"role_tool_calls:{role_name}", 0)
            role_table.add_row(role_name, str(invocations), str(tool_calls))
        console.print(role_table)

    console.print(
        "\n[dim]Note: New routing metrics are captured by Langfuse. "
        "This shows legacy on-disk data only.[/dim]"
    )


@routing_app.command("dlq")
def routing_dlq(
    last: int = typer.Option(50, "--last", "-n", help="Number of recent trace entries to scan"),
    threshold: float = typer.Option(
        0.5, "--threshold", "-t", help="Confidence threshold — entries below this are flagged"
    ),
) -> None:
    """Show failed or low-confidence routing decisions (dead-letter queue).

    Scans routing_trace.jsonl for delegation failures, cycle blocks, depth
    blocks, and classifications below the confidence threshold.
    """
    import json

    from nanobot.config.loader import load_config

    config = load_config()
    trace_path = config.workspace_path / "memory" / "routing_trace.jsonl"
    if not trace_path.exists():
        console.print("[dim]No routing trace found.[/dim]")
        raise typer.Exit(0)

    entries: list[dict] = []
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    if not entries:
        console.print("[dim]Trace file is empty.[/dim]")
        raise typer.Exit(0)

    # Scan the last N entries for failures or low-confidence decisions
    recent = entries[-last:]
    flagged: list[dict] = []
    for e in recent:
        is_failure = not e.get("success", True)
        is_low_conf = e.get("confidence", 1.0) > 0.0 and e.get("confidence", 1.0) < threshold
        event = e.get("event", "")
        is_block = event in ("delegate_cycle_blocked", "delegate_depth_blocked")
        if is_failure or is_low_conf or is_block:
            flagged.append(e)

    if not flagged:
        console.print(
            f"[green]No routing issues found in last {len(recent)} trace entries.[/green]"
        )
        raise typer.Exit(0)

    table = Table(title=f"Routing DLQ ({len(flagged)} issues in last {len(recent)} entries)")
    table.add_column("Time", style="dim", max_width=19)
    table.add_column("Event", style="red")
    table.add_column("Role", style="green")
    table.add_column("Conf", style="yellow", justify="right")
    table.add_column("Depth", style="magenta", justify="right")
    table.add_column("From", style="blue")
    table.add_column("Issue", style="red", max_width=30)

    for e in flagged:
        ts = str(e.get("timestamp", ""))[:19]
        conf = f"{e.get('confidence', 0.0):.2f}" if e.get("confidence") else ""
        depth = str(e.get("depth", ""))
        event = e.get("event", "")

        # Determine issue reason
        if event == "delegate_cycle_blocked":
            issue = "cycle detected"
        elif event == "delegate_depth_blocked":
            issue = "max depth reached"
        elif not e.get("success", True):
            issue = "delegation failed"
        else:
            issue = f"low confidence ({conf})"

        table.add_row(
            ts,
            event,
            str(e.get("role", "")),
            conf,
            depth,
            str(e.get("from_role", "")),
            issue,
        )
    console.print(table)


@routing_app.command("replay")
def routing_replay(
    session: str = typer.Option(..., help="Session key (e.g. 'telegram:123456789')"),
    role: str = typer.Option(..., help="Corrected role name (e.g. 'code', 'research')"),
    message: str | None = typer.Option(None, help="Override message text"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without executing"),
    no_save: bool = typer.Option(False, "--no-save", help="Don't persist to session history"),
) -> None:
    """Replay a misrouted message with a corrected role."""
    from loguru import logger

    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus
    from nanobot.config.loader import get_data_dir, load_config
    from nanobot.cron.service import CronService

    config = load_config()

    channel, _, chat_id = session.partition(":")
    if not chat_id:
        console.print("[red]Invalid session key — expected 'channel:chat_id' format.[/red]")
        raise typer.Exit(1)

    content = message
    if content is None:
        # Load last user message from session history
        from nanobot.session.manager import SessionManager

        sm = SessionManager(config.workspace_path)
        sess = sm.get_or_create(session)
        for m in reversed(sess.messages):
            if m.get("role") == "user":
                content = m.get("content", "")
                break
        if not content:
            console.print("[red]No user message found in session history.[/red]")
            console.print("[dim]Use --message to provide the message text explicitly.[/dim]")
            raise typer.Exit(1)

    if dry_run:
        console.print(f"[cyan]Role:[/cyan]    {role}")
        console.print(f"[cyan]Session:[/cyan] {session}")
        console.print(f"[cyan]Message:[/cyan] {content}")
        console.print("\n[dim]Dry run — no agent execution.[/dim]")
        return

    # Initialize observability
    from nanobot.agent.observability import init_langfuse
    from nanobot.agent.observability import shutdown as shutdown_langfuse

    init_langfuse(config.langfuse)

    bus = MessageBus()
    provider = _make_provider(config)

    cron_store_path = get_data_dir() / "cron" / "jobs.json"
    cron = CronService(cron_store_path)

    logger.disable("nanobot")
    _configure_log_sink(config, logger)

    agent_loop = AgentLoop(
        bus=bus,
        provider=provider,
        config=_make_agent_config(config),
        brave_api_key=config.tools.web.search.api_key or None,
        exec_config=config.tools.exec,
        cron_service=cron,
        mcp_servers=config.tools.mcp_servers,
        channels_config=config.channels,
        routing_config=config.agents.routing,
    )

    # Use a distinct session key when --no-save to avoid polluting history
    replay_session = f"{session}:replay" if no_save else session

    async def _run_replay() -> None:
        try:
            response = await agent_loop.process_direct(
                content,
                session_key=replay_session,
                channel=channel,
                chat_id=chat_id,
                forced_role=role,
            )
            _print_agent_response(response, render_markdown=True)
        finally:
            agent_loop.stop()
            try:
                await asyncio.wait_for(agent_loop.close_mcp(), timeout=5.0)
            except TimeoutError:
                console.print(
                    "[yellow]Warning:[/yellow] timed out while closing provider/MCP resources."
                )
            shutdown_langfuse()

    asyncio.run(_run_replay())


# ============================================================================
# Status Commands
# ============================================================================


memory_app = typer.Typer(help="Manage memory system")
app.add_typer(memory_app, name="memory")


def _memory_rollout_overrides(config: Config) -> dict[str, object]:
    defaults = config.agents.defaults
    return {
        "memory_rollout_mode": defaults.memory_rollout_mode,
        "memory_type_separation_enabled": defaults.memory_type_separation_enabled,
        "memory_router_enabled": defaults.memory_router_enabled,
        "memory_reflection_enabled": defaults.memory_reflection_enabled,
        "memory_shadow_mode": defaults.memory_shadow_mode,
        "memory_shadow_sample_rate": defaults.memory_shadow_sample_rate,
        "memory_vector_health_enabled": defaults.memory_vector_health_enabled,
        "memory_auto_reindex_on_empty_vector": defaults.memory_auto_reindex_on_empty_vector,
        "memory_history_fallback_enabled": defaults.memory_history_fallback_enabled,
        "memory_fallback_allowed_sources": defaults.memory_fallback_allowed_sources,
        "memory_fallback_max_summary_chars": defaults.memory_fallback_max_summary_chars,
        "rollout_gates": {
            "min_recall_at_k": defaults.memory_rollout_gate_min_recall_at_k,
            "min_precision_at_k": defaults.memory_rollout_gate_min_precision_at_k,
            "max_avg_memory_context_tokens": defaults.memory_rollout_gate_max_avg_memory_context_tokens,
            "max_history_fallback_ratio": defaults.memory_rollout_gate_max_history_fallback_ratio,
        },
    }


@memory_app.command("inspect")
def memory_inspect(
    query: str = typer.Option("", "--query", "-q", help="Optional retrieval query"),
    top_k: int = typer.Option(6, "--top-k", "-k", help="Top-k memories to display"),
) -> None:
    """Inspect memory backend health, profile, and retrieval results."""
    from nanobot.agent.memory import MemoryStore
    from nanobot.config.loader import load_config

    config = load_config()
    store = MemoryStore(
        config.workspace_path,
        rollout_overrides=_memory_rollout_overrides(config),
    )

    observability = store.eval_runner.get_observability_report()
    backend = observability.get("backend", {}) if isinstance(observability, dict) else {}
    profile = store.profile_mgr.read_profile()
    report = store.snapshot.verify_memory()
    events = store.ingester.read_events()

    console.print(f"{__logo__} Memory Inspect\n")
    console.print("Mode: [cyan]mem0[/cyan]")
    console.print(f"mem0 enabled: [cyan]{backend.get('mem0_enabled', False)}[/cyan]")
    console.print(f"mem0 mode: [cyan]{backend.get('mem0_mode', 'disabled')}[/cyan]")
    console.print(f"vector points: [cyan]{backend.get('vector_points_count', 0)}[/cyan]")
    console.print(f"mem0 get_all count: [cyan]{backend.get('mem0_get_all_count', 0)}[/cyan]")
    console.print(f"history rows: [cyan]{backend.get('history_rows_count', 0)}[/cyan]")
    console.print(f"vector health: [cyan]{backend.get('vector_health_state', 'unknown')}[/cyan]")
    console.print(f"Events: [green]{len(events)}[/green]")
    console.print(f"Profile items: [green]{report['profile_items']}[/green]")
    console.print(f"Open conflicts: [yellow]{report['open_conflicts']}[/yellow]")
    console.print(f"Stale events: [yellow]{report['stale_events']}[/yellow]")
    console.print(
        "\n[dim]Per-counter metrics have been removed. "
        "Use Langfuse for detailed observability.[/dim]"
    )

    if query.strip():
        retrieved = store.retriever.retrieve(
            query,
            top_k=top_k,
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

    pref_count = (
        len(profile.get("preferences", [])) if isinstance(profile.get("preferences"), list) else 0
    )
    fact_count = (
        len(profile.get("stable_facts", [])) if isinstance(profile.get("stable_facts"), list) else 0
    )
    console.print(f"\nProfile breakdown: preferences={pref_count}, stable_facts={fact_count}")


@memory_app.command("metrics")
def memory_metrics(
    delta: bool = typer.Option(False, "--delta", help="(deprecated) Previously showed deltas"),
    write_baseline: bool = typer.Option(
        False, "--write-baseline", help="(deprecated) Previously wrote baselines"
    ),
    baseline_file: str = typer.Option("", "--baseline-file", help="(deprecated)"),
) -> None:
    """Show memory backend health. Per-counter metrics now live in Langfuse."""
    from nanobot.agent.memory import MemoryStore
    from nanobot.config.loader import load_config

    config = load_config()
    store = MemoryStore(
        config.workspace_path,
        rollout_overrides=_memory_rollout_overrides(config),
    )
    observability = store.eval_runner.get_observability_report()
    backend = observability.get("backend", {}) if isinstance(observability, dict) else {}

    table = Table(title="Memory Backend Health")
    table.add_column("Key", style="cyan")
    table.add_column("Value", style="green")
    for key in (
        "mem0_enabled",
        "mem0_mode",
        "vector_points_count",
        "mem0_get_all_count",
        "history_rows_count",
        "vector_health_state",
    ):
        table.add_row(key, str(backend.get(key, "")))
    console.print(table)
    console.print(
        "\n[dim]Per-counter metrics have been removed. "
        "Use Langfuse for detailed observability.[/dim]"
    )


@memory_app.command("rebuild")
def memory_rebuild(
    max_events: int = typer.Option(
        30, "--max-events", help="Max recent events for MEMORY.md snapshot"
    ),
) -> None:
    """Rebuild memory/MEMORY.md from structured memory profile and events."""
    from nanobot.agent.memory import MemoryStore
    from nanobot.config.loader import load_config

    config = load_config()
    store = MemoryStore(
        config.workspace_path,
        rollout_overrides=_memory_rollout_overrides(config),
    )
    snapshot = store.snapshot.rebuild_memory_snapshot(max_events=max_events, write=True)
    line_count = len(snapshot.splitlines())
    console.print(f"[green]✓[/green] Rebuilt MEMORY.md with {line_count} lines")


@memory_app.command("reindex")
def memory_reindex(
    max_events: int = typer.Option(
        0, "--max-events", help="Optional max events to include (0 = all)"
    ),
    reset: bool = typer.Option(
        True,
        "--reset/--no-reset",
        help="Reset mem0 user memories before rebuilding from structured memory.",
    ),
) -> None:
    """Reindex mem0 vectors from structured profile/events only."""
    from nanobot.agent.memory import MemoryStore
    from nanobot.config.loader import load_config

    config = load_config()
    store = MemoryStore(
        config.workspace_path,
        rollout_overrides=_memory_rollout_overrides(config),
    )
    result = store.maintenance.reindex_from_structured_memory(
        max_events=max_events if max_events > 0 else None,
        reset_existing=reset,
        compact=False,
        read_profile_fn=store.profile_mgr.read_profile,
        read_events_fn=store.ingester.read_events,
        ingester=store.ingester,
        profile_keys=store.PROFILE_KEYS,
        vector_points_count_fn=store.maintenance._vector_points_count,
        mem0_get_all_rows_fn=store.maintenance._mem0_get_all_rows,
    )
    table = Table(title="Memory Reindex")
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("ok", str(result.get("ok")))
    table.add_row("reason", str(result.get("reason", "")))
    table.add_row("written", str(result.get("written", 0)))
    table.add_row("failed", str(result.get("failed", 0)))
    table.add_row("events_indexed", str(result.get("events_indexed", 0)))
    reset_payload = result.get("reset", {}) if isinstance(result.get("reset"), dict) else {}
    table.add_row("reset_requested", str(reset_payload.get("requested", False)))
    table.add_row("reset_ok", str(reset_payload.get("ok", False)))
    table.add_row("reset_reason", str(reset_payload.get("reason", "")))
    table.add_row("reset_deleted_estimate", str(reset_payload.get("deleted_estimate", 0)))
    console.print(table)


@memory_app.command("compact")
def memory_compact(
    max_events: int = typer.Option(
        0, "--max-events", help="Optional max events to include (0 = all)"
    ),
    reset: bool = typer.Option(
        True,
        "--reset/--no-reset",
        help="Reset mem0 user memories before compact rebuild.",
    ),
) -> None:
    """Compact backend memory (dedup/drop superseded) and rebuild mem0 from structured sources."""
    from nanobot.agent.memory import MemoryStore
    from nanobot.config.loader import load_config

    config = load_config()
    store = MemoryStore(
        config.workspace_path,
        rollout_overrides=_memory_rollout_overrides(config),
    )
    result = store.maintenance.reindex_from_structured_memory(
        max_events=max_events if max_events > 0 else None,
        reset_existing=reset,
        compact=True,
        read_profile_fn=store.profile_mgr.read_profile,
        read_events_fn=store.ingester.read_events,
        ingester=store.ingester,
        profile_keys=store.PROFILE_KEYS,
        vector_points_count_fn=store.maintenance._vector_points_count,
        mem0_get_all_rows_fn=store.maintenance._mem0_get_all_rows,
    )
    table = Table(title="Memory Compaction")
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("ok", str(result.get("ok")))
    table.add_row("reason", str(result.get("reason", "")))
    table.add_row("written", str(result.get("written", 0)))
    table.add_row("failed", str(result.get("failed", 0)))
    table.add_row("events_before_compaction", str(result.get("events_before_compaction", 0)))
    table.add_row("events_after_compaction", str(result.get("events_after_compaction", 0)))
    table.add_row("events_superseded_dropped", str(result.get("events_superseded_dropped", 0)))
    table.add_row("events_duplicates_dropped", str(result.get("events_duplicates_dropped", 0)))
    table.add_row("vector_points_after", str(result.get("vector_points_after", 0)))
    reset_payload = result.get("reset", {}) if isinstance(result.get("reset"), dict) else {}
    table.add_row("reset_requested", str(reset_payload.get("requested", False)))
    table.add_row("reset_ok", str(reset_payload.get("ok", False)))
    table.add_row("reset_reason", str(reset_payload.get("reason", "")))
    table.add_row("reset_deleted_estimate", str(reset_payload.get("deleted_estimate", 0)))
    console.print(table)


@memory_app.command("verify")
def memory_verify(
    stale_days: int = typer.Option(
        90, "--stale-days", help="Age threshold for stale events without TTL"
    ),
) -> None:
    """Verify memory consistency and freshness."""
    from nanobot.agent.memory import MemoryStore
    from nanobot.config.loader import load_config

    config = load_config()
    store = MemoryStore(
        config.workspace_path,
        rollout_overrides=_memory_rollout_overrides(config),
    )
    report = store.snapshot.verify_memory(stale_days=stale_days, update_profile=True)

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
    top_k: int = typer.Option(
        6, "--top-k", "-k", help="Default top-k when case does not specify it"
    ),
    seeded_profile: str = typer.Option(
        "", "--seeded-profile", help="Optional seeded profile JSON path"
    ),
    seeded_events: str = typer.Option(
        "", "--seeded-events", help="Optional seeded events JSONL path"
    ),
    seed_only: bool = typer.Option(
        False, "--seed-only", help="Seed + reindex only, do not run evaluation"
    ),
    export: bool = typer.Option(
        False, "--export", help="Save evaluation report JSON under memory/reports/"
    ),
    output_file: str = typer.Option(
        "", "--output-file", help="Optional JSON output path (implies --export)"
    ),
) -> None:
    """Evaluate memory retrieval quality (Recall@k, Precision@k) plus runtime KPIs."""
    import json

    from nanobot.agent.memory import MemoryStore
    from nanobot.config.loader import load_config

    config = load_config()
    store = MemoryStore(
        config.workspace_path,
        rollout_overrides=_memory_rollout_overrides(config),
    )

    if seeded_profile or seeded_events:
        if not seeded_profile or not seeded_events:
            console.print(
                "[red]Both --seeded-profile and --seeded-events are required together.[/red]"
            )
            raise typer.Exit(1)
        seed_result = store.maintenance.seed_structured_corpus(
            profile_path=Path(seeded_profile).expanduser(),
            events_path=Path(seeded_events).expanduser(),
            read_profile_fn=store.profile_mgr.read_profile,
            write_profile_fn=store.profile_mgr.write_profile,
            read_events_fn=store.ingester.read_events,
            ingester=store.ingester,
            profile_keys=store.PROFILE_KEYS,
            vector_points_count_fn=store.maintenance._vector_points_count,
            mem0_get_all_rows_fn=store.maintenance._mem0_get_all_rows,
        )
        seed_table = Table(title="Seeded Corpus")
        seed_table.add_column("Field", style="cyan")
        seed_table.add_column("Value", style="green")
        seed_table.add_row("ok", str(seed_result.get("ok", False)))
        seed_table.add_row("reason", str(seed_result.get("reason", "")))
        seed_table.add_row("seeded_profile_items", str(seed_result.get("seeded_profile_items", 0)))
        seed_table.add_row("seeded_events", str(seed_result.get("seeded_events", 0)))
        reindex_payload = (
            seed_result.get("reindex", {}) if isinstance(seed_result.get("reindex"), dict) else {}
        )
        seed_table.add_row("reindex_written", str(reindex_payload.get("written", 0)))
        seed_table.add_row("reindex_failed", str(reindex_payload.get("failed", 0)))
        seed_table.add_row(
            "vector_points_after", str(reindex_payload.get("vector_points_after", 0))
        )
        console.print(seed_table)
        if not bool(seed_result.get("ok")):
            raise typer.Exit(2)
        if seed_only:
            console.print("[green]✓[/green] Seed-only completed.")
            return

    path = (
        Path(cases_file) if cases_file else (config.workspace_path / "memory" / "eval_cases.json")
    )
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
    except (json.JSONDecodeError, FileNotFoundError, UnicodeDecodeError) as exc:
        console.print(f"[red]Failed to parse benchmark file:[/red] {exc}")
        raise typer.Exit(1) from None

    raw_cases = payload.get("cases") if isinstance(payload, dict) else payload
    if not isinstance(raw_cases, list):
        console.print("[red]Benchmark file must contain a JSON array or {'cases': [...]}[/red]")
        raise typer.Exit(1)

    evaluation = store.eval_runner.evaluate_retrieval_cases(
        raw_cases,
        default_top_k=top_k,
    )
    obs = store.eval_runner.get_observability_report()
    rollout_gate = store.eval_runner.evaluate_rollout_gates(evaluation, obs)
    eval_summary = evaluation.get("summary", {})

    table = Table(title="Memory Evaluation")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("cases", str(evaluation.get("cases", 0)))
    table.add_row("recall_at_k", str(eval_summary.get("recall_at_k", 0.0)))
    table.add_row("precision_at_k", str(eval_summary.get("precision_at_k", 0.0)))
    table.add_row("rollout_gate_passed", str(rollout_gate.get("passed", False)))
    console.print(table)

    gate_checks = rollout_gate.get("checks", [])
    if gate_checks:
        gate_table = Table(title="Rollout Gates")
        gate_table.add_column("Gate", style="cyan")
        gate_table.add_column("Actual", style="green")
        gate_table.add_column("Target")
        gate_table.add_column("Pass")
        for check in gate_checks:
            gate_table.add_row(
                str(check.get("name", "")),
                str(check.get("actual", "")),
                f"{check.get('op', '')} {check.get('threshold', '')}",
                "yes" if bool(check.get("passed")) else "no",
            )
        console.print(gate_table)

    details = evaluation.get("evaluated", [])
    if details:
        detail_table = Table(title="Case Breakdown")
        detail_table.add_column("Query", style="cyan")
        detail_table.add_column("TopK")
        detail_table.add_column("Expected")
        detail_table.add_column("Hits", style="green")
        detail_table.add_column("Recall@k", style="green")
        detail_table.add_column("Precision@k", style="green")
        detail_table.add_column("Why Missed")
        for item in details[:20]:
            why_missed = item.get("why_missed", [])
            detail_table.add_row(
                str(item.get("query", ""))[:60],
                str(item.get("top_k", "")),
                str(item.get("expected", "")),
                str(item.get("hits", "")),
                str(item.get("case_recall_at_k", "")),
                str(item.get("case_precision_at_k", "")),
                ",".join(str(x) for x in why_missed) if isinstance(why_missed, list) else "",
            )
        console.print(detail_table)

    if export or output_file:
        saved = store.eval_runner.save_evaluation_report(
            evaluation,
            obs,
            rollout={
                "status": store._rollout_config.get_status(),
                "gates": rollout_gate,
            },
            output_file=output_file or None,
        )
        console.print(f"[green]✓[/green] Saved report: {saved}")


@memory_app.command("conflicts")
def memory_conflicts(
    all: bool = typer.Option(False, "--all", help="Include resolved conflicts"),
) -> None:
    """List memory conflicts for manual review."""
    from nanobot.agent.memory import MemoryStore
    from nanobot.config.loader import load_config

    config = load_config()
    store = MemoryStore(
        config.workspace_path,
        rollout_overrides=_memory_rollout_overrides(config),
    )
    rows = store.conflict_mgr.list_conflicts(include_closed=all)
    if not rows:
        console.print("No conflicts found.")
        return

    table = Table(title="Memory Conflicts")
    table.add_column("Index", style="cyan")
    table.add_column("Field")
    table.add_column("Old")
    table.add_column("Old Mem0 ID", style="dim")
    table.add_column("New")
    table.add_column("New Mem0 ID", style="dim")
    table.add_column("Status", style="yellow")
    for item in rows:
        table.add_row(
            str(item.get("index", "")),
            str(item.get("field", "")),
            str(item.get("old", ""))[:70],
            str(item.get("old_memory_id", ""))[:24],
            str(item.get("new", ""))[:70],
            str(item.get("new_memory_id", ""))[:24],
            str(item.get("status", "")),
        )
    console.print(table)


@memory_app.command("resolve")
def memory_resolve(
    index: int = typer.Option(
        ..., "--index", help="Conflict index from `nanobot memory conflicts`"
    ),
    action: str = typer.Option(..., "--action", help="Resolution: keep_old | keep_new | dismiss"),
) -> None:
    """Resolve a single memory conflict."""
    from nanobot.agent.memory import MemoryStore
    from nanobot.config.loader import load_config

    config = load_config()
    store = MemoryStore(
        config.workspace_path,
        rollout_overrides=_memory_rollout_overrides(config),
    )
    details = store.conflict_mgr.resolve_conflict_details(index=index, action=action)
    if not details.get("ok"):
        console.print("[red]Failed to resolve conflict. Check index/action.[/red]")
        raise typer.Exit(1)
    console.print(f"[green]✓[/green] Conflict {index} resolved with action '{action}'")
    console.print(
        "mem0 operation: "
        f"[cyan]{details.get('mem0_operation', 'none')}[/cyan], "
        f"ok=[cyan]{details.get('mem0_ok', False)}[/cyan]"
    )
    if details.get("old_memory_id") or details.get("new_memory_id"):
        console.print(
            "mem0 ids: "
            f"old=[dim]{details.get('old_memory_id', '')}[/dim] "
            f"new=[dim]{details.get('new_memory_id', '')}[/dim]"
        )


@memory_app.command("pin")
def memory_pin(
    field: str = typer.Option(
        ...,
        "--field",
        help="Profile field (preferences|stable_facts|active_projects|relationships|constraints)",
    ),
    text: str = typer.Option(..., "--text", help="Memory text to pin"),
) -> None:
    """Pin a memory item so it is prioritized in snapshots and context."""
    from nanobot.agent.memory import MemoryStore
    from nanobot.config.loader import load_config

    config = load_config()
    store = MemoryStore(
        config.workspace_path,
        rollout_overrides=_memory_rollout_overrides(config),
    )
    try:
        ok = store.profile_mgr.set_item_pin(field, text, pinned=True)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from None
    if not ok:
        raise typer.Exit(1)
    console.print(f"[green]✓[/green] Pinned memory item in '{field}'")


@memory_app.command("unpin")
def memory_unpin(
    field: str = typer.Option(..., "--field", help="Profile field"),
    text: str = typer.Option(..., "--text", help="Memory text to unpin"),
) -> None:
    """Unpin a memory item."""
    from nanobot.agent.memory import MemoryStore
    from nanobot.config.loader import load_config

    config = load_config()
    store = MemoryStore(
        config.workspace_path,
        rollout_overrides=_memory_rollout_overrides(config),
    )
    try:
        ok = store.profile_mgr.set_item_pin(field, text, pinned=False)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from None
    if not ok:
        raise typer.Exit(1)
    console.print(f"[green]✓[/green] Unpinned memory item in '{field}'")


@memory_app.command("outdated")
def memory_outdated(
    field: str = typer.Option(..., "--field", help="Profile field"),
    text: str = typer.Option(..., "--text", help="Memory text to mark outdated"),
) -> None:
    """Mark a memory item as outdated (stale)."""
    from nanobot.agent.memory import MemoryStore
    from nanobot.config.loader import load_config

    config = load_config()
    store = MemoryStore(
        config.workspace_path,
        rollout_overrides=_memory_rollout_overrides(config),
    )
    try:
        ok = store.profile_mgr.mark_item_outdated(field, text)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from None
    if not ok:
        console.print("[red]Memory item not found.[/red]")
        raise typer.Exit(1)
    console.print(f"[green]✓[/green] Marked memory item as outdated in '{field}'")


@memory_app.command("migrate-graph")
def migrate_graph(
    neo4j_uri: str = typer.Option("bolt://localhost:7687", help="Neo4j server URI"),
    neo4j_auth: str = typer.Option("neo4j/password", help="Neo4j auth (user/password)"),
    neo4j_database: str = typer.Option("neo4j", help="Neo4j database name"),
) -> None:
    """Migrate knowledge graph from Neo4j to local networkx JSON file.

    Requires neo4j package: pip install neo4j
    """
    try:
        from neo4j import GraphDatabase  # type: ignore[import-untyped]
    except ImportError:
        console.print("[red]neo4j package not installed.[/red]")
        console.print("Install it first: pip install neo4j")
        raise typer.Exit(1) from None

    from nanobot.config.loader import load_config

    config = load_config()
    workspace = config.workspace_path

    # Parse auth
    parts = neo4j_auth.split("/", 1)
    user, password = parts[0], parts[1] if len(parts) > 1 else ""

    console.print(f"Connecting to Neo4j at {neo4j_uri}...")
    driver = None
    try:
        driver = GraphDatabase.driver(neo4j_uri, auth=(user, password))
        with driver.session(database=neo4j_database) as session:
            # Read all nodes
            nodes = session.run("MATCH (n) RETURN n").data()
            # Read all relationships
            rels = session.run(
                "MATCH ()-[r]->() RETURN r, type(r) as type,"
                " startNode(r).name as src, endNode(r).name as tgt"
            ).data()
    except Exception as exc:  # crash-barrier: neo4j connection errors are opaque
        console.print(f"[red]Failed to connect to Neo4j: {exc}[/red]")
        raise typer.Exit(1) from None
    finally:
        if driver is not None:
            driver.close()

    # Build networkx graph
    from nanobot.agent.memory.graph import KnowledgeGraph

    graph = KnowledgeGraph(workspace=workspace)

    node_count = 0
    for record in nodes:
        node = record["n"]
        props = dict(node.items())
        name = props.pop("name", str(node.id))
        graph._graph.add_node(name.lower(), **props)
        node_count += 1

    edge_count = 0
    for record in rels:
        src = record.get("src", "").lower()
        tgt = record.get("tgt", "").lower()
        rel_type = record.get("type", "RELATED_TO")
        if src and tgt:
            graph._graph.add_edge(src, tgt, type=rel_type)
            edge_count += 1

    graph._save()
    console.print(
        f"[green]Migration complete: {node_count} entities, {edge_count} relationships[/green]"
    )
    console.print(f"Saved to: {graph._json_path}")


@app.command("replay-deadletters")
def replay_deadletters(
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Preview what would be replayed without sending."
    ),
) -> None:
    """Replay undelivered outbound messages from the dead-letter file."""
    from nanobot.config.loader import load_config

    config = load_config()
    workspace = config.workspace_path
    dead_letter_path = workspace / "outbound_failed.jsonl"

    if not dead_letter_path.exists():
        console.print("[dim]No dead-letter file found — nothing to replay.[/dim]")
        raise typer.Exit(0)

    import json

    lines = [
        line.strip()
        for line in dead_letter_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not lines:
        console.print("[dim]Dead-letter file is empty — nothing to replay.[/dim]")
        raise typer.Exit(0)

    console.print(f"Found [bold]{len(lines)}[/bold] dead-letter message(s) in {dead_letter_path}\n")

    if dry_run:
        for i, line in enumerate(lines, 1):
            try:
                entry = json.loads(line)
                channel = entry.get("channel", "?")
                chat_id = entry.get("chat_id", "?")
                content_preview = (entry.get("content", ""))[:80]
                error = entry.get("error", "")
                console.print(f"  {i}. [{channel}:{chat_id}] {content_preview}")
                if error:
                    console.print(f"     [dim]error: {error}[/dim]")
            except json.JSONDecodeError:
                console.print(f"  {i}. [red]invalid JSON line[/red]")
        console.print("\n[dim]Dry run — no messages sent. Use without --dry-run to replay.[/dim]")
        raise typer.Exit(0)

    # Real replay requires starting channels
    from nanobot.bus.queue import MessageBus

    bus = MessageBus()
    from nanobot.channels.manager import ChannelManager

    manager = ChannelManager(config, bus)
    if not manager.channels:
        console.print("[red]No channels available for replay.[/red]")
        raise typer.Exit(1)

    console.print(f"Channels: {', '.join(manager.enabled_channels)}")

    async def _run() -> tuple[int, int, int]:
        return await manager.replay_dead_letters(dry_run=False)

    total, ok, fail = asyncio.run(_run())
    console.print(
        f"\nReplay complete: [green]{ok} sent[/green], [red]{fail} failed[/red] (of {total})"
    )
    if fail:
        console.print(f"[dim]Failed messages remain in {dead_letter_path}[/dim]")


@app.command()
def status() -> None:
    """Show nanobot status."""
    _status_impl()


# ============================================================================
# OAuth Login
# ============================================================================

provider_app = typer.Typer(help="Manage providers")
app.add_typer(provider_app, name="provider")


_LOGIN_HANDLERS: dict[str, Any] = {}


def _register_login(name: str) -> Any:
    def decorator(fn: Any) -> Any:
        _LOGIN_HANDLERS[name] = fn
        return fn

    return decorator


@provider_app.command("login")
def provider_login(
    provider: str = typer.Argument(
        ..., help="OAuth provider (e.g. 'openai-codex', 'github-copilot')"
    ),
) -> None:
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
        except Exception:  # crash-barrier: token errors must not prevent login flow
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
        console.print(
            f"[green]✓ Authenticated with OpenAI Codex[/green]  [dim]{token.account_id}[/dim]"
        )
    except ImportError:
        console.print("[red]oauth_cli_kit not installed. Run: pip install oauth-cli-kit[/red]")
        raise typer.Exit(1) from None


@_register_login("github_copilot")
def _login_github_copilot() -> None:
    import asyncio

    console.print("[cyan]Starting GitHub Copilot device flow...[/cyan]\n")

    async def _trigger() -> None:
        from litellm import acompletion

        await acompletion(
            model="github_copilot/gpt-4o",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=1,
        )

    try:
        asyncio.run(_trigger())
        console.print("[green]✓ Authenticated with GitHub Copilot[/green]")
    except Exception as e:  # crash-barrier: catch all provider/auth errors
        console.print(f"[red]Authentication error: {e}[/red]")
        raise typer.Exit(1) from None


if __name__ == "__main__":
    app()
