from __future__ import annotations

from nanobot.agent.tools.context import ContextAware, RequestContext


class _ContextTool:
    def __init__(self):
        self.last_ctx = None

    def set_context(self, ctx: RequestContext) -> None:
        self.last_ctx = ctx


def test_context_aware_sets_request_context():
    tool = _ContextTool()
    ctx = RequestContext(channel="test", chat_id="123", session_key="test:123")
    tool.set_context(ctx)
    assert tool.last_ctx.channel == "test"


def test_context_tool_is_instance_of_context_aware():
    tool = _ContextTool()
    assert isinstance(tool, ContextAware)
