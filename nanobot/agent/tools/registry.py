"""Tool registry for dynamic tool management."""

from copy import deepcopy
from typing import Any

from nanobot.agent.tools.base import Tool

# Minimum enum length that triggers collapsing to just the type in compact mode.
_COMPACT_ENUM_THRESHOLD = 5


class ToolRegistry:
    """
    Registry for agent tools.

    Allows dynamic registration and execution of tools.
    """

    def __init__(self, compact_schemas: bool = False, compact_schemas_max_desc_length: int = 80):
        self._tools: dict[str, Tool] = {}
        self._cached_definitions: list[dict[str, Any]] | None = None
        self._compact_schemas = compact_schemas
        self._compact_schemas_max_desc_length = compact_schemas_max_desc_length

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

    def has(self, name: str) -> bool:
        """Check if a tool is registered."""
        return name in self._tools

    @staticmethod
    def _compact_schema(schema: dict[str, Any], max_desc_length: int) -> dict[str, Any]:
        """Return a compacted copy of an OpenAI function schema.

        Strips ``description`` and ``default`` fields from individual parameters,
        collapses long ``enum`` lists (> ``_COMPACT_ENUM_THRESHOLD`` values) to
        just the parameter type, and truncates the top-level tool description to
        *max_desc_length* characters (0 = no truncation).
        """

        def _strip_props(obj: dict[str, Any]) -> None:
            """Recursively strip verbose fields from a JSON Schema object in-place."""
            props = obj.get("properties")
            if not isinstance(props, dict):
                return
            for prop in props.values():
                if not isinstance(prop, dict):
                    continue
                prop.pop("description", None)
                prop.pop("default", None)
                enum_vals = prop.get("enum")
                if isinstance(enum_vals, list) and len(enum_vals) > _COMPACT_ENUM_THRESHOLD:
                    prop.pop("enum", None)
                # Recurse into nested objects and array item schemas
                if prop.get("type") == "object" or "properties" in prop:
                    _strip_props(prop)
                items = prop.get("items")
                if isinstance(items, dict):
                    items.pop("description", None)
                    items.pop("default", None)

        schema = deepcopy(schema)
        fn = schema.get("function")
        if not isinstance(fn, dict):
            return schema

        desc = fn.get("description")
        if isinstance(desc, str) and max_desc_length > 0 and len(desc) > max_desc_length:
            fn["description"] = desc[:max_desc_length]

        params = fn.get("parameters")
        if isinstance(params, dict):
            _strip_props(params)

        return schema

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

        if self._compact_schemas:
            return [
                self._compact_schema(s, self._compact_schemas_max_desc_length)
                for s in self._cached_definitions
            ]
        return self._cached_definitions

    def prepare_call(
        self,
        name: str,
        params: dict[str, Any],
    ) -> tuple[Tool | None, dict[str, Any], str | None]:
        """Resolve, cast, and validate one tool call."""
        # Guard against invalid parameter types (e.g., list instead of dict)
        if not isinstance(params, dict) and name in ("write_file", "read_file"):
            return (
                None,
                params,
                (
                    f"Error: Tool '{name}' parameters must be a JSON object, got {type(params).__name__}. "
                    'Use named parameters: tool_name(param1="value1", param2="value2")'
                ),
            )

        tool = self._tools.get(name)
        if not tool:
            return (
                None,
                params,
                (f"Error: Tool '{name}' not found. Available: {', '.join(self.tool_names)}"),
            )

        cast_params = tool.cast_params(params)
        errors = tool.validate_params(cast_params)
        if errors:
            return (
                tool,
                cast_params,
                (f"Error: Invalid parameters for tool '{name}': " + "; ".join(errors)),
            )
        return tool, cast_params, None

    async def execute(self, name: str, params: dict[str, Any]) -> Any:
        """Execute a tool by name with given parameters."""
        _HINT = "\n\n[Analyze the error above and try a different approach.]"
        tool, params, error = self.prepare_call(name, params)
        if error:
            return error + _HINT

        try:
            assert tool is not None  # guarded by prepare_call()
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
