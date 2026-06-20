"""Prompt-safe output sink for the interactive CLI TUI.

While the persistent prompt is active, everything printed must go through
``run_in_terminal`` so prompt_toolkit can erase and redraw the input line.
This module owns that path: streamed answers are committed block-by-block
(markdown-rendered) above the prompt, while activity, reasoning, and
progress lines print as they arrive.
"""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from typing import Any

from prompt_toolkit import print_formatted_text
from prompt_toolkit.application import run_in_terminal
from prompt_toolkit.formatted_text import ANSI
from rich.console import Console
from rich.markdown import Markdown
from rich.markup import escape
from rich.padding import Padding
from rich.text import Text

from nanobot.cli.tui.activity import current_activity_name, format_activity_rows
from nanobot.cli.tui.state import CliTuiState

_REASONING_SENTENCE_ENDINGS = (".", "!", "?", "。", "！", "？")
_REASONING_FLUSH_CHARS = 60
_REASONING_DANGLING_WORD_CHARS = 2

_probe_console: Console | None = None


def _terminal_width() -> int:
    return max(20, shutil.get_terminal_size((80, 24)).columns)


def _color_system() -> str:
    global _probe_console
    if _probe_console is None:
        _probe_console = Console()
    return _probe_console.color_system or "standard"


def render_ansi(
    render: Callable[[Console], Any],
    *,
    color_system: str | None = None,
    width: int | None = None,
) -> str:
    """Render Rich output to an ANSI string prompt_toolkit can print safely."""
    capture = Console(
        force_terminal=sys.stdout.isatty(),
        color_system=color_system or _color_system(),
        width=width or _terminal_width(),
    )
    with capture.capture() as cap:
        render(capture)
    return cap.get()


def response_renderable(content: str, render_markdown: bool, metadata: Mapping | None = None):
    """Render plain-text command output without markdown collapsing newlines."""
    if not render_markdown or (metadata or {}).get("render_as") == "text":
        return Text(content)
    return Markdown(content)


def _terminal_theme() -> str:
    """Best-effort terminal theme, overridable with NANOBOT_TUI_THEME."""
    override = os.environ.get("NANOBOT_TUI_THEME", "").strip().lower()
    if override in {"light", "dark"}:
        return override
    value = os.environ.get("COLORFGBG", "")
    with suppress(ValueError, IndexError):
        return "light" if int(value.split(";")[-1]) >= 7 else "dark"
    # Unknown terminals should prefer the readable light-safe palette. Dark
    # terminals can opt into dark blocks with NANOBOT_TUI_THEME=dark.
    return "light"


def _message_styles() -> tuple[str, str, str, str]:
    """Return user, marker, assistant, and queued styles for the current terminal."""
    if _terminal_theme() == "light":
        user = "#0f172a on #e8f3ff"
        return user, "bold #0284c7 on #e8f3ff", "#111827 on #f3f4f6", "#0369a1 on #e8f3ff"
    user = "#dbeafe on #102033"
    return user, "bold #67e8f9 on #102033", "#e5e7eb on #15171a", "#93c5fd on #102033"


def _message_block(renderable: Any, style: str) -> Padding:
    """Return a subtle full-width block without adding a terminal-heavy border."""
    return Padding(renderable, (0, 1), style=style)


class ReasoningBuffer:
    """Batch reasoning deltas into readable sentence-sized chunks."""

    def __init__(self) -> None:
        self._text = ""

    def add(self, text: str) -> str | None:
        if not text:
            return None
        self._text += text
        if self._should_flush(text):
            return self._take_flushable()
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

    def _take_flushable(self) -> str | None:
        """Flush readable text while keeping tiny split words for the next delta."""
        flushable = self._text
        keep = ""
        candidate = self._text.rstrip()
        newline = candidate.rfind("\n")
        if newline >= 0:
            tail = candidate[newline + 1 :].strip()
            tail_word = tail.replace("'", "")
            if (
                0 < len(tail) <= _REASONING_DANGLING_WORD_CHARS
                and tail_word.isalpha()
            ):
                flushable = candidate[: newline + 1]
                keep = tail
        self._text = keep
        text = flushable.strip()
        return text or None


