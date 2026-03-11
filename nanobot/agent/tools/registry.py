"""Tool registry for dynamic tool management."""

from typing import Any, Callable

from nanobot.agent.tools.base import Tool, ToolResult


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

    async def execute(
        self,
        name: str,
        params: dict[str, Any],
        on_progress: Callable[..., Any] | None = None,
    ) -> tuple[str, str | None]:
        """
        Execute a tool by name with given parameters.

        Args:
            name: Tool name to execute.
            params: Tool parameters.
            on_progress: Optional callback for display content.

        Returns:
            Tuple of (content_for_llm, display_for_user).
            - content_for_llm: Sent to LLM and included in context.
            - display_for_user: Optional formatted content for user display (deprecated, use on_progress).
        """
        _HINT = "\n\n[Analyze the error above and try a different approach.]"

        tool = self._tools.get(name)
        if not tool:
            content = f"Error: Tool '{name}' not found. Available: {', '.join(self.tool_names)}"
            return content + _HINT, None

        try:
            # Attempt to cast parameters to match schema types
            params = tool.cast_params(params)

            # Validate parameters
            errors = tool.validate_params(params)
            if errors:
                content = f"Error: Invalid parameters for tool '{name}': " + "; ".join(errors) + _HINT
                return content, None

            result = await tool.execute(**params)

            # Handle ToolResult with separate LLM content and user display
            if isinstance(result, ToolResult):
                if result.display and on_progress:
                    # Send display content through callback (not to LLM)
                    await on_progress(result.display, display_type=result.display_type)
                # Return only content for LLM context
                if isinstance(result.content, str) and result.content.startswith("Error"):
                    return result.content + _HINT, None
                return result.content, None

            # Backward compatibility: direct string return
            result_str = str(result)
            if result_str.startswith("Error"):
                return result_str + _HINT, None
            return result_str, None

        except Exception as e:
            content = f"Error executing {name}: {str(e)}" + _HINT
            return content, None

    @property
    def tool_names(self) -> list[str]:
        """Get list of registered tool names."""
        return list(self._tools.keys())

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools
