"""Terminal input and rendering helpers for the interactive CLI."""

from __future__ import annotations

import os
import select
import sys
from collections.abc import Callable
from contextlib import nullcontext, suppress
from typing import Any, Literal, cast

from loguru import logger
from prompt_toolkit import PromptSession, print_formatted_text
from prompt_toolkit.application import run_in_terminal
from prompt_toolkit.formatted_text import ANSI, HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.key_processor import KeyPressEvent
from prompt_toolkit.keys import Keys
from prompt_toolkit.patch_stdout import patch_stdout
from rich.console import Console
from rich.markdown import Markdown
from rich.text import Text

from nanobot import __logo__
from nanobot.bus.outbound_events import (
    ProgressEvent,
    RetryWaitEvent,
    outbound_event_from_message,
)
from nanobot.cli.stream import StreamRenderer, ThinkingSpinner
from nanobot.utils.helpers import sanitize_surrogates as _sanitize_surrogates

__all__ = [
    "_ReasoningBuffer",
    "_ensure_interactive_tty_mode",
    "_flush_cli_reasoning",
    "_flush_pending_tty_input",
    "_init_prompt_session",
    "_is_exit_command",
    "_maybe_print_interactive_progress",
    "_print_agent_response",
    "_print_cli_progress_line",
    "_print_cli_reasoning",
    "_print_interactive_response",
    "_read_interactive_input_async",
    "_restore_terminal",
]

console = Console()
EXIT_COMMANDS = {"exit", "quit", "/exit", "/quit", ":q"}
_REASONING_SENTENCE_ENDINGS = (".", "!", "?", "。", "！", "？")
_REASONING_FLUSH_CHARS = 60
_prompt_session: PromptSession[str] | None = None
_saved_term_attrs: list[Any] | None = None


def _ensure_interactive_tty_mode() -> None:
    """Restore interactive line input after a raw-mode TTY leak."""
    try:
        fd = sys.stdin.fileno()
        if not os.isatty(fd):
            return
    except Exception:
        return

    with suppress(Exception):
        import termios

        attrs = termios.tcgetattr(fd)
        required_lflag = termios.ISIG | termios.ICANON | termios.ECHO
        blocked_input_flags = getattr(termios, "IGNCR", 0) | getattr(termios, "INLCR", 0)
        if (
            (attrs[3] & required_lflag) == required_lflag
            and attrs[0] & termios.ICRNL
            and not attrs[0] & blocked_input_flags
        ):
            return
        attrs[0] = (attrs[0] | termios.ICRNL) & ~blocked_input_flags
        attrs[3] |= required_lflag
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        termios.tcflush(fd, termios.TCIFLUSH)
        logger.debug("Restored foreground gateway TTY mode")


class SafeFileHistory(FileHistory):
    """FileHistory subclass that sanitizes surrogate characters on write.

    On Windows, special Unicode input (emoji, mixed-script) can produce
    surrogate characters that crash prompt_toolkit's file write.
    See issue #2846.
    """

    def store_string(self, string: str) -> None:
        super().store_string(_sanitize_surrogates(string))


def _flush_pending_tty_input() -> None:
    """Drop unread keypresses typed while the model was generating output."""
    try:
        fd = sys.stdin.fileno()
        if not os.isatty(fd):
            return
    except Exception:
        return

    with suppress(Exception):
        import termios

        termios.tcflush(fd, termios.TCIFLUSH)
        return

    with suppress(Exception):
        while True:
            ready, _, _ = select.select([fd], [], [], 0)
            if not ready:
                break
            if not os.read(fd, 4096):
                break


def _restore_terminal() -> None:
    """Restore terminal to its original state (echo, line buffering, etc.)."""
    if _saved_term_attrs is None:
        return
    with suppress(Exception):
        import termios

        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, _saved_term_attrs)


