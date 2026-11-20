from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Awaitable, Callable

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.command.spec import BuiltinCommandSpec

if TYPE_CHECKING:
    from nanobot.agent.loop import AgentLoop
    from nanobot.session.manager import Session
    from nanobot.utils.llm_runtime import LLMRuntime

Handler = Callable[["CommandContext"], Awaitable["CommandExpansion | InboundMessage | OutboundMessage | None"]]
InputHandler = Callable[["CommandInput"], Awaitable["CommandExpansion | OutboundMessage"]]
_BOT_SUFFIX_RE = re.compile(r"^[A-Za-z0-9_]+$")


@dataclass(frozen=True, slots=True)
class CommandInput:
    """Inputs available to a command that only transforms a user request."""

    msg: InboundMessage
    args: str
    is_user_turn: bool


@dataclass(frozen=True, slots=True)
class CommandExpansion:
    """A transformed input whose original command is persisted by the runtime."""

    message: InboundMessage
    temporary_session_error: str | None = None


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
        self._session_commands: set[str] = set()
        self._specs: list[BuiltinCommandSpec] = []

    @property
    def specs(self) -> tuple[BuiltinCommandSpec, ...]:
        return tuple(self._specs)

    def add_spec(self, spec: BuiltinCommandSpec, *, after: str | None = None) -> None:
        self._specs = [item for item in self._specs if item.command != spec.command]
        index = next((i + 1 for i, item in enumerate(self._specs) if item.command == after), len(self._specs))
        self._specs.insert(index, spec)

    def input_command(self, cmd: str, handler: InputHandler) -> None:
        """Register a command that receives only input facts and returns an expansion."""
        async def invoke(ctx: CommandContext) -> CommandExpansion | OutboundMessage:
            return await handler(CommandInput(ctx.msg, ctx.args, ctx.is_user_turn))

        self.exact(cmd, invoke)
        self.prefix(f"{cmd} ", invoke)

    def priority(self, cmd: str, handler: Handler) -> None:
        self._priority[cmd] = handler

    def exact(self, cmd: str, handler: Handler, *, session_queue: bool = False) -> None:
        self._exact[cmd] = handler
        if session_queue:
            self._session_commands.add(cmd)
        else:
            self._session_commands.discard(cmd)

    def prefix(self, pfx: str, handler: Handler) -> None:
        self._prefix.append((pfx, handler))
        self._prefix.sort(key=lambda p: len(p[0]), reverse=True)

    def is_priority(self, text: str) -> bool:
        return normalize_command_text(text).lower() in self._priority

    def requires_session_queue(self, text: str) -> bool:
        """Whether an exact command must run on the session worker."""
        cmd = normalize_command_text(text).lower()
        return cmd in self._session_commands and cmd not in self._priority

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

    async def dispatch_priority(
        self, ctx: CommandContext,
    ) -> CommandExpansion | InboundMessage | OutboundMessage | None:
        """Dispatch a priority command. Called from run() without the lock."""
        ctx.raw = normalize_command_text(ctx.raw)
        handler = self._priority.get(ctx.raw.lower())
        if handler:
            return await handler(ctx)
        return None

    async def dispatch(
        self, ctx: CommandContext,
    ) -> CommandExpansion | InboundMessage | OutboundMessage | None:
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
