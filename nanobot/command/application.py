"""The standard application's composed command registrations and display catalog."""

from __future__ import annotations

from nanobot.command.builtin import CHAT_UI_COMMAND_REPLACEMENTS, register_core_commands
from nanobot.command.builtin import build_help_text as build_registered_help_text
from nanobot.command.router import CommandRouter, normalize_command_text
from nanobot.command.spec import BuiltinCommandSpec
from nanobot.goal.command import register_goal_command


def register_builtin_commands(router: CommandRouter) -> None:
    """Register the standard application commands."""
    register_core_commands(router)
    register_goal_command(router)


def _builtin_specs() -> tuple[BuiltinCommandSpec, ...]:
    router = CommandRouter()
    register_builtin_commands(router)
    return router.specs


BUILTIN_COMMAND_SPECS = _builtin_specs()


def build_help_text(*, locale: object = None) -> str:
    return build_registered_help_text(BUILTIN_COMMAND_SPECS, locale=locale)


def builtin_command_palette() -> list[dict[str, str | bool]]:
    """Return structured command metadata for UI command palettes."""
    return [spec.as_dict() for spec in BUILTIN_COMMAND_SPECS if spec.command not in CHAT_UI_COMMAND_REPLACEMENTS]


def builtin_command_starts_agent_turn(text: str) -> bool:
    """Return whether WebUI ingress should expect a normal agent lifecycle."""
    normalized = normalize_command_text(text)
    command, separator, args = normalized.partition(" ")
    spec = next(
        (item for item in BUILTIN_COMMAND_SPECS if item.command == command.lower()),
        None,
    )
    if spec is None or (separator and not spec.accepts_args):
        return True
    if spec.lifecycle == "agent_turn":
        return True
    return spec.lifecycle == "agent_turn_with_args" and bool(args.strip())
