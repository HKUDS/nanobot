import asyncio
import json
from typing import Any

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.shell import ExecTool
from nanobot.bus.backends import InMemoryBusBackend
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.transport.contracts import InboundTransportMessage, OutboundTransportEvent
from nanobot.transport.ws_gateway import WebSocketGateway


class SampleTool(Tool):
    @property
    def name(self) -> str:
        return "sample"

    @property
    def description(self) -> str:
        return "sample tool"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 2},
                "count": {"type": "integer", "minimum": 1, "maximum": 10},
                "mode": {"type": "string", "enum": ["fast", "full"]},
                "meta": {
                    "type": "object",
                    "properties": {
                        "tag": {"type": "string"},
                        "flags": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["tag"],
                },
            },
            "required": ["query", "count"],
        }

    async def execute(self, **kwargs: Any) -> str:
        return "ok"


def test_validate_params_missing_required() -> None:
    tool = SampleTool()
    errors = tool.validate_params({"query": "hi"})
    assert "missing required count" in "; ".join(errors)


def test_validate_params_type_and_range() -> None:
    tool = SampleTool()
    errors = tool.validate_params({"query": "hi", "count": 0})
    assert any("count must be >= 1" in e for e in errors)

    errors = tool.validate_params({"query": "hi", "count": "2"})
    assert any("count should be integer" in e for e in errors)


def test_validate_params_enum_and_min_length() -> None:
    tool = SampleTool()
    errors = tool.validate_params({"query": "h", "count": 2, "mode": "slow"})
    assert any("query must be at least 2 chars" in e for e in errors)
    assert any("mode must be one of" in e for e in errors)


def test_validate_params_nested_object_and_array() -> None:
    tool = SampleTool()
    errors = tool.validate_params(
        {
            "query": "hi",
            "count": 2,
            "meta": {"flags": [1, "ok"]},
        }
    )
    assert any("missing required meta.tag" in e for e in errors)
    assert any("meta.flags[0] should be string" in e for e in errors)


def test_validate_params_ignores_unknown_fields() -> None:
    tool = SampleTool()
    errors = tool.validate_params({"query": "hi", "count": 2, "extra": "x"})
    assert errors == []


async def test_registry_returns_validation_error() -> None:
    reg = ToolRegistry()
    reg.register(SampleTool())
    result = await reg.execute("sample", {"query": "hi"})
    assert "Invalid parameters" in result


def test_exec_extract_absolute_paths_keeps_full_windows_path() -> None:
    cmd = r"type C:\user\workspace\txt"
    paths = ExecTool._extract_absolute_paths(cmd)
    assert paths == [r"C:\user\workspace\txt"]


def test_exec_extract_absolute_paths_ignores_relative_posix_segments() -> None:
    cmd = ".venv/bin/python script.py"
    paths = ExecTool._extract_absolute_paths(cmd)
    assert "/bin/python" not in paths


def test_exec_extract_absolute_paths_captures_posix_absolute_paths() -> None:
    cmd = "cat /tmp/data.txt > /tmp/out.txt"
    paths = ExecTool._extract_absolute_paths(cmd)
    assert "/tmp/data.txt" in paths
    assert "/tmp/out.txt" in paths


async def test_message_bus_uses_default_inmemory_backend() -> None:
    bus = MessageBus()

    inbound = InboundMessage(channel="cli", sender_id="u1", chat_id="c1", content="hello")
    await bus.publish_inbound(inbound)
    received_in = await bus.consume_inbound()
    assert received_in.content == "hello"

    outbound = OutboundMessage(channel="cli", chat_id="c1", content="world")
    await bus.publish_outbound(outbound)
    received_out = await bus.consume_outbound()
    assert received_out.content == "world"


async def test_message_bus_accepts_explicit_backend() -> None:
    backend = InMemoryBusBackend()
    bus = MessageBus(backend=backend)

    msg = InboundMessage(channel="telegram", sender_id="u2", chat_id="c2", content="x")
    await bus.publish_inbound(msg)
    consumed = await backend.consume_inbound()
    assert consumed.channel == "telegram"


def test_inbound_contract_converts_to_bus_message() -> None:
    inbound = InboundTransportMessage.model_validate(
        {
            "message_id": "msg-1",
            "session_key": "telegram:chat-1:thread-2",
            "channel": "telegram",
            "chat_id": "chat-1",
            "sender_id": "user-1",
            "content": "hello",
            "media": ["/tmp/a.png"],
            "attachments": [
                {"type": "image", "url": "https://example.com/x.png"},
                {"type": "file", "local_path": "/tmp/doc.pdf"},
            ],
            "metadata": {"thread_id": "2"},
        }
    )

    msg = inbound.to_bus_message()
    assert msg.channel == "telegram"
    assert msg.session_key == "telegram:chat-1:thread-2"
    assert msg.metadata["message_id"] == "msg-1"
    assert msg.metadata["thread_id"] == "2"
    assert len(msg.media) == 3


