"""Shared WebUI setup, URL, health, and browser helpers."""

import os
import re
import secrets
import shutil
import sys
import time
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, BinaryIO, cast

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
    "_print_webui_ready",
    "_resolve_webui_config_path",
    "_start_gateway_log_cursor",
    "_tcp_endpoint_reachable",
    "_validate_gateway_startup",
    "_wait_for_webui",
    "_warn_webui_bind_scope",
    "_webui_browser_url",
    "webui_bootstrap_secret",
    "_webui_build_mode_for_interactive",
    "_webui_channel_enabled",
    "_webui_credentials_match",
    "_webui_display_url",
    "_webui_endpoint_reachable",
]

console = Console()

_TEXT_ONLY_BROWSERS = frozenset({"elinks", "links", "links2", "lynx", "w3m"})


def _launch_browser(url: str) -> bool:
    """Open *url* and request a foreground browser window."""
    if sys.platform == "darwin":
        return _launch_macos_browser(url)
    if sys.platform == "win32":
        from nanobot.cli.windows_browser import launch_browser

        return launch_browser(url)
    return _launch_unix_browser(url)


def _launch_unix_browser(url: str) -> bool:
    """Launch the selected Unix browser without exposing launcher diagnostics."""
    choices = [choice for choice in os.environ.get("BROWSER", "").split(os.pathsep) if choice]
    for choice in choices or [None]:
        try:
            browser = webbrowser.get(choice)
        except webbrowser.Error:
            continue
        if isinstance(browser, webbrowser.GenericBrowser):
            # gio, xdg-open, and BROWSER command templates inherit this class.
            # BackgroundBrowser.open only polls once and inherits our stderr.
            command = [browser.name, *(arg.replace("%s", url) for arg in browser.args)]
            sys.audit("webbrowser.open", url)
            if _launch_browser_command(command):
                return True
        elif browser.open(url, new=2, autoraise=True):
            # Native Unix controllers already isolate their subprocess output.
            return True
    return False


def _launch_browser_command(command: list[str]) -> bool:
    """Report an immediate launch failure while allowing a browser to stay open."""
    import subprocess
    import threading

    try:
        process = subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True,
        )
    except OSError:
        return False
    try:
        return process.wait(timeout=5) == 0
    except subprocess.TimeoutExpired:
        # A direct browser command can stay alive for the whole browsing session.
        threading.Thread(target=process.wait, daemon=True).start()
        return True


def _text_only_browser_name() -> str | None:
    """Return the configured text browser name when it cannot run the WebUI."""
    if sys.platform in {"darwin", "win32"}:
        return None

    try:
        browser = webbrowser.get()
    except webbrowser.Error:
        return None

    command = str(getattr(browser, "name", "") or "").strip()
    if not command:
        return None

    import shlex

    try:
        executable = Path(shlex.split(command)[0])
    except (IndexError, ValueError):
        return None

    names = {executable.name.lower()}
    resolved_executable = Path(shutil.which(str(executable)) or executable)
    try:
        names.add(resolved_executable.resolve(strict=False).name.lower())
    except OSError:
        pass
    return next((name for name in names if name in _TEXT_ONLY_BROWSERS), None)


def _launch_macos_browser(url: str) -> bool:
    """Deliver URLs through Launch Services, never a credential-bearing argv."""
    import ctypes

    try:
        foundation = ctypes.CDLL(
            "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
        )
        services = ctypes.CDLL("/System/Library/Frameworks/CoreServices.framework/CoreServices")
        foundation.CFURLCreateWithBytes.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32, ctypes.c_void_p,
        ]
        foundation.CFURLCreateWithBytes.restype = ctypes.c_void_p
        foundation.CFRelease.argtypes = [ctypes.c_void_p]
        foundation.CFRelease.restype = None
        services.LSOpenCFURLRef.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        services.LSOpenCFURLRef.restype = ctypes.c_int32
        encoded = url.encode("utf-8")
        url_ref = foundation.CFURLCreateWithBytes(None, encoded, len(encoded), 0x08000100, None)
        if not url_ref:
            return False
        try:
            # HTTP URLs reach the preferred browser in a GURL Apple event, not
            # through `open <url>` or a BROWSER command's process arguments.
            return services.LSOpenCFURLRef(url_ref, None) == 0
        finally:
            foundation.CFRelease(url_ref)
    except (OSError, AttributeError, UnicodeError):
        # Callers may display exception text. Keep URLs out of error output and
        # never retry with a subprocess/controller that can expose credentials.
        return False


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
                    f"If prompted, enter the WebUI password from "
                    f"channels.websocket.{secret_key} in {config_path}.",
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
    return str(ws_cfg.get("tokenIssueSecret") or "").strip() or str(ws_cfg.get("token") or "").strip()


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
    return url.split("#", 1)[0].rstrip("/")


