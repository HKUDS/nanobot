"""CLI progress event renderer.

Extracted from the _cli_progress closure in commands.py so that
CliProgressHandler can be instantiated and tested independently of the
full CLI command stack.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Console

from nanobot.agent.callbacks import (
    DelegateEndEvent,
    DelegateStartEvent,
    ProgressEvent,
    StatusEvent,
    TextChunk,
    ToolCallEvent,
    ToolResultEvent,
)

if TYPE_CHECKING:
    from nanobot.config.schema import ChannelsConfig

__all__ = ["CliProgressHandler"]


class CliProgressHandler:
    """Renders agent progress events to the terminal.

    Extracted from the _cli_progress closure in commands.py so it can be
    instantiated and tested independently of the CLI command stack.
    """

    def __init__(
        self,
        console: Console,
        channels_config: ChannelsConfig | None = None,
    ) -> None:
        self._console = console
        self._channels_config = channels_config

    async def __call__(self, event: ProgressEvent) -> None:
        ch = self._channels_config
        match event:
            case TextChunk():
                if ch and not ch.send_progress:
                    return
                if event.content:
                    self._console.print(f"  [dim]↳ {event.content}[/dim]")
            case ToolCallEvent(tool_name=name):
                if ch and not ch.send_tool_hints:
                    return
                self._console.print(f"  [dim]↳ {name}(…)[/dim]")
            case StatusEvent() | ToolResultEvent() | DelegateStartEvent() | DelegateEndEvent():
                pass  # CLI does not render these; ignored explicitly
