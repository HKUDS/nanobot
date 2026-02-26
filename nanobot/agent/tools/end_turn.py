"""End-turn tool: model explicitly signals that its turn is complete."""

from typing import Any

from nanobot.agent.tools.base import Tool


class EndTurnTool(Tool):
    """Tool for the model to signal that its response is complete and the user may reply."""

    @property
    def name(self) -> str:
        return "end_turn"

    @property
    def description(self) -> str:
        return (
            "REQUIRED to end your turn. The user cannot reply until you call this tool. "
            "Call when your response is complete; pass your final message as 'content' (or leave empty to use your last message). "
            "If you have more to add, do not call yet—continue with tools or text, then call end_turn when done."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "Your final message to the user (required to end turn; if empty, your last text is used)",
                },
            },
            "required": [],
        }

    async def execute(self, content: str = "", **kwargs: Any) -> str:
        """No-op; the loop uses the tool call arguments to end the turn."""
        return "Turn ended."
