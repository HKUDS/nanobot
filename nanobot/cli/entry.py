"""Low-overhead console entrypoint for the native terminal client."""

from __future__ import annotations

import os
import sys
from contextlib import suppress

from nanobot.cli.process_identity import set_cli_process_identity


def _native_tui_candidate(args: list[str]) -> bool:
    """Return whether ``agent`` can start without the classic agent stack."""
    if not args or args[0] != "agent":
        return False
    for argument in args[1:]:
        if argument in {"--classic", "--no-tui", "-m", "--message"}:
            return False
        if argument.startswith("--message=") or (
            argument.startswith("-m") and not argument.startswith("--")
        ):
            return False
    return True


def _configure_windows_console() -> None:
    if sys.platform != "win32" or sys.stdout.encoding == "utf-8":
        return
    os.environ["PYTHONIOENCODING"] = "utf-8"
    with suppress(Exception):
        for stream in (sys.stdout, sys.stderr):
            reconfigure = getattr(stream, "reconfigure", None)
            if callable(reconfigure):
                reconfigure(encoding="utf-8", errors="replace")


def main() -> None:
    """Dispatch native TUI startup without importing the complete CLI graph."""
    set_cli_process_identity(sys.argv[1:])
    _configure_windows_console()
    if _native_tui_candidate(sys.argv[1:]):
        import typer

        from nanobot.cli.agent import agent

        fast_app = typer.Typer(add_completion=False)
        fast_app.command()(agent)
        command = typer.main.get_command(fast_app)
        command.main(args=sys.argv[2:], prog_name="nanobot agent")
        return

    from nanobot.cli.commands import app

    app()
