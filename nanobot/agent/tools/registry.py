"""Tool registry for dynamic tool management."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, cast

from nanobot.agent.tools.base import Tool, ToolResult
from nanobot.agent.tools.context import ContextAware, current_request_context

if TYPE_CHECKING:
    from nanobot.runtime_context import RuntimeContextProvider


def is_tool_error_result(result: Any) -> bool:
    return isinstance(result, ToolResult) and result.is_error


class ToolRegistry:
    """
    Registry for agent tools.

    Allows dynamic registration and execution of tools.
    """

    def __init__(self, max_consecutive_tool_failures: int = 3):
        self._tools: dict[str, Tool] = {}
        self._cached_definitions: list[dict[str, Any]] | None = None
        # Break infinite retry loops when the model keeps sending bad args (#4864)
        self.max_consecutive_tool_failures = max(1, int(max_consecutive_tool_failures))
        self._consecutive_failures: dict[str, int] = {}

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

    def get_runtime_context_providers(self) -> list[RuntimeContextProvider]:
        """Return tool-owned providers in stable tool-name order."""
        providers: list[RuntimeContextProvider] = []
        for name in sorted(self._tools):
            provider = self._tools[name].runtime_context_provider()
            if provider is not None:
                providers.append(provider)
        return providers

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
        return self.get(name) is not None

    @staticmethod
    def _schema_name(schema: dict[str, Any]) -> str:
        """Extract a normalized tool name from either OpenAI or flat schemas."""
        fn = schema.get("function")
        if isinstance(fn, dict):
            name = cast(dict[str, Any], fn).get("name")
            if isinstance(name, str):
                return name
        name = schema.get("name")
        return name if isinstance(name, str) else ""

    def get_definitions(self) -> list[dict[str, Any]]:
        """Get tool definitions with stable ordering for cache-friendly prompts.

        Built-in tools are sorted first as a stable prefix, then MCP tools are
        sorted and appended. The result is cached until the next
        register/unregister call.
        """
        if self._cached_definitions is None:
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
        tool = self.get(name)
        if not tool:
            suggestion = self._suggest_name(str(name))
            hint = f" Did you mean '{suggestion}'? Tool names must match exactly." if suggestion else ""
            return None, params, (
                ToolResult.error(
                    f"Error: Tool '{name}' not found.{hint} Available: {', '.join(self.tool_names)}"
                )
            )
        # Compatibility for external tools that still implement the legacy
        # setter protocol. Built-ins read the authoritative ContextVar
        # directly and never copy routing state.
        if isinstance(tool, ContextAware) and (ctx := current_request_context()) is not None:
            tool.set_context(ctx)

        params = self._coerce_params(tool, params)
        # Truncated/malformed JSON object strings (e.g. '{"recap": "') must not
        # be executed — they cause complete_goal/update_goal retry loops (#4864).
        # Keep the "parameters must be a JSON object" phrase so existing registry
        # / runner tests and model retries still match on the same signal.
        if isinstance(params, str):
            stripped = params.strip()
            if stripped.startswith(("{", "[")):
                return tool, params, (
                    ToolResult.error(
                        f"Error: Tool '{name}' parameters must be a JSON object, got "
                        f"truncated or invalid JSON arguments: {stripped[:120]!r}. "
                        f"Retry with a complete JSON object matching the tool schema "
                        f'(for goals: {{"action": "complete", "recap": "..."}}).'
                    )
                )
        if not isinstance(params, dict):
            return tool, params, (
                ToolResult.error(
                    f"Error: Tool '{name}' parameters must be a JSON object, got "
                    f"{type(params).__name__}. Use named parameters like "
                    'tool_name(param1="value1", param2="value2") matching the tool schema.'
                )
            )

        cast_params = tool.cast_params(cast(dict[str, Any], params))
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
        if not isinstance(params, dict):
            return params
        arguments_payload = cast(dict[str, Any], params)
        if set(arguments_payload) != {"arguments"}:
            return arguments_payload
        properties = (tool.parameters or {}).get("properties", {})
        if isinstance(properties, dict) and "arguments" in properties:
            return arguments_payload
        return cls._coerce_argument_value(arguments_payload.get("arguments"))

    def _record_tool_failure(self, name: str) -> int:
        count = self._consecutive_failures.get(name, 0) + 1
        self._consecutive_failures[name] = count
        return count

    def _clear_tool_failure(self, name: str) -> None:
        self._consecutive_failures.pop(name, None)

    def consecutive_failure_count(self, name: str) -> int:
        """How many consecutive failures the named tool has produced."""
        return self._consecutive_failures.get(name, 0)

    async def execute(self, name: str, params: Any) -> Any:
        """Execute a tool by name with given parameters."""
        hint = "\n\n[Analyze the error above and try a different approach.]"
        tool, params, error = self.prepare_call(name, params)
        if error:
            fails = self._record_tool_failure(str(name))
            if fails >= self.max_consecutive_tool_failures:
                return ToolResult.error(
                    str(error)
                    + f"\n\n[Circuit-break: tool '{name}' failed {fails} times in a row "
                    f"(malformed args or execution). Stop retrying this tool; "
                    f"finish the user turn or use a different approach. Fixes #4864 loops.]"
                )
            return ToolResult.error(str(error) + hint)

        try:
            assert tool is not None  # guarded by prepare_call()
            result = await tool.execute(**params)
            if is_tool_error_result(result):
                fails = self._record_tool_failure(str(name))
                if fails >= self.max_consecutive_tool_failures:
                    return ToolResult.error(
                        str(result)
                        + f"\n\n[Circuit-break: tool '{name}' failed {fails} times in a row. "
                        f"Stop retrying; do not call it again with the same bad args.]"
                    )
                return ToolResult.error(str(result) + hint)
            self._clear_tool_failure(str(name))
            return result
        except Exception as e:
            fails = self._record_tool_failure(str(name))
            if fails >= self.max_consecutive_tool_failures:
                return ToolResult.error(
                    f"Error executing {name}: {str(e)}"
                    + f"\n\n[Circuit-break: tool '{name}' failed {fails} times in a row.]"
                )
            return ToolResult.error(f"Error executing {name}: {str(e)}" + hint)

    @property
    def tool_names(self) -> list[str]:
        """Get list of registered tool names."""
        return list(self._tools.keys())

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return self.has(name)
