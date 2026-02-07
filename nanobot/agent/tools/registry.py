"""Tool registry for dynamic tool management."""

import time
from typing import Any, TYPE_CHECKING

from nanobot.agent.tools.base import Tool

if TYPE_CHECKING:
    from nanobot.agent.tools.tool_logger import ToolLogger


class ToolRegistry:
    """Registry for agent tools with optional execution logging."""
    
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
        session_key: str | None = None,
        logger: "ToolLogger | None" = None
    ) -> str:
        """Execute a tool by name with given parameters."""
        tool = self._tools.get(name)
        if not tool:
            return f"Error: Tool '{name}' not found"

        start = time.perf_counter()
        try:
            errors = tool.validate_params(params)
            if errors:
                return f"Error: Invalid parameters: {'; '.join(errors)}"
            result = await tool.execute(**params)
        except Exception as e:
            result = f"Error executing {name}: {e}"
        
        duration_ms = (time.perf_counter() - start) * 1000
        
        if logger and session_key:
            await logger.log_tool_call(
                session_key=session_key,
                tool_name=name,
                params=params,
                result=result,
                duration_ms=duration_ms,
            )
        
        return result
    
    @property
    def tool_names(self) -> list[str]:
        """Get list of registered tool names."""
        return list(self._tools.keys())
    
    def __len__(self) -> int:
        return len(self._tools)
    
    def __contains__(self, name: str) -> bool:
        return name in self._tools
