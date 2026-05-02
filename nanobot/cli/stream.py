"""Streaming renderer for CLI output.

Line-buffered streaming with horizontal borders.
Uses a custom renderable (LinePanel) to draw top and bottom borders
with straight lines, while omitting left and right borders and indents
to prevent copy-paste issues in the terminal.
"""

from __future__ import annotations

import sys
import time
from typing import TYPE_CHECKING

from rich.console import Console, ConsoleOptions, RenderResult
from rich.live import Live
from rich.markdown import Markdown
from rich.segment import Segment
from rich.style import Style
from rich.text import Text

from nanobot import __logo__

if TYPE_CHECKING:
    from rich.console import RenderableType


def _make_console() -> Console:
    """Create a Console that emits plain text when stdout is not a TTY."""
    return Console(file=sys.stdout, force_terminal=sys.stdout.isatty())


class LinePanel:
    """A custom panel that draws top and bottom straight borders,
    but omits vertical borders (left/right) and padding.

    This ensures that when users select text in the terminal to copy, they do not
    copy vertical border characters, massive blocks of trailing spaces, or indentations.
    """

    def __init__(self, renderable: RenderableType, title: str):
        self.renderable = renderable
        self.title = title

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        width = options.max_width
        title_text = f" {self.title} "
        fill = width - 2 - len(title_text)
        
        border_style = Style(color="cyan", dim=True)
        
        # Top border
        yield Segment(f"──{title_text}{'─' * max(0, fill)}\n", border_style)

        # Render the inner content, full width
        lines = console.render_lines(self.renderable, options)
        
        for line in lines:
            # Strip trailing segments that are just empty spaces AND have no background color
            while line and not line[-1].text.strip() and not (line[-1].style and line[-1].style.bgcolor):
                line.pop()
            
            if line:
                last_seg = line[-1]
                # If the last segment doesn't have a background color, strip its trailing spaces
                if not (last_seg.style and last_seg.style.bgcolor):
                    last_text = last_seg.text.rstrip()
                    if last_text:
                        line[-1] = Segment(last_text, last_seg.style, last_seg.control)
                    else:
                        line.pop()

            yield from line
            yield Segment("\n")
            
        # Bottom border
        yield Segment(f"{'─' * width}\n", border_style)


def _make_panel(renderable: RenderableType, width: int | None = None) -> LinePanel:
    """Wrap content in a line-bordered panel for non-streaming static display."""
    return LinePanel(renderable, f"{__logo__} nanobot")


class ThinkingSpinner:
    """Spinner that shows 'nanobot is thinking...' with pause support."""

    def __init__(self, console: Console | None = None):
        c = console or _make_console()
        self._spinner = c.status(f"[dim]{__logo__} nanobot is thinking...[/dim]", spinner="dots")
        self._active = False

    def __enter__(self):
        self._spinner.start()
        self._active = True
        return self

    def __exit__(self, *exc):
        self._active = False
        self._spinner.stop()
        return False

    def pause(self):
        """Context manager: temporarily stop spinner for clean output."""
        from contextlib import contextmanager

        @contextmanager
        def _ctx():
            if self._spinner and self._active:
                self._spinner.stop()
            try:
                yield
            finally:
                if self._spinner and self._active:
                    self._spinner.start()

        return _ctx()


class StreamRenderer:
    """Rich Live streaming with LinePanel.

    Restores markdown rendering and stable Live updates while avoiding
    the copy-paste trailing space issue of traditional panels.
    """

    def __init__(self, render_markdown: bool = True, show_spinner: bool = True):
        self._md = render_markdown
        self._show_spinner = show_spinner
        self._buf = ""
        self._live: Live | None = None
        self._t = 0.0
        self.streamed = False
        self._spinner: ThinkingSpinner | None = None
        self._start_spinner()

    def _render(self) -> RenderableType:
        content = self._buf or ""
        renderable = Markdown(content) if self._md and content else Text(content)
        return LinePanel(renderable, f"{__logo__} nanobot")

    def _start_spinner(self) -> None:
        if self._show_spinner:
            self._spinner = ThinkingSpinner()
            self._spinner.__enter__()

    def _stop_spinner(self) -> None:
        if self._spinner:
            self._spinner.__exit__(None, None, None)
            self._spinner = None

    async def on_delta(self, delta: str) -> None:
        self.streamed = True
        self._buf += delta
        if self._live is None:
            if not self._buf.strip():
                return
            self._stop_spinner()
            c = _make_console()
            c.print()  # spacing before panel
            self._live = Live(self._render(), console=c, auto_refresh=False)
            self._live.start()
        
        now = time.monotonic()
        if (now - self._t) > 0.15:
            self._live.update(self._render())
            self._live.refresh()
            self._t = now

    async def on_end(self, *, resuming: bool = False) -> None:
        if self._live:
            self._live.update(self._render())
            self._live.refresh()
            self._live.stop()
            self._live = None
        self._stop_spinner()
        
        if resuming:
            self._buf = ""
            self._start_spinner()
        else:
            _make_console().print()

    def stop_for_input(self) -> None:
        """Stop spinner before user input to avoid prompt_toolkit conflicts."""
        self._stop_spinner()

    async def close(self) -> None:
        """Stop spinner/live without rendering a final streamed round."""
        if self._live:
            self._live.stop()
            self._live = None
        self._stop_spinner()
