"""Inspection commands: status, agents, models, health."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from nanobot import __logo__, __version__
from nanobot.config.loader import get_config_path, load_config
from nanobot.config.paths import get_data_dir

console = Console()

# ---------------------------------------------------------------------------
# PID file helpers (shared with gateway)
# ---------------------------------------------------------------------------

_PID_FILENAME = "gateway.pid"


def _pid_file() -> Path:
    return get_data_dir() / _PID_FILENAME


def write_gateway_pid() -> None:
    """Write the current process PID and start time to the PID file."""
    pf = _pid_file()
    pf.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "pid": os.getpid(),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "version": __version__,
    }
    pf.write_text(json.dumps(data), encoding="utf-8")


def remove_gateway_pid() -> None:
    """Remove the PID file on clean shutdown."""
    pf = _pid_file()
    if pf.exists():
        pf.unlink(missing_ok=True)


def _read_gateway_pid() -> dict | None:
    """Read the PID file. Returns None if missing or stale."""
    pf = _pid_file()
    if not pf.exists():
        return None
    try:
        data = json.loads(pf.read_text(encoding="utf-8"))
    except Exception:
        return None
    pid = data.get("pid")
    if not pid:
        return None
    # Check if process is alive
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return None
    return data


def _format_duration(seconds: float) -> str:
    """Format seconds into a human-readable duration string."""
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        m, s = divmod(int(seconds), 60)
        return f"{m}m {s}s"
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    if h < 24:
        return f"{h}h {m}m {s}s"
    d, h = divmod(h, 24)
    return f"{d}d {h}h {m}m"


# ---------------------------------------------------------------------------
# nanobot status
# ---------------------------------------------------------------------------

def show_status() -> None:
    """Show comprehensive nanobot status."""
    config_path = get_config_path()
    config = load_config()
    workspace = config.workspace_path

    console.print(f"{__logo__} nanobot v{__version__} Status\n")

    # --- Config & Workspace ---
    config_ok = config_path.exists()
    workspace_ok = workspace.exists()
    console.print(f"  Config:    {config_path} {'[green]✓[/green]' if config_ok else '[red]✗[/red]'}")
    console.print(f"  Workspace: {workspace} {'[green]✓[/green]' if workspace_ok else '[red]✗[/red]'}")

    if not config_ok:
        console.print("\n[yellow]No config found. Run [cyan]nanobot onboard[/cyan] to get started.[/yellow]")
        return

    # --- Gateway ---
    gw = _read_gateway_pid()
    console.print()
    if gw:
        started = gw.get("started_at", "")
        try:
            started_dt = datetime.fromisoformat(started)
            uptime = _format_duration((datetime.now(timezone.utc) - started_dt).total_seconds())
        except Exception:
            uptime = "unknown"
        console.print(f"  [bold]Gateway[/bold]    [green]● running[/green]  PID {gw['pid']}  uptime {uptime}")
    else:
        console.print("  [bold]Gateway[/bold]    [dim]○ not running[/dim]")

    # --- Provider & Model ---
    provider_name = config.get_provider_name() or "unknown"
    model = config.agents.defaults.model
    console.print(f"  [bold]Provider[/bold]   {provider_name}")
    console.print(f"  [bold]Model[/bold]      {model}")

    # --- Channels ---
    try:
        from nanobot.channels.registry import discover_all

        all_channels = discover_all()
        enabled = []
        for name in sorted(all_channels):
            section = getattr(config.channels, name, None)
            if section is None:
                continue
            is_enabled = (
                section.get("enabled", False)
                if isinstance(section, dict)
                else getattr(section, "enabled", False)
            )
            if is_enabled:
                enabled.append(name)
        if enabled:
            console.print(f"  [bold]Channels[/bold]   {', '.join(enabled)}")
        else:
            console.print("  [bold]Channels[/bold]   [dim]none enabled[/dim]")
    except Exception:
        console.print("  [bold]Channels[/bold]   [dim]unable to discover[/dim]")

    # --- Heartbeat ---
    hb = config.gateway.heartbeat
    if hb.enabled:
        console.print(f"  [bold]Heartbeat[/bold]  every {hb.interval_s}s")
    else:
        console.print("  [bold]Heartbeat[/bold]  [dim]disabled[/dim]")

    # --- Workspace info ---
    console.print()
    if workspace_ok:
        # Count sessions
        sessions_dir = workspace / "sessions"
        n_sessions = len(list(sessions_dir.glob("*.jsonl"))) if sessions_dir.is_dir() else 0
        # Workspace size
        total_bytes = sum(f.stat().st_size for f in workspace.rglob("*") if f.is_file())
        if total_bytes < 1024:
            size_str = f"{total_bytes} B"
        elif total_bytes < 1024 * 1024:
            size_str = f"{total_bytes / 1024:.1f} KB"
        else:
            size_str = f"{total_bytes / (1024 * 1024):.1f} MB"
        console.print(f"  [bold]Workspace[/bold]  {n_sessions} session(s), {size_str} on disk")

    # --- API keys summary ---
    console.print()
    from nanobot.providers.registry import PROVIDERS

    for spec in PROVIDERS:
        p = getattr(config.providers, spec.name, None)
        if p is None:
            continue
        if spec.is_oauth:
            console.print(f"  {spec.label}: [green]✓ (OAuth)[/green]")
        elif spec.is_local:
            if p.api_base:
                console.print(f"  {spec.label}: [green]✓ {p.api_base}[/green]")
        else:
            if p.api_key:
                console.print(f"  {spec.label}: [green]✓[/green]")


# ---------------------------------------------------------------------------
# nanobot agents
# ---------------------------------------------------------------------------

def show_agents() -> None:
    """Show agent sessions, profiles, and running subagents."""
    config_path = get_config_path()
    config = load_config()
    workspace = config.workspace_path

    console.print(f"{__logo__} nanobot Agents\n")

    if not config_path.exists():
        console.print("[yellow]No config found. Run [cyan]nanobot onboard[/cyan] first.[/yellow]")
        return

    # --- Agent Profiles ---
    console.print("[bold]Configured Profiles[/bold]")
    table = Table(show_header=True, header_style="bold")
    table.add_column("Profile", style="cyan")
    table.add_column("Model")
    table.add_column("Provider")
    table.add_column("Max Tokens")
    table.add_column("Temperature")

    defaults = config.agents.defaults
    provider_name = config.get_provider_name() or "auto"
    table.add_row(
        "defaults",
        defaults.model,
        provider_name,
        str(defaults.max_tokens),
        str(defaults.temperature),
    )
    console.print(table)

    # --- Active Sessions ---
    console.print()
    sessions_dir = workspace / "sessions"
    if sessions_dir.is_dir():
        from nanobot.session.manager import SessionManager

        sm = SessionManager(workspace)
        sessions = sm.list_sessions()
        if sessions:
            console.print(f"[bold]Active Sessions[/bold] ({len(sessions)} total)")
            st = Table(show_header=True, header_style="bold")
            st.add_column("Session Key", style="cyan")
            st.add_column("Messages", justify="right")
            st.add_column("Updated")
            for s in sessions[:20]:  # Show up to 20
                key = s.get("key", "?")
                updated = s.get("updated_at", "")
                if updated:
                    try:
                        dt = datetime.fromisoformat(updated)
                        updated = dt.strftime("%Y-%m-%d %H:%M")
                    except Exception:
                        pass
                # Count messages from metadata line
                msg_count = "?"
                try:
                    path = s.get("path")
                    if path:
                        with open(path, encoding="utf-8") as f:
                            lines = sum(1 for _ in f) - 1  # minus metadata line
                        msg_count = str(max(0, lines))
                except Exception:
                    pass
                st.add_row(key, msg_count, updated)
            console.print(st)
        else:
            console.print("[bold]Active Sessions[/bold]  [dim]none[/dim]")
    else:
        console.print("[bold]Active Sessions[/bold]  [dim]workspace not found[/dim]")

    # --- Running Gateway ---
    console.print()
    gw = _read_gateway_pid()
    if gw:
        console.print(f"[bold]Gateway[/bold]  [green]● running[/green] (PID {gw['pid']})")
    else:
        console.print("[bold]Gateway[/bold]  [dim]○ not running[/dim]")

    # --- Cron Jobs ---
    try:
        from nanobot.cron.service import CronService

        cron_store = workspace / "cron" / "jobs.json"
        if cron_store.exists():
            cron = CronService(cron_store)
            status = cron.status()
            n_jobs = status.get("jobs", 0)
            if n_jobs:
                console.print(f"[bold]Cron[/bold]       {n_jobs} scheduled job(s)")
            else:
                console.print("[bold]Cron[/bold]       [dim]no jobs[/dim]")
        else:
            console.print("[bold]Cron[/bold]       [dim]no jobs[/dim]")
    except Exception:
        console.print("[bold]Cron[/bold]       [dim]unable to read[/dim]")


# ---------------------------------------------------------------------------
# nanobot models
# ---------------------------------------------------------------------------

def show_models() -> None:
    """Show model information for the current provider."""
    config_path = get_config_path()
    config = load_config()

    console.print(f"{__logo__} nanobot Models\n")

    if not config_path.exists():
        console.print("[yellow]No config found. Run [cyan]nanobot onboard[/cyan] first.[/yellow]")
        return

    provider_name = config.get_provider_name() or "unknown"
    model = config.agents.defaults.model
    api_base = config.get_api_base()

    console.print(f"  [bold]Active Provider[/bold]: {provider_name}")
    console.print(f"  [bold]Active Model[/bold]:    {model}")
    if api_base:
        console.print(f"  [bold]API Base[/bold]:        {api_base}")
    console.print()

    # Show all configured providers with their status
    console.print("[bold]All Providers[/bold]")
    table = Table(show_header=True, header_style="bold")
    table.add_column("Provider", style="cyan")
    table.add_column("Status")
    table.add_column("API Base")
    table.add_column("Type")

    from nanobot.providers.registry import PROVIDERS

    for spec in PROVIDERS:
        p = getattr(config.providers, spec.name, None)
        if p is None:
            continue

        if spec.is_oauth:
            status = "[green]OAuth[/green]"
            api_key_status = ""
        elif spec.is_local:
            has_base = bool(p.api_base)
            status = "[green]configured[/green]" if has_base else "[dim]not set[/dim]"
        else:
            has_key = bool(p.api_key)
            status = "[green]key set[/green]" if has_key else "[dim]no key[/dim]"

        base = p.api_base or spec.default_api_base or ""
        if spec.is_gateway:
            kind = "gateway"
        elif spec.is_local:
            kind = "local"
        elif spec.is_oauth:
            kind = "oauth"
        else:
            kind = "standard"

        table.add_row(spec.label, status, base, kind)

    console.print(table)

    # Show model-specific info
    console.print()
    console.print("[bold]Current Configuration[/bold]")
    defaults = config.agents.defaults
    console.print(f"  Model:                {defaults.model}")
    console.print(f"  Max Tokens:           {defaults.max_tokens}")
    console.print(f"  Context Window:       {defaults.context_window_tokens:,}")
    console.print(f"  Temperature:          {defaults.temperature}")
    console.print(f"  Max Tool Iterations:  {defaults.max_tool_iterations}")
    if defaults.reasoning_effort:
        console.print(f"  Reasoning Effort:     {defaults.reasoning_effort}")
    console.print(f"  Timezone:             {defaults.timezone}")


# ---------------------------------------------------------------------------
# nanobot health
# ---------------------------------------------------------------------------

def show_health() -> None:
    """Check health of all nanobot connections."""
    config_path = get_config_path()
    config = load_config()
    workspace = config.workspace_path

    console.print(f"{__logo__} nanobot Health Check\n")

    checks: list[tuple[str, bool, str]] = []

    # 1. Config file
    if config_path.exists():
        checks.append(("Config file", True, str(config_path)))
    else:
        checks.append(("Config file", False, f"not found: {config_path}"))

    # 2. Workspace
    if workspace.exists():
        checks.append(("Workspace", True, str(workspace)))
    else:
        checks.append(("Workspace", False, f"not found: {workspace}"))

    # 3. Gateway
    gw = _read_gateway_pid()
    if gw:
        checks.append(("Gateway process", True, f"PID {gw['pid']}"))
    else:
        checks.append(("Gateway process", False, "not running"))

    # 4. Provider API key
    provider_name = config.get_provider_name()
    if provider_name:
        p = config.get_provider()
        spec_ok = False
        spec_msg = provider_name
        from nanobot.providers.registry import find_by_name
        spec = find_by_name(provider_name)
        if spec:
            if spec.is_oauth:
                spec_ok = True
                spec_msg = f"{provider_name} (OAuth)"
            elif spec.is_local:
                spec_ok = bool(p and p.api_base)
                spec_msg = f"{provider_name} ({p.api_base if p and p.api_base else 'no api_base'})"
            else:
                spec_ok = bool(p and p.api_key)
                spec_msg = f"{provider_name} ({'key set' if spec_ok else 'no key'})"
        checks.append(("Provider", spec_ok, spec_msg))
    else:
        checks.append(("Provider", False, "no provider matched"))

    # 5. Channels
    try:
        from nanobot.channels.registry import discover_all

        all_channels = discover_all()
        enabled_channels = []
        for name in sorted(all_channels):
            section = getattr(config.channels, name, None)
            if section is None:
                continue
            is_enabled = (
                section.get("enabled", False)
                if isinstance(section, dict)
                else getattr(section, "enabled", False)
            )
            if is_enabled:
                enabled_channels.append(name)
        if enabled_channels:
            checks.append(("Channels", True, ", ".join(enabled_channels)))
        else:
            checks.append(("Channels", False, "no channels enabled"))
    except Exception as e:
        checks.append(("Channels", False, f"error: {e}"))

    # 6. Heartbeat
    hb = config.gateway.heartbeat
    if hb.enabled:
        checks.append(("Heartbeat", True, f"every {hb.interval_s}s"))
    else:
        checks.append(("Heartbeat", False, "disabled"))

    # 7. MCP servers
    mcp_servers = config.tools.mcp_servers
    if mcp_servers:
        for name, srv_cfg in mcp_servers.items():
            if srv_cfg.command:
                checks.append((f"MCP: {name}", True, f"stdio ({srv_cfg.command})"))
            elif srv_cfg.url:
                checks.append((f"MCP: {name}", True, f"http ({srv_cfg.url})"))
            else:
                checks.append((f"MCP: {name}", False, "no command or url"))
    else:
        checks.append(("MCP servers", True, "none configured"))

    # 8. Cron store
    cron_store = workspace / "cron" / "jobs.json"
    if cron_store.exists():
        try:
            data = json.loads(cron_store.read_text(encoding="utf-8"))
            n = len(data.get("jobs", [])) if isinstance(data, dict) else 0
            checks.append(("Cron store", True, f"{n} job(s)"))
        except Exception:
            checks.append(("Cron store", False, "corrupt file"))
    else:
        checks.append(("Cron store", True, "no jobs"))

    # --- Print results ---
    all_ok = all(ok for _, ok, _ in checks)

    table = Table(show_header=True, header_style="bold")
    table.add_column("Check", style="cyan")
    table.add_column("Status")
    table.add_column("Details")

    for name, ok, detail in checks:
        status = "[green]✓ ok[/green]" if ok else "[red]✗ fail[/red]"
        table.add_row(name, status, detail)

    console.print(table)
    console.print()

    if all_ok:
        console.print("[green]All checks passed ✓[/green]")
    else:
        failed = [name for name, ok, _ in checks if not ok]
        console.print(f"[red]{len(failed)} check(s) failed: {', '.join(failed)}[/red]")