class MarkdownStreamBuffer:
    """Accumulate stream deltas and emit committed markdown blocks.

    Blocks split on blank lines outside fenced code so committed output
    renders stably; the unfinished tail stays buffered until ``flush()``.
    """

    def __init__(self) -> None:
        self._tail = ""

    def feed(self, delta: str) -> list[str]:
        if not delta:
            return []
        self._tail += delta
        blocks: list[str] = []
        while True:
            boundary = self._boundary(self._tail)
            if boundary is None:
                break
            block = self._tail[:boundary].rstrip("\n")
            self._tail = self._strip_leading_blank_lines(self._tail[boundary:])
            if block.strip():
                blocks.append(block)
        return blocks

    def flush(self) -> str | None:
        tail, self._tail = self._tail.strip("\n"), ""
        return tail if tail.strip() else None

    @staticmethod
    def _boundary(text: str) -> int | None:
        """Offset of the first blank line outside fenced code, after content."""
        last_newline = text.rfind("\n")
        if last_newline < 0:
            return None
        fence: str | None = None
        has_content = False
        pos = 0
        for line in text[: last_newline + 1].splitlines(keepends=True):
            stripped = line.strip()
            if fence is not None:
                if stripped.startswith(fence):
                    fence = None
            elif stripped.startswith("```") or stripped.startswith("~~~"):
                fence = stripped[:3]
            elif not stripped and has_content:
                return pos
            if stripped:
                has_content = True
            pos += len(line)
        return None

    @staticmethod
    def _strip_leading_blank_lines(text: str) -> str:
        while True:
            newline = text.find("\n")
            if newline < 0 or text[:newline].strip():
                return text
            text = text[newline + 1 :]


async def _emit_above_prompt(ansi: str) -> None:
    def _write() -> None:
        print_formatted_text(ANSI(ansi), end="")

    await run_in_terminal(_write)


