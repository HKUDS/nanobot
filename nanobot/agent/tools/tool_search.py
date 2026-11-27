from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from typing import Any

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.registry import CORE_TOOL_NAMES, ToolRegistry
from nanobot.agent.tools.tool_search_index import ToolSearchIndex

_PAGE = 5


def tool_view(registry: ToolRegistry, schema_token_budget: int) -> ToolRegistry:
    """Create a run-local view when the allowed non-core tools exceed budget."""
    if not schema_token_budget or registry.has("tool_search") or registry.searchable_schema_tokens() <= schema_token_budget:
        return registry
    return _RunTools(registry)


class _SearchTool(Tool):
    _plugin_discoverable = False

    def __init__(self, groups: list[str], search: Callable[[str], tuple[list[str], list[str]]]) -> None:
        self._search = search
        self._groups = groups

    @property
    def name(self) -> str:
        return "tool_search"

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {"query": {"type": "string", "minLength": 1}}, "required": ["query"]}

    @property
    def description(self) -> str:
        hints = " Catalog groups include: " + ", ".join(self._groups) + "." if self._groups else ""
        return (
            "Find additional tools by the specific operation or result you need. Use English keywords "
            "or an exact tool name. Include the domain and requested field, not record IDs. "
            "If the matches do not provide that result, search again with different terms."
            + hints
        )

    async def execute(self, **kwargs: Any) -> str:
        matches, other = self._search(kwargs["query"])
        if not matches:
            return "No matches. Try other service or action keywords."
        result = "Available now: " + ", ".join(matches)
        if other:
            result += "\nOther matches (search by exact name to load): " + ", ".join(other)
        return result


class _RunTools(ToolRegistry):
    def __init__(self, source: ToolRegistry) -> None:
        super().__init__()
        self._source = source
        self._snapshot: list[dict[str, Any]] | None = None
        self._catalog: dict[str, Tool] = {}
        self._index: ToolSearchIndex | None = None
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
        groups: Counter[str] = Counter()
        for old in self.tool_names:
            self.unregister(old)
        for schema in snapshot:
            name = self._schema_name(schema)
            tool = self._source.get(name)
            if tool is None:
                continue
            if name in CORE_TOOL_NAMES:
                self.register(tool)
                self._visible.append(schema)
            else:
                # MCP has explicit namespaces; plugins often use a shared name prefix.
                group = tool.mcp_server or (name.split("_", 1)[0] if "_" in name else "")
                if group:
                    groups[group] += 1
                self._schemas[name] = schema
                self._catalog[name] = tool
        hints = [name for name, count in groups.most_common(16) if count > 1]
        search = _SearchTool(hints, self._search)
        self.register(search)
        self._visible.append(search.to_schema())
        self._loaded = {name: None for name in self._loaded if name in self._catalog}
        for name in self._loaded:
            self.register(self._catalog[name])
            self._visible.append(self._schemas[name])

    def _search(self, query: str) -> tuple[list[str], list[str]]:
        self._refresh()
        if self._index is None:
            self._index = ToolSearchIndex(list(self._catalog.values()))
        ranked = self._index.search(query, limit=2 * _PAGE)
        matches = ranked[:_PAGE]
        new = [name for name in matches if name not in self._loaded]
        if new:
            # Append, don't re-sort or mutate an already-issued request's tools list.
            self._visible = [*self._visible, *(self._schemas[name] for name in new)]
            for name in new:
                self.register(self._catalog[name])
                self._loaded[name] = None
        return matches, [name for name in ranked[_PAGE:] if name not in self._loaded]

    def get(self, name: str) -> Tool | None:
        self._refresh()
        return super().get(name)

    def get_definitions(self) -> list[dict[str, Any]]:
        self._refresh()
        return self._visible
