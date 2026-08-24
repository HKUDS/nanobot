"""WebUI CLI command."""

from pathlib import Path

import typer
from pydantic import ValidationError
from rich.console import Console

from nanobot.cli import terminal as cli_terminal
from nanobot.cli.runtime_config import (
    _load_runtime_config,
    _print_config_error,
    _print_runtime_config_validation_error,
    _provider_setup_error,
)
from nanobot.cli.webui_support import (
    _attach_to_background_gateway,
    _confirm_webui_action,
    _ensure_local_webui_channel,
    _gateway_health_bind_note,
    _gateway_health_ready,
    _gateway_health_url,
    _gateway_instance_command,
    _host_for_local_browser,
    _load_webui_setup_config,
    _open_webui_browser,
    _prepare_webui_bundle_for_gateway,
    _print_foreground_port_conflict,
    _resolve_webui_config_path,
    _tcp_endpoint_reachable,
    _warn_webui_bind_scope,
    _webui_browser_url,
    _webui_build_mode_for_interactive,
    _webui_display_url,
    _webui_endpoint_reachable,
)
from nanobot.config.paths import get_workspace_path
from nanobot.utils.helpers import sync_workspace_templates
from nanobot.webui.dev import (
    WebUIDevError,
    WebUIDevServer,
    run_webui_dev_server,
    webui_dev_browser_url,
    webui_dev_proxy_target,
)

console = Console()


def _wait_with_existing_foreground_gateway(
    gateway_host: str,
    gateway_port: int,
    dev_server: WebUIDevServer,
) -> None:
    """Keep a Vite sidecar alive without taking ownership of an external gateway."""
    import time

    console.print(
        "[dim]Vite is attached to the existing foreground gateway. "
        "Press Ctrl+C to stop Vite; the gateway will keep running.[/dim]"
    )
    try:
        while True:
            dev_server.ensure_running()
            if not _gateway_health_ready(gateway_host, gateway_port):
                break
            time.sleep(0.5)
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopping the WebUI dev server.[/yellow]")


