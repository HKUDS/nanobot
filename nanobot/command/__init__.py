from typing import TYPE_CHECKING, Callable

from nanobot.command.router import CommandContext, CommandRouter

if TYPE_CHECKING:
    from nanobot.command.application import register_builtin_commands


def __getattr__(name: str) -> Callable[[CommandRouter], None]:
    if name == "register_builtin_commands":
        from nanobot.command.application import register_builtin_commands

        globals()[name] = register_builtin_commands
        return register_builtin_commands
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["CommandContext", "CommandRouter", "register_builtin_commands"]
