"""Tool for subagent to ask user questions."""

from typing import Any

from nanobot.agent.tools.base import Tool


class AskUserTool(Tool):
    """Tool that allows subagent to ask user questions and wait for response.

    This tool sends a question to the user via the main agent and pauses
    subagent execution until the user responds. The subagent then resumes
    with the user's answer.
    """

    def __init__(self, ask_callback: Any):
        """Initialize with callback to handle ask request.

        Args:
            ask_callback: Async callable that sends question and waits for response.
                         Signature: async (question: str) -> str
        """
        self._ask_callback = ask_callback

    @property
    def name(self) -> str:
        return "ask_user"

    @property
    def description(self) -> str:
        return (
            "Ask the user a question and wait for their response. "
            "Use this when you need user input to proceed with the task, "
            "such as confirming an action, choosing between options, "
            "or getting clarification. The subagent will pause until "
            "the user replies."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": (
                        "The question to ask the user. Be clear and specific. "
                        "If you need confirmation, explain what you're about to do."
                    ),
                },
            },
            "required": ["question"],
        }

    async def execute(self, question: str, **kwargs: Any) -> str:
        """Execute the ask_user tool.

        Args:
            question: The question to ask the user.

        Returns:
            The user's response.
        """
        return await self._ask_callback(question)
