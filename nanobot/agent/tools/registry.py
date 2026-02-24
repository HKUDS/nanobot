"""Tool registry for dynamic tool management."""

from typing import Any

from nanobot.agent.tools.base import Tool


class ToolRegistry:
    """
    Registry for agent tools.

    Allows dynamic registration and execution of tools.
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

    async def execute(self, name: str, params: dict[str, Any]) -> str:
        """
        Execute a tool by name with given parameters.

        Args:
            name: Tool name.
            params: Tool parameters.

        Returns:
            Tool execution result as string.

        Raises:
            KeyError: If tool not found.
        """
        _HINT = "\n\n[Analyze the error above and try a different approach.]"

        from loguru import logger
        logger.debug(f"Registry.execute: Looking for tool '{name}'")
        logger.debug(f"Registry.execute: Available tools: {list(self._tools.keys())}")

        tool = self._tools.get(name)
        if not tool:
            logger.error(f"Registry.execute: Tool '{name}' NOT FOUND")
            return f"Error: Tool '{name}' not found. Available: {', '.join(self.tool_names)}" + _HINT

        logger.debug(f"Registry.execute: Tool '{name}' found, validating params: {params}")
        try:
            errors = tool.validate_params(params)
            if errors:
                logger.warning(f"Registry.execute: Validation errors for '{name}': {errors}")
                return f"Error: Invalid parameters for tool '{name}': " + "; ".join(errors) + _HINT
            logger.debug(f"Registry.execute: Executing '{name}' with params: {params}")
            result = await tool.execute(**params)
            logger.debug(f"Registry.execute: '{name}' returned: {result[:100] if len(result) > 100 else result}...")
            if isinstance(result, str) and result.startswith("Error"):
                return result + _HINT
            return result
        except Exception as e:
            logger.error(f"Registry.execute: Error executing '{name}': {e}", exc_info=True)
            return f"Error executing {name}: {str(e)}" + _HINT

    @property
    def tool_names(self) -> list[str]:
        """Get list of registered tool names."""
        return list(self._tools.keys())

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools
