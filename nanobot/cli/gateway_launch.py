"""Adapt terminal, WebUI bundle and Dock behavior to the Gateway application."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from pathlib import Path
from typing import TYPE_CHECKING, Any

import typer
from rich.console import Console

from nanobot.cli import terminal
from nanobot.cli.webui_support import (
    _gateway_health_bind_note,
    _gateway_health_url,
    _host_for_local_browser,
    _prepare_webui_bundle_for_gateway,
    _print_foreground_port_conflict,
    _tcp_endpoint_reachable,
    _webui_browser_url,
    _webui_channel_enabled,
    _webui_endpoint_reachable,
)
from nanobot.security.network import is_loopback_host

if TYPE_CHECKING:
    from nanobot.config.schema import Config
    from nanobot.gateway.runtime import GatewayInstance
    from nanobot.update_restart import GatewayStartup

console = Console()


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


def run_gateway(
    config: Config,
    *,
    port: int | None = None,
    verbose: bool = False,
    unconfigured_provider_error: str | None = None,
    gateway_instance: GatewayInstance | None = None,
    update_startup: "GatewayStartup | None" = None,
) -> None:
    # Administrative commands and --help never need the Agent or its providers.
    from nanobot.cli.dock import watch_gateway_icon
    from nanobot.gateway.application import GatewayPresentation, GatewayRunError
    from nanobot.gateway.application import run_gateway as run_application

    dock_url: str | None = None

    def check_ports(port: int) -> None:
        nonlocal dock_url
        webui_url = _webui_browser_url(config)
        host = config.gateway.host
        webui_enabled = _webui_channel_enabled(config)
        if (
            _tcp_endpoint_reachable(_host_for_local_browser(host), port)
            or (webui_enabled and _webui_endpoint_reachable(webui_url))
        ):
            _print_foreground_port_conflict(webui_url=webui_url, gateway_host=host, gateway_port=port)
            raise typer.Exit(1)
        dock_url = webui_url if webui_enabled else None

    def watch_dock(state_path: Path, activated: asyncio.Event) -> Coroutine[Any, Any, None] | None:
        if dock_url is None:
            return None
        return watch_gateway_icon(dock_url, instance=state_path, activated=activated)

    presentation = GatewayPresentation(
        check_ports=check_ports,
        prepare_webui=lambda: _prepare_webui_bundle_for_gateway(config, mode="warn"),
        prepare_terminal=terminal._ensure_interactive_tty_mode,  # pyright: ignore[reportPrivateUsage]
        report_health=_print_gateway_health_endpoint,
        watch_dock=watch_dock,
    )
    try:
        run_application(
            config, presentation=presentation, port=port, verbose=verbose,
            unconfigured_provider_error=unconfigured_provider_error, gateway_instance=gateway_instance,
            update_startup=update_startup,
        )
    except GatewayRunError as exc:
        raise typer.Exit(1) from exc
