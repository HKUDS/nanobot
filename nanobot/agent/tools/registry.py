"""Tool registry for dynamic tool management."""

from typing import Any

from nanobot.agent.tools.base import Tool
from nanobot.agent.tool_ranker import ToolRanker


class ToolRegistry:
    """
    Registry for agent tools.

    Allows dynamic registration and execution of tools.
    """

    def __init__(self):
        self._tools: dict[str, Tool] = {}
        self._ranker = ToolRanker()

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

    def get_definitions(self, user_query: str | None = None, top_k: int = 0) -> list[dict[str, Any]]:
        """
        Get tool definitions in OpenAI format.

        Args:
            user_query: Optional user query for smart tool injection
            top_k: Number of top tools to return (0 = all tools)

        Returns:
            List of tool definitions, optionally ranked by relevance
        """
        all_definitions = [tool.to_schema() for tool in self._tools.values()]
        
        if user_query and top_k > 0:
            return self._ranker.rank_tools(user_query, all_definitions, top_k)
        
        return all_definitions

    async def execute(self, name: str, params: dict[str, Any]) -> str:
        """Execute a tool by name with given parameters."""
        _HINT = "\n\n[Analyze the error above and try a different approach.]"

        tool = self._tools.get(name)
        if not tool:
            return f"Error: Tool '{name}' not found. Available: {', '.join(self.tool_names)}"

        try:
            errors = tool.validate_params(params)
            if errors:
                return f"Error: Invalid parameters for tool '{name}': " + "; ".join(errors) + _HINT
            result = await tool.execute(**params)
            if isinstance(result, str) and result.startswith("Error"):
                return result + _HINT
            return result
        except Exception as e:
            return f"Error executing {name}: {str(e)}" + _HINT

    @property
    def tool_names(self) -> list[str]:
        """Get list of registered tool names."""
        return list(self._tools.keys())

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools
