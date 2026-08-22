"""Diagnostic health checks for nanobot — verifies config, providers, network, workspace."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from nanobot import __version__


class CheckStatus(Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    SKIP = "skip"


@dataclass
class CheckResult:
    name: str
    status: CheckStatus
    detail: str = ""
    suggestion: str = ""
    duration_ms: float = 0.0


@dataclass
class DoctorReport:
    results: list[CheckResult] = field(default_factory=list)

    @property
    def all_pass(self) -> bool:
        return all(r.status != CheckStatus.FAIL for r in self.results)

    @property
    def fail_count(self) -> int:
        return sum(1 for r in self.results if r.status == CheckStatus.FAIL)

    @property
    def warn_count(self) -> int:
        return sum(1 for r in self.results if r.status == CheckStatus.WARN)


def _status_icon(status: CheckStatus) -> str:
    return {CheckStatus.PASS: "[green]✓[/green]",
            CheckStatus.WARN: "[yellow]![/yellow]",
            CheckStatus.FAIL: "[red]✗[/red]",
            CheckStatus.SKIP: "[dim]○[/dim]"}[status]


async def _check_config_exists(config_path: Path) -> CheckResult:
    t0 = time.monotonic()
    if config_path.exists():
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
            # basic structure check
            has_providers = "providers" in data
            has_agents = "agents" in data
            if has_providers and has_agents:
                return CheckResult("Config file", CheckStatus.PASS,
                                   detail=f"Valid JSON at {config_path}",
                                   duration_ms=(time.monotonic() - t0) * 1000)
            return CheckResult("Config file", CheckStatus.WARN,
                               detail=f"Config at {config_path} is missing expected sections",
                               suggestion="Run `nanobot onboard --wizard` to regenerate",
                               duration_ms=(time.monotonic() - t0) * 1000)
        except json.JSONDecodeError as e:
            return CheckResult("Config file", CheckStatus.FAIL,
                               detail=f"Invalid JSON: {e}",
                               suggestion=f"Fix or delete {config_path} and run `nanobot onboard --wizard`",
                               duration_ms=(time.monotonic() - t0) * 1000)
    return CheckResult("Config file", CheckStatus.FAIL,
                       detail=f"Config not found at {config_path}",
                       suggestion="Run `nanobot onboard` to create configuration",
                       duration_ms=(time.monotonic() - t0) * 1000)


async def _check_api_keys(config_path: Path) -> CheckResult:
    t0 = time.monotonic()
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return CheckResult("API keys", CheckStatus.SKIP,
                           detail="Config unreadable, skipped",
                           duration_ms=0)
    providers = data.get("providers", {})
    configured: list[str] = []
    for name, cfg in providers.items():
        if isinstance(cfg, dict):
            if cfg.get("apiKey") or cfg.get("apiBase"):
                configured.append(name)
    if configured:
        return CheckResult("API keys", CheckStatus.PASS,
                           detail=f"{len(configured)} provider(s) configured: {', '.join(configured)}",
                           duration_ms=(time.monotonic() - t0) * 1000)
    return CheckResult("API keys", CheckStatus.FAIL,
                       detail="No API keys or local endpoints configured",
                       suggestion="Get a key from https://platform.deepseek.com/api_keys "
                                  "or https://openrouter.ai/keys, "
                                  "then run `nanobot onboard --wizard`",
                       duration_ms=(time.monotonic() - t0) * 1000)


async def _check_workspace(config_path: Path) -> CheckResult:
    t0 = time.monotonic()
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        ws_raw = data.get("agents", {}).get("defaults", {}).get("workspace", "~/.nanobot/workspace")
    except Exception:
        ws_raw = "~/.nanobot/workspace"
    ws_path = Path(ws_raw).expanduser().resolve()
    if ws_path.exists():
        writable = os.access(str(ws_path), os.W_OK)
        if writable:
            return CheckResult("Workspace", CheckStatus.PASS,
                               detail=f"Exists and writable: {ws_path}",
                               duration_ms=(time.monotonic() - t0) * 1000)
        return CheckResult("Workspace", CheckStatus.FAIL,
                           detail=f"Exists but not writable: {ws_path}",
                           suggestion=f"Check permissions: chmod 755 {ws_path}",
                           duration_ms=(time.monotonic() - t0) * 1000)
    try:
        ws_path.mkdir(parents=True, exist_ok=True)
        return CheckResult("Workspace", CheckStatus.PASS,
                           detail=f"Created: {ws_path}",
                           duration_ms=(time.monotonic() - t0) * 1000)
    except Exception as e:
        return CheckResult("Workspace", CheckStatus.FAIL,
                           detail=f"Cannot create: {e}",
                           suggestion="Check parent directory permissions",
                           duration_ms=(time.monotonic() - t0) * 1000)


async def _check_python_version() -> CheckResult:
    t0 = time.monotonic()
    vi = sys.version_info
    if vi >= (3, 11):
        return CheckResult("Python version", CheckStatus.PASS,
                           detail=f"Python {vi.major}.{vi.minor}.{vi.micro}",
                           duration_ms=(time.monotonic() - t0) * 1000)
    return CheckResult("Python version", CheckStatus.FAIL,
                       detail=f"Python {vi.major}.{vi.minor}.{vi.micro} (requires >=3.11)",
                       suggestion="Upgrade Python to 3.11 or later",
                       duration_ms=(time.monotonic() - t0) * 1000)


async def _check_network() -> CheckResult:
    """Test basic network connectivity to common model API endpoints."""
    t0 = time.monotonic()
    import httpx
    endpoints = [
        ("DashScope", "https://dashscope.aliyuncs.com/compatible-mode/v1/models"),
        ("DeepSeek", "https://api.deepseek.com/v1/models"),
        ("OpenRouter", "https://openrouter.ai/api/v1/models"),
    ]
    results: list[str] = []
    async with httpx.AsyncClient(timeout=5.0) as client:
        for name, url in endpoints:
            try:
                resp = await client.get(url)
                results.append(f"{name}: {resp.status_code}")
            except Exception as e:
                results.append(f"{name}: unreachable ({type(e).__name__})")
    reachable = sum(1 for r in results if "unreachable" not in r)
    duration_ms = (time.monotonic() - t0) * 1000
    if reachable >= 1:
        return CheckResult("Network", CheckStatus.PASS,
                           detail=", ".join(results),
                           duration_ms=duration_ms)
    return CheckResult("Network", CheckStatus.WARN,
                       detail=", ".join(results),
                       suggestion="Check your internet connection or proxy settings",
                       duration_ms=duration_ms)


async def _check_api_connectivity(config_path: Path) -> CheckResult:
    """Test the configured provider's API with a minimal request."""
    t0 = time.monotonic()
    try:
        from nanobot.config.loader import load_config, set_config_path
        set_config_path(config_path)
        config = load_config(config_path)
    except Exception as e:
        return CheckResult("API connectivity", CheckStatus.SKIP,
                           detail=f"Config load failed: {e}",
                           duration_ms=0)
    try:
        from nanobot.providers.factory import make_provider
        provider = make_provider(config)
    except ValueError as e:
        return CheckResult("API connectivity", CheckStatus.FAIL,
                           detail=f"Cannot create provider: {e}",
                           suggestion="Check your API key and model configuration",
                           duration_ms=(time.monotonic() - t0) * 1000)
    except Exception as e:
        return CheckResult("API connectivity", CheckStatus.WARN,
                           detail=f"Provider init warning: {e}",
                           duration_ms=(time.monotonic() - t0) * 1000)
    try:
        resolved = config.resolve_preset()
        model = resolved.model
        # Send a minimal test request — just list models or a tiny completion
        test_messages = [{"role": "user", "content": "hi"}]
        response = await asyncio.wait_for(
            provider.chat_with_retry(messages=test_messages, model=model, max_tokens=5),
            timeout=15.0,
        )
        content = (response.content or "")[:80]
        duration_ms = (time.monotonic() - t0) * 1000
        if response.finish_reason == "error":
            return CheckResult("API connectivity", CheckStatus.FAIL,
                               detail=f"Model error: {content}",
                               suggestion="Check your API key validity and model name",
                               duration_ms=duration_ms)
        return CheckResult("API connectivity", CheckStatus.PASS,
                           detail=f"Model `{model}` responded in {duration_ms:.0f}ms",
                           duration_ms=duration_ms)
    except asyncio.TimeoutError:
        return CheckResult("API connectivity", CheckStatus.FAIL,
                           detail="Request timed out (15s)",
                           suggestion="Check network or try a different provider",
                           duration_ms=(time.monotonic() - t0) * 1000)
    except Exception as e:
        msg = str(e)[:120]
        return CheckResult("API connectivity", CheckStatus.FAIL,
                           detail=f"Request failed: {msg}",
                           suggestion="Verify your API key is valid and not expired",
                           duration_ms=(time.monotonic() - t0) * 1000)


