"""CLI commands for nanobot — assembly module.

This module creates the top-level Typer ``app`` and registers all sub-commands
and sub-apps from the extracted CLI modules.  No business logic lives here.
"""

from __future__ import annotations

import sys

import typer

from nanobot import __logo__
from nanobot.cli._shared import (
    onboard as _onboard_impl,
)
from nanobot.cli._shared import (
    status as _status_impl,
)
from nanobot.cli._shared import version_callback
from nanobot.cli.agent import agent as _agent_impl
from nanobot.cli.channels import channels_app
from nanobot.cli.cron import cron_app
from nanobot.cli.gateway import gateway as _gateway_impl
from nanobot.cli.gateway import ui as _ui_impl
from nanobot.cli.memory import memory_app
from nanobot.cli.provider import provider_app
from nanobot.cli.routing import replay_deadletters, routing_app

app = typer.Typer(
    name="nanobot",
    help=f"{__logo__} nanobot - Personal AI Assistant",
    no_args_is_help=True,
)

# On Windows the default console encoding (cp1252) cannot render many Unicode
# characters the LLM emits (arrows, dashes, etc.).  Reconfigure stdout to
# UTF-8 so Rich can write them without a UnicodeEncodeError.
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:  # crash-barrier: non-standard stdout (e.g. pytest capture)
        pass


@app.callback()
def main(
    version: bool = typer.Option(None, "--version", "-v", callback=version_callback, is_eager=True),
) -> None:
    """nanobot - Personal AI Assistant."""
    pass


# ---------------------------------------------------------------------------
# Top-level commands
# ---------------------------------------------------------------------------


@app.command()
def onboard() -> None:
    """Initialize nanobot configuration and workspace."""
    _onboard_impl()


@app.command()
def status() -> None:
    """Show nanobot status."""
    _status_impl()


app.command()(_gateway_impl)
app.command()(_ui_impl)
app.command()(_agent_impl)

# ---------------------------------------------------------------------------
# Sub-apps
# ---------------------------------------------------------------------------

app.add_typer(channels_app, name="channels")
app.add_typer(cron_app, name="cron")
app.add_typer(routing_app, name="routing")
app.add_typer(memory_app, name="memory")
app.add_typer(provider_app, name="provider")

app.command("replay-deadletters")(replay_deadletters)

if __name__ == "__main__":
    app()
