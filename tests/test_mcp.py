"""Tests for MCP client integration (config, adapter, manager, registry)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.config.schema import McpConfig, McpServerConfig
from nanobot.mcp.tools import McpToolAdapter
from nanobot.mcp.client import McpClientManager


# ============================================================================
# Config parsing
# ============================================================================


def test_mcp_server_config_http_defaults() -> None:
    cfg = McpServerConfig()
    assert cfg.enabled is True
    assert cfg.type == "http"
    assert cfg.url == ""
    assert cfg.headers == {}
    assert cfg.command == ""
    assert cfg.args == []
    assert cfg.env == {}


def test_mcp_server_config_from_dict_http() -> None:
    data = {
        "type": "http",
        "url": "http://localhost:8000/mcp",
        "headers": {"Authorization": "Bearer tok"},
    }
    cfg = McpServerConfig.model_validate(data)
    assert cfg.type == "http"
    assert cfg.url == "http://localhost:8000/mcp"
    assert cfg.headers == {"Authorization": "Bearer tok"}


def test_mcp_server_config_from_dict_stdio() -> None:
    data = {
        "type": "stdio",
        "command": "python",
        "args": ["server.py", "--verbose"],
        "env": {"API_KEY": "secret"},
    }
    cfg = McpServerConfig.model_validate(data)
    assert cfg.type == "stdio"
    assert cfg.command == "python"
    assert cfg.args == ["server.py", "--verbose"]
    assert cfg.env == {"API_KEY": "secret"}


def test_mcp_server_config_disabled() -> None:
    cfg = McpServerConfig.model_validate({"enabled": False, "url": "http://x"})
    assert cfg.enabled is False


def test_mcp_config_empty() -> None:
    cfg = McpConfig()
    assert cfg.servers == {}


def test_mcp_config_multiple_servers() -> None:
    data = {
        "servers": {
            "srv1": {"type": "http", "url": "http://a/mcp"},
            "srv2": {"type": "stdio", "command": "node", "args": ["s.js"]},
        }
    }
    cfg = McpConfig.model_validate(data)
    assert len(cfg.servers) == 2
    assert cfg.servers["srv1"].url == "http://a/mcp"
    assert cfg.servers["srv2"].command == "node"


# ============================================================================
# McpToolAdapter
# ============================================================================


def _make_adapter(
    server: str = "test_srv",
    tool: str = "greet",
    desc: str = "Say hello",
    schema: dict | None = None,
    client: Any = None,
) -> McpToolAdapter:
    return McpToolAdapter(
        server_name=server,
        tool_name=tool,
        tool_description=desc,
        input_schema=schema or {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
        client=client or MagicMock(),
    )


def test_adapter_name_format() -> None:
    adapter = _make_adapter(server="google_workspace", tool="list_emails")
    assert adapter.name == "mcp__google_workspace__list_emails"


def test_adapter_description() -> None:
    adapter = _make_adapter(desc="Fetch calendar events")
    assert adapter.description == "Fetch calendar events"


def test_adapter_default_description() -> None:
    adapter = McpToolAdapter(
        server_name="s",
        tool_name="t",
        tool_description="",
        input_schema={},
        client=MagicMock(),
    )
    assert "MCP tool t from s" in adapter.description


def test_adapter_parameters() -> None:
    schema = {
        "type": "object",
        "properties": {"q": {"type": "string"}},
        "required": ["q"],
    }
    adapter = _make_adapter(schema=schema)
    assert adapter.parameters == schema


def test_adapter_to_schema() -> None:
    adapter = _make_adapter()
    schema = adapter.to_schema()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "mcp__test_srv__greet"
    assert schema["function"]["description"] == "Say hello"
    assert "properties" in schema["function"]["parameters"]


def test_adapter_is_tool_subclass() -> None:
    adapter = _make_adapter()
    assert isinstance(adapter, Tool)


async def test_adapter_execute_success() -> None:
    """Mock client.call_tool and verify adapter forwards args and returns text."""
    mock_client = AsyncMock()
    text_block = MagicMock()
    text_block.text = "Hello, Alice!"
    mock_client.call_tool.return_value = MagicMock(content=[text_block])

    adapter = _make_adapter(client=mock_client)
    result = await adapter.execute(name="Alice")

    mock_client.call_tool.assert_awaited_once_with("greet", {"name": "Alice"})
    assert result == "Hello, Alice!"


async def test_adapter_execute_multiple_blocks() -> None:
    """Multiple content blocks are joined with newlines."""
    mock_client = AsyncMock()
    b1 = MagicMock()
    b1.text = "Line 1"
    b2 = MagicMock()
    b2.text = "Line 2"
    mock_client.call_tool.return_value = MagicMock(content=[b1, b2])

    adapter = _make_adapter(client=mock_client)
    result = await adapter.execute(name="Bob")
    assert result == "Line 1\nLine 2"


async def test_adapter_execute_empty_result() -> None:
    mock_client = AsyncMock()
    mock_client.call_tool.return_value = MagicMock(content=[])

    adapter = _make_adapter(client=mock_client)
    result = await adapter.execute(name="X")
    assert result == "(empty result)"


async def test_adapter_execute_error_handling() -> None:
    """On exception, adapter returns a descriptive error string (no crash)."""
    mock_client = AsyncMock()
    mock_client.call_tool.side_effect = ConnectionError("server down")

    adapter = _make_adapter(server="srv", tool="t", client=mock_client)
    result = await adapter.execute(name="X")
    assert "Error calling MCP tool" in result
    assert "server down" in result


# ============================================================================
# McpClientManager
# ============================================================================


def test_manager_not_started_initially() -> None:
    cfg = McpConfig(servers={"s": McpServerConfig(url="http://x/mcp")})
    mgr = McpClientManager(cfg)
    assert mgr.is_started is False
    assert mgr.get_tools() == []


async def test_manager_start_discovers_tools() -> None:
    """Mock FastMCP Client to simulate tool discovery."""
    fake_tool = MagicMock()
    fake_tool.name = "do_thing"
    fake_tool.description = "Does the thing"
    fake_tool.inputSchema = {
        "type": "object",
        "properties": {"x": {"type": "integer"}},
    }

    mock_client_instance = AsyncMock()
    mock_client_instance.list_tools.return_value = [fake_tool]
    mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
    mock_client_instance.__aexit__ = AsyncMock(return_value=False)

    cfg = McpConfig(servers={
        "my_srv": McpServerConfig(type="http", url="http://localhost:9999/mcp"),
    })
    mgr = McpClientManager(cfg)

    with patch("nanobot.mcp.client.Client", return_value=mock_client_instance):
        tools = await mgr.start()

    assert mgr.is_started is True
    assert len(tools) == 1
    assert tools[0].name == "mcp__my_srv__do_thing"
    assert tools[0].description == "Does the thing"


async def test_manager_start_skips_disabled_server() -> None:
    cfg = McpConfig(servers={
        "off": McpServerConfig(enabled=False, url="http://localhost/mcp"),
    })
    mgr = McpClientManager(cfg)

    # Should not even attempt to import/create a Client
    tools = await mgr.start()
    assert tools == []
    assert mgr.is_started is True


async def test_manager_start_unreachable_server() -> None:
    """Unreachable server logs warning but doesn't crash; returns no tools."""
    mock_client_instance = AsyncMock()
    mock_client_instance.__aenter__ = AsyncMock(side_effect=ConnectionError("refused"))

    cfg = McpConfig(servers={
        "bad": McpServerConfig(type="http", url="http://localhost:1/mcp"),
    })
    mgr = McpClientManager(cfg)

    with patch("nanobot.mcp.client.Client", return_value=mock_client_instance):
        tools = await mgr.start()

    assert tools == []
    assert mgr.is_started is True


