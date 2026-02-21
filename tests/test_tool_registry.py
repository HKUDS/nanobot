from typing import Any

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.registry import ToolRegistry


class EchoTool(Tool):
    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "echoes message"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        }

    async def execute(self, **kwargs: Any) -> str:
        return kwargs["message"]


class BrokenTool(Tool):
    @property
    def name(self) -> str:
        return "broken"

    @property
    def description(self) -> str:
        return "always fails"

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs: Any) -> str:
        raise RuntimeError("boom")


def test_register_get_unregister_lifecycle() -> None:
    """Registers, fetches, and unregisters tools by name."""
    registry = ToolRegistry()
    tool = EchoTool()
    registry.register(tool)
    assert registry.get("echo") is tool
    assert "echo" in registry
    registry.unregister("echo")
    assert registry.get("echo") is None
    assert "echo" not in registry


def test_get_definitions_and_tool_names() -> None:
    """Returns OpenAI schemas and current tool names."""
    registry = ToolRegistry()
    registry.register(EchoTool())
    definitions = registry.get_definitions()
    assert len(definitions) == 1
    assert definitions[0]["function"]["name"] == "echo"
    assert registry.tool_names == ["echo"]


async def test_execute_success() -> None:
    """Executes registered tool and returns success output."""
    registry = ToolRegistry()
    registry.register(EchoTool())
    result = await registry.execute("echo", {"message": "hello"})
    assert result == "hello"


async def test_execute_not_found() -> None:
    """Returns not-found error when tool name is unknown."""
    registry = ToolRegistry()
    result = await registry.execute("missing", {})
    assert result == "Error: Tool 'missing' not found"


async def test_execute_exception() -> None:
    """Returns execution error when tool raises an exception."""
    registry = ToolRegistry()
    registry.register(BrokenTool())
    result = await registry.execute("broken", {})
    assert result == "Error executing broken: boom"
