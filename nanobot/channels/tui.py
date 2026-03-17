"""TUI (Terminal User Interface) channel using prompt_toolkit and rich."""

from __future__ import annotations

import asyncio
import sys
from typing import Any

from loguru import logger
from prompt_toolkit import PromptSession, print_formatted_text
from prompt_toolkit.application import run_in_terminal
from prompt_toolkit.formatted_text import ANSI, HTML
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.patch_stdout import patch_stdout
from pydantic import Field
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import Base

_EXIT_WORDS = {"exit", "quit", ":q"}


def _to_ansi(render_fn) -> str:
    """Capture a Rich renderable as an ANSI string for prompt_toolkit output."""
    c = Console(force_terminal=True, color_system="standard")
    with c.capture() as capture:
        render_fn(c)
    return capture.get()


_BRAILLE_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

_COMMANDS: dict[str, str] = {
    "/help": "Show this help message",
    "/new":  "Start a new conversation (clears session history)",
    "/clear": "Clear the terminal screen",
    "/stop": "Exit TUI mode",
}


class TuiConfig(Base):
    """TUI channel configuration."""

    enabled: bool = False
    allow_from: list[str] = Field(default_factory=lambda: ["local_user"])
    user_id: str = "local_user"


class TuiChannel(BaseChannel):
    """Terminal User Interface channel using prompt_toolkit and rich."""

    name = "tui"
    display_name = "TUI"

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = TuiConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: TuiConfig = config
        self._chat_id: str = "tui"
        self._session_counter: int = 0
        self._loading_task: asyncio.Task[None] | None = None
        self._response_done: asyncio.Event = asyncio.Event()
        self._response_done.set()
        self._session: PromptSession = PromptSession(
            history=InMemoryHistory(),
        )

    async def _animate_loading(self) -> None:
        """Print a Braille spinner directly to the real terminal until cancelled."""
        out = sys.__stdout__
        idx = 0
        try:
            while True:
                frame = _BRAILLE_FRAMES[idx % len(_BRAILLE_FRAMES)]
                out.write(f"\r\033[2K  {frame} thinking...")
                out.flush()
                idx += 1
                await asyncio.sleep(0.12)
        except asyncio.CancelledError:
            out.write("\r\033[2K")
            out.flush()

    def _start_loading(self) -> None:
        """Kick off the loading spinner as a background task."""
        if self._loading_task is None or self._loading_task.done():
            self._loading_task = asyncio.get_running_loop().create_task(
                self._animate_loading()
            )

    async def _stop_loading(self) -> None:
        """Cancel the loading spinner and clear the line."""
        if self._loading_task is not None and not self._loading_task.done():
            self._loading_task.cancel()
            try:
                await self._loading_task
            except asyncio.CancelledError:
                pass
            self._loading_task = None

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return TuiConfig().model_dump(by_alias=True)

    async def _dispatch_command(self, text: str) -> bool:
        """Handle a slash command. Returns True if the TUI should exit."""
        cmd = text.strip().split()[0].lower()

        if cmd in {"/stop", "/exit", "/quit"}:
            return True

        if cmd == "/help":
            def _print_help() -> None:
                t = Table(show_header=True, header_style="bold cyan", border_style="dim")
                t.add_column("Command", style="cyan", no_wrap=True)
                t.add_column("Description")
                for name, desc in _COMMANDS.items():
                    t.add_row(name, desc)
                print_formatted_text(ANSI(_to_ansi(lambda c: c.print(t))), end="")
            await run_in_terminal(_print_help)

        elif cmd == "/new":
            self._session_counter += 1
            self._chat_id = f"tui-{self._session_counter}"
            n = self._session_counter
            def _print_new() -> None:
                print_formatted_text(
                    ANSI(_to_ansi(lambda c: c.print(f"[dim]New session started (session {n}).[/dim]"))),
                    end="",
                )
            await run_in_terminal(_print_new)

        elif cmd == "/clear":
            def _do_clear() -> None:
                out = sys.__stdout__
                out.write("\033[2J\033[H")
                out.flush()
                rule = _to_ansi(lambda c: c.rule("[bold cyan]nanobot TUI[/bold cyan]"))
                out.write(rule)
                out.flush()
            await run_in_terminal(_do_clear)

        else:
            def _print_unknown() -> None:
                print_formatted_text(
                    ANSI(_to_ansi(lambda c: c.print(
                        f"[yellow]Unknown command: {cmd}[/yellow]  "
                        "Type [cyan]/help[/cyan] for available commands."
                    ))),
                    end="",
                )
            await run_in_terminal(_print_unknown)

        return False

    async def start(self) -> None:
        """Start the TUI input loop."""
        self._running = True

        console = Console()
        console.rule("[bold cyan]nanobot TUI[/bold cyan]")
        console.print(
            "[dim]Type your message and press Enter. "
            "Type [cyan]/help[/cyan] for commands, [cyan]/stop[/cyan] or Ctrl+D to quit.[/dim]\n"
        )

        with patch_stdout():
            while self._running:
                try:
                    text = await self._session.prompt_async(
                        HTML("<b fg='ansiblue'>You:</b> ")
                    )
                    text = text.strip()
                    if not text:
                        continue

                    if text.lower() in _EXIT_WORDS:
                        break

                    if text.startswith("/"):
                        should_exit = await self._dispatch_command(text)
                        if should_exit:
                            break
                        continue

                    self._response_done.clear()
                    await self._handle_message(
                        sender_id=self.config.user_id,
                        chat_id=self._chat_id,
                        content=text,
                    )
                    self._start_loading()
                    await self._response_done.wait()
                except KeyboardInterrupt:
                    continue
                except EOFError:
                    break

        self._running = False
        console.print("\n[dim]Goodbye![/dim]")

    async def stop(self) -> None:
        """Stop the TUI channel."""
        self._running = False
        await self._stop_loading()
        self._response_done.set()

    async def send(self, msg: OutboundMessage) -> None:
        """Display a message in the TUI."""
        is_progress = msg.metadata.get("_progress", False)
        is_tool_hint = msg.metadata.get("_tool_hint", False)
        content = msg.content or ""

        if not is_progress:
            await self._stop_loading()
            self._response_done.set()

        def _render() -> None:
            if is_progress and is_tool_hint:
                ansi = _to_ansi(lambda c: c.print(f"  [dim]> {content}[/dim]"))
            elif is_progress:
                ansi = _to_ansi(lambda c: c.print(f"  [dim]{content}[/dim]"))
            else:
                ansi = _to_ansi(
                    lambda c: (
                        c.print("[bold cyan]nanobot:[/bold cyan]"),
                        c.print(Markdown(content)),
                    )
                )
            print_formatted_text(ANSI(ansi), end="")

        try:
            await run_in_terminal(_render)
        except Exception as e:
            logger.warning("TUI render error: {}", e)
