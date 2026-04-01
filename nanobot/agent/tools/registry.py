"""Tool registry for dynamic tool management."""

from __future__ import annotations

from collections import Counter
from typing import Any

from loguru import logger

from nanobot.agent.tools.base import Tool


class ToolRegistry:
    """
    Registry for agent tools.

    Allows dynamic registration and execution of tools.
    Supports plan mode (read-only tool filtering) and circuit breaker
    (disable tools after repeated failures).
    """

    _CIRCUIT_BREAKER_THRESHOLD = 3

    def __init__(self):
        self._tools: dict[str, Tool] = {}
        self._plan_mode: bool = False
        self._failure_counts: Counter[str] = Counter()
        self._disabled_tools: set[str] = set()

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

    # ------------------------------------------------------------------
    # Plan mode: only expose read-only tools
    # ------------------------------------------------------------------

    def set_plan_mode(self, enabled: bool) -> None:
        """Toggle plan mode.  When active, only read-only tools are visible."""
        self._plan_mode = enabled

    @property
    def plan_mode(self) -> bool:
        return self._plan_mode

    def _visible_tools(self) -> dict[str, Tool]:
        """Return tools visible in the current mode."""
        if not self._plan_mode:
            return self._tools
        return {n: t for n, t in self._tools.items() if t.is_read_only}

    def get_definitions(self) -> list[dict[str, Any]]:
        """Get tool definitions in OpenAI format (respects plan mode)."""
        return [tool.to_schema() for tool in self._visible_tools().values()]

    # ------------------------------------------------------------------
    # Circuit breaker: disable tools after repeated failures
    # ------------------------------------------------------------------

    def record_success(self, name: str) -> None:
        """Reset failure counter on successful execution."""
        self._failure_counts[name] = 0
        self._disabled_tools.discard(name)

    def record_failure(self, name: str) -> None:
        """Increment failure counter; disable tool after threshold."""
        self._failure_counts[name] += 1
        if self._failure_counts[name] >= self._CIRCUIT_BREAKER_THRESHOLD:
            self._disabled_tools.add(name)
            logger.warning(
                "Circuit breaker: tool '{}' disabled after {} consecutive failures",
                name, self._failure_counts[name],
            )

    def is_disabled(self, name: str) -> bool:
        """Check if a tool has been disabled by the circuit breaker."""
        return name in self._disabled_tools

    def reset_circuit_breaker(self, name: str | None = None) -> None:
        """Reset circuit breaker for a specific tool or all tools."""
        if name:
            self._failure_counts[name] = 0
            self._disabled_tools.discard(name)
        else:
            self._failure_counts.clear()
            self._disabled_tools.clear()

    def get_failure_summary(self) -> str | None:
        """Return a summary of repeated failures for injection into context.

        Returns ``None`` when there are no notable failures.
        """
        lines: list[str] = []
        for name, count in self._failure_counts.items():
            if count >= 2:
                lines.append(
                    f"- {name}: failed {count} time(s)"
                    + (" [DISABLED]" if name in self._disabled_tools else "")
                )
        return "\n".join(lines) if lines else None

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def execute(self, name: str, params: dict[str, Any]) -> Any:
        """Execute a tool by name with given parameters."""
        _HINT = "\n\n[Analyze the error above and try a different approach.]"

        # Plan mode guard
        if self._plan_mode:
            tool = self._tools.get(name)
            if tool and not tool.is_read_only:
                return (
                    f"Error: Tool '{name}' is not available in plan mode. "
                    f"Only read-only tools can be used while planning. "
                    f"Available: {', '.join(self._visible_tools())}"
                )

        # Circuit breaker guard
        if self.is_disabled(name):
            return (
                f"Error: Tool '{name}' has been disabled after "
                f"{self._failure_counts[name]} consecutive failures. "
                f"Try a completely different approach." + _HINT
            )

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
            if isinstance(result, str) and result.startswith("Error"):
                self.record_failure(name)
                return result + _HINT
            self.record_success(name)
            return result
        except Exception as e:
            self.record_failure(name)
            return f"Error executing {name}: {str(e)}" + _HINT

    @property
    def tool_names(self) -> list[str]:
        """Get list of registered tool names."""
        return list(self._tools.keys())

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools
