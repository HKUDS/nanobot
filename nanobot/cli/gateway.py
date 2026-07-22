"""Typer commands for foreground and background gateway control."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import typer
from loguru import logger
from rich.console import Console

from nanobot.config.schema import Config
from nanobot.gateway import (
    GatewayRuntime,
    GatewayRuntimePaths,
    GatewayStartOptions,
    GatewayStatus,
)
from nanobot.gateway.service import (
    GatewayServiceInstaller,
    GatewayServiceOptions,
    GatewayServiceResult,
    ServiceManagerKind,
)
from nanobot.webui.build import BuildMode

RuntimeConfigLoader = Callable[[str | None, str | None], Config]
GatewayRunner = Callable[..., None]
GatewayRuntimeFactory = Callable[..., Any]
GatewayServiceFactory = Callable[[], Any]
WebUIBundlePreparer = Callable[[Config, BuildMode], None]


def create_gateway_app(
    *,
    console: Console,
    log_handler_id: int,
    load_runtime_config: RuntimeConfigLoader,
    run_gateway: GatewayRunner,
    runtime_factory: GatewayRuntimeFactory | None = None,
    service_factory: GatewayServiceFactory | None = None,
    prepare_webui_bundle: WebUIBundlePreparer | None = None,
) -> typer.Typer:
    gateway_app = typer.Typer(
        help="Start and manage the nanobot gateway.",
        invoke_without_command=True,
        no_args_is_help=False,
    )

    def configure_logging(verbose: bool) -> None:
        if not verbose:
            return
        logger.remove(log_handler_id)
        logger.add(
            sys.stderr,
            format=(
                "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
                "<level>{level: <5}</level> | "
                "<cyan>{extra[channel]}</cyan> | "
                "<level>{message}</level>"
            ),
            level="DEBUG",
            colorize=None,
            filter=lambda record: record["extra"].setdefault("channel", "-") or True,
        )

    def runtime_for_instance(*, workspace: str | None = None, config: str | None = None):
        if runtime_factory is not None:
            return runtime_factory(workspace=workspace, config=config)
        config_path = str(Path(config).expanduser().resolve(strict=False)) if config else None
        workspace_path = str(Path(workspace).expanduser().resolve(strict=False)) if workspace else None
        data_dir = Path(config_path).parent if config_path else None
        return GatewayRuntime(
            paths=GatewayRuntimePaths.for_instance(
                data_dir=data_dir,
                workspace=workspace_path,
                config_path=config_path,
            )
        )

    def service_installer():
        return service_factory() if service_factory is not None else GatewayServiceInstaller()

    def interactive_build_mode() -> BuildMode:
        # `nanobot gateway` is often launched by tests, supervisors, or service managers.
        # The higher-level `nanobot webui` command owns interactive first-run guidance.
        return "warn"

    def start_options(
        *,
        port: int | None,
        verbose: bool,
        workspace: str | None,
        config: str | None,
        loaded_config: Config | None = None,
    ) -> GatewayStartOptions:
        cfg = loaded_config or load_runtime_config(config, workspace)
        resolved_config = str(Path(config).expanduser().resolve()) if config else None
        resolved_workspace = str(Path(workspace).expanduser().resolve(strict=False)) if workspace else None
        return GatewayStartOptions(
            port=port if port is not None else cfg.gateway.port,
            verbose=verbose,
            workspace=resolved_workspace,
            config_path=resolved_config,
        )

    def print_status(status: GatewayStatus) -> None:
        console.print(f"Running: {'yes' if status.running else 'no'}")
        console.print(f"Reason: {status.reason}")
        if status.pid is not None:
            console.print(f"PID: {status.pid}")
        if status.port is not None:
            console.print(f"Port: {status.port}")
        if status.started_at is not None:
            console.print(f"Started At: {status.started_at}")
        console.print(f"State: {status.state_path}")
        console.print(f"Logs: {status.log_path}")

    def print_service_result(result: GatewayServiceResult) -> None:
        console.print(f"Manager: {result.manager}")
        if result.path is not None:
            console.print(f"Path: {result.path}")
        if result.commands:
            console.print("Commands:")
            for command in result.commands:
                console.print("  " + " ".join(command))
        if result.content is not None:
            console.print()
            console.print(result.content)

    @gateway_app.callback(invoke_without_command=True)
    def gateway(
        ctx: typer.Context,
        port: int | None = typer.Option(None, "--port", "-p", help="Gateway port"),
        workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
        verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
        config: str | None = typer.Option(None, "--config", "-c", help="Path to config file"),
        foreground: bool = typer.Option(False, "--foreground", help="Run in the foreground"),
        background: bool = typer.Option(False, "--background", help="Start as a background process"),
    ) -> None:
        """Start the nanobot gateway."""
        if ctx.invoked_subcommand is not None:
            return
        if foreground and background:
            console.print("[red]Error: --foreground and --background cannot be used together.[/red]")
            raise typer.Exit(1)
        if background:
            cfg = load_runtime_config(config, workspace)
            if prepare_webui_bundle is not None:
                prepare_webui_bundle(cfg, interactive_build_mode())
            runtime = runtime_for_instance(workspace=workspace, config=config)
            result = runtime.start_background(
                start_options(
                    port=port,
                    verbose=verbose,
                    workspace=workspace,
                    config=config,
                    loaded_config=cfg,
                )
            )
            if result.ok:
                console.print("[green]Gateway started in the background.[/green]")
                print_status(result.status)
                return
            console.print(f"[yellow]Gateway was not started: {result.message}[/yellow]")
            print_status(result.status)
            raise typer.Exit(1)

        configure_logging(verbose)
        cfg = load_runtime_config(config, workspace)
        run_gateway(cfg, port=port, webui_bundle_mode=interactive_build_mode())

    @gateway_app.command("status")
    def gateway_status(
        workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
        config: str | None = typer.Option(None, "--config", "-c", help="Path to config file"),
    ) -> None:
        """Show the background gateway status."""
        print_status(runtime_for_instance(workspace=workspace, config=config).status())

    @gateway_app.command("logs")
    def gateway_logs(
        tail: int = typer.Option(200, "--tail", help="Number of recent lines to show"),
        follow: bool = typer.Option(True, "--follow/--no-follow", help="Follow new log output"),
        workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
        config: str | None = typer.Option(None, "--config", "-c", help="Path to config file"),
    ) -> None:
        """Show background gateway logs."""
        runtime = runtime_for_instance(workspace=workspace, config=config)
        if follow:
            raise typer.Exit(runtime.follow_logs(tail=tail))
        lines = runtime.read_log_tail(tail=tail)
        if not lines:
            console.print("[dim]No gateway log output available yet.[/dim]")
            return
        for line in lines:
            console.print(line)

    @gateway_app.command("stop")
    def gateway_stop(
        timeout: int = typer.Option(20, "--timeout", help="Stop timeout in seconds"),
        workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
        config: str | None = typer.Option(None, "--config", "-c", help="Path to config file"),
    ) -> None:
        """Stop the background gateway."""
        result = runtime_for_instance(workspace=workspace, config=config).stop(timeout_s=timeout)
        if result.ok:
            console.print("[green]Gateway stopped.[/green]")
        else:
            console.print(f"[yellow]Gateway was not stopped: {result.message}[/yellow]")
        print_status(result.status)
        if not result.ok and result.message != "gateway_not_running":
            raise typer.Exit(1)

    @gateway_app.command("restart")
    def gateway_restart(
        port: int | None = typer.Option(None, "--port", "-p", help="Gateway port"),
        workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
        verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
        config: str | None = typer.Option(None, "--config", "-c", help="Path to config file"),
        timeout: int = typer.Option(20, "--timeout", help="Restart timeout in seconds"),
    ) -> None:
        """Restart the background gateway."""
        cfg = load_runtime_config(config, workspace)
        if prepare_webui_bundle is not None:
            prepare_webui_bundle(cfg, interactive_build_mode())
        runtime = runtime_for_instance(workspace=workspace, config=config)
        result = runtime.restart(
            start_options(
                port=port,
                verbose=verbose,
                workspace=workspace,
                config=config,
                loaded_config=cfg,
            ),
            timeout_s=timeout,
        )
        if result.ok:
            console.print("[green]Gateway restarted in the background.[/green]")
            print_status(result.status)
            return
        console.print(f"[red]Gateway restart failed: {result.message}[/red]")
        print_status(result.status)
        raise typer.Exit(1)

    @gateway_app.command("install-service")
    def gateway_install_service(
        port: int | None = typer.Option(None, "--port", "-p", help="Gateway port"),
        workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
        verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
        config: str | None = typer.Option(None, "--config", "-c", help="Path to config file"),
        name: str = typer.Option("nanobot-gateway", "--name", help="Service name"),
        manager: ServiceManagerKind = typer.Option("auto", "--manager", help="auto, systemd, or launchd"),
        enable: bool = typer.Option(True, "--enable/--no-enable", help="Enable the service after writing it"),
        start_now: bool = typer.Option(True, "--start/--no-start", help="Start the service after writing it"),
        dry_run: bool = typer.Option(False, "--dry-run", help="Print generated service without installing"),
    ) -> None:
        """Install a systemd user service or macOS LaunchAgent for the gateway."""
        options = GatewayServiceOptions(
            start=start_options(port=port, verbose=verbose, workspace=workspace, config=config),
            name=name,
            manager=manager,
            enable=enable,
            start_now=start_now,
        )
        try:
            result = service_installer().install(options, dry_run=dry_run)
        except subprocess.CalledProcessError as exc:
            console.print(f"[red]Service install failed while running: {' '.join(exc.cmd)}[/red]")
            raise typer.Exit(exc.returncode or 1) from exc
        except OSError as exc:
            console.print(f"[red]Service install failed: {exc}[/red]")
            raise typer.Exit(1) from exc
        if result.ok:
            console.print("[green]Gateway service installed.[/green]" if not dry_run else "[green]Gateway service dry run.[/green]")
            print_service_result(result)
            return
        console.print(f"[red]Gateway service was not installed: {result.message}[/red]")
        print_service_result(result)
        raise typer.Exit(1)

    @gateway_app.command("uninstall-service")
    def gateway_uninstall_service(
        name: str = typer.Option("nanobot-gateway", "--name", help="Service name"),
        manager: ServiceManagerKind = typer.Option("auto", "--manager", help="auto, systemd, or launchd"),
        dry_run: bool = typer.Option(False, "--dry-run", help="Print actions without uninstalling"),
    ) -> None:
        """Uninstall the system gateway service."""
        try:
            result = service_installer().uninstall(name=name, manager=manager, dry_run=dry_run)
        except subprocess.CalledProcessError as exc:
            console.print(f"[red]Service uninstall failed while running: {' '.join(exc.cmd)}[/red]")
            raise typer.Exit(exc.returncode or 1) from exc
        except OSError as exc:
            console.print(f"[red]Service uninstall failed: {exc}[/red]")
            raise typer.Exit(1) from exc
        if result.ok:
            console.print("[green]Gateway service uninstalled.[/green]" if not dry_run else "[green]Gateway service uninstall dry run.[/green]")
            print_service_result(result)
            return
        console.print(f"[red]Gateway service was not uninstalled: {result.message}[/red]")
        print_service_result(result)
        raise typer.Exit(1)

    return gateway_app
