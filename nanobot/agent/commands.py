"""Command definitions and dispatch for the agent loop.

Commands are slash-prefixed messages (e.g. /stop, /new, /help) that are
handled specially — either immediately in the run() loop or inside
_process_message before the LLM is called.

To add a new command:
1. Add a CommandDef to COMMANDS
2. If immediate=True, add a handler in AgentLoop._handle_immediate_command
3. If immediate=False, add handling in AgentLoop._process_message
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CommandDef:
    """Definition of a slash command."""

    name: str
    description: str
    immediate: bool = False  # True = handled in run() loop, bypasses message processing


# Registry of all known commands.
# "immediate" commands are handled while the agent may be busy (e.g. /stop).
# Non-immediate commands go through normal _process_message flow.
COMMANDS: dict[str, CommandDef] = {
    "/stop": CommandDef("/stop", "Stop the current task", immediate=True),
    "/new": CommandDef("/new", "Start a new conversation"),
    "/help": CommandDef("/help", "Show available commands"),
}


def parse_command(text: str) -> str | None:
    """Extract a slash command from message text.

    Returns the command string (e.g. "/stop") or None if not a command.
    """
    stripped = text.strip()
    if not stripped.startswith("/"):
        return None
    return stripped.split()[0].lower()


def is_immediate_command(cmd: str) -> bool:
    """Check if a command should be handled immediately, bypassing processing."""
    defn = COMMANDS.get(cmd)
    return defn.immediate if defn else False


def get_help_text() -> str:
    """Generate help text from registered commands."""
    lines = ["🐈 nanobot commands:"]
    for defn in COMMANDS.values():
        lines.append(f"{defn.name} — {defn.description}")
    return "\n".join(lines)
