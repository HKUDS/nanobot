"""Command palette helpers for the CLI TUI."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from prompt_toolkit.application import get_app
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.filters import Condition
from prompt_toolkit.lexers import Lexer

from nanobot.command.builtin import builtin_command_palette

_MAX_PALETTE_ROWS = 18
_COMMAND_WIDTH = 24
_MIN_DESCRIPTION_WIDTH = 28


def palette_entries() -> list[dict[str, Any]]:
    return builtin_command_palette()


def is_palette_prefix(text: str) -> bool:
    text = text.lstrip()
    return text.startswith("/") and " " not in text


def _active_buffer_text() -> str:
    try:
        return get_app().current_buffer.text
    except Exception:
        return ""


def slash_completion_filter() -> Condition:
    """True only while the buffer is a bare ``/command`` token.

    Wiring this as ``complete_while_typing`` makes prompt_toolkit reserve menu
    space (and pop the completion dropdown directly under the input) ONLY when
    choosing a slash command — so there is no permanent gap below the input the
    rest of the time. See ``PromptSession._get_default_buffer_control_height``.
    """
    return Condition(lambda: is_palette_prefix(_active_buffer_text()))


def entry_label(entry: Mapping[str, Any]) -> str:
    command = str(entry.get("command") or "")
    arg_hint = str(entry.get("arg_hint") or "")
    return f"{command} {arg_hint}".strip()


def entry_description(entry: Mapping[str, Any]) -> str:
    return str(entry.get("description") or entry.get("title") or "")


def filter_palette(prefix: str) -> list[dict[str, Any]]:
    needle = prefix.strip().lower()
    entries = palette_entries()
    if not needle or needle == "/":
        return entries
    return [
        entry
        for entry in entries
        if str(entry.get("command", "")).lower().startswith(needle)
        or needle in str(entry.get("title", "")).lower()
    ]


def known_commands() -> set[str]:
    """Recognized slash command tokens (lowercased), e.g. ``/new``, ``/model``."""
    return {
        str(entry.get("command") or "").lower()
        for entry in palette_entries()
        if entry.get("command")
    }


class SlashCommandLexer(Lexer):
    """Highlight the leading ``/command`` token once it matches a known command,
    the way Claude Code colors a recognized command in the input line."""

    def lex_document(self, document: Document):
        known = known_commands()
        lines = document.lines

        def get_line(lineno: int) -> list[tuple[str, str]]:
            text = lines[lineno]
            stripped = text.lstrip()
            if stripped.startswith("/"):
                token = stripped.split(" ", 1)[0]
                if token.lower() in known:
                    indent = text[: len(text) - len(stripped)]
                    rest = stripped[len(token) :]
                    fragments: list[tuple[str, str]] = []
                    if indent:
                        fragments.append(("", indent))
                    fragments.append(("class:slash-command", token))
                    if rest:
                        fragments.append(("", rest))
                    return fragments
            return [("", text)]

        return get_line


class SlashCommandCompleter(Completer):
    """Prompt-toolkit completer for slash commands."""

    def get_completions(self, document: Document, _complete_event):
        prefix = document.text_before_cursor.strip()
        if not prefix.startswith("/") or " " in prefix:
            return
        for entry in filter_palette(prefix):
            command = str(entry.get("command") or "")
            if not command:
                continue
            yield Completion(
                command,
                start_position=-len(prefix),
                display=entry_label(entry),
                display_meta=entry_description(entry),
            )


def _truncate(text: str, width: int) -> str:
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width <= 1:
        return "…"
    return f"{text[: width - 1]}…"


def command_palette_text(
    prefix: str,
    *,
    max_rows: int = _MAX_PALETTE_ROWS,
    width: int | None = None,
) -> str:
    """Return terminal-integrated slash command help text."""
    divider = ""
    description_width: int | None = None
    if width:
        divider = f"{'─' * max(8, width)}\n"
        description_width = max(_MIN_DESCRIPTION_WIDTH, width - _COMMAND_WIDTH - 2)

    text = prefix.strip()
    if not text.startswith("/"):
        return f"{divider}/ for commands"

    entries = filter_palette(text)
    if not entries:
        return f"{divider}No matching commands"

    rows: list[str] = []
    for entry in entries[:max_rows]:
        description = entry_description(entry)
        if description_width is not None:
            description = _truncate(description, description_width)
        rows.append(f"{entry_label(entry):<{_COMMAND_WIDTH}} {description}")
    if len(entries) > max_rows:
        rows.append(f"... {len(entries) - max_rows} more")
    body = "\n".join(rows)
    return f"{divider}{body}"
