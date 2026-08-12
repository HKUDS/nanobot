"""Register, validate, and execute one safe in-process tool."""

import asyncio

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.registry import ToolRegistry


@tool_parameters(
    {
        "type": "object",
        "properties": {"left": {"type": "integer"}, "right": {"type": "integer"}},
        "required": ["left", "right"],
        "additionalProperties": False,
    }
)
class AddTool(Tool):
    @property
    def name(self) -> str:
        return "lesson_add"

    @property
    def description(self) -> str:
        return "Add two integers without side effects."

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, **kwargs: int) -> int:
        return kwargs["left"] + kwargs["right"]


async def main() -> None:
    registry = ToolRegistry()
    registry.register(AddTool())
    print(registry.get_definitions()[0]["function"]["name"])
    print(await registry.execute("lesson_add", {"left": 2, "right": 3}))


if __name__ == "__main__":
    asyncio.run(main())
