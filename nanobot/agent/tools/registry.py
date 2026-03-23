"""Tool registry for dynamic tool management."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.agent.tools.base import Tool

if TYPE_CHECKING:
    from nanobot.security.guards import GuardContext, ToolGuard


class ToolRegistry:
    """
    Registry for agent tools.

    Allows dynamic registration and execution of tools.
    Supports pluggable :class:`ToolGuard` instances that are evaluated
    **before** every tool invocation.
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._guards: list[ToolGuard] = []

    # -- Tool management ----------------------------------------------------

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

    # -- Guard management ---------------------------------------------------

    def add_guard(self, guard: "ToolGuard") -> None:
        """Register a tool guard.  Guards run in registration order."""
        self._guards.append(guard)
        logger.debug("Registered tool guard: {}", guard.name)

    def remove_guard(self, guard: "ToolGuard") -> None:
        """Remove a previously registered guard."""
        try:
            self._guards.remove(guard)
        except ValueError:
            pass

    @property
    def guards(self) -> list["ToolGuard"]:
        """Currently registered guards (read-only snapshot)."""
        return list(self._guards)

    # -- Execution ----------------------------------------------------------

    def _run_guards(self, ctx: "GuardContext") -> tuple["GuardContext", str | None]:
        """Run all applicable guards.  Returns (possibly-rewritten ctx, error_or_None)."""
        from nanobot.security.guards import BwrapGuard

        for guard in self._guards:
            if not guard.applies_to(ctx.tool_name):
                continue
            result = guard.check(ctx)
            if not result.allowed:
                logger.info(
                    "Guard '{}' blocked {}(…): {}",
                    guard.name,
                    ctx.tool_name,
                    result.reason,
                )
                return ctx, f"Error: {result.reason}"

        # After all checks pass, apply transforms (e.g. BwrapGuard rewriting)
        for guard in self._guards:
            if not guard.applies_to(ctx.tool_name):
                continue
            if isinstance(guard, BwrapGuard):
                ctx = guard.transform(ctx)

        return ctx, None

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

            # Run guards
            if self._guards:
                from nanobot.security.guards import GuardContext

                ctx = GuardContext(
                    tool_name=name,
                    params=params,
                    working_dir=getattr(tool, "working_dir", None),
                )
                ctx, guard_error = self._run_guards(ctx)
                if guard_error:
                    return guard_error + _HINT
                params = ctx.params

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
