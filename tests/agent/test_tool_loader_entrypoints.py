import asyncio
from unittest.mock import MagicMock, patch

import pytest

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.context import (
    RequestContext,
    ToolContext,
    current_request_context,
    request_context,
)
from nanobot.agent.tools.loader import ToolLoader
from nanobot.agent.tools.registry import ToolRegistry, is_tool_error_result


def test_loader_discovers_entry_point_tools():
    """Simulate an entry-point plugin being discovered."""
    mock_ep = MagicMock()
    mock_ep.name = "my_plugin"

    class _FakeTool(Tool):
        __name__ = "FakeTool"
        _plugin_discoverable = True
        _scopes = {"core"}

        @property
        def name(self) -> str:
            return "fake_tool"

        @property
        def description(self) -> str:
            return "A fake tool for testing."

        @property
        def parameters(self) -> dict:
            return {"type": "object"}

        @classmethod
        def enabled(cls, ctx):
            return True

        @classmethod
        def create(cls, ctx):
            return MagicMock()

        async def execute(self, **_):
            return "ok"

    mock_ep.load.return_value = _FakeTool

    with patch("nanobot.agent.tools.loader.entry_points", return_value=[mock_ep]):
        loader = ToolLoader()
        discovered = loader._discover_plugins()

    assert "my_plugin" in discovered
    assert discovered["my_plugin"] is _FakeTool


def test_loader_skips_abstract_entry_point_tools():
    """Verify abstract tool classes registered via entry_points are skipped."""
    mock_ep = MagicMock()
    mock_ep.name = "abstract_plugin"

    class _AbstractTool(Tool):
        __name__ = "AbstractTool"
        _plugin_discoverable = True
        _scopes = {"core"}

        @classmethod
        def enabled(cls, ctx):
            return True

        @classmethod
        def create(cls, ctx):
            return MagicMock()

        # Intentionally missing abstract properties (name, description, parameters, execute)

    mock_ep.load.return_value = _AbstractTool

    with patch("nanobot.agent.tools.loader.entry_points", return_value=[mock_ep]):
        loader = ToolLoader()
        discovered = loader._discover_plugins()

    assert "abstract_plugin" not in discovered


@pytest.mark.asyncio
async def test_loader_entry_point_error_wrapper_preserves_tool_api(tmp_path):
    """Only adapt legacy plugin error strings; keep the wrapped tool API intact."""
    mock_ep = MagicMock()
    mock_ep.name = "api_plugin"

    class _ApiPluginTool(Tool):
        config_key = "api_plugin"

        @property
        def name(self) -> str:
            return "api_plugin"

        @property
        def description(self) -> str:
            return "Entry-point plugin with custom tool API methods."

        @property
        def parameters(self) -> dict:
            return {"type": "object", "properties": {"value": {"type": "string"}}}

        @property
        def read_only(self) -> bool:
            return True

        @property
        def concurrency_safe(self) -> bool:
            return False

        def cast_params(self, params: dict) -> dict:
            return {"value": str(params["value"])}

        def validate_params(self, params: dict) -> list[str]:
            return [] if params == {"value": "1"} else ["bad value"]

        def to_schema(self) -> dict:
            return {"name": self.name, "custom": True}

        async def execute(self, **_):
            return "Error: plugin failed"

    mock_ep.load.return_value = _ApiPluginTool

    registry = ToolRegistry()
    with patch("nanobot.agent.tools.loader.entry_points", return_value=[mock_ep]):
        ToolLoader(test_classes=[]).load(
            ToolContext(config=None, workspace=str(tmp_path)),
            registry,
        )

    tool = registry.get("api_plugin")
    assert tool is not None
    assert tool.config_key == "api_plugin"
    assert tool.read_only is True
    assert tool.concurrency_safe is False
    assert tool.cast_params({"value": 1}) == {"value": "1"}
    assert tool.validate_params({"value": "1"}) == []
    assert tool.to_schema() == {"name": "api_plugin", "custom": True}

    result = await tool.execute(value="1")
    assert is_tool_error_result(result) is True
    assert str(result) == "Error: plugin failed"


def _load_plugin(tool_cls: type[Tool]) -> ToolRegistry:
    mock_ep = MagicMock(name=tool_cls.__name__)
    mock_ep.load.return_value = tool_cls
    registry = ToolRegistry()
    with patch("nanobot.agent.tools.loader.entry_points", return_value=[mock_ep]):
        ToolLoader(test_classes=[]).load(ToolContext(config=None, workspace="."), registry)
    return registry


class _ContextPlugin(Tool):
    name = "context_plugin"
    description = "A plugin that reads the request context across an await."
    parameters = {"type": "object", "properties": {}}


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_first", [False, True], ids=["completion", "cancellation"])
async def test_legacy_entry_point_context_is_isolated_between_requests(cancel_first):
    first_started = asyncio.Event()
    second_prepared = asyncio.Event()
    release_first = asyncio.Event()

    class LegacyPlugin(_ContextPlugin):
        def set_context(self, ctx: RequestContext) -> None:
            self.context = ctx

        async def execute(self, **kwargs):
            if self.context.chat_id == "a":
                first_started.set()
                await release_first.wait()
            return self.context.channel, self.context.chat_id, self.context.session_key

    registry = _load_plugin(LegacyPlugin)

    async def request_a():
        with request_context(RequestContext(channel="slack", chat_id="a", session_key="slack:a")):
            return await registry.execute("context_plugin", {})

    async def request_b():
        with request_context(RequestContext(channel="email", chat_id="b", session_key="email:b")):
            # The runner prepares separately from execution and can suspend in a hook.
            tool, params, error = registry.prepare_call("context_plugin", {})
            assert tool is not None and error is None
            second_prepared.set()
            return await tool.execute(**params)

    async with asyncio.timeout(5):
        async with asyncio.TaskGroup() as tasks:
            task_a = tasks.create_task(request_a())
            await first_started.wait()
            task_b = tasks.create_task(request_b())
            await second_prepared.wait()
            if cancel_first:
                task_a.cancel()
            else:
                release_first.set()

    if cancel_first:
        assert task_a.cancelled()
    else:
        assert task_a.result() == ("slack", "a", "slack:a")
    assert task_b.result() == ("email", "b", "email:b")


@pytest.mark.asyncio
async def test_entry_point_without_legacy_setter_remains_concurrent():
    first_started = asyncio.Event()
    second_started = asyncio.Event()

    class ContextVarPlugin(_ContextPlugin):
        async def execute(self, **kwargs):
            ctx = current_request_context()
            assert ctx is not None
            if ctx.chat_id == "a":
                first_started.set()
                await second_started.wait()
            else:
                await first_started.wait()
                second_started.set()
            return current_request_context()

    registry = _load_plugin(ContextVarPlugin)
    contexts = [RequestContext(channel="test", chat_id=chat_id) for chat_id in ("a", "b")]

    async def invoke(ctx):
        with request_context(ctx):
            return await registry.execute("context_plugin", {})

    async with asyncio.timeout(5):
        results = await asyncio.gather(*(invoke(ctx) for ctx in contexts))
    assert results == contexts