def _ensure_local_webui_channel(
    config: Config,
    *,
    port: int | None,
    yes: bool,
) -> bool:
    """Enable the local WebUI channel with safe localhost defaults."""
    from nanobot.channels.websocket.runtime import WebSocketConfig
    from nanobot.config.loader import resolve_config_env_vars

    current: Any = getattr(config.channels, "websocket", None) or {}
    resolved = resolve_config_env_vars(config.model_copy(deep=True))
    model = WebSocketConfig.model_validate(getattr(resolved.channels, "websocket", None) or {})
    saved: dict[str, Any] = dict(current) if current else model.model_dump(by_alias=True, exclude_none=True)
    changed = False

    needs_enable = not model.enabled
    needs_port = port is not None and model.port != port
    needs_secret = not model.has_access_auth
    if current and not needs_enable and not needs_port and not needs_secret:
        return False

    _confirm_webui_action("Set up WebUI?", yes=yes)

    if not model.enabled:
        saved["enabled"] = True
        changed = True
    if port is not None and model.port != port:
        saved["port"] = port
        changed = True
    if needs_secret:
        saved.pop("token_issue_secret", None)
        saved.pop("token_issue_secret_generated", None)
        saved["tokenIssueSecret"] = secrets.token_urlsafe(32)
        saved["tokenIssueSecretGenerated"] = True
        if not model.websocket_requires_token:
            saved.pop("websocket_requires_token", None)
            saved["websocketRequiresToken"] = True
        changed = True

    setattr(config.channels, "websocket", saved)
    return changed or not current


def _warn_webui_bind_scope(config: Config) -> None:
    ws_cfg = _webui_config_dict(config)
    host = str(ws_cfg.get("host") or "127.0.0.1")
    if host in {"127.0.0.1", "localhost", "::1"}:
        return
    console.print(
        "[yellow]Warning: WebUI is configured to bind outside localhost. "
        "Keep access authentication configured and use this only on trusted networks.[/yellow]"
    )


def _wait_for_webui(url: str, *, timeout_s: float = 5.0) -> bool:
    """Return whether the WebUI listener becomes available within the timeout."""
    import time
    from urllib.parse import urlparse

    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if _tcp_endpoint_reachable(host, port, timeout_s=0.2):
            return True
        time.sleep(0.1)
    return False


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


def _webui_credentials_match(url: str, secret: str) -> bool:
    """Verify login before reusing a listener without this instance's runtime record."""
    from urllib.parse import urlsplit, urlunsplit

    import httpx

    from nanobot.webui.http_utils import webui_auth_headers

    parsed = urlsplit(url)
    bootstrap_url = urlunsplit((parsed.scheme, parsed.netloc, "/webui/bootstrap", "", ""))
    try:
        response = httpx.get(
            bootstrap_url, headers=webui_auth_headers(secret), timeout=2,
            trust_env=False, follow_redirects=False,
        )
        if response.status_code != 200:
            return False
        payload = response.json()
        return isinstance(payload, dict) and bool(cast(dict[str, Any], payload).get("api_token"))
    except (httpx.HTTPError, ValueError):
        return False


def _print_foreground_port_conflict(
    *,
    webui_url: str,
    gateway_host: str,
    gateway_port: int,
) -> None:
    console.print("[red]Cannot open this WebUI: the address is already in use.[/red]")
    console.print()
    console.print(Text(f"Page: {_webui_display_url(webui_url)}", style="cyan"), soft_wrap=True)
    console.print(
        Text(f"Service: {_gateway_health_url(gateway_host, gateway_port)}", style="dim"),
        soft_wrap=True,
    )
    console.print()
    console.print("Stop the existing instance from the terminal where you started it.")
    console.print(
        "To run another instance, choose unused ports with "
        "[cyan]--port[/cyan] and [cyan]--gateway-port[/cyan]."
    )


