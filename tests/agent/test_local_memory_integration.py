import asyncio

from nanobot.agent.hook import AgentHookContext
from nanobot.agent.local_memory import LocalMemoryConfig, forget_local_memory, has_local_memory_server, search_local_memory
from nanobot.agent.local_memory_hook import LocalMemoryHook
from nanobot.agent.tools.registry import ToolRegistry


class _FakeTool:
    def __init__(self, name, result):
        self.name = name
        self.description = name
        self.parameters = {"type": "object", "properties": {}, "additionalProperties": True}
        self._result = result
        self.calls = []

    def cast_params(self, params):
        return params

    def validate_params(self, params):
        return []

    async def execute(self, **kwargs):
        self.calls.append(kwargs)
        return self._result


def _registry_with_tool(name, result):
    registry = ToolRegistry()
    tool = _FakeTool(name, result)
    registry.register(tool)
    return registry


def _registry_with_tools(*tool_specs):
    registry = ToolRegistry()
    tools = {}
    for name, result in tool_specs:
        tool = _FakeTool(name, result)
        registry.register(tool)
        tools[name] = tool
    return registry, tools


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


def test_forget_local_memory_deprecates_matching_record():
    registry, tools = _registry_with_tools(
        (
            "mcp_local_memory_memory_search",
            {"matches": [{"record_id": "rec_1", "title": "Restart path", "summary": "Use restart-by-agent.sh"}]},
        ),
        ("mcp_local_memory_memory_deprecate", {"ok": True}),
    )
    cfg = LocalMemoryConfig(enabled=True, search_first=True)

    result = asyncio.run(forget_local_memory(registry, "restart path", cfg))

    assert result is True
    assert tools["mcp_local_memory_memory_deprecate"].calls
    call = tools["mcp_local_memory_memory_deprecate"].calls[0]
    assert call["record_id"] == "rec_1"
    assert "forget" in call["reason"].lower()


def test_local_memory_hook_marks_forget_request_before_iteration():
    cfg = LocalMemoryConfig(enabled=True, search_first=True)
    hook = LocalMemoryHook(cfg)
    registry = _registry_with_tool("mcp_local_memory_memory_search", {"matches": []})
    context = AgentHookContext(
        iteration=1,
        messages=[{"role": "user", "content": "forget that restart path"}],
        agent=type("Agent", (), {"tools": registry})(),
    )

    asyncio.run(hook.before_iteration(context))

    assert context.memory_action == "forget"
    assert context.memory_target_query == "restart path"
    assert context.messages[0]["role"] == "system"
    assert "forget" in context.messages[0]["content"].lower()