async def _check_optional_deps() -> CheckResult:
    t0 = time.monotonic()
    missing: list[str] = []
    try:
        import aiohttp  # noqa: F401
    except ImportError:
        missing.append("aiohttp (API server)")
    try:
        import discord  # noqa: F401
    except ImportError:
        missing.append("discord.py (Discord channel)")
    try:
        import matrix_nio  # noqa: F401
    except ImportError:
        missing.append("matrix-nio (Matrix channel)")
    duration_ms = (time.monotonic() - t0) * 1000
    if not missing:
        return CheckResult("Optional dependencies", CheckStatus.PASS,
                           detail="All key optional packages available",
                           duration_ms=duration_ms)
    return CheckResult("Optional dependencies", CheckStatus.WARN,
                       detail=f"Missing: {', '.join(missing)}",
                       suggestion="Install with: pip install nanobot-ai[api,discord,matrix]",
                       duration_ms=duration_ms)


async def _check_memory_system(config_path: Path) -> CheckResult:
    t0 = time.monotonic()
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        ws_raw = data.get("agents", {}).get("defaults", {}).get("workspace", "~/.nanobot/workspace")
    except Exception:
        ws_raw = "~/.nanobot/workspace"
    ws_path = Path(ws_raw).expanduser().resolve()
    memory_file = ws_path / "memory" / "MEMORY.md"
    dream_file = ws_path / "memory" / ".dream_cursor"
    details: list[str] = []
    if memory_file.exists():
        size = memory_file.stat().st_size
        details.append(f"MEMORY.md: {size} bytes")
    else:
        details.append("MEMORY.md: not yet created")
    if dream_file.exists():
        details.append("Dream: initialized")
    else:
        details.append("Dream: not yet run")
    return CheckResult("Memory system", CheckStatus.PASS if memory_file.exists() else CheckStatus.WARN,
                       detail=", ".join(details),
                       suggestion="Memory initializes after first conversation" if not memory_file.exists() else "",
                       duration_ms=(time.monotonic() - t0) * 1000)


