"""GeoClaw CLI entrypoints."""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from rich.console import Console

from geoclaw import __logo__, __version__
from geoclaw.runtime import GeoClawLoop, sync_geoclaw_skills

app = typer.Typer(
    name="geoclaw",
    help=f"{__logo__} GeoClaw - geospatial workflow agent built on nanobot",
    no_args_is_help=True,
)
console = Console()


@app.callback()
def main() -> None:
    """GeoClaw commands."""


@app.command()
def sync_skills(
    workspace: str | None = typer.Option(
        None, "--workspace", "-w", help="Workspace directory to sync packaged skills into"
    ),
):
    """Copy packaged GeoClaw skills into the target workspace."""
    from nanobot.config.paths import get_workspace_path

    workspace_path = get_workspace_path(workspace)
    sync_geoclaw_skills(workspace_path)
    console.print(f"[green]Synced GeoClaw skills to[/green] {workspace_path / 'skills'}")


@app.command()
def agent(
    message: str = typer.Option(..., "--message", "-m", help="Message to send to GeoClaw"),
    session_id: str = typer.Option("cli:direct", "--session", "-s", help="Session ID"),
    workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
    config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
    markdown: bool = typer.Option(True, "--markdown/--no-markdown", help="Render markdown output"),
):
    """Run a single GeoClaw request through nanobot runtime + geospatial tools."""
    from rich.markdown import Markdown

    from nanobot.bus.queue import MessageBus
    from nanobot.cli.commands import _load_runtime_config, _make_provider
    from nanobot.config.paths import get_cron_dir
    from nanobot.cron.service import CronService

    loaded = _load_runtime_config(config, workspace)
    sync_geoclaw_skills(loaded.workspace_path)

    bus = MessageBus()
    provider = _make_provider(loaded)
    cron = CronService(get_cron_dir() / "jobs.json")
    loop = GeoClawLoop(
        bus=bus,
        provider=provider,
        workspace=loaded.workspace_path,
        model=loaded.agents.defaults.model,
        max_iterations=loaded.agents.defaults.max_tool_iterations,
        context_window_tokens=loaded.agents.defaults.context_window_tokens,
        web_search_config=loaded.tools.web.search,
        web_proxy=loaded.tools.web.proxy or None,
        exec_config=loaded.tools.exec,
        cron_service=cron,
        restrict_to_workspace=loaded.tools.restrict_to_workspace,
        mcp_servers=loaded.tools.mcp_servers,
        channels_config=loaded.channels,
    )

    async def _run_once() -> str:
        try:
            return await loop.process_direct(message, session_key=session_id)
        finally:
            await loop.close_mcp()

    console.print(f"[cyan]{__logo__} GeoClaw v{__version__}[/cyan]")
    response = asyncio.run(_run_once())
    if markdown:
        console.print(Markdown(response))
    else:
        console.print(response)


if __name__ == "__main__":
    app()