async def test_manager_start_idempotent() -> None:
    """Calling start() twice returns same tools without reconnecting."""
    fake_tool = MagicMock()
    fake_tool.name = "t"
    fake_tool.description = "d"
    fake_tool.inputSchema = {}

    mock_client = AsyncMock()
    mock_client.list_tools.return_value = [fake_tool]
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    cfg = McpConfig(servers={
        "s": McpServerConfig(type="http", url="http://x/mcp"),
    })
    mgr = McpClientManager(cfg)

    with patch("nanobot.mcp.client.Client", return_value=mock_client):
        tools1 = await mgr.start()
        tools2 = await mgr.start()

    assert tools1 == tools2
    # Client constructor should have been called only once
    assert mock_client.__aenter__.await_count == 1


async def test_manager_stop_cleans_up() -> None:
    mock_client = AsyncMock()
    mock_client.list_tools.return_value = []
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    cfg = McpConfig(servers={
        "s": McpServerConfig(type="http", url="http://x/mcp"),
    })
    mgr = McpClientManager(cfg)

    with patch("nanobot.mcp.client.Client", return_value=mock_client):
        await mgr.start()

    assert mgr.is_started is True

    await mgr.stop()
    assert mgr.is_started is False
    assert mgr.get_tools() == []
    mock_client.__aexit__.assert_awaited()


