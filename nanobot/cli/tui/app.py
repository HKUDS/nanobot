"""Lightweight prompt-toolkit/Rich TUI facade for `nanobot agent`.

The interactive surface is deliberately *inline* (like Claude Code): the input
line lives at the bottom of the normal terminal flow, output scrolls above it
in the native scrollback, and nothing takes over the alternate screen.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from pathlib import Path

from prompt_toolkit.application import get_app
from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings
from rich.console import Console

from nanobot.cli.tui.commands import is_palette_prefix
from nanobot.cli.tui.render import render_startup
from nanobot.cli.tui.state import CliTuiState

_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def should_use_tui(*, classic: bool, no_tui: bool) -> bool:
    """Return whether the inline TUI surface should be used."""
    if classic or no_tui:
        return False
    return bool(sys.stdin.isatty() and sys.stdout.isatty())


def _buffer_text() -> str:
    try:
        return get_app().current_buffer.text
    except Exception:
        return ""


def build_rprompt(state: CliTuiState) -> Callable[[], list[tuple[str, str]]]:
    """Right-prompt (on the input line, no gap). Idle shortcut hints only — live
    turn status is shown on its own line above the input by
    :func:`build_prompt_message`. Cleared while the slash dropdown is open."""

    def _rprompt() -> list[tuple[str, str]]:
        if state.turn_active or is_palette_prefix(_buffer_text()):
            return []
        reasoning = "on" if state.show_reasoning else "off"
        return [("class:toolbar-hint", f"/ cmds · ctrl+o reasoning {reasoning}")]

    return _rprompt


def build_prompt_message(
    state: CliTuiState,
    bot_name: str,
    *,
    width: Callable[[], int],
) -> Callable[[], list[tuple[str, str]]]:
    """The prompt's (multi-line) message. While a turn runs it prefixes a live
    ``✻ nanobot is thinking…`` line that sits at the bottom of the transcript,
    just above the input box; output scrolls in above it and it clears when the
    turn ends."""

    def _message() -> list[tuple[str, str]]:
        parts: list[tuple[str, str]] = []
        if state.turn_active:
            frame = _SPINNER_FRAMES[int(time.monotonic() * 10) % len(_SPINNER_FRAMES)]
            parts.append(
                (
                    "class:thinking",
                    f"{frame} {bot_name} · {state.status_label} "
                    f"({state.elapsed_seconds}s · esc to interrupt)\n",
                )
            )
        parts.append(("class:prompt-divider", f"{'─' * width()}\n"))
        parts.append(("class:prompt", "› "))
        return parts

    return _message


def build_key_bindings(
    state: CliTuiState,
    *,
    on_interrupt: Callable[[], None],
    on_toggle_reasoning: Callable[[], None],
) -> KeyBindings:
    """esc interrupts a running turn, ctrl+o toggles reasoning. The slash
    command dropdown (↑/↓ select, tab/enter accept) is prompt_toolkit's native
    completion menu, so it needs no custom bindings."""
    bindings = KeyBindings()
    turn_running = Condition(lambda: state.turn_active)

    # Not eager: a lone Escape fires after prompt_toolkit's escape-sequence
    # timeout, so arrow keys / history navigation keep working mid-turn.
    @bindings.add("escape", filter=turn_running)
    def _interrupt(_event) -> None:
        on_interrupt()

    @bindings.add("c-o")
    def _toggle_reasoning(_event) -> None:
        on_toggle_reasoning()

    return bindings


class CliTuiApp:
    """Owns the branded startup banner and the shared session state."""

    def __init__(
        self,
        *,
        console: Console,
        model: str,
        preset: str,
        workspace: Path,
        access_mode: str,
        session_id: str,
        show_logs: bool = False,
    ) -> None:
        self.state = CliTuiState(
            model=model,
            preset=preset,
            workspace=workspace,
            access_mode=access_mode,
            session_id=session_id,
            show_logs=show_logs,
        )
        self._console = console

    def render_startup(self) -> None:
        render_startup(self._console, self.state)
