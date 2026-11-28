from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from typing import TYPE_CHECKING, Any, cast

from nanobot.agent.tools.base import Tool, ToolResult
from nanobot.agent.tools.mcp import MCPToolWrapper
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.tool_search_index import ToolSearchIndex
from nanobot.providers.base import ToolCallRequest, parse_tool_arguments

if TYPE_CHECKING:
    from nanobot.agent.tools.mcp_metadata import MCPServerInfo

_PAGE = 5
DISCOVERY_TOOLS = frozenset({"tool_search", "call_tool"})


def tool_view(registry: ToolRegistry, *, disabled: frozenset[str] = frozenset()) -> ToolRegistry:
    """Keep permitted direct tools visible and scope MCP discovery to this run."""
    source = registry.excluding(disabled) if disabled else registry
    if any(isinstance(source.get(name), MCPToolWrapper) for name in source.tool_names):
        return _RunTools(source)
    return source


def mcp_server_directory(tools: ToolRegistry) -> tuple[MCPServerInfo, ...]:
    """Describe only servers reachable through this view's discovery bridge."""
    return tools.server_directory() if isinstance(tools, _RunTools) else ()


class _SearchTool(Tool):
    _plugin_discoverable = False

    @property
    def name(self) -> str:
        return "tool_search"

    @property
    def description(self) -> str:
        return (
            "Find MCP tools by server, operation, requested field, or exact tool name. "
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
        self.disabled_names = source.disabled_names
        self._index: ToolSearchIndex | None = None
        self._catalog: dict[str, MCPToolWrapper] = {}
        self._discovered: dict[str, MCPToolWrapper] = {}
        self._gateways = (_SearchTool(self._search), _CallTool(self))

    def _refresh(self) -> None:
        # Rebuild only on registration changes (including same-name reconnects), never on search.
        snapshot = self._source.get_definitions()
        if snapshot is self._snapshot:
            return
        direct: dict[str, Tool] = {}
        deferred: dict[str, MCPToolWrapper] = {}
        for name in self._source.tool_names:
            tool = self._source.get(name)
            if isinstance(tool, MCPToolWrapper):
                deferred[name] = tool
            elif tool is not None:
                direct[name] = tool
        visible = [schema for schema in snapshot if self._schema_name(schema) in direct]
        if deferred and not any(name in self.disabled_names or self._source.has(name) for name in DISCOVERY_TOOLS):
            for gateway in self._gateways:
                direct[gateway.name] = gateway
                visible.append(gateway.to_schema())
        else:
            deferred.clear()
        self._tools = direct
        self._catalog = deferred
        self._discovered = {name: old for name, old in self._discovered.items() if deferred.get(name) is old}
        self._index = None
        self._cached_definitions = visible
        self._snapshot = snapshot

    def get(self, name: str) -> Tool | None:
        self._refresh()
        return super().get(name)

    @property
    def tool_names(self) -> list[str]:
        self._refresh()
        return super().tool_names

    def __len__(self) -> int:
        self._refresh()
        return super().__len__()

    def get_definitions(self) -> list[dict[str, Any]]:
        self._refresh()
        return super().get_definitions()

    def excluding(self, disabled: frozenset[str]) -> ToolRegistry:
        # A new restriction must filter searches and dispatch, not just the visible gateway names.
        return tool_view(self._source, disabled=disabled) if disabled - self.disabled_names else self

    def server_directory(self) -> tuple[MCPServerInfo, ...]:
        self._refresh()
        records = {tool.server_info for tool in self._catalog.values()}
        return tuple(sorted(records, key=lambda info: (
            info.name, info.description is not None, info.description or "",
            info.instructions is not None, info.instructions or "",
        )))

    def discovered_source(self, name: str) -> ToolRegistry | None:
        self._refresh()
        return self._source if name in self._discovered else None

    def _search(self, query: str) -> str:
        self._refresh()
        if self._index is None:
            self._index = ToolSearchIndex(list(self._catalog.values()))
        exact = query.strip()
        ranked = [exact] if exact in self._catalog else self._index.search(query, limit=2 * _PAGE)
        matches = [self._catalog[name] for name in ranked[:_PAGE]]
        self._discovered.update((tool.name, tool) for tool in matches)
        result: dict[str, Any] = {"tools": [tool.to_schema()["function"] for tool in matches],
                                  "other_matches": ranked[_PAGE:]}
        if not ranked:
            result["hint"] = "Try the MCP server name, an operation, or a parameter name."
            if nearest := self._index.nearest_name(query):
                result["suggestion"] = {"name": nearest, "source": self._catalog[nearest].server_info.name}
        return json.dumps(result, ensure_ascii=False, separators=(",", ":"))


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