def webui(
    port: int | None = typer.Option(None, "--port", "-p", help="WebUI port"),
    gateway_port: int | None = typer.Option(
        None,
        "--gateway-port",
        help="Gateway health port",
    ),
    workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
    config: str | None = typer.Option(None, "--config", "-c", help="Path to config file"),
    background: bool = typer.Option(
        False,
        "--background",
        help="Deprecated; use `nanobot gateway --background`",
    ),
    dev: bool = typer.Option(
        False,
        "--dev",
        help="Run the Vite development server with live frontend updates",
    ),
    no_open: bool = typer.Option(False, "--no-open", help="Do not open a browser"),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Apply safe local WebUI defaults without prompting",
    ),
) -> None:
    """Prepare the local WebUI, start the gateway, and open the browser workbench."""
    from nanobot.config.loader import resolve_config_env_vars, save_config
    from nanobot.gateway import (
        GatewayClientLease,
        GatewayInstance,
        GatewayRuntime,
    )

    cli_terminal._ensure_interactive_tty_mode()
    config_path = _resolve_webui_config_path(config)
    if background:
        import shlex

        command = ["nanobot", "gateway", "--background", "--config", str(config_path)]
        if workspace:
            command.extend(
                ["--workspace", str(Path(workspace).expanduser().resolve(strict=False))]
            )
        console.print(
            "[red]`nanobot webui --background` no longer owns gateway lifecycle.[/red]"
        )
        console.print("Start the persistent gateway explicitly, then open the WebUI:")
        console.print("  [cyan]" + " ".join(shlex.quote(part) for part in command) + "[/cyan]")
        console.print(
            "  [cyan]nanobot webui --config " + shlex.quote(str(config_path)) + "[/cyan]"
        )
        raise typer.Exit(1)
    created_config = not config_path.exists()
    if created_config:
        console.print(f"[yellow]No config found at {config_path}.[/yellow]")
        _confirm_webui_action("Create a nanobot config and workspace now?", yes=yes)

    setup_config = _load_webui_setup_config(config_path)
    if workspace:
        setup_config.agents.defaults.workspace = workspace

    try:
        resolved_setup_config = resolve_config_env_vars(
            setup_config.model_copy(deep=True),
            config_path=config_path,
        )
    except ValueError as exc:
        _print_config_error(exc)
        raise typer.Exit(1) from exc

    provider_error = _provider_setup_error(resolved_setup_config)
    if provider_error:
        console.print(f"[yellow]Model setup is incomplete: {provider_error}[/yellow]")
        console.print("Configure a provider and model in WebUI Settings → Models.")

    try:
        changed_webui, generated_bootstrap_secret = _ensure_local_webui_channel(
            setup_config,
            port=port,
            yes=yes,
        )
        _warn_webui_bind_scope(setup_config)
        webui_url = _webui_browser_url(setup_config)
    except ValidationError as exc:
        retry_command = f'nanobot webui --config "{config_path}"'
        _print_runtime_config_validation_error(
            exc,
            config_path=config_path,
            summary="WebUI configuration is invalid.",
            path_prefix=("channels", "websocket"),
            retry_command=retry_command,
        )
        raise typer.Exit(1) from exc
    except ValueError as exc:
        console.print(f"[red]Error: invalid WebUI channel config: {exc}[/red]")
        raise typer.Exit(1) from exc

    if created_config or provider_error or changed_webui or workspace:
        save_config(setup_config, config_path)
        console.print(f"[green]✓[/green] Saved config: {config_path}")

    workspace_path = get_workspace_path(setup_config.workspace_path)
    workspace_path.mkdir(parents=True, exist_ok=True)
    sync_workspace_templates(workspace_path)

    runtime_config = _load_runtime_config(str(config_path), workspace)
    effective_gateway_port = gateway_port if gateway_port is not None else runtime_config.gateway.port

    dev_browser_url = webui_dev_browser_url(webui_url) if dev else None
    console.print()
    if dev_browser_url:
        console.print(f"WebUI dev: [cyan]{_webui_display_url(dev_browser_url)}[/cyan]")
        console.print(f"WebUI gateway: [cyan]{_webui_display_url(webui_url)}[/cyan]")
    else:
        console.print(f"WebUI: [cyan]{_webui_display_url(webui_url)}[/cyan]")
    gateway_health_url = _gateway_health_url(
        runtime_config.gateway.host,
        effective_gateway_port,
    )
    console.print(
        f"Gateway health: [cyan]{gateway_health_url}[/cyan]"
        f"{_gateway_health_bind_note(runtime_config.gateway.host)}"
    )
    if no_open:
        console.print("[dim]Browser opening disabled by --no-open.[/dim]")
        if generated_bootstrap_secret:
            console.print(
                "[yellow]A WebUI bootstrap secret was generated and saved in this config.[/yellow]"
            )
            console.print(
                "[dim]Open the WebUI and enter channels.websocket.tokenIssueSecret from "
                f"{config_path}, or rerun without --no-open to open the authenticated URL.[/dim]"
            )

    webui_bundle_mode = _webui_build_mode_for_interactive(yes=yes)
    _prepare_webui_bundle_for_gateway(
        runtime_config,
        mode="skip" if dev else webui_bundle_mode,
    )

    instance = GatewayInstance.resolve(
        config_path=config_path,
        workspace=workspace,
    )
    runtime = GatewayRuntime(paths=instance.paths)
    start_options = instance.start_options(port=effective_gateway_port)

    def ensure_shared_gateway(*, client_lease: GatewayClientLease) -> None:
        """Start or refresh the one managed gateway shared by local clients."""
        result = client_lease.ensure_on_demand_gateway(start_options)
        restarted = False
        restart_attempted = False
        if not result.ok and result.message == "gateway_already_running" and changed_webui:
            restart_attempted = True
            console.print("[yellow]WebUI config changed; restarting the background gateway.[/yellow]")
            result = runtime.restart(start_options, timeout_s=20)
            restarted = result.ok
        if not result.ok and (restart_attempted or result.message != "gateway_already_running"):
            action = "restarted" if restart_attempted else "started"
            console.print(f"[yellow]Gateway was not {action}: {result.message}[/yellow]")
            console.print(f"Logs: {result.status.log_path}")
            raise typer.Exit(1)
        if restarted:
            console.print("[green]Gateway restarted in the background.[/green]")
        elif result.ok:
            console.print("[green]Gateway started in the background.[/green]")
        else:
            console.print("[yellow]Gateway is already running in the background.[/yellow]")

    def print_shared_gateway_controls() -> None:
        console.print(
            "Manage this instance: "
            f"[cyan]{_gateway_instance_command('status', config_path=config_path, workspace=workspace)}[/cyan]"
        )
        console.print(
            "View logs: "
            f"[cyan]{_gateway_instance_command('logs', config_path=config_path, workspace=workspace)}[/cyan]"
        )
        console.print("[dim]Closing the browser does not stop channels or automations.[/dim]")
        console.print(
            "Stop nanobot: "
            f"[cyan]{_gateway_instance_command('stop', config_path=config_path, workspace=workspace)}[/cyan]"
        )

    gateway_ready = _gateway_health_ready(runtime_config.gateway.host, effective_gateway_port)
    webui_ready = _webui_endpoint_reachable(webui_url)
    if gateway_ready and webui_ready:
        lease = GatewayClientLease(runtime, kind="webui")
        lease.acquire()
        try:
            if changed_webui and runtime.status().running:
                ensure_shared_gateway(client_lease=lease)
                gateway_ready = _gateway_health_ready(
                    runtime_config.gateway.host,
                    effective_gateway_port,
                )
                webui_ready = _webui_endpoint_reachable(webui_url)
                if not gateway_ready or not webui_ready:
                    console.print("[red]Gateway did not become ready after the config update.[/red]")
                    raise typer.Exit(1)
            console.print(
                "[yellow]Gateway is already running; attaching to the existing WebUI.[/yellow]"
            )
            if not dev:
                console.print(
                    "Restart the gateway if you need it to pick up local source changes: "
                    f"[cyan]{_gateway_instance_command('restart', config_path=config_path, workspace=workspace)}[/cyan]"
                )
                if not no_open:
                    _open_webui_browser(webui_url, wait=False)
                if runtime.status().running:
                    _attach_to_background_gateway(runtime)
                else:
                    console.print(
                        "[yellow]This gateway is controlled by another foreground command. "
                        "Stop it from that terminal.[/yellow]"
                    )
                return

            try:
                assert dev_browser_url is not None
                with run_webui_dev_server(
                    target_url=webui_dev_proxy_target(webui_url),
                    browser_url=dev_browser_url,
                    output=lambda message: console.print(f"[green]✓[/green] {message}"),
                ) as dev_server:
                    if not no_open:
                        _open_webui_browser(dev_browser_url, wait=False)
                    if runtime.status().running:
                        _attach_to_background_gateway(
                            runtime,
                            poll_hook=dev_server.ensure_running,
                        )
                    else:
                        _wait_with_existing_foreground_gateway(
                            runtime_config.gateway.host,
                            effective_gateway_port,
                            dev_server,
                        )
            except WebUIDevError as exc:
                console.print(f"[red]Error: {exc}[/red]")
                raise typer.Exit(1) from exc
            return
        finally:
            lease.release(wait_for_stop=False)

    gateway_port_taken = gateway_ready or _tcp_endpoint_reachable(
        _host_for_local_browser(runtime_config.gateway.host),
        effective_gateway_port,
    )
    webui_port_taken = webui_ready
    if gateway_port_taken or webui_port_taken:
        _print_foreground_port_conflict(
            webui_url=webui_url,
            gateway_host=runtime_config.gateway.host,
            gateway_port=effective_gateway_port,
        )
        raise typer.Exit(1)

    lease = GatewayClientLease(runtime, kind="webui")
    lease.acquire()
    try:
        ensure_shared_gateway(client_lease=lease)
        print_shared_gateway_controls()
        if dev_browser_url:
            dev_proxy_target = webui_dev_proxy_target(webui_url)
            try:
                with run_webui_dev_server(
                    target_url=dev_proxy_target,
                    browser_url=dev_browser_url,
                    output=lambda message: console.print(f"[green]✓[/green] {message}"),
                ) as dev_server:
                    if not no_open:
                        _open_webui_browser(dev_browser_url)
                    _attach_to_background_gateway(
                        runtime,
                        poll_hook=dev_server.ensure_running,
                    )
            except WebUIDevError as exc:
                console.print(f"[red]Error: {exc}[/red]")
                raise typer.Exit(1) from exc
            return

        if not no_open:
            _open_webui_browser(webui_url)
        _attach_to_background_gateway(runtime)
    finally:
        lease.release(wait_for_stop=False)
