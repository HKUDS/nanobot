"""Tool registry for dynamic tool management."""

from typing import Any

from nanobot.agent.tools.base import Tool, ToolContext


class ToolRegistry:
    """
    Registry for agent tools.

    Allows dynamic registration and execution of tools.
    Context is passed per-call, not stored on tool instances.
    """

    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        """Unregister a tool by name."""
        self._tools.pop(name, None)

    def get(self, name: str) -> Tool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        """Check if a tool is registered."""
        return name in self._tools

    def get_definitions(self) -> list[dict[str, Any]]:
        """Get all tool definitions in OpenAI format."""
        return [tool.to_schema() for tool in self._tools.values()]

    async def execute(
        self, name: str, params: dict[str, Any], ctx: ToolContext | None = None
    ) -> str:
        """
        Execute a tool by name with given parameters.

        Args:
            name: Tool name.
            params: Tool parameters.
            ctx: Execution context (channel, chat_id, etc.).

        Returns:
            Tool execution result as string.
        """
        tool = self._tools.get(name)
        if not tool:
            raise LookupError(f"Tool '{name}' not found")

        ctx = ctx or ToolContext()

        errors = tool.validate_params(params)
        if errors:
            raise ValueError(
                f"Invalid parameters for tool '{name}': " + "; ".join(errors)
            )

        return await tool.execute(ctx, **params)

    @property
    def tool_names(self) -> list[str]:
        """Get list of registered tool names."""
        return list(self._tools.keys())

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools
