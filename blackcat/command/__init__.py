"""Slash command routing and built-in handlers."""

from blackcat.command.builtin import register_builtin_commands
from blackcat.command.router import CommandContext, CommandRouter

__all__ = ["CommandContext", "CommandRouter", "register_builtin_commands"]
