"""Exercise the real webhook listener and message bus against a fake provider."""

import asyncio
import json
import socket

import httpx
import pytest
import pytest_asyncio

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.manager import ChannelManager
from nanobot.channels.registry import load_channel_class, load_channel_plugin
from nanobot.channels.sendblue.runtime import SendblueChannel, SendblueConfig
from nanobot.config.schema import Config
from nanobot.providers.base import LLMProvider, LLMResponse

LINE = "+15550000001"
USER = "+15550000002"


@pytest_asyncio.fixture
async def channel():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    config = Config.model_validate({"channels": {
        "websocket": {"enabled": False},
        "sendblue": {"enabled": True, "apiKey": "test-key",
            "apiSecret": "test-api-secret", "fromNumber": LINE,
            "webhookSecret": "test-webhook-secret", "allowFrom": [USER], "port": port},
    }})
    manager = ChannelManager(config, MessageBus())
    channel = manager.channels["sendblue"]
    assert isinstance(channel, load_channel_class("sendblue"))
    task = asyncio.create_task(manager.start_all())
    try:
        async with asyncio.timeout(5):
            while not channel.is_running:
                if task.done():
                    await task
                await asyncio.sleep(0.01)
        yield channel, f"http://127.0.0.1:{port}/sendblue/webhook"
    finally:
        await manager.stop_all()
        await task


def event(**changes):
    return {
        "message_handle": "in-1", "is_outbound": False, "from_number": USER,
        "to_number": LINE, "content": "Hello agent", "status": "RECEIVED", **changes,
    }


async def test_webhook_to_bus_and_reply(channel):
    ch, url = channel
    async with httpx.AsyncClient() as client:
        responses = await asyncio.gather(*[
            client.post(url, json=event(), headers={"sb-signing-secret": "test-webhook-secret"})
            for _ in range(2)
        ])
    assert [r.status_code for r in responses] == [204, 204]
    msg = await asyncio.wait_for(ch.bus.consume_inbound(), 1)
    assert (msg.channel, msg.sender_id, msg.chat_id, msg.content) == (
        "sendblue", USER, USER, "Hello agent"
    )
    assert ch.bus.inbound_size == 0
    requests = []

    def send(request):
        requests.append(request)
        return httpx.Response(200, json={"message_handle": "out-1", "status": "QUEUED", "error_code": 0})

    await ch._client.aclose()
    ch._client = httpx.AsyncClient(transport=httpx.MockTransport(send))
    await ch.send(OutboundMessage(channel="sendblue", chat_id=msg.chat_id, content="Hello human"))
    assert len(requests) == 1
    assert str(requests[0].url) == "https://api.sendblue.com/api/send-message"
    assert requests[0].headers["sb-api-key-id"] == "test-key"
    assert requests[0].headers["sb-api-secret-key"] == "test-api-secret"
    assert json.loads(requests[0].content) == {
        "from_number": LINE, "number": USER, "content": "Hello human"
    }


@pytest.mark.parametrize(("changes", "secret", "status"), [
    ({}, "wrong", 401), ({"is_outbound": "false"}, "test-webhook-secret", 400),
    ({"is_outbound": True}, "test-webhook-secret", 204),
    ({"to_number": "+15550000003"}, "test-webhook-secret", 204),
    ({"from_number": "+15550000003"}, "test-webhook-secret", 204),
    ({"group_id": "group"}, "test-webhook-secret", 204),
    ({"status": "DELIVERED"}, "test-webhook-secret", 204),
])
async def test_webhook_boundaries(channel, changes, secret, status):
    ch, url = channel
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=event(**changes), headers={"sb-signing-secret": secret})
    assert response.status_code == status
    assert ch.bus.inbound_size == 0


