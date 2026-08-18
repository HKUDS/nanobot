"""Agent CLI command."""

import sys

import typer
from rich.console import Console

from nanobot.cli.runtime_config import _load_runtime_config

console = Console()


def agent(
    message: str | None = typer.Option(None, "--message", "-m", help="Message to send to the agent"),
    session_id: str | None = typer.Option(None, "--session", "-s", help="Session ID"),
    workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
    config: str | None = typer.Option(None, "--config", "-c", help="Path to config file"),
    markdown: bool = typer.Option(
        True,
        "--markdown/--no-markdown",
        help="Render assistant output as Markdown",
    ),
    logs: bool = typer.Option(
        False,
        "--logs/--no-logs",
        help="Show nanobot runtime logs during chat",
    ),
    classic: bool = typer.Option(
        False,
        "--classic",
        help="Use the compatibility Python prompt instead of the terminal UI",
    ),
    theme: str = typer.Option(
        "auto",
        "--theme",
        help="Native terminal UI appearance: auto, dark, or light",
    ),
) -> None:
    """Chat in the terminal or send one message non-interactively."""
    runtime_config = _load_runtime_config(config, workspace)
    theme = theme.strip().lower()
    if theme not in {"auto", "dark", "light"}:
        raise typer.BadParameter("must be auto, dark, or light", param_hint="--theme")

    if message is None and not classic:
        from nanobot.cli.tui_launcher import TuiSessionError, TuiUnavailableError, launch_tui
        from nanobot.config.loader import get_config_path

        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise typer.BadParameter(
                "the native TUI requires an interactive terminal; use --message for "
                "one-shot input or --classic for the compatibility prompt",
                param_hint="terminal",
            )
        if not markdown:
            raise typer.BadParameter("--no-markdown requires --classic", param_hint="--no-markdown")
        if logs:
            raise typer.BadParameter("--logs requires --classic", param_hint="--logs")
        try:
            exit_code = launch_tui(
                runtime_config,
                config_path=get_config_path().resolve(strict=False),
                workspace_override=workspace,
                session_id=session_id,
                theme=theme,
            )
        except TuiSessionError as exc:
            raise typer.BadParameter(str(exc), param_hint="--session") from exc
        except TuiUnavailableError as exc:
            console.print(f"[red]Native TUI unavailable: {exc}[/red]")
            console.print(
                "[dim]Use `nanobot agent --classic` only if you want the compatibility prompt.[/dim]"
            )
            raise typer.Exit(1) from exc
        if exit_code:
            raise typer.Exit(exit_code)
        return

    from nanobot.cli.agent_runtime import run_local_agent

    run_local_agent(
        runtime_config,
        message=message,
        session_id=session_id or "cli:direct",
        markdown=markdown,
        logs=logs,
    )
