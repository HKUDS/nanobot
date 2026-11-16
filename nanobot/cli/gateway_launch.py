"""Adapt the CLI and desktop launch behavior to the Gateway application."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine, Iterator
from contextlib import suppress
from typing import TYPE_CHECKING, Any

import typer
from rich.console import Console

from nanobot.cli import terminal
from nanobot.cli.webui_support import (
    _gateway_health_bind_note,
    _gateway_health_url,
    _host_for_local_browser,
    _launch_browser,
    _prepare_webui_bundle_for_gateway,
    _print_foreground_port_conflict,
    _tcp_endpoint_reachable,
    _webui_browser_url,
    _webui_channel_enabled,
    _webui_display_url,
    _webui_endpoint_reachable,
)
from nanobot.security.network import is_loopback_host

if TYPE_CHECKING:
    from nanobot.config.schema import Config
    from nanobot.gateway.runtime import GatewayInstance
    from nanobot.update_restart import GatewayStartup
    from nanobot.webui.build import BuildMode
    from nanobot.webui.dev import WebUIDevServer

console = Console()


def _http_endpoint_responding(url: str, *, timeout_s: float = 0.25) -> bool:
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(url, timeout=timeout_s):
            return True
    except urllib.error.HTTPError:
        return True
    except (OSError, urllib.error.URLError, TimeoutError, ValueError):
        return False


async def _watch_webui_dev_server(
    server: WebUIDevServer,
    shutdown_event: asyncio.Event,
    *,
    poll_interval_s: float = 0.2,
) -> None:
    while not shutdown_event.is_set():
        await asyncio.sleep(poll_interval_s)
        if shutdown_event.is_set():
            return
        server.ensure_running()


def _print_gateway_health_endpoint(host: str, port: int) -> None:
    console.print(
        f"[green]✓[/green] Health endpoint: {_gateway_health_url(host, port)}"
        f"{_gateway_health_bind_note(host)}"
    )
    if is_loopback_host(host):
        return

    console.print(
        "[yellow]Warning: the unauthenticated health endpoint is listening beyond loopback "
        "and may be reachable from other devices. "
        f"Keep port {port} private or protect it with a firewall or reverse proxy.[/yellow]"
    )


async def _open_browser_when_ready(
    open_browser_url: str, open_browser_ready_url: str | None, host: str, port: int,
) -> None:
    from urllib.parse import urlparse

    # Channels start asynchronously. When the caller supplies a backend
    # readiness route, wait for an actual HTTP response rather than probing
    # the WebSocket listener with an incomplete TCP connection.
    if open_browser_ready_url:
        for _ in range(40):
            if await asyncio.to_thread(
                _http_endpoint_responding,
                open_browser_ready_url,
            ):
                break
            await asyncio.sleep(0.1)

    parsed = urlparse(open_browser_url)
    target_host = parsed.hostname or host or "127.0.0.1"
    target_port = parsed.port or port
    for _ in range(40):
        try:
            _reader, writer = await asyncio.open_connection(
                target_host,
                target_port,
            )
            writer.close()
            with suppress(Exception):
                await writer.wait_closed()
            break
        except OSError:
            await asyncio.sleep(0.1)
    display_url = _webui_display_url(open_browser_url)
    try:
        if _launch_browser(open_browser_url):
            console.print(f"[green]✓[/green] Opened browser at {display_url}")
        else:
            console.print(f"[yellow]Could not open browser; visit {display_url}[/yellow]")
    except Exception as e:
        console.print(f"[yellow]Could not open browser ({e}); visit {display_url}[/yellow]")


def run_gateway(
    config: Config,
    *,
    port: int | None = None,
    verbose: bool = False,
    open_browser_url: str | None = None,
    open_browser_ready_url: str | None = None,
    webui_static_dist: bool = True,
    webui_bundle_mode: BuildMode = "warn",
    webui_runtime_surface: str = "browser",
    webui_runtime_capabilities: dict[str, Any] | None = None,
    health_server_enabled: bool = True,
    unconfigured_provider_error: str | None = None,
    webui_dev_server: WebUIDevServer | None = None,
    gateway_instance: GatewayInstance | None = None,
    update_startup: "GatewayStartup | None" = None,
) -> None:
    # Administrative commands and --help never need the Agent or its providers.
    from nanobot.cli.dock import watch_gateway_icon
    from nanobot.gateway.application import GatewayPresentation, GatewayRunError
    from nanobot.gateway.application import run_gateway as run_application

    webui_url = ""

    def check_ports(port: int, health_enabled: bool) -> None:
        nonlocal webui_url
        webui_url = _webui_browser_url(config)
        host = config.gateway.host
        if (
            (health_enabled and _tcp_endpoint_reachable(_host_for_local_browser(host), port))
            or (_webui_channel_enabled(config) and _webui_endpoint_reachable(webui_url))
        ):
            _print_foreground_port_conflict(webui_url=webui_url, gateway_host=host, gateway_port=port)
            raise typer.Exit(1)

    def client_tasks(
        port: int, instance: GatewayInstance, activated: asyncio.Event, stop: asyncio.Event,
    ) -> Iterator[tuple[str, Coroutine[Any, Any, None]]]:
        if _webui_channel_enabled(config):
            yield "nanobot-dock", watch_gateway_icon(webui_url, instance=instance.paths.state_path, activated=activated)
        if open_browser_url:
            yield "nanobot-open-browser", _open_browser_when_ready(
                open_browser_url, open_browser_ready_url, config.gateway.host, port,
            )
        if webui_dev_server is not None:
            yield "nanobot-webui-dev-server", _watch_webui_dev_server(webui_dev_server, stop)

    presentation = GatewayPresentation(
        check_ports=check_ports,
        prepare_webui=lambda: _prepare_webui_bundle_for_gateway(
            config, mode=webui_bundle_mode, webui_static_dist=webui_static_dist,
        ),
        prepare_terminal=terminal._ensure_interactive_tty_mode,  # pyright: ignore[reportPrivateUsage]
        report_health=_print_gateway_health_endpoint,
        client_tasks=client_tasks,
    )
    try:
        run_application(
            config, presentation=presentation, port=port, verbose=verbose,
            webui_static_dist=webui_static_dist, webui_runtime_surface=webui_runtime_surface,
            webui_runtime_capabilities=webui_runtime_capabilities, health_server_enabled=health_server_enabled,
            unconfigured_provider_error=unconfigured_provider_error, gateway_instance=gateway_instance,
            update_startup=update_startup,
        )
    except GatewayRunError as exc:
        raise typer.Exit(1) from exc
