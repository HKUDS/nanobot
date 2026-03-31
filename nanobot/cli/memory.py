# size-exception: CLI command module — many small command functions
"""CLI commands for the memory subsystem."""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from rich.table import Table

from nanobot import __logo__
from nanobot.cli._shared import console
from nanobot.memory.constants import PROFILE_KEYS

memory_app = typer.Typer(help="Manage memory system")


@memory_app.command("inspect")
def memory_inspect(
    query: str = typer.Option("", "--query", "-q", help="Optional retrieval query"),
    top_k: int = typer.Option(6, "--top-k", "-k", help="Top-k memories to display"),
) -> None:
    """Inspect memory backend health, profile, and retrieval results."""
    from nanobot.config.loader import load_config
    from nanobot.memory import MemoryStore

    config = load_config()
    ac = config.agents.defaults
    store = MemoryStore(
        config.workspace_path,
        memory_config=ac.memory,
    )

    observability = store.eval_runner.get_observability_report()
    backend = observability.get("backend", {}) if isinstance(observability, dict) else {}
    profile = store.profile_mgr.read_profile()
    report = store.snapshot.verify_memory()
    events = store.ingester.read_events()

    console.print(f"{__logo__} Memory Inspect\n")
    console.print("Mode: [cyan]vector[/cyan]")
    console.print(f"vector enabled: [cyan]{backend.get('vector_enabled', False)}[/cyan]")
    console.print(f"vector mode: [cyan]{backend.get('vector_mode', 'disabled')}[/cyan]")
    console.print(f"vector points: [cyan]{backend.get('vector_points_count', 0)}[/cyan]")
    console.print(f"vector search count: [cyan]{backend.get('vector_search_count', 0)}[/cyan]")
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
        retrieved = asyncio.run(
            store.retriever.retrieve(
                query,
                top_k=top_k,
            )
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
                item.timestamp[:16],
                item.type,
                f"{item.scores.final_score:.3f}",
                item.summary,
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
def memory_metrics() -> None:
    """Show memory backend health. Per-counter metrics now live in Langfuse."""
    from nanobot.config.loader import load_config
    from nanobot.memory import MemoryStore

    config = load_config()
    ac = config.agents.defaults
    store = MemoryStore(
        config.workspace_path,
        memory_config=ac.memory,
    )
    observability = store.eval_runner.get_observability_report()
    backend = observability.get("backend", {}) if isinstance(observability, dict) else {}

    table = Table(title="Memory Backend Health")
    table.add_column("Key", style="cyan")
    table.add_column("Value", style="green")
    for key in (
        "vector_enabled",
        "vector_mode",
        "vector_points_count",
        "vector_search_count",
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
        30, "--max-events", help="Max recent events for memory snapshot"
    ),
) -> None:
    """Rebuild memory snapshot from structured memory profile and events."""
    from nanobot.config.loader import load_config
    from nanobot.memory import MemoryStore

    config = load_config()
    ac = config.agents.defaults
    store = MemoryStore(
        config.workspace_path,
        memory_config=ac.memory,
    )
    snapshot = store.snapshot.rebuild_memory_snapshot(max_events=max_events, write=True)
    line_count = len(snapshot.splitlines())
    console.print(f"[green]✓[/green] Rebuilt memory snapshot with {line_count} lines")


