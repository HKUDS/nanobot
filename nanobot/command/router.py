"""Minimal command routing table for slash commands."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Awaitable, Callable

if TYPE_CHECKING:
    from nanobot.bus.events import InboundMessage, OutboundMessage
    from nanobot.session.manager import Session

Handler = Callable[["CommandContext"], Awaitable["OutboundMessage | None"]]
_BOT_SUFFIX_RE = re.compile(r"^[A-Za-z0-9_]+$")


def normalize_command_text(text: str) -> str:
    """Normalize slash-command transport variants before routing.

    Telegram and Discord-style command dispatch can produce ``/cmd@bot args``.
    The bot suffix belongs to the transport, not the command name, so strip it
    once at the router boundary while preserving user arguments verbatim.
    """
    stripped = text.strip()
    if not stripped.startswith("/"):
        return stripped
    first, sep, rest = stripped.partition(" ")
    if "@" not in first:
        return stripped
    command, suffix = first.rsplit("@", 1)
    if command and suffix and _BOT_SUFFIX_RE.fullmatch(suffix):
        return f"{command}{sep}{rest}" if sep else command
    return stripped


@dataclass
class CommandContext:
    """Everything a command handler needs to produce a response."""

    msg: InboundMessage
    session: Session | None
    key: str
    raw: str
    args: str = ""
    loop: Any = None


class CommandRouter:
    """Pure dict-based command dispatch.

    Three tiers checked in order:
      1. *priority* — exact-match commands handled before the dispatch lock
         (e.g. /stop, /restart).
      2. *exact* — exact-match commands handled inside the dispatch lock.
      3. *prefix* — longest-prefix-first match (e.g. "/team ").
    """

    def __init__(self) -> None:
        self._priority: dict[str, Handler] = {}
        self._exact: dict[str, Handler] = {}
        self._prefix: list[tuple[str, Handler]] = []

    def priority(self, cmd: str, handler: Handler) -> None:
        self._priority[cmd] = handler

    def exact(self, cmd: str, handler: Handler) -> None:
        self._exact[cmd] = handler

    def prefix(self, pfx: str, handler: Handler) -> None:
        self._prefix.append((pfx, handler))
        self._prefix.sort(key=lambda p: len(p[0]), reverse=True)

    def is_priority(self, text: str) -> bool:
        return normalize_command_text(text).lower() in self._priority

    def is_dispatchable_command(self, text: str) -> bool:
        """Check whether *text* matches any non-priority command tier (exact or prefix).

        Does NOT check priority tier.
        If this returns True, ``dispatch()`` is guaranteed to match a handler.
        """
        cmd = normalize_command_text(text).lower()
        if cmd in self._exact:
            return True
        for pfx, _ in self._prefix:
            if cmd.startswith(pfx):
                return True
        return False

    async def dispatch_priority(self, ctx: CommandContext) -> OutboundMessage | None:
        """Dispatch a priority command. Called from run() without the lock."""
        ctx.raw = normalize_command_text(ctx.raw)
        handler = self._priority.get(ctx.raw.lower())
        if handler:
            return await handler(ctx)
        return None

    async def dispatch(self, ctx: CommandContext) -> OutboundMessage | None:
        """Try exact, then prefix handlers. Returns None if unhandled."""
        ctx.raw = normalize_command_text(ctx.raw)
        cmd = ctx.raw.lower()

        if handler := self._exact.get(cmd):
            return await handler(ctx)

        for pfx, handler in self._prefix:
            if cmd.startswith(pfx):
                ctx.args = ctx.raw[len(pfx):]
                return await handler(ctx)

        return None
