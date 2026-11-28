from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from typing import Any, cast

from nanobot.agent.tools.base import Tool, ToolResult
from nanobot.agent.tools.registry import CORE_TOOL_NAMES, ToolRegistry
from nanobot.agent.tools.tool_search_index import ToolSearchIndex
from nanobot.providers.base import ToolCallRequest, parse_tool_arguments

_PAGE = 5
DISCOVERY_TOOLS = frozenset({"tool_search", "call_tool"})


def tool_view(registry: ToolRegistry, schema_token_budget: int, *, disabled: frozenset[str] = frozenset()) -> ToolRegistry:
    """Use fixed discovery entry points only when the allowed non-core catalog exceeds budget."""
    if (not schema_token_budget or not DISCOVERY_TOOLS.isdisjoint(disabled)
            or any(registry.has(name) for name in DISCOVERY_TOOLS)
            or registry.searchable_schema_tokens() <= schema_token_budget):
        return registry
    return _RunTools(registry)


class _SearchTool(Tool):
    _plugin_discoverable = False

    @property
    def name(self) -> str:
        return "tool_search"

    @property
    def description(self) -> str:
        return (
            "Find additional tools by operation and requested field, using English keywords or an exact tool name. "
            "Returns names and full parameter schemas. To execute a match use call_tool, not a direct function call. "
            "Search an other_matches name to get its schema."
        )

    def __init__(self, search: Callable[[str], str]) -> None:
        self._search = search

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {"query": {"type": "string", "minLength": 1}}, "required": ["query"]}

    async def execute(self, **kwargs: Any) -> str:
        return self._search(kwargs["query"])


class _CallTool(Tool):
    _plugin_discoverable = False

    @property
    def name(self) -> str:
        return "call_tool"

    @property
    def description(self) -> str:
        return (
            "Execute a tool returned by tool_search in this run. Pass its exact name and an arguments object "
            "matching its returned parameter schema. For tools already listed directly, call them directly."
        )

    def __init__(self, catalog: _RunTools) -> None:
        self._catalog = catalog

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {"name": {"type": "string", "minLength": 1},
                "arguments": {"type": "object", "additionalProperties": True}},
                "required": ["name", "arguments"], "additionalProperties": False}

    async def execute(self, **kwargs: Any) -> Any:
        name = kwargs["name"]
        source = self._catalog.discovered_source(name)
        if source is None:
            return ToolResult.error("Tool not available through call_tool. Search for it with tool_search in this run.")
        return await source.execute(name, kwargs["arguments"])


class _RunTools(ToolRegistry):
    def __init__(self, source: ToolRegistry) -> None:
        super().__init__()
        self._source = source
        self._snapshot: list[dict[str, Any]] | None = None
        self._index: ToolSearchIndex | None = None
        self._catalog: dict[str, Tool] = {}
        self._discovered: dict[str, Tool] = {}
        for name in sorted(CORE_TOOL_NAMES - DISCOVERY_TOOLS):
            if (tool := source.get(name)) is not None:
                self.register(tool)
        self.register(_SearchTool(self._search))
        self.register(_CallTool(self))

    def get(self, name: str) -> Tool | None:
        registered = super().get(name)
        if registered is None or name in DISCOVERY_TOOLS:
            return registered
        return self._source.get(name)

    def discovered_source(self, name: str) -> ToolRegistry | None:
        # A reconnect may replace a tool under the same name with a different schema.
        known = self._discovered.get(name)
        return self._source if known is not None and self._source.get(name) is known else None

    def _search(self, query: str) -> str:
        snapshot = self._source.get_definitions()
        if snapshot is not self._snapshot or self._index is None:
            self._snapshot = snapshot
            self._catalog = {name: tool for name in self._source.tool_names if name not in CORE_TOOL_NAMES
                             and (tool := self._source.get(name)) is not None}
            self._index = ToolSearchIndex(list(self._catalog.values()))
        exact = query.strip()
        ranked = [exact] if exact in self._catalog else self._index.search(query, limit=2 * _PAGE)
        matches = [self._catalog[name] for name in ranked[:_PAGE]]
        self._discovered.update((tool.name, tool) for tool in matches)
        schemas = [tool.to_schema() for tool in matches]
        return json.dumps(
            {"tools": [schema.get("function", schema) for schema in schemas], "other_matches": ranked[_PAGE:]},
            ensure_ascii=False, separators=(",", ":"),
        )


def discovery_target(tools: ToolRegistry, call: ToolCallRequest) -> tuple[ToolRegistry, ToolCallRequest]:
    """Keep the wire call intact, but apply normal execution policy and hooks to the discovered operation."""
    if not isinstance(tools, _RunTools) or call.name != "call_tool":
        return tools, call
    payload = parse_tool_arguments(call.arguments)
    if isinstance(payload, dict):
        envelope = cast(dict[str, Any], payload)
        if envelope.keys() == {"name", "arguments"}:
            name, args = envelope["name"], envelope["arguments"]
            if isinstance(name, str) and isinstance(args, dict) and (source := tools.discovered_source(name)) is not None:
                return source, replace(call, name=name, arguments=args)
    return tools, call