# ============================================================================
# McpClientManager._build_transport
# ============================================================================


def test_build_transport_http() -> None:
    cfg = McpServerConfig(type="http", url="http://localhost:8000/mcp")
    with patch("nanobot.mcp.client.StreamableHttpTransport") as mock_cls:
        McpClientManager._build_transport("test", cfg)
        mock_cls.assert_called_once_with(url="http://localhost:8000/mcp", headers={})


def test_build_transport_http_with_headers() -> None:
    cfg = McpServerConfig(
        type="http", url="http://x/mcp", headers={"X-Key": "val"}
    )
    with patch("nanobot.mcp.client.StreamableHttpTransport") as mock_cls:
        McpClientManager._build_transport("test", cfg)
        mock_cls.assert_called_once_with(
            url="http://x/mcp", headers={"X-Key": "val"}
        )


def test_build_transport_stdio() -> None:
    cfg = McpServerConfig(
        type="stdio", command="python", args=["s.py"], env={"K": "V"}
    )
    with patch("nanobot.mcp.client.StdioTransport") as mock_cls:
        McpClientManager._build_transport("test", cfg)
        mock_cls.assert_called_once_with(
            command="python", args=["s.py"], env={"K": "V"}
        )


def test_build_transport_http_missing_url() -> None:
    cfg = McpServerConfig(type="http", url="")
    try:
        McpClientManager._build_transport("test", cfg)
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "url" in str(e).lower()


def test_build_transport_stdio_missing_command() -> None:
    cfg = McpServerConfig(type="stdio", command="")
    try:
        McpClientManager._build_transport("test", cfg)
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "command" in str(e).lower()


def test_build_transport_unknown_type() -> None:
    cfg = McpServerConfig(type="websocket")
    try:
        McpClientManager._build_transport("test", cfg)
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "unsupported" in str(e).lower()


# ============================================================================
# ToolRegistry integration
# ============================================================================


def test_registry_includes_mcp_tool() -> None:
    adapter = _make_adapter()
    reg = ToolRegistry()
    reg.register(adapter)

    assert reg.has("mcp__test_srv__greet")
    defs = reg.get_definitions()
    names = [d["function"]["name"] for d in defs]
    assert "mcp__test_srv__greet" in names


async def test_registry_execute_delegates_to_mcp_tool() -> None:
    mock_client = AsyncMock()
    text_block = MagicMock()
    text_block.text = "result"
    mock_client.call_tool.return_value = MagicMock(content=[text_block])

    adapter = _make_adapter(client=mock_client)
    reg = ToolRegistry()
    reg.register(adapter)

    result = await reg.execute("mcp__test_srv__greet", {"name": "World"})
    assert result == "result"
    mock_client.call_tool.assert_awaited_once_with("greet", {"name": "World"})
