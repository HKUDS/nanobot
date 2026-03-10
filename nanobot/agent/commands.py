"""Command registry for slash commands."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Awaitable, Callable

if TYPE_CHECKING:
    from nanobot.agent.commands import CommandResult

# Type aliases
CommandHandler = Callable[..., Awaitable["CommandResult | None"]]


@dataclass
class CommandContext:
    """Context passed to command handlers."""

    message: Any  # InboundMessage
    session: Any | None = None  # Session
    agent: Any = field(default=None)  # AgentLoop


@dataclass
class CommandResult:
    """Result returned by command handlers."""

    content: str | None = None
    response: Any = field(default=None)  # OutboundMessage
    response_needed: bool = True


class CommandRegistry:
    """Registry for slash commands."""

    def __init__(self):
        self._commands: dict[str, CommandHandler] = {}
        self._descriptions: dict[str, str] = {}
        self._immediate_commands: set[str] = set()

    def register(
        self,
        name: str,
        handler: CommandHandler,
        description: str = "",
        immediate: bool = False,
    ) -> None:
        """Register a command handler."""
        self._commands[name] = handler
        self._descriptions[name] = description
        if immediate:
            self._immediate_commands.add(name)

    def get_handler(self, name: str) -> CommandHandler | None:
        """Get handler for a command."""
        return self._commands.get(name)

    def is_immediate(self, name: str) -> bool:
        """Check if command needs immediate processing in main loop."""
        return name in self._immediate_commands

    def get_help_text(self) -> str:
        """Generate help text from registered commands."""
        if not self._descriptions:
            return "No commands available."

        lines = ["🐈 nanobot commands:"]
        for name, desc in self._descriptions.items():
            lines.append(f"/{name} — {desc}")
        return "\n".join(lines)


# Global registry instance
_registry: CommandRegistry | None = None


def get_registry() -> CommandRegistry:
    """Get the global command registry."""
    global _registry
    if _registry is None:
        _registry = CommandRegistry()
    return _registry


async def help_handler(context: CommandContext) -> CommandResult:
    """Handle /help command - show available commands."""
    registry = get_registry()
    return CommandResult(content=registry.get_help_text())


def create_help_handler():
    """Factory function to create help handler."""
    return help_handler


async def new_handler(context: CommandContext) -> CommandResult:
    """Handle /new command - archive and start new session."""
    import asyncio

    msg = context.message
    session = context.session
    agent = context.agent

    lock = agent._consolidation_locks.setdefault(session.key, asyncio.Lock())
    agent._consolidating.add(session.key)
    try:
        async with lock:
            snapshot = session.messages[session.last_consolidated:]
            if snapshot:
                # Create temp session for archival
                temp = type('Session', (), {'key': session.key, 'messages': list(snapshot)})()
                if not await agent._consolidate_memory(temp, archive_all=True):
                    return CommandResult(
                        content="Memory archival failed, session not cleared. Please try again.",
                    )
    except Exception:
        import logging
        logging.exception("/new archival failed for {}", session.key)
        return CommandResult(
            content="Memory archival failed, session not cleared. Please try again.",
        )
    finally:
        agent._consolidating.discard(session.key)

    session.clear()
    agent.sessions.save(session)
    agent.sessions.invalidate(session.key)
    return CommandResult(content="New session started.")


def create_new_handler():
    """Factory function to create new handler."""
    return new_handler


async def stop_handler(context: CommandContext) -> CommandResult:
    """Handle /stop command - cancel current tasks.

    Note: This handler is special - it needs to be executed in the main loop
    before message dispatch, not in the message processing pipeline.
    The actual cancellation is handled by AgentLoop._handle_stop().
    """
    # The /stop command is handled specially in the main loop
    # This handler exists for consistency but is not directly called
    from loguru import logger
    logger.info("Stop command received")
    return CommandResult(content="", response_needed=False)


def create_stop_handler():
    """Factory function to create stop handler."""
    return stop_handler
