import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.channels.api import ApiChannel, _ClientConnection
from nanobot.config.schema import ApiChannelConfig


class _DummyWriter:
    def __init__(self) -> None:
        self.writes: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.writes.append(data)

    async def drain(self) -> None:
        return None

    def get_extra_info(self, _name: str):
        return None

    def close(self) -> None:
        return None

    async def wait_closed(self) -> None:
        return None


def _make_connection(channel: ApiChannel) -> _ClientConnection:
    return _ClientConnection(reader=None, writer=_DummyWriter(), channel=channel)


@pytest.mark.asyncio
async def test_message_send_publishes_inbound_message() -> None:
    bus = MessageBus()
    channel = ApiChannel(ApiChannelConfig(enabled=True), bus)
    conn = _make_connection(channel)

    result = await conn._dispatch_method(
        "message.send",
        {"content": "hello", "chat_id": "web", "sender_id": "tester"},
    )

    inbound = await bus.consume_inbound()
    assert result == {"status": "accepted"}
    assert inbound.channel == "api"
    assert inbound.chat_id == "web"
    assert inbound.sender_id == "tester"
    assert inbound.content == "hello"


@pytest.mark.asyncio
async def test_command_execute_reset_publishes_new_session_command() -> None:
    bus = MessageBus()
    channel = ApiChannel(ApiChannelConfig(enabled=True), bus)
    conn = _make_connection(channel)

    result = await conn._dispatch_method(
        "command.execute",
        {"command": "reset", "chat_id": "web", "sender_id": "tester"},
    )

    inbound = await bus.consume_inbound()
    assert result == {"status": "accepted"}
    assert inbound.content == "/new"
    assert inbound.chat_id == "web"
    assert inbound.sender_id == "tester"


@pytest.mark.asyncio
async def test_tool_methods_use_registered_runtime() -> None:
    bus = MessageBus()
    channel = ApiChannel(ApiChannelConfig(enabled=True), bus)
    conn = _make_connection(channel)

    async def list_tools():
        return [{"name": "sample", "description": "sample tool", "parameters": {}}]

    async def call_tool(name: str, arguments: dict[str, object]):
        return {
            "tool_name": name,
            "content": "{}",
            "parsed": arguments,
            "is_json": True,
        }

    channel.set_tool_runtime(list_tools=list_tools, call_tool=call_tool)

    listed = await conn._dispatch_method("tool.list", {})
    called = await conn._dispatch_method("tool.call", {"name": "sample", "arguments": {"x": 1}})

    assert listed == {"tools": [{"name": "sample", "description": "sample tool", "parameters": {}}]}
    assert called == {
        "tool_name": "sample",
        "content": "{}",
        "parsed": {"x": 1},
        "is_json": True,
    }


def test_resolve_api_exposed_tools_supports_mcp_server_scope() -> None:
    loop = AgentLoop.__new__(AgentLoop)

    class _Registry:
        tool_names = [
            "exec",
            "mcp_home assistant_GetLiveContext",
            "mcp_home assistant_HassTurnOn",
            "mcp_foundry dnd_status",
        ]

    loop.tools = _Registry()

    resolved = loop._resolve_api_exposed_tools({"exec", "mcp:home assistant"})

    assert resolved == {
        "exec",
        "mcp_home assistant_GetLiveContext",
        "mcp_home assistant_HassTurnOn",
    }