def _build_cli_key_bindings() -> KeyBindings:
    """Key bindings for the interactive prompt.

    Behaviour:
      * Enter       -> submit the current input (keeps the familiar
                       single-line Enter-to-send feel even though the buffer
                       is multiline-capable).
      * Alt+Enter   -> insert a newline for multi-line input.
      * Shift+Enter -> insert a newline on terminals that emit the CSI-u
                       (kitty / fixterms) keyboard-protocol encoding for it.
    """
    # prompt_toolkit does not recognize CSI-u, so register its Shift+Enter
    # sequence as a best-effort addition without overriding existing mappings.
    with suppress(Exception):
        from prompt_toolkit.input import ansi_escape_sequences as _aes

        _aes.ANSI_SEQUENCES.setdefault("\x1b[13;2u", Keys.ControlF3)

    kb = KeyBindings()

    @kb.add("enter")
    def _(event: KeyPressEvent) -> None:
        event.current_buffer.validate_and_handle()

    @kb.add("escape", "enter")  # Alt+Enter / Meta+Enter (ESC + CR, "\x1b\r")
    def _(event: KeyPressEvent) -> None:
        event.current_buffer.insert_text("\n")

    # LF-as-Enter terminals send Alt+Enter as ESC + LF rather than ESC + CR.
    @kb.add("escape", Keys.ControlJ)  # Alt+Enter on LF-as-Enter terminals
    def _(event: KeyPressEvent) -> None:
        event.current_buffer.insert_text("\n")

    @kb.add(Keys.ControlF3)  # Shift+Enter on CSI-u capable terminals
    def _(event: KeyPressEvent) -> None:
        event.current_buffer.insert_text("\n")

    return kb


def _init_prompt_session() -> None:
    """Create the prompt_toolkit session with persistent file history."""
    global _prompt_session, _saved_term_attrs

    # Save terminal state so we can restore it on exit
    with suppress(Exception):
        import termios

        _saved_term_attrs = termios.tcgetattr(sys.stdin.fileno())

    from nanobot.config.paths import get_cli_history_path

    history_file = get_cli_history_path()
    history_file.parent.mkdir(parents=True, exist_ok=True)

    _prompt_session = PromptSession(
        history=SafeFileHistory(str(history_file)),
        enable_open_in_editor=False,
        # Multiline-capable buffer; Enter still submits via the custom key
        # bindings, while Alt+Enter adds a newline.
        multiline=True,
        key_bindings=_build_cli_key_bindings(),
    )


def _make_console() -> Console:
    return Console(file=sys.stdout)


def _render_interactive_ansi(render_fn: Callable[[Console], None]) -> str:
    """Render Rich output to ANSI so prompt_toolkit can print it safely."""
    ansi_console = Console(
        force_terminal=sys.stdout.isatty(),
        color_system=cast(
            Literal["auto", "standard", "256", "truecolor", "windows"],
            console.color_system or "standard",
        ),
        width=console.width,
    )
    with ansi_console.capture() as capture:
        render_fn(ansi_console)
    return capture.get()


def _print_agent_response(
    response: str,
    render_markdown: bool,
    metadata: dict[str, Any] | None = None,
    show_header: bool = True,
) -> None:
    """Render assistant response with consistent terminal styling."""
    console = _make_console()
    content = response or ""
    body = _response_renderable(content, render_markdown, metadata)
    if show_header:
        console.print()
        console.print(f"[cyan]{__logo__} nanobot[/cyan]")
    console.print(body)
    console.print()


def _response_renderable(
    content: str, render_markdown: bool, metadata: dict[str, Any] | None = None
) -> Text | Markdown:
    """Render plain-text command output without markdown collapsing newlines."""
    if not render_markdown:
        return Text(content)
    if (metadata or {}).get("render_as") == "text":
        return Text(content)
    return Markdown(content)


async def _print_interactive_line(text: str) -> None:
    """Print async interactive updates with prompt_toolkit-safe Rich styling."""

    def _write() -> None:
        ansi = _render_interactive_ansi(lambda c: c.print(f"  [dim]↳ {text}[/dim]"))
        print_formatted_text(ANSI(ansi), end="")

    await run_in_terminal(_write)


