from __future__ import annotations

from collections.abc import Callable
from typing import Any

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.mcp_search_index import McpSearchIndex
from nanobot.agent.tools.registry import ToolRegistry


def mcp_tool_view(registry: ToolRegistry, schema_token_budget: int) -> ToolRegistry:
    """Create a private discovery surface only when the allowed MCP catalog exceeds budget."""
    if not schema_token_budget or registry.has("tool_search") or registry.mcp_schema_tokens() <= schema_token_budget:
        return registry
    return _McpRunTools(registry)


class _SearchTool(Tool):
    _plugin_discoverable = False

    def __init__(self, servers: list[str], search: Callable[[str], list[str]]) -> None:
        self._search = search
        self._servers = servers

    @property
    def name(self) -> str:
        return "tool_search"

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {"query": {"type": "string", "minLength": 1}}, "required": ["query"]}

    @property
    def description(self) -> str:
        return (
            "Find and load MCP tools by service, action and object (English keywords or exact tool name). "
            "Call a matching tool directly on your next step. Available services: " + ", ".join(self._servers)
        )

    async def execute(self, **kwargs: Any) -> str:
        matches = self._search(kwargs["query"])
        return "Available now: " + ", ".join(matches) if matches else "No matches. Try other service or action keywords."


class _McpRunTools(ToolRegistry):
    def __init__(self, source: ToolRegistry) -> None:
        super().__init__()
        self._source = source
        self._snapshot: list[dict[str, Any]] | None = None
        self._catalog: dict[str, Tool] = {}
        self._index: McpSearchIndex | None = None
        self._loaded: dict[str, None] = {}
        self._visible: list[dict[str, Any]] = []
        self._schemas: dict[str, dict[str, Any]] = {}
        self._refresh()

    def _refresh(self) -> None:
        # Registration/reconnect replaces the source snapshot. Never execute a retired wrapper.
        snapshot = self._source.get_definitions()
        if snapshot is self._snapshot:
            return
        self._snapshot = snapshot
        self._index = None
        self._catalog = {}
        self._schemas = {}
        self._visible = []
        servers: set[str] = set()
        for old in self.tool_names:
            self.unregister(old)
        for schema in snapshot:
            name = self._schema_name(schema)
            tool = self._source.get(name)
            if tool is None:
                continue
            if tool.mcp_server is None:
                self.register(tool)
                self._visible.append(schema)
            else:
                servers.add(tool.mcp_server)
                self._schemas[name] = schema
                self._catalog[name] = tool
        search = _SearchTool(sorted(servers), self._search)
        self.register(search)
        self._visible.append(search.to_schema())
        self._loaded = {name: None for name in self._loaded if name in self._catalog}
        for name in self._loaded:
            self.register(self._catalog[name])
            self._visible.append(self._schemas[name])

    def _search(self, query: str) -> list[str]:
        self._refresh()
        if self._index is None:
            self._index = McpSearchIndex(list(self._catalog.values()))
        matches = self._index.search(query)
        new = [name for name in matches if name not in self._loaded]
        if new:
            # Append, don't re-sort or mutate an already-issued request's tools list.
            self._visible = [*self._visible, *(self._schemas[name] for name in new)]
            for name in new:
                self.register(self._catalog[name])
                self._loaded[name] = None
        return matches

    def get(self, name: str) -> Tool | None:
        self._refresh()
        return super().get(name)

    def get_definitions(self) -> list[dict[str, Any]]:
        self._refresh()
        return self._visible