class TuiOutput:
    """Single sink for everything the interactive TUI prints.

    The outbound consumer feeds every bus message into ``handle_outbound``;
    key bindings call ``toggle_reasoning``; the input loop calls
    ``start_user_turn`` when a fresh turn begins.
    """

    def __init__(
        self,
        state: CliTuiState,
        *,
        render_markdown: bool = True,
        bot_name: str = "nanobot",
        emit: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        self._state = state
        self._md = render_markdown
        self._bot_name = bot_name
        self._emit = emit or _emit_above_prompt
        self._stream = MarkdownStreamBuffer()
        self._reasoning = ReasoningBuffer()
        self._hidden_reasoning: list[str] = []
        self._header_printed = False

    async def _print(self, render: Callable[[Console], Any]) -> None:
        await self._emit(render_ansi(render))

    async def handle_outbound(self, msg: Any, channels_config: Any = None) -> None:
        """Render one outbound bus message above the prompt."""
        meta = msg.metadata or {}
        if meta.get("_stream_delta"):
            self._ensure_turn()
            self._state.note_responding()
            for block in self._stream.feed(msg.content or ""):
                await self._print_answer_block(block)
            return
        if meta.get("_stream_end"):
            tail = self._stream.flush()
            if tail:
                await self._print_answer_block(tail)
            if meta.get("_resuming"):
                self._state.note_thinking()
            return
        if meta.get("_streamed"):
            # Final message of a streamed turn — content already shown via deltas.
            self._end_turn()
            return
        if meta.get("cli_clear"):
            await self.clear_screen()
            self._end_turn()
            return
        if meta.get("cli_resume_session") is not None:
            # /resume and /fork switch which session subsequent input routes to.
            self._state.active_chat_id = str(meta["cli_resume_session"])
            await self.clear_screen()
            if msg.content:
                await self.print_response(msg.content, meta)
            else:
                self._end_turn()
            return
        if meta.get("_tool_events") or meta.get("_file_edit_events"):
            # Start-phase events only drive the live status line; the persistent
            # log shows the completed action + its result on a single cluster.
            self._ensure_turn()
            self._note_tool_activity(meta)
            rows = format_activity_rows(meta, include_start=False)
            if rows:
                await self._print_rows(rows)
            return
        if meta.get("_retry_wait"):
            await self.print_progress(msg.content or "")
            return
        if meta.get("_progress"):
            self._ensure_turn()
            await self._handle_progress(msg.content or "", meta, channels_config)
            return
        media = list(getattr(msg, "media", None) or [])
        if media:
            # Generated images / audio delivered via the message tool.
            await self.print_media(media)
        if msg.content:
            await self.print_response(msg.content, meta)
        else:
            # Empty sentinel, or media-only delivery.
            self._end_turn()

    async def print_media(self, media: list[str]) -> None:
        """Surface outbound media (paths) since the terminal can't inline them."""
        paths = [m for m in media if isinstance(m, str) and m]
        if not paths:
            return
        await self._ensure_header()

        def _render(c: Console) -> None:
            for path in paths:
                name = path.rsplit("/", 1)[-1]
                c.print(
                    f"  [magenta]🖼 {escape(name)}[/magenta]  [dim]{escape(path)}[/dim]"
                )

        await self._print(_render)

    async def print_user_input(self, content: str) -> None:
        """Render the submitted user input after prompt_toolkit erases the edit line."""
        text = content.strip()
        if not text:
            return
        user_style, marker_style, _assistant_style, _queued_style = _message_styles()
        body = Text.assemble(
            ("› ", marker_style),
            (text, user_style),
        )
        await self._print(lambda c: c.print(_message_block(body, user_style)))

    async def print_response(self, content: str, metadata: Mapping | None = None) -> None:
        tail = self._stream.flush()
        if tail:
            await self._print_answer_block(tail)
        await self._ensure_header()
        body = response_renderable(content, self._md, metadata)
        _user_style, _marker_style, assistant_style, _queued_style = _message_styles()
        await self._print(lambda c: (c.print(_message_block(body, assistant_style)), c.print()))
        self._end_turn()

    async def print_progress(self, text: str) -> None:
        if not text.strip():
            return
        await self._ensure_header()
        await self._print(lambda c: c.print(f"  [dim]↳ {escape(text)}[/dim]"))

    async def print_reasoning(self, text: str) -> None:
        if not text.strip():
            return
        await self._ensure_header()

        def _render(console: Console) -> None:
            for line in text.splitlines():
                if line.strip():
                    console.print(f"[dim italic]✻ {escape(line)}[/dim italic]")
                else:
                    console.print()

        await self._print(_render)

    async def print_notice(self, text: str) -> None:
        await self._print(lambda c: c.print(f"[bright_black]· {escape(text)}[/bright_black]"))

    async def print_queued(self, text: str) -> None:
        """Acknowledge a follow-up typed while a turn is still running."""
        user_style, _marker_style, _assistant_style, queued_style = _message_styles()
        body = Text.assemble(
            ("↳ queued  ", queued_style),
            (text.strip(), user_style),
        )
        await self._print(lambda c: c.print(_message_block(body, user_style)))

    async def toggle_reasoning(self) -> None:
        """Flip reasoning visibility; reveal what was buffered while hidden."""
        self._state.show_reasoning = not self._state.show_reasoning
        if self._state.show_reasoning:
            pending = "".join(self._hidden_reasoning).strip()
            self._hidden_reasoning.clear()
            await self.print_notice("reasoning on (ctrl+o to hide)")
            if pending:
                await self.print_reasoning(pending)
        else:
            self._reasoning.clear()
            await self.print_notice("reasoning hidden (ctrl+o to show)")

    def start_user_turn(self) -> None:
        """Reset per-turn buffers when the user starts a fresh turn."""
        self._hidden_reasoning.clear()
        self._reasoning.clear()

    async def clear_screen(self) -> None:
        await self._emit("\x1b[2J\x1b[H")
        self._stream = MarkdownStreamBuffer()

    async def _print_answer_block(self, block: str) -> None:
        await self._ensure_header()
        body = Markdown(block) if self._md else Text(block)
        _user_style, _marker_style, assistant_style, _queued_style = _message_styles()
        await self._print(lambda c: (c.print(_message_block(body, assistant_style)), c.print()))

    async def _print_rows(self, rows: list[str]) -> None:
        await self._print(lambda c: [c.print(row, highlight=False) for row in rows])

    async def _ensure_header(self) -> None:
        if self._header_printed:
            return
        self._header_printed = True
        await self._print(lambda c: (c.print(), c.print(f"[cyan]{escape(self._bot_name)}[/cyan]")))

    def _ensure_turn(self) -> None:
        if not self._state.turn_active:
            self._state.begin_turn()

    def _end_turn(self) -> None:
        self._header_printed = False
        self._reasoning.clear()
        self._state.end_turn()

    def _note_tool_activity(self, meta: Mapping[str, Any]) -> None:
        name = current_activity_name(meta)
        if name:
            self._state.note_tool(name)
        else:
            self._state.note_thinking()

    async def _handle_progress(self, content: str, meta: Mapping, channels_config: Any) -> None:
        if meta.get("_reasoning_end"):
            if self._state.show_reasoning:
                text = self._reasoning.flush()
                if text:
                    await self.print_reasoning(text)
            return
        if meta.get("_reasoning") or meta.get("_reasoning_delta"):
            if not self._state.show_reasoning:
                self._hidden_reasoning.append(content)
                return
            text = self._reasoning.add(content)
            if text:
                await self.print_reasoning(text)
            return
        is_tool_hint = bool(meta.get("_tool_hint"))
        if channels_config is not None:
            if is_tool_hint and not channels_config.send_tool_hints:
                return
            if not is_tool_hint and not channels_config.send_progress:
                return
        await self.print_progress(content)
