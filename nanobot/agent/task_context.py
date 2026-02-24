"""Per-task context variables for tool routing.

Uses Python contextvars so each tool read is isolated when running
under concurrent asyncio tasks (future PR). For now this is a pure
refactor — the serial run() loop sets these before _process_message.
"""

from contextvars import ContextVar

# Routing context — set by _set_tool_context before each _process_message
current_channel: ContextVar[str] = ContextVar("current_channel", default="")
current_chat_id: ContextVar[str] = ContextVar("current_chat_id", default="")
current_message_id: ContextVar[str | None] = ContextVar("current_message_id", default=None)

# Per-turn state for MessageTool
message_sent_in_turn: ContextVar[bool] = ContextVar("message_sent_in_turn", default=False)
