"""Minimal command routing table for slash commands."""

from __future__ import annotations

import re
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from nanobot.bus.events import InboundMessage, OutboundMessage

if TYPE_CHECKING:
    from nanobot.agent.loop import AgentLoop
    from nanobot.session.manager import Session
    from nanobot.utils.llm_runtime import LLMRuntime

Handler = Callable[["CommandContext"], Awaitable["InboundMessage | OutboundMessage | None"]]
_BOT_SUFFIX_RE = re.compile(r"^[A-Za-z0-9_]+$")


def command_text(message: InboundMessage) -> str:
    """Return routable text; command-generated agent input must not be dispatched again."""
    return "" if message.metadata.get("original_command") else message.content.strip()


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
    loop: AgentLoop = field(kw_only=True)
    runtime: LLMRuntime | None = None
    is_user_turn: bool = False
    turn_scopes: list[AbstractContextManager[Any]] = field(default_factory=list)


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

    def command_name(self, text: str) -> str | None:
        """Return the registered command name, or None for ordinary chat text.

        A leading slash alone is not command intent: absolute paths and other
        slash-prefixed text must remain available to the agent.
        """
        parts = normalize_command_text(text).split(maxsplit=1)
        return self._registered_commands().get(parts[0].lower()) if parts else None

    def is_dispatchable_command(self, text: str) -> bool:
        """Check whether *text* should be handled by non-priority dispatch.

        Exact priority commands are handled separately. Recognized non-priority
        commands and malformed uses of registered commands are dispatched here
        so argument errors can be rejected instead of reaching the LLM.
        """
        cmd = normalize_command_text(text).lower()
        if cmd in self._priority:
            return False
        if cmd in self._exact:
            return True
        for pfx, _ in self._prefix:
            if cmd.startswith(pfx):
                return True
        return self.command_name(text) is not None

    async def dispatch_priority(self, ctx: CommandContext) -> InboundMessage | OutboundMessage | None:
        """Dispatch a priority command. Called from run() without the lock."""
        ctx.raw = normalize_command_text(ctx.raw)
        handler = self._priority.get(ctx.raw.lower())
        if handler:
            return await handler(ctx)
        return None

    async def dispatch(self, ctx: CommandContext) -> InboundMessage | OutboundMessage | None:
        """Try exact and prefix handlers, then validate registered commands."""
        if ctx.msg.metadata.get("original_command"):
            return None
        ctx.raw = normalize_command_text(ctx.raw)
        cmd = ctx.raw.lower()

        if handler := self._exact.get(cmd):
            return await handler(ctx)

        for pfx, handler in self._prefix:
            if cmd.startswith(pfx):
                ctx.args = ctx.raw[len(pfx):]
                return await handler(ctx)

        return self._invalid_command_response(ctx)

    def _invalid_command_response(self, ctx: CommandContext) -> OutboundMessage | None:
        canonical = self.command_name(ctx.raw)
        if canonical is None:
            return None

        entered = ctx.raw.split(maxsplit=1)[0]
        accepts_args = any(
            pfx.rstrip().lower() == entered.lower()
            for pfx, _ in self._prefix
        )
        if accepts_args:
            content = (
                f'Invalid command "{entered}". '
                'Use "/help" to list available commands.'
            )
        else:
            content = (
                f'Command "{canonical}" does not accept arguments. '
                f'Did you mean "{canonical}"?'
            )

        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content=content,
            metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
        )

    def _registered_commands(self) -> dict[str, str]:
        commands = [*self._priority, *self._exact]
        commands.extend(pfx.rstrip() for pfx, _ in self._prefix)
        return {command.lower(): command for command in commands if command}
