import asyncio

from nanobot.agent.local_memory import LocalMemoryConfig, has_local_memory_server, search_local_memory
from nanobot.agent.tools.registry import ToolRegistry


class _FakeTool:
    def __init__(self, name, result):
        self.name = name
        self.description = name
        self.parameters = {"type": "object", "properties": {}, "additionalProperties": True}
        self._result = result

    def cast_params(self, params):
        return params

    def validate_params(self, params):
        return []

    async def execute(self, **kwargs):
        return self._result


def _registry_with_tool(name, result):
    registry = ToolRegistry()
    registry.register(_FakeTool(name, result))
    return registry


def test_has_local_memory_server_accepts_flat_memory_search_name():
    registry = _registry_with_tool(
        "mcp_local_memory_memory_search",
        {"matches": []},
    )
    assert has_local_memory_server(registry, "local_memory") is True


def test_has_local_memory_server_accepts_flat_memory_build_context_name():
    registry = _registry_with_tool(
        "mcp_local_memory_memory_build_context",
        {"context": "remembered context"},
    )
    assert has_local_memory_server(registry, "local_memory") is True


def test_search_local_memory_prefers_build_context_flat_name():
    registry = _registry_with_tool(
        "mcp_local_memory_memory_build_context",
        {"context": "compact retained context"},
    )
    cfg = LocalMemoryConfig(enabled=True, search_first=True)

    result = asyncio.run(search_local_memory(registry, "continue", cfg))

    assert result is not None
    assert result.heading == "Supplemental local-memory recall"
    assert "compact retained context" in result.content


def test_search_local_memory_falls_back_to_flat_memory_search_name():
    registry = _registry_with_tool(
        "mcp_local_memory_memory_search",
        {"matches": [{"title": "Restart path", "summary": "Use the agent restart script."}]},
    )
    cfg = LocalMemoryConfig(enabled=True, search_first=True)

    result = asyncio.run(search_local_memory(registry, "continue", cfg))

    assert result is not None
    assert "Restart path" in result.content
    assert "agent restart script" in result.content
