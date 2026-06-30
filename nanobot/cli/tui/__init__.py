"""CLI TUI helpers for nanobot."""

from nanobot.cli.tui.activity import format_activity_rows
from nanobot.cli.tui.app import (
    CliTuiApp,
    build_key_bindings,
    build_prompt_message,
    build_rprompt,
    should_use_tui,
)
from nanobot.cli.tui.commands import slash_completion_filter
from nanobot.cli.tui.output import TuiOutput

__all__ = [
    "CliTuiApp",
    "TuiOutput",
    "build_key_bindings",
    "build_prompt_message",
    "build_rprompt",
    "format_activity_rows",
    "should_use_tui",
    "slash_completion_filter",
]
