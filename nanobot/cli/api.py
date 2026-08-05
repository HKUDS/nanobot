"""Typer commands for reporting the OpenAI-compatible API server status."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from nanobot.api.runtime import ApiRuntime, api_runtime_paths
from nanobot.config.loader import get_config_path
from nanobot.config.schema import Config
from nanobot.process_runtime import ProcessStatus

RuntimeConfigLoader = Callable[[str | None, str | None], Config]
ApiRuntimeFactory = Callable[..., Any]


def create_api_app(
    *,
    console: Console,
    load_runtime_config: RuntimeConfigLoader,
    runtime_factory: ApiRuntimeFactory | None = None,
) -> typer.Typer:
    api_app = typer.Typer(
        help="Report the OpenAI-compatible API server status.",
        invoke_without_command=True,
        no_args_is_help=False,
    )

    def runtime_for_instance(*, config: str | None = None) -> ApiRuntime:
        if runtime_factory is not None:
            return runtime_factory(config=config)
        config_path = get_config_path()
        if config:
            config_path = Path(config).expanduser().resolve(strict=False)
        return ApiRuntime(paths=api_runtime_paths(config_path))

    def print_status(status: ProcessStatus, *, endpoint: str, config_path: Path) -> None:
        console.print(f"Running: {'yes' if status.running else 'no'}")
        console.print(f"Managed: {'yes' if status.managed else 'no'}")
        console.print(f"Reason: {status.reason}")
        console.print(f"Endpoint: {endpoint}")
        console.print(f"Config: {config_path}")
        if status.pid is not None:
            console.print(f"PID: {status.pid}")
        if status.port is not None:
            console.print(f"Port: {status.port}")
        if status.started_at is not None:
            console.print(f"Started At: {status.started_at}")
        console.print(f"State: {status.state_path}")
        console.print(f"Logs: {status.log_path}")

    @api_app.command("status")
    def api_status(
        config: str | None = typer.Option(None, "--config", "-c", help="Path to config file"),
    ) -> None:
        """Show the OpenAI-compatible API server status."""
        loaded = load_runtime_config(config, None)
        api_cfg = loaded.api
        connect_host = "127.0.0.1" if api_cfg.host in {"0.0.0.0", "::"} else api_cfg.host
        endpoint = f"http://{connect_host}:{api_cfg.port}/v1"
        display_config = Path(config).expanduser().resolve(strict=False) if config else get_config_path()
        status = runtime_for_instance(config=config).effective_status(
            host=connect_host,
            port=api_cfg.port,
        )
        print_status(status, endpoint=endpoint, config_path=display_config)

    return api_app