@memory_app.command("reindex")
def memory_reindex(
    max_events: int = typer.Option(
        0, "--max-events", help="Optional max events to include (0 = all)"
    ),
    reset: bool = typer.Option(
        True,
        "--reset/--no-reset",
        help="Reset vector memories before rebuilding from structured memory.",
    ),
) -> None:
    """Reindex vectors from structured profile/events only."""
    from nanobot.config.loader import load_config
    from nanobot.memory import MemoryStore

    config = load_config()
    ac = config.agents.defaults
    store = MemoryStore(
        config.workspace_path,
        memory_config=ac.memory,
    )
    result = store.maintenance.reindex_from_structured_memory(
        max_events=max_events if max_events > 0 else None,
        reset_existing=reset,
        compact=False,
        read_profile_fn=store.profile_mgr.read_profile,
        read_events_fn=store.ingester.read_events,
        ingester=store.ingester,
        profile_keys=PROFILE_KEYS,
        vector_points_count_fn=None,
        vector_rows_fn=None,
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
        help="Reset vector memories before compact rebuild.",
    ),
) -> None:
    """Compact backend memory (dedup/drop superseded) and rebuild vectors from structured sources."""
    from nanobot.config.loader import load_config
    from nanobot.memory import MemoryStore

    config = load_config()
    ac = config.agents.defaults
    store = MemoryStore(
        config.workspace_path,
        memory_config=ac.memory,
    )
    result = store.maintenance.reindex_from_structured_memory(
        max_events=max_events if max_events > 0 else None,
        reset_existing=reset,
        compact=True,
        read_profile_fn=store.profile_mgr.read_profile,
        read_events_fn=store.ingester.read_events,
        ingester=store.ingester,
        profile_keys=PROFILE_KEYS,
        vector_points_count_fn=None,
        vector_rows_fn=None,
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
    from nanobot.config.loader import load_config
    from nanobot.memory import MemoryStore

    config = load_config()
    ac = config.agents.defaults
    store = MemoryStore(
        config.workspace_path,
        memory_config=ac.memory,
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

    from nanobot.config.loader import load_config
    from nanobot.memory import MemoryStore

    config = load_config()
    ac = config.agents.defaults
    store = MemoryStore(
        config.workspace_path,
        memory_config=ac.memory,
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
            profile_keys=PROFILE_KEYS,
            vector_points_count_fn=None,
            vector_rows_fn=None,
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

    evaluation = asyncio.run(
        store.eval_runner.evaluate_retrieval_cases(
            raw_cases,
            default_top_k=top_k,
        )
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
                "status": store._memory_config.rollout_status(),
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
    from nanobot.config.loader import load_config
    from nanobot.memory import MemoryStore

    config = load_config()
    ac = config.agents.defaults
    store = MemoryStore(
        config.workspace_path,
        memory_config=ac.memory,
    )
    rows = store.conflict_mgr.list_conflicts(include_closed=all)
    if not rows:
        console.print("No conflicts found.")
        return

    table = Table(title="Memory Conflicts")
    table.add_column("Index", style="cyan")
    table.add_column("Field")
    table.add_column("Old")
    table.add_column("Old Memory ID", style="dim")
    table.add_column("New")
    table.add_column("New Memory ID", style="dim")
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
    from nanobot.config.loader import load_config
    from nanobot.memory import MemoryStore

    config = load_config()
    ac = config.agents.defaults
    store = MemoryStore(
        config.workspace_path,
        memory_config=ac.memory,
    )
    details = store.conflict_mgr.resolve_conflict_details(index=index, action=action)
    if not details.get("ok"):
        console.print("[red]Failed to resolve conflict. Check index/action.[/red]")
        raise typer.Exit(1)
    console.print(f"[green]✓[/green] Conflict {index} resolved with action '{action}'")
    console.print(
        "db operation: "
        f"[cyan]{details.get('db_operation', 'none')}[/cyan], "
        f"ok=[cyan]{details.get('db_ok', False)}[/cyan]"
    )
    if details.get("old_memory_id") or details.get("new_memory_id"):
        console.print(
            "memory ids: "
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
    from nanobot.config.loader import load_config
    from nanobot.memory import MemoryStore

    config = load_config()
    ac = config.agents.defaults
    store = MemoryStore(
        config.workspace_path,
        memory_config=ac.memory,
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
    from nanobot.config.loader import load_config
    from nanobot.memory import MemoryStore

    config = load_config()
    ac = config.agents.defaults
    store = MemoryStore(
        config.workspace_path,
        memory_config=ac.memory,
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
    from nanobot.config.loader import load_config
    from nanobot.memory import MemoryStore

    config = load_config()
    ac = config.agents.defaults
    store = MemoryStore(
        config.workspace_path,
        memory_config=ac.memory,
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
