"""CLI commands for multi-agent routing diagnostics."""

from __future__ import annotations

import asyncio

import typer
from rich.table import Table

from nanobot.cli._shared import (
    _configure_log_sink,
    _make_agent_config,
    _make_provider,
    _print_agent_response,
    console,
)

routing_app = typer.Typer(help="Multi-agent routing diagnostics")


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

    from nanobot.agent.agent_factory import build_agent
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

    agent_loop = build_agent(
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
