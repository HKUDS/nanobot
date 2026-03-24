"""Slash command routing and built-in handlers."""

from nanobot.command.builtin import register_builtin_commands
from nanobot.command.router import CommandContext, CommandRouter
from nanobot.command.team import register_team_commands

__all__ = [
    "CommandContext",
    "CommandRouter",
    "register_builtin_commands",
    "register_team_commands",
]
