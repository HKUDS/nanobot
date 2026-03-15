"""Example plugin: a simple greeting tool.

Copy this file to ~/.nanobot/workspace/tools/ and restart nanobot.
The LLM will be able to call it like any built-in tool.
"""

from nanobot.agent.tools import Tool, ToolContext


class GreetTool(Tool):
    """A minimal plugin that uses ToolContext to know its workspace."""

    def __init__(self, context: ToolContext):
        self._workspace = context.workspace

    @property
    def name(self):
        return "greet"

    @property
    def description(self):
        return "Greet someone by name"

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Who to greet",
                },
            },
            "required": ["name"],
        }

    async def execute(self, name: str, **kwargs) -> str:
        return f"Hello, {name}! (from workspace {self._workspace})"
