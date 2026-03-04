"""Tool registry for dynamic tool management."""

import re
from typing import Any

from nanobot.agent.tools.base import Tool


# Common API key patterns for redaction
_SECRET_PATTERNS = [
    # Generic patterns
    (r'(api[_-]?key["\s:=]+["\']?)([a-zA-Z0-9_\-]{20,})', r'\1[REDACTED]'),
    (r'(secret["\s:=]+["\']?)([a-zA-Z0-9_\-]{20,})', r'\1[REDACTED]'),
    (r'(token["\s:=]+["\']?)([a-zA-Z0-9_\-]{20,})', r'\1[REDACTED]'),
    # Provider-specific
    (r'(sk[-_]?or[-_]?[a-zA-Z0-9]{20,})', '[REDACTED]'),
    (r'(sk[-_]?ant[-_]?api[-_]?[a-zA-Z0-9]{20,})', '[REDACTED]'),
    (r'(sk[-_]?openai[-_]?[a-zA-Z0-9]{20,})', '[REDACTED]'),
    (r'(ghp_[a-zA-Z0-9]{36})', '[REDACTED]'),
    (r'(github_pat_[a-zA-Z0-9_]{22,})', '[REDACTED]'),
    (r'(xox[baprs]-[a-zA-Z0-9]{10,})', '[REDACTED]'),  # Slack
    (r'(AIza[0-9A-Za-z_\-]{35})', '[REDACTED]'),  # Google API
    (r'(AKIA[0-9A-Z]{16})', '[REDACTED]'),  # AWS Access Key
]

_RE_COMPILED = [(re.compile(p, re.IGNORECASE), r) for p, r in _SECRET_PATTERNS]


def _redact_secrets(text: str) -> str:
    """Redact common API key patterns from text."""
    for pattern, replacement in _RE_COMPILED:
        text = pattern.sub(replacement, text)
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
            errors = tool.validate_params(params)
            if errors:
                return f"Error: Invalid parameters for tool '{name}': " + "; ".join(errors) + _HINT
            result = await tool.execute(**params)
            if isinstance(result, str) and result.startswith("Error"):
                return result + _HINT
            # Redact secrets from tool output (defense-in-depth)
            return _redact_secrets(result)
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
