"""A2A protocol integration checks without a listening socket."""

import asyncio

import httpx
import pytest

pytest.importorskip("a2a.server.apps")

from a2a.types import Message, Part, Role, SendMessageSuccessResponse, TextPart

from nanobot.agent.tools.a2a_client import A2AClientTool
from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.a2a.runtime import A2AChannel
from nanobot.channels.registry import load_channel_plugin
from nanobot.config.schema import A2AConfig


def test_a2a_plugin_and_card():
    assert load_channel_plugin("a2a").load_channel_class() is A2AChannel
    channel = A2AChannel(A2AConfig(enabled=True), MessageBus())

    async def check():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=channel.a2a_app.build()),
            base_url="http://localhost:8080",
        ) as client:
            response = await client.get("/.well-known/agent-card.json")
            assert response.status_code == 200
            assert response.json()["name"] == "nanobot"

    asyncio.run(check())


def test_a2a_message_roundtrip():
    bus = MessageBus()
    channel = A2AChannel(A2AConfig(enabled=True), bus)

    async def check():
        async def reply():
            inbound = await bus.consume_inbound()
            assert inbound.content == "ping"
            await channel.send(
                OutboundMessage(channel="a2a", chat_id=inbound.chat_id, content="pong")
            )

        task = asyncio.create_task(reply())
        payload = {
            "jsonrpc": "2.0",
            "id": "1",
            "method": "message/send",
            "params": {
                "message": {
                    "role": "user",
                    "parts": [{"kind": "text", "text": "ping"}],
                    "messageId": "abc",
                }
            },
        }
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=channel.a2a_app.build()),
            base_url="http://localhost:8080",
            timeout=3,
        ) as client:
            response = await client.post("/", json=payload)
        await task
        assert response.status_code == 200
        assert response.json()["result"]["parts"][0]["text"] == "pong"

    asyncio.run(check())


def test_client_extracts_direct_message():
    message = Message(role=Role.agent, parts=[Part(root=TextPart(text="pong"))], messageId="1")
    response = SendMessageSuccessResponse(id="x", result=message)
    assert A2AClientTool()._extract_response(response, "demo") == "pong"
