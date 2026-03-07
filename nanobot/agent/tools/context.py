"""Context management tools for clearing and compacting conversation history."""

from typing import Any

from loguru import logger

from nanobot.agent.tools.base import Tool


class ClearContextTool(Tool):
    """Tool to clear the conversation context/history."""

    def __init__(self, agent: Any):
        self.agent = agent

    @property
    def name(self) -> str:
        return "clear_context"

    @property
    def description(self) -> str:
        return (
            "Clear the entire conversation history/context window for the current session. "
            "This will reset the conversation as if it just started. "
            "Use this when the context gets too long or you want to start fresh. "
            "Warning: This cannot be undone!"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "confirm": {
                    "type": "boolean",
                    "description": "Optional: Set to true to confirm (tool will execute immediately without confirmation)",
                },
            },
        }

    async def execute(self, **kwargs) -> str:
        # Execute immediately without confirmation
        try:
            # Get the session key from kwargs or use the most recent session
            session_key = kwargs.get("session_key")
            if not session_key:
                # Get the most recent session
                sessions = self.agent.sessions.list_sessions()
                if sessions:
                    session_key = sessions[0]["key"]
                else:
                    return "❌ No active sessions found to clear."

            session = self.agent.sessions.get_or_create(session_key)

            message_count = len(session.messages)
            session.clear()
            self.agent.sessions.save(session)

            logger.info(
                f"Cleared context for session {session_key}: {message_count} messages removed"
            )
            return (
                f"✅ Context cleared successfully!\n\n"
                f"Removed {message_count} messages from the conversation.\n"
                f"Session: `{session_key}`\n\n"
                f"The conversation has been reset. Let's start fresh!"
            )

        except Exception as e:
            logger.exception("Error clearing context")
            return f"❌ Error clearing context: {str(e)}"


class CompactContextTool(Tool):
    """Tool to compact/summarize the conversation context."""

    def __init__(self, agent: Any):
        self.agent = agent

    @property
    def name(self) -> str:
        return "compact_context"

    @property
    def description(self) -> str:
        return (
            "Compact the conversation context by summarizing older messages. "
            "This reduces token usage while preserving important information. "
            "Recent messages are kept intact, older ones are summarized. "
            "Use this when approaching context limits but want to maintain context."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "keep_recent": {
                    "type": "integer",
                    "description": "Number of recent messages to keep unchanged (default: 10)",
                    "default": 10,
                },
                "confirm": {
                    "type": "boolean",
                    "description": "Must be True to confirm compacting the context",
                },
            },
            "required": ["confirm"],
        }

    async def execute(self, **kwargs) -> str:
        confirm = kwargs.get("confirm", False)
        keep_recent = kwargs.get("keep_recent", 10)

        if not confirm:
            return (
                "⚠️ To compact the context, you must confirm by setting `confirm=True`.\n\n"
                "This will summarize older messages to reduce token usage."
            )

        try:
            # Get the session key from kwargs or use the most recent session
            session_key = kwargs.get("session_key")
            if not session_key:
                # Get the most recent session
                sessions = self.agent.sessions.list_sessions()
                if sessions:
                    session_key = sessions[0]["key"]
                else:
                    return "❌ No active sessions found to compact."

            session = self.agent.sessions.get_or_create(session_key)

            total_messages = len(session.messages)

            if total_messages <= keep_recent:
                return (
                    f"ℹ️ Not enough messages to compact.\n\n"
                    f"Current messages: {total_messages}\n"
                    f"Keep recent: {keep_recent}\n\n"
                    f"Add more messages to the conversation first!"
                )

            # Get messages to summarize (everything except the most recent ones)
            messages_to_summarize = session.messages[:-keep_recent]
            recent_messages = session.messages[-keep_recent:]

            # Create a summary of older messages
            summary = self._create_summary(messages_to_summarize)

            # Clear and rebuild session with summary + recent messages
            session.clear()

            # Add summary as a system message
            if summary:
                session.add_message(
                    "system",
                    f"[Context Summary] {summary}",
                    compacted=True,
                    original_count=len(messages_to_summarize),
                )

            # Add back the recent messages
            for msg in recent_messages:
                session.add_message(
                    msg["role"],
                    msg["content"],
                    **{k: v for k, v in msg.items() if k not in ["role", "content", "timestamp"]},
                )

            self.agent.sessions.save(session)

            saved_messages = len(messages_to_summarize)
            remaining_messages = len(session.messages)

            logger.info(
                f"Compacted context for session {session_key}: {saved_messages} messages summarized into 1"
            )

            return (
                f"✅ Context compacted successfully!\n\n"
                f"📊 Statistics:\n"
                f"  • Original messages: {total_messages}\n"
                f"  • Summarized: {saved_messages}\n"
                f"  • Kept recent: {keep_recent}\n"
                f"  • Current messages: {remaining_messages}\n"
                f"  • Saved: {saved_messages - 1} message slots\n\n"
                f"📝 Summary:\n{summary[:500]}{'...' if len(summary) > 500 else ''}\n\n"
                f"Session: `{session_key}`"
            )

        except Exception as e:
            logger.exception("Error compacting context")
            return f"❌ Error compacting context: {str(e)}"

    def _create_summary(self, messages: list[dict[str, Any]]) -> str:
        """Create a summary of the conversation messages."""
        if not messages:
            return ""

        # Extract key information
        topics = []
        files_mentioned = []
        tools_used = []
        key_decisions = []

        for msg in messages:
            content = msg.get("content", "")
            if not content:
                continue

            role = msg.get("role", "")

            # Track files mentioned
            if "." in content and "/" in content:
                # Simple heuristic for file paths
                words = content.split()
                for word in words:
                    if "/" in word and "." in word and len(word) > 3:
                        files_mentioned.append(word.strip("'\".,;:()[]{}"))

            # Track tools used
            if role == "assistant" and ("tool" in content.lower() or "execut" in content.lower()):
                tools_used.append(content[:100])

            # Track key decisions/commands
            if role == "user" and len(content) < 200:
                if any(
                    word in content.lower()
                    for word in ["create", "add", "implement", "fix", "change", "update"]
                ):
                    key_decisions.append(content[:150])

        # Build summary
        parts = []

        if key_decisions:
            parts.append(f"Key requests: {'; '.join(key_decisions[-5:])}")

        if files_mentioned:
            unique_files = list(set(files_mentioned))[:10]
            parts.append(f"Files discussed: {', '.join(unique_files)}")

        if tools_used:
            parts.append(f"Tools were used for execution")

        summary = " | ".join(parts) if parts else "Previous conversation about various topics"

        return summary
