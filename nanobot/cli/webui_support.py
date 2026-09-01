"""Shared WebUI setup, URL, health, and browser helpers."""

import os
import subprocess
import sys
import time
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, BinaryIO

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.markup import escape
from rich.text import Text

from nanobot.cli.runtime_config import (
    _load_config_for_cli,
    _print_model_setup_steps,
    _print_runtime_config_validation_error,
    _provider_setup_error,
)
from nanobot.config.schema import Config
from nanobot.security.network import is_loopback_host
from nanobot.webui.build import (
    BuildMode,
    WebUIBuildError,
    ensure_webui_bundle,
    inspect_webui_bundle,
)

if TYPE_CHECKING:
    from nanobot.gateway.runtime import GatewayRuntime

__all__ = [
    "_attach_to_background_gateway",
    "_confirm_webui_action",
    "_ensure_local_webui_channel",
    "_gateway_health_bind_note",
    "_gateway_health_ready",
    "_gateway_health_url",
    "_gateway_instance_command",
    "_host_for_local_browser",
    "_load_webui_setup_config",
    "_launch_browser",
    "_open_webui_browser",
    "_prepare_webui_bundle_for_gateway",
    "_print_foreground_port_conflict",
    "_print_webui_foreground_lifecycle",
    "_resolve_webui_config_path",
    "_run_quick_start_for_webui",
    "_tcp_endpoint_reachable",
    "_validate_gateway_startup",
    "_warn_webui_bind_scope",
    "_webui_browser_url",
    "webui_bootstrap_secret",
    "_webui_build_mode_for_interactive",
    "_webui_channel_enabled",
    "_webui_display_url",
    "_webui_endpoint_reachable",
]

console = Console()