async def test_malformed_and_oversized_body(channel):
    ch, url = channel
    async with httpx.AsyncClient() as client:
        for body, status in [("{", 400), ("x" * 65537, 413)]:
            response = await client.post(url, content=body, headers={"sb-signing-secret": "test-webhook-secret"})
            assert response.status_code == status
    assert ch.bus.inbound_size == 0


@pytest.mark.parametrize(("http_status", "payload"), [
    (401, {}), (429, {}), (500, {}), (302, {}), (200, {}),
    (200, {"message_handle": "out-1", "status": "ERROR"}),
    (200, {"message_handle": "out-1", "status": "DECLINED", "error_code": 4001}),
])
async def test_failed_send_is_not_reported_as_success_or_retried(channel, http_status, payload):
    ch, _ = channel
    calls = []

    def send(request):
        calls.append(request)
        return httpx.Response(http_status, json=payload)

    await ch._client.aclose()
    ch._client = httpx.AsyncClient(transport=httpx.MockTransport(send))
    with pytest.raises(RuntimeError) as error:
        await ch.send(OutboundMessage(channel="sendblue", chat_id=USER, content="Hello"))
    assert not ch.should_retry_send_error(error.value)
    assert len(calls) == 1


async def test_queue_failure_can_be_redelivered(channel, monkeypatch):
    ch, url = channel
    original = ch.bus.publish_inbound

    async def fail(msg):
        raise RuntimeError("queue unavailable")

    monkeypatch.setattr(ch.bus, "publish_inbound", fail)
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=event(), headers={"sb-signing-secret": "test-webhook-secret"})
        assert response.status_code == 500
        monkeypatch.setattr(ch.bus, "publish_inbound", original)
        response = await client.post(url, json=event(), headers={"sb-signing-secret": "test-webhook-secret"})
        assert response.status_code == 204
    assert ch.bus.inbound_size == 1


def test_setup_defaults_and_fail_closed():
    assert load_channel_plugin("sendblue").setup.fields["apiSecret"].kind == "secret"
    assert SendblueChannel.default_config()["enabled"] is False
    with pytest.raises(ValueError):
        SendblueConfig().validate_runtime()
    with pytest.raises(ValueError, match="allowFrom"):
        SendblueConfig(api_key="key", api_secret="secret", webhook_secret="secret", from_number=LINE).validate_runtime()


async def test_real_agent_loop_round_trip_and_followup(channel, tmp_path):
    ch, url = channel
    observed = []
    replies = []

    class FixtureProvider(LLMProvider):
        def get_default_model(self):
            return "fixture-model"

        async def chat(self, messages, **kwargs):
            observed.append(messages)
            return LLMResponse(content=f"Reply {len(observed)}")

    loop = AgentLoop(bus=ch.bus, provider=FixtureProvider(provider_name="fixture"),
                     workspace=tmp_path, model="fixture-model")

    def send(request):
        replies.append(json.loads(request.content))
        return httpx.Response(200, json={"message_handle": f"out-{len(replies)}",
                                        "status": "QUEUED", "error_code": 0})

    await ch._client.aclose()
    ch._client = httpx.AsyncClient(transport=httpx.MockTransport(send))
    task = asyncio.create_task(loop.run())
    try:
        async with httpx.AsyncClient() as client:
            for index in (1, 2):
                response = await client.post(url, json=event(message_handle=f"in-{index}",
                    content=f"Hello agent {index}"),
                    headers={"sb-signing-secret": "test-webhook-secret"})
                assert response.status_code == 204
                async with asyncio.timeout(10):
                    while len(replies) < index:
                        await asyncio.sleep(0.01)
        assert [reply["content"] for reply in replies] == ["Reply 1", "Reply 2"]
        assert all(reply["number"] == USER and reply["from_number"] == LINE for reply in replies)
        assert "Hello agent 1" in str(observed[1])
        assert "Reply 1" in str(observed[1])
        assert "Hello agent 2" in str(observed[1])
    finally:
        loop.stop()
        await asyncio.wait_for(task, 5)
