"""Example plugin: roll dice.

A simple stateless tool that doesn't need ToolContext.
Copy to ~/.nanobot/workspace/tools/ and restart nanobot.
"""

import random

from nanobot.agent.tools import Tool


class DiceTool(Tool):
    """Roll one or more dice. Demonstrates a no-context plugin."""

    @property
    def name(self):
        return "roll_dice"

    @property
    def description(self):
        return "Roll one or more dice and return the results"

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {
                "sides": {
                    "type": "integer",
                    "description": "Number of sides per die (default 6)",
                    "minimum": 2,
                    "maximum": 100,
                },
                "count": {
                    "type": "integer",
                    "description": "Number of dice to roll (default 1)",
                    "minimum": 1,
                    "maximum": 20,
                },
            },
            "required": [],
        }

    async def execute(self, sides: int = 6, count: int = 1, **kwargs) -> str:
        rolls = [random.randint(1, sides) for _ in range(count)]
        total = sum(rolls)
        return f"Rolled {count}d{sides}: {rolls} (total: {total})"
