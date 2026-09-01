import pytest

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.context import ToolContext
from nanobot.agent.tools.loader import ToolLoader


class _CoreOnlyTool(Tool):
    _scopes = {"core"}

    @property
    def name(self):
        return "core_only"

    @property
    def description(self):
        return "..."

    @property
    def parameters(self):
        return {"type": "object"}

    async def execute(self, **_):
        return "ok"


class _SubagentOnlyTool(Tool):
    _scopes = {"subagent"}

    @property
    def name(self):
        return "sub_only"

    @property
    def description(self):
        return "..."

    @property
    def parameters(self):
        return {"type": "object"}

    async def execute(self, **_):
        return "ok"


class _UniversalTool(Tool):
    _scopes = {"core", "subagent", "memory"}

    @property
    def name(self):
        return "universal"

    @property
    def description(self):
        return "..."

    @property
    def parameters(self):
        return {"type": "object"}

    async def execute(self, **_):
        return "ok"


@pytest.mark.asyncio
async def test_loader_filters_by_scope():
    from nanobot.agent.tools.registry import ToolRegistry

    loader = ToolLoader(test_classes=[_CoreOnlyTool, _SubagentOnlyTool, _UniversalTool])

    registry = ToolRegistry()
    ctx = ToolContext(config={}, workspace="/tmp")
    loader.load(ctx, registry, scope="core")

    assert registry.has("core_only")
    assert not registry.has("sub_only")
    assert registry.has("universal")
