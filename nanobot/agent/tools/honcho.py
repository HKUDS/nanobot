"""Honcho tool for querying user context."""

from typing import Any

from nanobot.agent.tools.base import Tool


class HonchoTool(Tool):
    """
    Tool for querying Honcho's AI-native memory.

    Allows the agent to retrieve relevant context about users
    based on their history and learned preferences.
    """

    def __init__(self, session_manager: "HonchoSessionManager"):
        """
        Initialize the Honcho tool.

        Args:
            session_manager: The HonchoSessionManager instance.
        """
        self._session_manager = session_manager
        self._current_session_key: str | None = None

    @property
    def name(self) -> str:
        return "query_user_context"

    @property
    def description(self) -> str:
        return (
            "Query Honcho to retrieve relevant context about the user based on their "
            "history and preferences. Use this when you need to understand the user's "
            "background, preferences, past interactions, or goals. This helps you "
            "personalize your responses and provide more relevant assistance."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "A natural language question about the user. Examples: "
                        "'What are this user's main goals?', "
                        "'What communication style does this user prefer?', "
                        "'What topics has this user discussed recently?', "
                        "'What is this user's technical expertise level?'"
                    ),
                }
            },
            "required": ["query"],
        }

    def set_context(self, session_key: str) -> None:
        """
        Set the current session context.

        Args:
            session_key: The session key (channel:chat_id).
        """
        self._current_session_key = session_key

    async def execute(self, query: str) -> str:
        """
        Execute the Honcho context query.

        Args:
            query: Natural language question about the user.

        Returns:
            Honcho's response about the user.
        """
        if not self._current_session_key:
            return "Error: No session context set. Unable to query user information."

        try:
            result = self._session_manager.get_user_context(
                self._current_session_key, query
            )
            return result
        except Exception as e:
            return f"Error querying user context: {str(e)}"