async def _print_interactive_response(
    response: str,
    render_markdown: bool,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Print async interactive replies with prompt_toolkit-safe Rich styling."""

    def _write() -> None:
        content = response or ""

        def _render(target: Console) -> None:
            target.print()
            target.print(f"[cyan]{__logo__} nanobot[/cyan]")
            target.print(_response_renderable(content, render_markdown, metadata))
            target.print()

        ansi = _render_interactive_ansi(_render)
        print_formatted_text(ANSI(ansi), end="")

    await run_in_terminal(_write)


def _print_cli_progress_line(
    text: str,
    thinking: ThinkingSpinner | None,
    renderer: StreamRenderer | None = None,
) -> None:
    """Print a CLI progress line, pausing the spinner if needed."""
    if not text.strip():
        return
    target = renderer.console if renderer else console
    pause = renderer.pause_spinner() if renderer else (thinking.pause() if thinking else nullcontext())
    with pause:
        if renderer:
            renderer.ensure_header()
        target.print(f"  [dim]↳ {text}[/dim]")


class _ReasoningBuffer:
    def __init__(self) -> None:
        self._text = ""

    def add(self, text: str) -> str | None:
        if not text:
            return None
        self._text += text
        if self._should_flush(text):
            return self.flush()
        return None

    def flush(self) -> str | None:
        text = self._text.strip()
        self._text = ""
        return text or None

    def clear(self) -> None:
        self._text = ""

    def _should_flush(self, text: str) -> bool:
        stripped = text.rstrip()
        return (
            "\n" in text
            or stripped.endswith(_REASONING_SENTENCE_ENDINGS)
            or len(self._text) >= _REASONING_FLUSH_CHARS
        )


def _print_cli_reasoning(
    text: str,
    thinking: ThinkingSpinner | None,
    renderer: StreamRenderer | None = None,
) -> None:
    """Print reasoning/thinking content in a distinct style."""
    if not text.strip():
        return
    target = renderer.console if renderer else console
    pause = renderer.pause_spinner() if renderer else (thinking.pause() if thinking else nullcontext())
    with pause:
        if renderer:
            renderer.ensure_header()
        target.print(f"[dim italic]✻ {text}[/dim italic]")


def _flush_cli_reasoning(
    reasoning_buffer: _ReasoningBuffer,
    thinking: ThinkingSpinner | None,
    renderer: StreamRenderer | None = None,
) -> None:
    text = reasoning_buffer.flush()
    if text:
        _print_cli_reasoning(text, thinking, renderer)


async def _print_interactive_progress_line(
    text: str,
    thinking: ThinkingSpinner | None,
    renderer: StreamRenderer | None = None,
) -> None:
    """Print an interactive progress line, pausing the spinner if needed."""
    if not text.strip():
        return
    if renderer:
        with renderer.pause_spinner():
            renderer.ensure_header()
            renderer.console.print(f"  [dim]↳ {text}[/dim]")
    else:
        with thinking.pause() if thinking else nullcontext():
            await _print_interactive_line(text)


async def _maybe_print_interactive_progress(
    msg: Any,
    thinking: ThinkingSpinner | None,
    channels_config: Any,
    renderer: StreamRenderer | None = None,
    reasoning_buffer: _ReasoningBuffer | None = None,
) -> bool:
    event = outbound_event_from_message(msg)
    if isinstance(event, RetryWaitEvent):
        await _print_interactive_progress_line(msg.content, thinking, renderer)
        return True

    if not isinstance(event, ProgressEvent):
        return False

    reasoning_buffer = reasoning_buffer or _ReasoningBuffer()

    if event.reasoning_end:
        if channels_config and not channels_config.show_reasoning:
            reasoning_buffer.clear()
        else:
            _flush_cli_reasoning(reasoning_buffer, thinking, renderer)
        return True

    is_tool_hint = event.tool_hint
    is_reasoning = event.reasoning or event.reasoning_delta
    if is_reasoning:
        if channels_config and not channels_config.show_reasoning:
            reasoning_buffer.clear()
            return True
        text = reasoning_buffer.add(msg.content)
        if text:
            _print_cli_reasoning(text, thinking, renderer)
        return True
    if channels_config and is_tool_hint and not channels_config.send_tool_hints:
        return True
    if channels_config and not is_tool_hint and not channels_config.send_progress:
        return True

    await _print_interactive_progress_line(msg.content, thinking, renderer)
    return True


def _is_exit_command(command: str) -> bool:
    """Return True when input should end interactive chat."""
    return command.lower() in EXIT_COMMANDS


async def _read_interactive_input_async() -> str:
    """Read user input using prompt_toolkit (handles paste, history, display).

    prompt_toolkit natively handles:
    - Multiline paste (bracketed paste mode)
    - History navigation (up/down arrows)
    - Clean display (no ghost characters or artifacts)
    """
    if _prompt_session is None:
        raise RuntimeError("Call _init_prompt_session() first")
    try:
        with patch_stdout():
            return await _prompt_session.prompt_async(
                HTML("<b fg='ansiblue'>You:</b> "),
            )
    except EOFError as exc:
        raise KeyboardInterrupt from exc
