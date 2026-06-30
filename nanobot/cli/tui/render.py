"""Rich render helpers for the CLI TUI."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table
from rich.text import Text

from nanobot import __version__
from nanobot.cli.tui.state import CliTuiState


def render_startup(console: Console, state: CliTuiState) -> None:
    """Render the startup banner and current session status."""
    details = [
        Text.assemble(("nanobot", "bold cyan"), f" v{__version__}"),
        Text(str(state.model), style="bold"),
        Text(f"{state.preset or 'default'} • {state.access_mode} • {state.status}"),
        Text(str(state.workspace), style="dim"),
        Text(state.session_id, style="dim"),
    ]

    table = Table.grid(padding=(0, 1))
    table.add_column()
    for detail in details:
        table.add_row(detail)
    console.print(table)
    console.print(
        "[dim]/ for commands · esc interrupts a running turn · "
        "ctrl+o shows/hides reasoning · exit to quit[/dim]"
    )
    console.print("[dim]You can keep typing while the agent works — Enter queues a follow-up.[/dim]\n")
