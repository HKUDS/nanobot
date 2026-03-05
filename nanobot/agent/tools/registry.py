"""Tool registry for dynamic tool management."""

from typing import Any

from loguru import logger

from nanobot.agent.tools.base import Tool, ToolResult
from nanobot.errors import ToolExecutionError, ToolNotFoundError, ToolValidationError


class ToolRegistry:
    """
    Registry for agent tools.
    
    Allows dynamic registration and execution of tools.
    """
    
    _HINT = "\n\n[Analyze the error above and try a different approach.]"

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
    
    async def execute(self, name: str, params: dict[str, Any]) -> ToolResult:
        """Execute a tool by name with given parameters.

        Always returns a ``ToolResult``.  Legacy tools that still return a
        bare string are automatically wrapped.
        """
        tool = self._tools.get(name)
        if not tool:
            err = ToolNotFoundError(name, self.tool_names)
            return ToolResult.fail(str(err), error_type="not_found")

        try:
            errors = tool.validate_params(params)
            if errors:
                err = ToolValidationError(name, errors)
                return ToolResult.fail(str(err) + self._HINT, error_type="validation")

            raw = await tool.execute(**params)

            # Normalise into ToolResult (supports legacy str returns)
            if isinstance(raw, ToolResult):
                result = raw
            elif isinstance(raw, str):
                # Backward compat: detect old-style "Error…" strings.
                if raw.startswith("Error"):
                    result = ToolResult.fail(raw)
                else:
                    result = ToolResult.ok(raw)
            else:
                result = ToolResult.ok(str(raw))

            # Append retry hint for failures
            if not result.success:
                if not result.output.endswith(self._HINT):
                    result.output += self._HINT

            return result

        except ToolExecutionError as e:
            logger.opt(exception=True).debug("Tool '{}' raised {}", name, e.error_type)
            return ToolResult.fail(str(e) + self._HINT, error_type=e.error_type)
        except Exception as e:
            logger.opt(exception=True).debug("Tool '{}' raised", name)
            return ToolResult.fail(f"Error executing {name}: {str(e)}" + self._HINT, error_type="unknown")
    
    @property
    def tool_names(self) -> list[str]:
        """Get list of registered tool names."""
        return list(self._tools.keys())
    
    def __len__(self) -> int:
        return len(self._tools)
    
    def __contains__(self, name: str) -> bool:
        return name in self._tools
