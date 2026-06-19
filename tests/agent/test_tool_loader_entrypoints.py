from unittest.mock import MagicMock, patch

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.loader import ToolLoader


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
