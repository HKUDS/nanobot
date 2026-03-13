"""Tool registry for dynamic tool management."""

import re
from typing import Any

from nanobot.agent.tools.base import Tool

# Patterns that match common secret/token formats in tool output.
# These are intentionally broad to catch leaked API keys, tokens, and passwords.
_SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r'\b(sk-[a-zA-Z0-9_-]{20,})\b'),        # OpenAI-style keys
    re.compile(r'\b(sk-ant-[a-zA-Z0-9_-]{20,})\b'),     # Anthropic keys
    re.compile(r'\b(gho_[a-zA-Z0-9]{36,})\b'),           # GitHub OAuth tokens
    re.compile(r'\b(ghp_[a-zA-Z0-9]{36,})\b'),           # GitHub personal tokens
    re.compile(r'\b(ghs_[a-zA-Z0-9]{36,})\b'),           # GitHub server tokens
    re.compile(r'\b(xoxb-[a-zA-Z0-9-]+)\b'),             # Slack bot tokens
    re.compile(r'\b(xapp-[a-zA-Z0-9-]+)\b'),             # Slack app tokens
    re.compile(r'\b(AKIA[A-Z0-9]{16})\b'),               # AWS access key IDs
    re.compile(r'\b(AIza[a-zA-Z0-9_-]{35})\b'),          # Google API keys
]


def _redact_secrets(text: str) -> str:
    """Replace known secret patterns with [REDACTED] in tool output."""
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


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
        """Execute a tool by name with given parameters."""
        _HINT = "\n\n[Analyze the error above and try a different approach.]"

        tool = self._tools.get(name)
        if not tool:
            return f"Error: Tool '{name}' not found. Available: {', '.join(self.tool_names)}"

        try:
            # Attempt to cast parameters to match schema types
            params = tool.cast_params(params)
            
            # Validate parameters
            errors = tool.validate_params(params)
            if errors:
                return f"Error: Invalid parameters for tool '{name}': " + "; ".join(errors) + _HINT
            result = await tool.execute(**params)
            if isinstance(result, str):
                result = _redact_secrets(result)
                if result.startswith("Error"):
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
