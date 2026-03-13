"""Tool registry for dynamic tool management."""

from typing import Any

from loguru import logger

from nanobot.agent.tools.base import Tool

# Promoted MCP tools are demoted back to summary after this many idle rounds.
_MCP_IDLE_DEMOTE_ROUNDS = 3


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
        """Get all tool definitions in OpenAI format.

        Tools with ``is_summary_only`` set to ``True`` emit a minimal schema
        (name + description, empty parameters) to reduce context size.

        Each call also ticks idle counters on promoted MCP tools and demotes
        those that have been idle for ``_MCP_IDLE_DEMOTE_ROUNDS`` rounds.
        """
        defs = []
        for tool in self._tools.values():
            # Tick idle and auto-demote promoted MCP tools
            if hasattr(tool, "tick_idle"):
                tool.tick_idle()
                if (
                    not getattr(tool, "is_summary_only", True)
                    and getattr(tool, "idle_rounds", 0) >= _MCP_IDLE_DEMOTE_ROUNDS
                ):
                    tool.demote_to_summary()
                    logger.debug("MCP tool '{}' demoted to summary (idle)", tool.name)

            if getattr(tool, "is_summary_only", False):
                defs.append(tool.to_summary_schema())
            else:
                defs.append(tool.to_schema())
        return defs

    async def execute(self, name: str, params: dict[str, Any]) -> str:
        """Execute a tool by name with given parameters."""
        _HINT = "\n\n[Analyze the error above and try a different approach.]"

        tool = self._tools.get(name)
        if not tool:
            return f"Error: Tool '{name}' not found. Available: {', '.join(self.tool_names)}"

        # Intercept summary-only MCP tools: promote and return full schema
        if getattr(tool, "is_summary_only", False):
            tool.promote_to_full()
            schema_text = tool.get_full_schema_text()
            return (
                f"Tool '{name}' requires parameters. "
                f"The full schema is now available. "
                f"Please retry with the correct parameters:\n\n{schema_text}"
            )

        try:
            # Attempt to cast parameters to match schema types
            params = tool.cast_params(params)

            # Validate parameters
            errors = tool.validate_params(params)
            if errors:
                return f"Error: Invalid parameters for tool '{name}': " + "; ".join(errors) + _HINT
            result = await tool.execute(**params)

            # Reset idle counter on successful MCP tool use
            if hasattr(tool, "mark_used"):
                tool.mark_used()

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