def test_outbound_event_maps_progress_to_delta() -> None:
    outbound = OutboundMessage(
        channel="telegram",
        chat_id="chat-1",
        content="thinking...",
        metadata={"_progress": True},
    )

    event = OutboundTransportEvent.from_bus_message(outbound)
    assert event.event_type == "message.delta"
    assert event.message.channel == "telegram"


def test_outbound_event_maps_final_to_completed() -> None:
    outbound = OutboundMessage(
        channel="telegram",
        chat_id="chat-1",
        content="done",
    )

    event = OutboundTransportEvent.from_bus_message(outbound)
    assert event.event_type == "message.completed"


class _FakeWebSocket:
    def __init__(self):
        self.sent: list[dict[str, Any]] = []

    async def send(self, payload: str) -> None:
        self.sent.append(json.loads(payload))


def test_ws_gateway_normalize_channels() -> None:
    bus = MessageBus()
    gateway = WebSocketGateway(bus=bus)

    assert gateway._normalize_channels("telegram") == set()
    assert gateway._normalize_channels(None) == set()
    assert gateway._normalize_channels([" telegram ", "telegram", "", 1, "cli"]) == {"telegram", "cli"}


async def test_ws_gateway_handle_frame_ping() -> None:
    bus = MessageBus()
    gateway = WebSocketGateway(bus=bus)
    ws = _FakeWebSocket()

    await gateway._handle_frame(ws, json.dumps({"type": "ping"}))
    assert ws.sent[-1] == {"type": "pong"}


async def test_ws_gateway_handle_frame_subscribe_and_invalid_json() -> None:
    bus = MessageBus()
    gateway = WebSocketGateway(bus=bus)
    ws = _FakeWebSocket()
    gateway._subscriptions[ws] = set()

    await gateway._handle_frame(ws, "not-json")
    assert ws.sent[-1]["type"] == "error"
    assert ws.sent[-1]["error"] == "invalid_json"

    await gateway._handle_frame(
        ws,
        json.dumps({"type": "subscribe", "channels": ["telegram", " cli ", "telegram"]}),
    )
    assert gateway._subscriptions[ws] == {"telegram", "cli"}
    assert ws.sent[-1] == {"type": "subscribed", "channels": ["cli", "telegram"]}


async def test_ws_gateway_handle_frame_inbound_and_invalid_inbound() -> None:
    bus = MessageBus()
    gateway = WebSocketGateway(bus=bus)
    ws = _FakeWebSocket()

    await gateway._handle_frame(
        ws,
        json.dumps({"type": "inbound", "message": {"channel": "web"}}),
    )
    assert ws.sent[-1]["type"] == "error"
    assert ws.sent[-1]["error"] == "invalid_inbound"

    payload = {
        "type": "inbound",
        "message": {
            "message_id": "m-1",
            "session_key": "web:user-1",
            "channel": "web",
            "chat_id": "user-1",
            "sender_id": "user-1",
            "content": "hello",
        },
    }
    await gateway._handle_frame(ws, json.dumps(payload))
    inbound = await bus.consume_inbound()
    assert inbound.session_key == "web:user-1"
    assert inbound.content == "hello"
    assert ws.sent[-1] == {"type": "ack", "message_id": "m-1"}


async def test_ws_gateway_dispatch_outbound_respects_subscriptions() -> None:
    bus = MessageBus()
    gateway = WebSocketGateway(bus=bus)
    ws_all = _FakeWebSocket()
    ws_telegram = _FakeWebSocket()

    gateway._clients = {ws_all, ws_telegram}
    gateway._subscriptions = {
        ws_all: set(),
        ws_telegram: {"telegram"},
    }
    gateway._running = True

    task = asyncio.create_task(gateway._dispatch_outbound())
    try:
        await bus.publish_outbound(
            OutboundMessage(channel="web", chat_id="user-1", content="hello")
        )

        for _ in range(20):
            if ws_all.sent:
                break
            await asyncio.sleep(0.01)

        assert len(ws_all.sent) == 1
        assert ws_all.sent[0]["type"] == "outbound"
        assert ws_all.sent[0]["event"]["message"]["channel"] == "web"
        assert ws_telegram.sent == []
    finally:
        gateway._running = False
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