async def _check_file_permissions(config_path: Path) -> CheckResult:
    t0 = time.monotonic()
    try:
        st = config_path.stat()
        mode = st.st_mode & 0o777
        if mode <= 0o600:
            return CheckResult("Config permissions", CheckStatus.PASS,
                               detail=f"Secure: {oct(mode)}",
                               duration_ms=(time.monotonic() - t0) * 1000)
        return CheckResult("Config permissions", CheckStatus.WARN,
                           detail=f"Too permissive: {oct(mode)} (should be 600)",
                           suggestion=f"Run: chmod 600 {config_path}",
                           duration_ms=(time.monotonic() - t0) * 1000)
    except Exception as e:
        return CheckResult("Config permissions", CheckStatus.SKIP,
                           detail=str(e),
                           duration_ms=0)


async def run_doctor(config_path: Path | None = None) -> DoctorReport:
    """Run all diagnostic checks and return a report."""
    from nanobot.config.loader import get_config_path as _loader_get_config_path

    resolved = Path(config_path).expanduser().resolve() if config_path else _loader_get_config_path()
    report = DoctorReport()

    # Phase 1: local checks (no network needed)
    for check in [
        _check_python_version(),
        _check_config_exists(resolved),
    ]:
        report.results.append(await check)

    # Only proceed if config is readable
    if not resolved.exists():
        report.results.append(CheckResult("Further checks", CheckStatus.SKIP,
                                          detail="Config not found, stopping"))
        return report

    for check in [
        _check_file_permissions(resolved),
        _check_api_keys(resolved),
        _check_workspace(resolved),
        _check_optional_deps(),
        _check_memory_system(resolved),
    ]:
        report.results.append(await check)

    # Phase 2: network checks (only if keys exist)
    has_keys = any(r.status == CheckStatus.PASS for r in report.results if r.name == "API keys")
    if has_keys:
        report.results.append(await _check_network())
        report.results.append(await _check_api_connectivity(resolved))
    else:
        report.results.append(CheckResult("Network", CheckStatus.SKIP,
                                          detail="Skipped — no API keys configured"))
        report.results.append(CheckResult("API connectivity", CheckStatus.SKIP,
                                          detail="Skipped — no API keys configured"))

    return report


def print_report(report: DoctorReport, console: Console | None = None) -> None:
    """Print a formatted doctor report to the console."""
    c = console or Console()

    c.print()
    c.print(Panel.fit(
        f"[bold]🐈 nanobot v{__version__} — Health Check[/bold]",
        border_style="blue",
    ))

    tbl = Table(show_header=False, box=None, padding=(0, 2))
    tbl.add_column("Status", style="bold", width=3)
    tbl.add_column("Check", style="cyan")
    tbl.add_column("Detail")
    for r in report.results:
        icon = _status_icon(r.status)
        duration = f" [dim]({r.duration_ms:.0f}ms)[/dim]" if r.duration_ms > 10 else ""
        tbl.add_row(icon, r.name + duration, r.detail)
    c.print(tbl)

    # Print suggestions for warnings and failures
    issues = [r for r in report.results if r.status in (CheckStatus.WARN, CheckStatus.FAIL)]
    if issues:
        c.print()
        c.print("[bold]Suggestions:[/bold]")
        for r in issues:
            if r.suggestion:
                c.print(f"  {_status_icon(r.status)} [cyan]{r.name}[/cyan]: {r.suggestion}")

    # Summary
    c.print()
    if report.all_pass:
        c.print("[green]✓ All checks passed — nanobot is healthy![/green]")
    else:
        fails = report.fail_count
        warns = report.warn_count
        parts: list[str] = []
        if fails:
            parts.append(f"[red]{fails} failure(s)[/red]")
        if warns:
            parts.append(f"[yellow]{warns} warning(s)[/yellow]")
        c.print(f"Summary: {', '.join(parts)}")
        if fails:
            c.print("\n[dim]Run `nanobot onboard --wizard` to fix configuration issues.[/dim]")
    c.print()
