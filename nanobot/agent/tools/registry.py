"""Tool registry for dynamic tool management."""

import json
from collections.abc import Callable
from typing import Any

from nanobot.agent.tools.base import Tool, ToolResult


def is_tool_error_result(name: str, result: Any) -> bool:
    return isinstance(result, ToolResult) and result.is_error


class ToolRegistry:
    """
    Registry for agent tools.

    Allows dynamic registration and execution of tools.
    """

    def __init__(self):
        self._tools: dict[str, Tool] = {}
        self._cached_definitions: list[dict[str, Any]] | None = None

    def register(self, tool: Tool) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool
        self._cached_definitions = None

    def unregister(self, name: str) -> None:
        """Unregister a tool by name."""
        self._tools.pop(name, None)
        self._cached_definitions = None

    def get(self, name: str) -> Tool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    @staticmethod
    def _lookup_key(name: str) -> str:
        """Normalize names for suggestions only; never for execution."""
        return "".join(ch.lower() for ch in name if ch.isalnum())

    def _suggest_name(self, name: str) -> str | None:
        key = self._lookup_key(str(name or ""))
        if not key:
            return None
        matches = [
            registered
            for registered in self._tools
            if self._lookup_key(registered) == key
        ]
        if len(matches) == 1:
            return matches[0]
        return None

    def has(self, name: str) -> bool:
        """Check if a tool is registered."""
        return name in self._tools

    @staticmethod
    def _schema_name(schema: dict[str, Any]) -> str:
        """Extract a normalized tool name from either OpenAI or flat schemas."""
        fn = schema.get("function")
        if isinstance(fn, dict):
            name = fn.get("name")
            if isinstance(name, str):
                return name
        name = schema.get("name")
        return name if isinstance(name, str) else ""

    def get_definitions(self) -> list[dict[str, Any]]:
        """Get tool definitions with stable ordering for cache-friendly prompts.

        Built-in tools are sorted first as a stable prefix, then MCP tools are
        sorted and appended.  The result is cached until the next
        register/unregister call.
        """
        if self._cached_definitions is not None:
            return self._cached_definitions

        definitions = [tool.to_schema() for tool in self._tools.values()]
        builtins: list[dict[str, Any]] = []
        mcp_tools: list[dict[str, Any]] = []
        for schema in definitions:
            name = self._schema_name(schema)
            if name.startswith("mcp_"):
                mcp_tools.append(schema)
            else:
                builtins.append(schema)

        builtins.sort(key=self._schema_name)
        mcp_tools.sort(key=self._schema_name)
        self._cached_definitions = builtins + mcp_tools
        return self._cached_definitions

    def prepare_call(
        self,
        name: str,
        params: Any,
    ) -> tuple[Tool | None, Any, str | None]:
        """Resolve, cast, and validate one tool call."""
        tool = self._tools.get(name)
        if not tool:
            suggestion = self._suggest_name(str(name))
            hint = f" Did you mean '{suggestion}'? Tool names must match exactly." if suggestion else ""
            return None, params, (
                ToolResult.error(
                    f"Error: Tool '{name}' not found.{hint} Available: {', '.join(self.tool_names)}"
                )
            )

        params = self._coerce_params(tool, params)
        if not isinstance(params, dict):
            return tool, params, (
                ToolResult.error(
                    f"Error: Tool '{name}' parameters must be a JSON object, got "
                    f"{type(params).__name__}. Use named parameters like "
                    'tool_name(param1="value1", param2="value2") matching the tool schema.'
                )
            )

        cast_params = tool.cast_params(params)
        errors = tool.validate_params(cast_params)
        if errors:
            return tool, cast_params, (
                ToolResult.error(f"Error: Invalid parameters for tool '{name}': " + "; ".join(errors))
            )
        return tool, cast_params, None

    @classmethod
    def _coerce_argument_value(cls, value: Any) -> Any:
        if value is None:
            return {}
        if not isinstance(value, str):
            return value

        stripped = value.strip()
        if not stripped:
            return {}

        if not stripped.startswith(("{", "[")):
            return value

        try:
            parsed = json.loads(stripped)
        except Exception:
            return value

        return parsed

    @classmethod
    def _coerce_params(cls, tool: Tool, params: Any) -> Any:
        params = cls._coerce_argument_value(params)
        return cls._unwrap_arguments_payload(tool, params)

    @classmethod
    def _unwrap_arguments_payload(cls, tool: Tool, params: Any) -> Any:
        if not isinstance(params, dict) or set(params) != {"arguments"}:
            return params
        properties = (tool.parameters or {}).get("properties", {})
        if isinstance(properties, dict) and "arguments" in properties:
            return params
        return cls._coerce_argument_value(params.get("arguments"))

    async def execute(self, name: str, params: Any) -> Any:
        """Execute a tool by name with given parameters."""
        hint = "\n\n[Analyze the error above and try a different approach.]"
        tool, params, error = self.prepare_call(name, params)
        if error:
            return ToolResult.error(str(error) + hint)

        try:
            assert tool is not None  # guarded by prepare_call()
            result = await tool.execute(**params)
            if is_tool_error_result(name, result):
                return ToolResult.error(str(result) + hint)
            return result
        except Exception as e:
            return ToolResult.error(f"Error executing {name}: {str(e)}" + hint)

    @property
    def tool_names(self) -> list[str]:
        """Get list of registered tool names."""
        return list(self._tools.keys())

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools


