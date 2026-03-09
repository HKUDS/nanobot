"""Tool registry for dynamic tool management."""

from dataclasses import dataclass
from typing import Any

from nanobot.agent.tools.base import Tool


@dataclass
class ToolRegistration:
    """Registered tool metadata.

    `active` controls whether the tool is exposed in model-facing tool lists.
    It does not affect direct lookup or execution once the tool is registered.
    """

    tool: Tool
    source: str = "builtin"
    active: bool = True


class ToolRegistry:
    """
    Registry for agent tools.

    Allows dynamic registration and execution of tools.
    """

    def __init__(self):
        self._entries: dict[str, ToolRegistration] = {}

    def register(self, tool: Tool, *, source: str = "builtin", active: bool = True) -> None:
        """Register a tool."""
        self._entries[tool.name] = ToolRegistration(tool=tool, source=source, active=active)

    def unregister(self, name: str) -> None:
        """Unregister a tool by name."""
        self._entries.pop(name, None)

    def get_entry(self, name: str) -> ToolRegistration | None:
        """Get a registration entry by tool name."""
        return self._entries.get(name)

    def get(self, name: str) -> Tool | None:
        """Get a tool by name."""
        entry = self._entries.get(name)
        return entry.tool if entry else None

    def has(self, name: str) -> bool:
        """Check if a tool is registered."""
        return name in self._entries

    def get_active_definitions(self) -> list[dict[str, Any]]:
        """Get only model-exposed tool definitions in OpenAI format."""
        return [entry.tool.to_schema() for entry in self._entries.values() if entry.active]

    def get_definitions(self) -> list[dict[str, Any]]:
        """Get all registered tool definitions in OpenAI format."""
        return [entry.tool.to_schema() for entry in self._entries.values()]

    def activate(self, name: str) -> bool:
        """Mark a registered tool as active."""
        entry = self._entries.get(name)
        if not entry:
            return False
        entry.active = True
        return True

    def deactivate(self, name: str) -> bool:
        """Mark a registered tool as inactive."""
        entry = self._entries.get(name)
        if not entry:
            return False
        entry.active = False
        return True

    async def execute(self, name: str, params: dict[str, Any]) -> str:
        """Execute a tool by name with given parameters."""
        _hint = "\n\n[Analyze the error above and try a different approach.]"

        entry = self._entries.get(name)
        if not entry:
            return f"Error: Tool '{name}' not found. Available: {', '.join(self.tool_names)}"

        tool = entry.tool

        try:
            # Attempt to cast parameters to match schema types
            params = tool.cast_params(params)

            # Validate parameters
            errors = tool.validate_params(params)
            if errors:
                return f"Error: Invalid parameters for tool '{name}': " + "; ".join(errors) + _hint
            result = await tool.execute(**params)
            if isinstance(result, str) and result.startswith("Error"):
                return result + _hint
            return result
        except Exception as e:
            return f"Error executing {name}: {str(e)}" + _hint

    @property
    def tool_names(self) -> list[str]:
        """Get list of registered tool names."""
        return list(self._entries.keys())

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, name: str) -> bool:
        return name in self._entries
