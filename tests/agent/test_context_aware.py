from __future__ import annotations

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.context import ContextAware, RequestContext, request_context
from nanobot.agent.tools.registry import ToolRegistry


class _ContextTool(Tool):
    name = "legacy_context"
    description = "External-style tool using the legacy context setter."
    parameters = {"type": "object", "properties": {}}

    def __init__(self):
        self.last_ctx = None

    def set_context(self, ctx: RequestContext) -> None:
        self.last_ctx = ctx

    async def execute(self, **kwargs):
        return self.last_ctx


async def test_registry_injects_request_context_into_legacy_tool():
    tool = _ContextTool()
    registry = ToolRegistry()
    registry.register(tool)
    ctx = RequestContext(channel="test", chat_id="123", session_key="test:123")

    with request_context(ctx):
        result = await registry.execute(tool.name, {})

    assert result is ctx
    assert tool.last_ctx is ctx


def test_context_tool_is_instance_of_context_aware():
    tool = _ContextTool()
    assert isinstance(tool, ContextAware)