def _open_webui_browser(url: str, *, wait: bool = True) -> bool:
    """Request a browser launch; the printed login link remains the fallback."""
    if wait:
        _wait_for_webui(url)
    text_browser = _text_only_browser_name()
    if text_browser:
        console.print(
            f"[yellow]The configured browser ({escape(text_browser)}) cannot run the WebUI "
            "because it does not support JavaScript.[/yellow]"
        )
        return False
    try:
        if _launch_browser(url):
            return True
    except Exception:
        pass
    console.print(
        "[yellow]Could not open a browser automatically. Open the link above.[/yellow]"
    )
    return False


def _print_webui_ready(
    config: Config,
    config_path: Path,
    url: str,
    *,
    workspace: str | None,
    dev: bool,
    managed: bool,
    provider_error: str | None = None,
) -> None:
    """Show one ready state and a complete browser handoff in the local terminal."""
    ws_cfg = _webui_config_dict(config)
    console.print()
    console.print("[bold green]WebUI ready[/bold green]" + (" [dim](development)[/dim]" if dev else ""))
    console.print()
    console.print("Open in your browser:")
    if webui_bootstrap_secret(config):
        # Terminal wrapping keeps this one copyable line, including in narrow panes.
        console.print(url, style="cyan", markup=False, highlight=False, soft_wrap=True)
        console.print("[dim]This link signs you in. Do not share it.[/dim]")
        console.print(Text(f"Page: {_webui_display_url(url)}", style="dim"), soft_wrap=True)
    else:
        console.print(url, style="cyan", markup=False, highlight=False, soft_wrap=True)
        if ws_cfg.get("trustedProxyAuth"):
            console.print("Sign in through your configured trusted proxy.")
    if provider_error:
        console.print()
        console.print("[bold]Next step[/bold]")
        if config.get_provider_name():
            console.print(Text(f"Model setup is incomplete:\n{provider_error}", style="yellow"))
        console.print("Choose a provider and model:")
        console.print("WebUI Settings → Models.", style="bold")
    console.print()
    console.print(Text(f"Config: {config_path}", style="dim"), soft_wrap=True)
    console.print()
    log_command = _gateway_instance_command("logs", config_path=config_path, workspace=workspace)
    console.print(Text(f"Logs: {log_command}", style="dim"), soft_wrap=True)
    if managed:
        lifecycle = "Keep this terminal open while using WebUI.\n"
        lifecycle += "Ctrl+C stops development mode." if dev else "Press Ctrl+C to exit."
    else:
        lifecycle = "WebUI is already running. To stop it, use the terminal where it was started."
        if dev:
            lifecycle += "\nCtrl+C stops development mode."
    console.print()
    console.print(Text(lifecycle, style="dim"))
    console.print()


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
    log_cursor: _GatewayLogCursor | None = None,
    poll_hook: Callable[[], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Keep the launcher attached and surface new gateway warnings and errors."""
    status = runtime.status()
    log_path = status.log_path
    cursor = log_cursor or _start_gateway_log_cursor(log_path)
    show_detail = False

    def print_logs(*, flush: bool = False) -> None:
        nonlocal show_detail
        for line in _read_new_gateway_logs(log_path, cursor, flush=flush):
            # Full logs remain available through `nanobot gateway logs`.
            match = re.match(r"^\S+ \| (TRACE|DEBUG|INFO|SUCCESS|WARNING|ERROR|CRITICAL)\s+\|", line)
            if match:
                show_detail = match[1] in {"WARNING", "ERROR", "CRITICAL"}
            elif re.search(r"\b(?:\w*Warning:|WARNING:|ERROR:|CRITICAL:|Traceback \()", line):
                show_detail = True
            if not show_detail:
                continue
            style = "yellow" if match and match[1] == "WARNING" else None
            if match and match[1] in {"ERROR", "CRITICAL"}:
                style = "red"
            console.print(line, style=style, markup=False, highlight=False)

    try:
        while status.running:
            print_logs()
            if poll_hook is not None:
                poll_hook()
            sleep(0.5)
            status = runtime.status()
    except KeyboardInterrupt:
        print_logs(flush=True)
        console.print("\n[dim]WebUI launcher detached.[/dim]")
        return

    print_logs(flush=True)
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
