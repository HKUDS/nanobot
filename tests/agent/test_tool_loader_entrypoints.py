from unittest.mock import MagicMock, patch

import pytest

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.context import ToolContext
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
    assert is_tool_error_result("api_plugin", result) is True
    assert str(result) == "Error: plugin failed"
