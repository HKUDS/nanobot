"""Streaming renderer for CLI output.

Uses Rich Live with ``transient=True`` for in-place markdown updates during
streaming.  After the live display stops, a final clean render is printed
so the content persists on screen.  ``transient=True`` ensures the live
area is erased before ``stop()`` returns, avoiding the duplication bug
that plagued earlier approaches.
"""

from __future__ import annotations

import sys
from contextlib import contextmanager, nullcontext

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.text import Text


def _clear_current_line(console: Console) -> None:
    """Erase a transient status line before printing persistent output."""
    file = console.file
    isatty = getattr(file, "isatty", lambda: False)
    if not isatty():
        return
    file.write("\r\x1b[2K")
    file.flush()


def _make_console() -> Console:
    """Create a Console that emits plain text when stdout is not a TTY.

    Rich's spinner, Live render, and cursor-visibility escape codes all
    key off ``Console.is_terminal``. Forcing ``force_terminal=True`` overrode
    the ``isatty()`` check and caused control sequences (``\\x1b[?25l``,
    braille spinner frames) to pollute programmatic consumers such as
    ``docker exec -i`` or pipes, even with ``NO_COLOR`` or ``TERM=dumb``.
    Deferring to ``isatty()`` keeps Rich output in interactive terminals
    and plain text everywhere else (#3265).
    """
    return Console(file=sys.stdout, force_terminal=sys.stdout.isatty())


class ThinkingSpinner:
    """Spinner that shows '<bot_name> is thinking...' with pause support."""

    def __init__(self, console: Console | None = None, bot_name: str = "nanobot"):
        c = console or _make_console()
        self._console = c
        self._spinner = c.status(f"[dim]{bot_name} is thinking...[/dim]", spinner="dots")
        self._active = False

    def __enter__(self):
        self._spinner.start()
        self._active = True
        return self

    def __exit__(self, *exc):
        self._active = False
        self._spinner.stop()
        _clear_current_line(self._console)
        return False

    def pause(self):
        """Context manager: temporarily stop spinner for clean output."""
        from contextlib import contextmanager

        @contextmanager
        def _ctx():
            if self._spinner and self._active:
                self._spinner.stop()
                _clear_current_line(self._console)
            try:
                yield
            finally:
                if self._spinner and self._active:
                    self._spinner.start()

        return _ctx()


class StreamRenderer:
    """Streaming renderer with Rich Live for in-place updates.

    During streaming: updates content in-place via Rich Live.
    On end: stops Live (transient=True erases it), then prints final render.

    Flow per round:
      spinner -> first delta -> header + Live updates ->
      on_end -> stop Live + final render
    """

    def __init__(
        self,
        render_markdown: bool = True,
        show_spinner: bool = True,
        bot_name: str = "nanobot",
        bot_icon: str = "🐈",
    ):
        self._md = render_markdown
        self._show_spinner = show_spinner
        self._bot_name = bot_name
        self._bot_icon = bot_icon
        self._buf = ""
        self.streamed = False
        self._console = _make_console()
        self._live: Live | None = None
        self._spinner: ThinkingSpinner | None = None
        self._header_printed = False
        self._start_spinner()

    def _renderable(self):
        """Create a renderable from the current buffer."""
        if self._md and self._buf:
            return Markdown(self._buf)
        return Text(self._buf or "")

    def _render_str(self) -> str:
        """Render current buffer to a plain string via Rich."""
        with self._console.capture() as cap:
            self._console.print(self._renderable())
        return cap.get()

    def _start_spinner(self) -> None:
        if self._show_spinner:
            self._spinner = ThinkingSpinner(bot_name=self._bot_name)
            self._spinner.__enter__()

    def _stop_spinner(self) -> None:
        if self._spinner:
            self._spinner.__exit__(None, None, None)
            self._spinner = None

    @property
    def console(self) -> Console:
        """Expose the Live's console so external print functions can use it."""
        return self._console

    @property
    def header_printed(self) -> bool:
        """Whether this turn has already opened the assistant output block."""
        return self._header_printed

    def ensure_header(self) -> None:
        """Stop transient status and print the assistant header once."""
        # A turn can print trace rows before the final answer, then restart the
        # spinner while tools run. The next answer delta still needs to stop
        # that spinner even though the header was already printed.
        self._stop_spinner()
        if self._header_printed:
            return
        self._console.print()
        header = f"{self._bot_icon} {self._bot_name}" if self._bot_icon else self._bot_name
        self._console.print(f"[cyan]{header}[/cyan]")
        self._header_printed = True

    def pause_spinner(self):
        """Context manager: temporarily stop transient output for clean trace lines."""
        @contextmanager
        def _pause():
            live_was_active = self._live is not None
            if self._live:
                # Trace/reasoning can arrive after answer streaming has started.
                # Stop the transient Live view first so it does not leak a raw
                # partial markdown frame before the trace line.
                self._live.stop()
                self._live = None
            with self._spinner.pause() if self._spinner else nullcontext():
                yield
            # If more answer deltas arrive after the trace, on_delta() will
            # create a fresh Live using the existing buffer. If no deltas arrive,
            # on_end() prints the final buffered answer once.
            if live_was_active:
                return

        return _pause()

    async def on_delta(self, delta: str) -> None:
        self.streamed = True
        self._buf += delta
        if self._live is None:
            if not self._buf.strip():
                return
            self.ensure_header()
            self._live = Live(
                self._renderable(),
                console=self._console,
                auto_refresh=False,
                transient=True,
            )
            self._live.start()
        else:
            self._live.update(self._renderable())
        self._live.refresh()

    async def on_end(self, *, resuming: bool = False) -> None:
        if self._live:
            # Double-refresh to sync _shape before stop() calls refresh().
            self._live.refresh()
            self._live.update(self._renderable())
            self._live.refresh()
            self._live.stop()
            self._live = None
        self._stop_spinner()
        if self._buf.strip():
            # Print final rendered content (persists after Live is gone).
            out = sys.stdout
            out.write(self._render_str())
            out.flush()
        if resuming:
            self._buf = ""
            self._start_spinner()

    def stop_for_input(self) -> None:
        """Stop spinner before user input to avoid prompt_toolkit conflicts."""
        self._stop_spinner()

    def pause(self):
        """Context manager: pause spinner for external output. No-op once streaming has started."""
        if self._spinner:
            return self._spinner.pause()
        return nullcontext()

    async def close(self) -> None:
        """Stop spinner/live without rendering a final streamed round."""
        if self._live:
            self._live.stop()
            self._live = None
        self._stop_spinner()