class ToolRegistryView:
    """Per-run filtered view over a shared :class:`ToolRegistry`.

    The underlying registry owns tool instances and request context.  This view
    only changes what schemas and calls are visible for one runner invocation.
    """

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        include: set[str] | frozenset[str] | None = None,
        exclude: set[str] | frozenset[str] | None = None,
        allow: Callable[[str], bool] | None = None,
    ) -> None:
        self._registry = registry
        self._include = frozenset(include) if include is not None else None
        self._exclude = frozenset(exclude or ())
        self._allow = allow

    def _allowed(self, name: str) -> bool:
        if self._include is not None:
            base_allowed = name in self._include
        else:
            base_allowed = name not in self._exclude
        if not base_allowed:
            return False
        if self._allow is None:
            return True
        return self._allow(name)

    def get_definitions(self) -> list[dict[str, Any]]:
        definitions = [
            schema
            for schema in self._registry.get_definitions()
            if self._allowed(ToolRegistry._schema_name(schema))
        ]
        builtins: list[dict[str, Any]] = []
        mcp_tools: list[dict[str, Any]] = []
        for schema in definitions:
            name = ToolRegistry._schema_name(schema)
            if name.startswith("mcp_"):
                mcp_tools.append(schema)
            else:
                builtins.append(schema)
        builtins.sort(key=ToolRegistry._schema_name)
        mcp_tools.sort(key=ToolRegistry._schema_name)
        return builtins + mcp_tools

    def get(self, name: str) -> Tool | None:
        if not self._allowed(name):
            return None
        return self._registry.get(name)

    def prepare_call(
        self,
        name: str,
        params: Any,
    ) -> tuple[Tool | None, Any, str | None]:
        if not self._allowed(name):
            return None, params, (
                ToolResult.error(
                    f"Error: Tool '{name}' not found. Available: {', '.join(self.tool_names)}"
                )
            )
        return self._registry.prepare_call(name, params)

    async def execute(self, name: str, params: Any) -> Any:
        hint = "\n\n[Analyze the error above and try a different approach.]"
        if not self._allowed(name):
            return ToolResult.error(
                f"Error: Tool '{name}' not found. Available: {', '.join(self.tool_names)}"
                + hint
            )
        return await self._registry.execute(name, params)

    @property
    def tool_names(self) -> list[str]:
        return [name for name in self._registry.tool_names if self._allowed(name)]

    def __len__(self) -> int:
        return len(self.tool_names)

    def __contains__(self, name: str) -> bool:
        return self._allowed(name) and name in self._registry