def _launch_browser(url: str) -> bool:
    """Open *url* and request a foreground browser window."""
    if sys.platform == "darwin":
        result = subprocess.run(
            ["open", url],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return result.returncode == 0
    return bool(webbrowser.open(url, new=2, autoraise=True))


def _confirm_webui_action(message: str, *, yes: bool) -> None:
    """Confirm a WebUI first-run mutation or fail clearly in non-interactive shells."""
    if yes:
        return
    if not _cli_can_prompt():
        console.print(
            "[red]Error: WebUI setup needs confirmation. Re-run with --yes or use "
            "`nanobot onboard --wizard`.[/red]"
        )
        raise typer.Exit(1)
    if not typer.confirm(message, default=True):
        console.print("[yellow]WebUI setup cancelled.[/yellow]")
        raise typer.Exit(1)


def _cli_can_prompt() -> bool:
    try:
        return sys.stdin.isatty()
    except Exception:
        return False


def _webui_build_mode_for_interactive(*, yes: bool = False) -> BuildMode:
    if yes:
        return "auto"
    return "prompt" if _cli_can_prompt() else "warn"


def _resolve_webui_config_path(config: str | None) -> Path:
    """Resolve the config path used by ``nanobot webui`` and bind loader state."""
    from nanobot.config.loader import get_config_path, set_config_path

    if not config:
        return get_config_path()
    config_path = Path(config).expanduser().resolve(strict=False)
    set_config_path(config_path)
    console.print(f"[dim]Using config: {config_path}[/dim]")
    return config_path


def _load_webui_setup_config(config_path: Path) -> Config:
    """Load config for first-run mutation without resolving env-var placeholders."""
    return _load_config_for_cli(config_path)


def _webui_config_dict(config: Config) -> dict[str, Any]:
    """Return the current WebSocket config as a mutable alias-key dictionary."""
    from nanobot.channels.websocket.runtime import WebSocketConfig

    current: Any = getattr(config.channels, "websocket", None) or {}
    model = WebSocketConfig.model_validate(current)
    return model.model_dump(by_alias=True, exclude_none=True)


def _webui_channel_enabled(config: Config) -> bool:
    from nanobot.channels.websocket.runtime import WebSocketConfig

    current: Any = getattr(config.channels, "websocket", None) or {}
    return bool(WebSocketConfig.model_validate(current).enabled)


def _validate_gateway_startup(config: Config) -> str | None:
    """Validate gateway startup and return a provider error recoverable through WebUI."""
    from nanobot.config.loader import get_config_path

    config_path = get_config_path()
    try:
        webui_config = _webui_config_dict(config)
    except ValidationError as exc:
        retry_command = f'nanobot gateway --config "{config_path}"'
        _print_runtime_config_validation_error(
            exc,
            config_path=config_path,
            summary="Gateway configuration is invalid.",
            path_prefix=("channels", "websocket"),
            retry_command=retry_command,
        )
        raise typer.Exit(1) from exc

    provider_error = _provider_setup_error(config)
    if not provider_error:
        return None

    if bool(webui_config["enabled"]):
        console.print(
            Text(f"Provider/model setup is incomplete: {provider_error}", style="yellow")
        )
        console.print(
            "Gateway will start so you can configure a provider and model "
            "in WebUI Settings → Models."
        )
        browser_url = _webui_browser_url(config)
        webui_url = browser_url.split("/#/", 1)[0]
        console.print(Text(f"WebUI: {webui_url}", style="cyan"))
        if browser_url != webui_url:
            secret_key = (
                "tokenIssueSecret"
                if str(webui_config.get("tokenIssueSecret") or "").strip()
                else "token"
            )
            console.print(
                Text(
                    f"If prompted, enter the configured channels.websocket.{secret_key} "
                    f"value (see {config_path}).",
                    style="dim",
                )
            )
        return provider_error

    console.print(Text(f"Gateway cannot start: {provider_error}", style="red"))
    console.print("Complete provider/model setup:")
    _print_model_setup_steps(config_path)
    raise typer.Exit(1)


def _prepare_webui_bundle_for_gateway(
    config: Config,
    *,
    mode: BuildMode,
    webui_static_dist: bool = True,
) -> None:
    """Refresh or warn about stale bundled WebUI assets before gateway startup."""
    if not webui_static_dist or not _webui_channel_enabled(config):
        return

    def _print(message: str) -> None:
        console.print(f"[yellow]{escape(message)}[/yellow]")

    def _confirm(message: str) -> bool:
        return typer.confirm(message, default=True)

    try:
        # Interactive WebUI commands keep source and bundle in lockstep.
        # Warn-only gateway startup must not block on a frontend build.
        if mode not in {"skip", "warn"} and inspect_webui_bundle().source_available:
            mode = "auto"
        ensure_webui_bundle(
            mode=mode,
            confirm=_confirm if mode == "prompt" else None,
            output=_print,
        )
    except WebUIBuildError as exc:
        if mode == "warn":
            console.print(f"[yellow]Warning: {escape(str(exc))}[/yellow]")
            return
        console.print(f"[red]Error: {escape(str(exc))}[/red]")
        raise typer.Exit(1) from exc


def _host_for_local_browser(host: str) -> str:
    """Map bind hosts to a browser-openable local host."""
    if host in {"0.0.0.0", ""}:
        return "127.0.0.1"
    if host == "::":
        return "[::1]"
    if ":" in host and not host.startswith("["):
        return f"[{host}]"
    return host


def _gateway_health_url(host: str, port: int) -> str:
    """Return a health URL that can be opened from this device."""
    return f"http://{_host_for_local_browser(host)}:{port}/health"


def _gateway_health_bind_note(host: str) -> str:
    """Describe a non-local bind without presenting it as a usable URL."""
    return "" if is_loopback_host(host) else f" [dim](listening on {host})[/dim]"


def webui_bootstrap_secret(config: Config) -> str:
    """Return the shared local bootstrap credential for WebUI protocol clients."""
    ws_cfg = _webui_config_dict(config)
    return str(ws_cfg.get("tokenIssueSecret") or ws_cfg.get("token") or "").strip()


def _webui_browser_url(config: Config) -> str:
    from urllib.parse import quote

    ws_cfg = _webui_config_dict(config)
    host = _host_for_local_browser(str(ws_cfg.get("host") or "127.0.0.1"))
    port = int(ws_cfg.get("port") or 8765)
    base_url = f"http://{host}:{port}"
    secret = webui_bootstrap_secret(config)
    if not secret:
        return base_url
    return f"{base_url}/#/?bootstrapSecret={quote(secret, safe='')}"


def _webui_display_url(url: str) -> str:
    marker = "bootstrapSecret="
    if marker not in url:
        return url
    prefix, _ = url.split(marker, 1)
    return f"{prefix}{marker}<redacted>"


def _ensure_local_webui_channel(
    config: Config,
    *,
    port: int | None,
    yes: bool,
) -> tuple[bool, bool]:
    """Enable the local WebUI channel with safe localhost defaults."""
    from nanobot.channels.websocket.runtime import WebSocketConfig

    current: Any = getattr(config.channels, "websocket", None) or {}
    model = WebSocketConfig.model_validate(current)
    changed = False
    generated_secret = False

    needs_enable = not model.enabled
    needs_port = port is not None and model.port != port
    needs_secret = not model.token_issue_secret.strip() and not model.token.strip()
    if not needs_enable and not needs_port and not needs_secret:
        return False, False

    target_port = port if port is not None else model.port
    console.print()
    console.print("[bold]Local WebUI setup[/bold]")
    console.print(f"  URL: [cyan]http://127.0.0.1:{target_port}[/cyan]")
    console.print("  Bind: [cyan]127.0.0.1 only[/cyan] (not exposed to your LAN)")
    console.print("  Auth: generated WebUI bootstrap secret stored in config")
    console.print(
        "  LAN access requires an explicit host change plus a WebUI password in config."
    )
    _confirm_webui_action("Update the local WebUI channel in this config?", yes=yes)

    if not model.enabled:
        model.enabled = True
        changed = True
    if model.host != "127.0.0.1":
        model.host = "127.0.0.1"
        changed = True
    if port is not None and model.port != port:
        model.port = port
        changed = True
    if not model.websocket_requires_token:
        model.websocket_requires_token = True
        changed = True
    if needs_secret:
        import secrets

        model.token_issue_secret = secrets.token_urlsafe(32)
        changed = True
        generated_secret = True

    setattr(config.channels, "websocket", model.model_dump(by_alias=True, exclude_none=True))
    return changed, generated_secret


def _warn_webui_bind_scope(config: Config) -> None:
    ws_cfg = _webui_config_dict(config)
    host = str(ws_cfg.get("host") or "127.0.0.1")
    if host in {"127.0.0.1", "localhost", "::1"}:
        return
    console.print(
        "[yellow]Warning: WebUI is configured to bind outside localhost. "
        "Keep tokenIssueSecret set and use this only on trusted networks.[/yellow]"
    )


def _wait_for_webui(url: str, *, timeout_s: float = 5.0) -> None:
    """Best-effort wait for the WebUI listener before opening a browser."""
    import time
    from urllib.parse import urlparse

    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if _tcp_endpoint_reachable(host, port, timeout_s=0.2):
            return
        time.sleep(0.1)


def _tcp_endpoint_reachable(host: str, port: int, *, timeout_s: float = 0.25) -> bool:
    """Return whether a local TCP endpoint accepts connections."""
    import socket

    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except OSError:
        return False


def _gateway_health_ready(host: str, port: int, *, timeout_s: float = 0.4) -> bool:
    """Return whether the nanobot gateway health endpoint responds OK."""
    import json
    import urllib.error
    import urllib.request

    browser_host = _host_for_local_browser(host)
    try:
        with urllib.request.urlopen(
            f"http://{browser_host}:{port}/health",
            timeout=timeout_s,
        ) as response:
            if response.status != 200:
                return False
            body = response.read(1024)
    except (OSError, urllib.error.URLError, TimeoutError, ValueError):
        return False

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    return payload.get("status") == "ok"


def _webui_endpoint_reachable(url: str, *, timeout_s: float = 0.25) -> bool:
    """Return whether the WebUI URL's TCP endpoint is already listening."""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return _tcp_endpoint_reachable(host, port, timeout_s=timeout_s)


def _print_foreground_port_conflict(
    *,
    webui_url: str,
    gateway_host: str,
    gateway_port: int,
) -> None:
    gateway_running = _gateway_health_ready(gateway_host, gateway_port)
    if gateway_running:
        console.print(
            "[yellow]A nanobot gateway is already running for this local instance.[/yellow]"
        )
    else:
        console.print(
            "[red]Error: nanobot cannot start because one of its local ports "
            "is already in use.[/red]"
        )
    console.print(f"  WebUI: [cyan]{_webui_display_url(webui_url)}[/cyan]")
    console.print(
        f"  Gateway health: "
        f"[cyan]http://{_host_for_local_browser(gateway_host)}:{gateway_port}/health[/cyan]"
    )
    console.print()
    if gateway_running:
        console.print("Use the existing instance, or stop it first:")
    else:
        console.print("If this is an existing nanobot instance, use it or stop it first:")
    console.print("  [cyan]nanobot gateway status[/cyan]")
    console.print("  [cyan]nanobot gateway stop[/cyan]")
    console.print(
        "Or choose different ports with [cyan]--port[/cyan] "
        "and [cyan]--gateway-port[/cyan]."
    )


def _open_webui_browser(url: str, *, wait: bool = True) -> None:
    """Open the WebUI in the user's default browser, with a copyable fallback."""
    if wait:
        _wait_for_webui(url)
    display_url = _webui_display_url(url)
    try:
        if _launch_browser(url):
            console.print(f"[green]✓[/green] Opened WebUI: [cyan]{display_url}[/cyan]")
        else:
            console.print(f"[yellow]Could not open browser; visit {display_url}[/yellow]")
    except Exception as exc:
        console.print(f"[yellow]Could not open browser ({exc}); visit {display_url}[/yellow]")


def _print_webui_foreground_lifecycle(*, attached: bool) -> None:
    """Explain how the browser and gateway lifecycles differ."""
    console.print()
    if attached:
        console.print("[green]WebUI is attached to the shared gateway.[/green]")
    else:
        console.print("[green]WebUI is attached to the shared gateway.[/green]")
    console.print("[dim]Closing the browser does not stop channels or automations.[/dim]")
    console.print(
        "[dim]Following live gateway logs. Press Ctrl+C to detach; the gateway stops "
        "only when the last local client exits.[/dim]"
    )


_LOG_ANCHOR_BYTES = 64


@dataclass
class _GatewayLogCursor:
    offset: int = 0
    identity: tuple[int, int] | None = None
    anchor: bytes = b""
    pending: bytes = b""


def _log_anchor(handle: BinaryIO, offset: int) -> bytes:
    size = min(offset, _LOG_ANCHOR_BYTES)
    handle.seek(offset - size)
    return handle.read(size)


def _start_gateway_log_cursor(log_path: Path) -> _GatewayLogCursor:
    """Start following at the current end of *log_path*."""
    try:
        with log_path.open("rb") as handle:
            stat = os.fstat(handle.fileno())
            offset = stat.st_size
            return _GatewayLogCursor(
                offset=offset,
                identity=(stat.st_dev, stat.st_ino),
                anchor=_log_anchor(handle, offset),
            )
    except OSError:
        return _GatewayLogCursor()


def _read_new_gateway_logs(
    log_path: Path,
    cursor: _GatewayLogCursor,
    *,
    flush: bool = False,
) -> list[str]:
    """Read complete gateway log lines appended after *cursor*."""
    try:
        with log_path.open("rb") as handle:
            stat = os.fstat(handle.fileno())
            identity = (stat.st_dev, stat.st_ino)
            reset = cursor.identity != identity or stat.st_size < cursor.offset
            if not reset and cursor.offset:
                reset = _log_anchor(handle, cursor.offset) != cursor.anchor
            if reset:
                cursor.offset = 0
                cursor.pending = b""

            handle.seek(cursor.offset)
            chunk = handle.read()
            cursor.offset = handle.tell()
            cursor.identity = identity
            cursor.anchor = _log_anchor(handle, cursor.offset)
    except OSError:
        return []

    parts = (cursor.pending + chunk).split(b"\n")
    cursor.pending = parts.pop()
    if flush and cursor.pending:
        parts.append(cursor.pending)
        cursor.pending = b""
    return [part.removesuffix(b"\r").decode("utf-8", errors="replace") for part in parts]


def _attach_to_background_gateway(
    runtime: "GatewayRuntime",
    *,
    poll_hook: Callable[[], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Keep the launcher attached and mirror this gateway's new log output."""
    status = runtime.status()
    log_path = status.log_path
    cursor = _start_gateway_log_cursor(log_path)
    _print_webui_foreground_lifecycle(attached=True)
    try:
        while status.running:
            for line in _read_new_gateway_logs(log_path, cursor):
                console.print(line, markup=False, highlight=False)
            if poll_hook is not None:
                poll_hook()
            sleep(0.5)
            status = runtime.status()
    except KeyboardInterrupt:
        for line in _read_new_gateway_logs(log_path, cursor, flush=True):
            console.print(line, markup=False, highlight=False)
        console.print("\n[yellow]WebUI launcher detached.[/yellow]")
        return

    for line in _read_new_gateway_logs(log_path, cursor, flush=True):
        console.print(line, markup=False, highlight=False)
    console.print("[yellow]Gateway stopped.[/yellow]")


def _gateway_instance_command(
    subcommand: str,
    *,
    config_path: Path,
    workspace: str | None,
) -> str:
    """Return a copyable gateway command for the same config/workspace instance."""
    import shlex

    parts = ["nanobot", "gateway", subcommand, "--config", str(config_path)]
    if workspace:
        workspace_path = str(Path(workspace).expanduser().resolve(strict=False))
        parts.extend(["--workspace", workspace_path])
    return " ".join(shlex.quote(part) for part in parts)


def _run_quick_start_for_webui(
    config: Config,
    *,
    yes: bool,
    config_path: Path,
) -> Config:
    """Offer the existing Quick Start flow when provider setup is missing."""
    if yes:
        console.print(
            "[red]Error: provider/model setup is incomplete, and --yes cannot answer "
            "provider credentials.[/red]"
        )
        console.print("Complete provider/model setup:")
        _print_model_setup_steps(config_path)
        raise typer.Exit(1)

    console.print()
    console.print("[yellow]Model provider setup is not ready.[/yellow]")
    console.print(
        "Quick Start will ask for provider, API key/base URL, model, and WebUI password."
    )
    _confirm_webui_action("Run Quick Start now?", yes=False)

    from nanobot.cli.onboard import run_quick_start_onboard

    try:
        result = run_quick_start_onboard(config)
    except RuntimeError as exc:
        console.print(f"[red]Error: {exc}[/red]")
        console.print(
            "[yellow]Run `nanobot onboard --wizard` "
            "after installing wizard dependencies.[/yellow]"
        )
        raise typer.Exit(1) from exc
    if not result.should_save:
        console.print("[yellow]Quick Start cancelled. No changes were saved.[/yellow]")
        raise typer.Exit(1)
    return result.config
