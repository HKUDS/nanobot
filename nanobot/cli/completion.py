"""Slash command auto-completion for prompt_toolkit."""

from __future__ import annotations

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nanobot.command.router import CommandRouter


class SlashCommandCompleter(Completer):
    """Dynamic completer that provides slash command suggestions.

    Suggests commands as the user types "/..." and shows the command
    description from the handler's docstring.
    """

    def __init__(self, router: CommandRouter) -> None:
        self._router = router

    def get_completions(self, document: Document, _) -> list[Completion]:
        """Return completions matching the current word being typed."""
        word = document.get_word_before_cursor()

        # Only show completions when word starts with slash
        if not word.startswith("/"):
            return []

        # Only show completions when slash is truly at line start
        # (no non-whitespace content before the first /)
        stripped = document.text_before_cursor.rstrip()
        if "/" in stripped:
            before_slash = stripped[:stripped.index("/")]
            if before_slash.strip() != "":
                # There is content before / → not at line start
                return []

        # Collect all registered commands
        commands: list[tuple[str, str]] = []

        # Priority commands (exact match)
        for cmd in self._router._priority:
            handler = self._router._priority[cmd]
            doc = handler.__doc__ or ""
            commands.append((cmd, doc.strip()))

        # Exact commands
        for cmd in self._router._exact:
            if cmd not in self._router._priority:
                handler = self._router._exact[cmd]
                doc = handler.__doc__ or ""
                commands.append((cmd, doc.strip()))

        # Prefix commands
        for pfx, handler in self._router._prefix:
            doc = handler.__doc__ or ""
            commands.append((pfx, doc.strip()))

        # Filter and create completions
        completions = []
        lower_word = word.lower()
        for cmd, description in commands:
            if cmd.lower().startswith(lower_word):
                # Provide the full command as completion
                completions.append(
                    Completion(
                        text=cmd,
                        start_position=-len(word),
                        display=cmd,
                        display_meta=description[:60] if description else "",
                    )
                )

        return completions


def attach_slash_completion(session: PromptSession, router: CommandRouter) -> None:
    """Attach slash command completion to a PromptSession."""
    completer = SlashCommandCompleter(router)
    session.completer = completer
