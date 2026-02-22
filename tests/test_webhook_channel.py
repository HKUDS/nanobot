import asyncio

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.webhook import WebhookChannel
from nanobot.config.schema import WebhookConfig


def _make_channel(*, token: str = "") -> WebhookChannel:
    cfg = WebhookConfig(
        enabled=True,
        webhook_host="127.0.0.1",
        webhook_port=18794,
        webhook_path="/v1/inbound",
        send_path="/v1/outbound",
        connector_url="http://127.0.0.1:19400/v1/outbound",
        token=token,
    )
    return WebhookChannel(cfg, MessageBus())


@pytest.mark.asyncio
async def test_inbound_route_publishes_message_to_bus() -> None:
    channel = _make_channel()

    status, response = await channel.handle_http_request(
        method="POST",
        path="/v1/inbound",
        headers={
            "Content-Type": "application/json",
            "x-webhook-sender-id": "did:example:sender",
            "x-webhook-chat-id": "did:example:receiver",
        },
        body=b'{"content":"hello"}',
        remote_addr="127.0.0.1:4567",
    )

    assert status == 202
    assert response == {"status": "accepted"}

    inbound = await asyncio.wait_for(channel.bus.consume_inbound(), timeout=1)
    assert inbound.channel == "webhook"
    assert inbound.sender_id == "did:example:sender"
    assert inbound.chat_id == "did:example:receiver"
    assert inbound.content == "hello"


@pytest.mark.asyncio
async def test_outbound_route_forwards_to_connector(monkeypatch: pytest.MonkeyPatch) -> None:
    channel = _make_channel()
    captured: dict[str, str] = {}

    async def fake_forward(payload: dict[str, str]) -> tuple[int, dict[str, str]]:
        captured.update(payload)
        return 202, {"status": "accepted"}

    monkeypatch.setattr(channel, "_forward_to_connector", fake_forward)

    status, response = await channel.handle_http_request(
        method="POST",
        path="/v1/outbound",
        headers={"Content-Type": "application/json"},
        body=b'{"to":"did:example:peer","content":"ping","peer":"alice"}',
        remote_addr="127.0.0.1:4567",
    )

    assert status == 202
    assert response == {"status": "accepted"}
    assert captured == {
        "to": "did:example:peer",
        "content": "ping",
        "peer": "alice",
    }


@pytest.mark.asyncio
async def test_send_uses_connector_forwarding(monkeypatch: pytest.MonkeyPatch) -> None:
    channel = _make_channel()
    captured: dict[str, str] = {}

    async def fake_forward(payload: dict[str, str]) -> tuple[int, dict[str, str]]:
        captured.update(payload)
        return 202, {"status": "accepted"}

    monkeypatch.setattr(channel, "_forward_to_connector", fake_forward)

    await channel.send(
        OutboundMessage(
            channel="webhook",
            chat_id="did:example:peer",
            content="hello from nanobot",
            metadata={"peer": "bob"},
        )
    )

    assert captured == {
        "to": "did:example:peer",
        "content": "hello from nanobot",
        "peer": "bob",
    }


@pytest.mark.asyncio
async def test_token_auth_is_optional_but_enforced_when_configured() -> None:
    channel = _make_channel(token="secret-token")

    status, _ = await channel.handle_http_request(
        method="POST",
        path="/v1/inbound",
        headers={"Content-Type": "application/json"},
        body=b'{"content":"hello"}',
        remote_addr="127.0.0.1:4567",
    )
    assert status == 403

    status, response = await channel.handle_http_request(
        method="POST",
        path="/v1/inbound",
        headers={
            "Content-Type": "application/json",
            "x-webhook-token": "secret-token",
            "x-webhook-sender-id": "did:example:sender",
        },
        body=b'{"content":"hello"}',
        remote_addr="127.0.0.1:4567",
    )
    assert status == 202
    assert response == {"status": "accepted"}


@pytest.mark.asyncio
async def test_outbound_route_requires_to_and_content_fields() -> None:
    channel = _make_channel()

    status, _ = await channel.handle_http_request(
        method="POST",
        path="/v1/outbound",
        headers={"Content-Type": "application/json"},
        body=b'{"content":"hello"}',
        remote_addr="127.0.0.1:4567",
    )
    assert status == 400

    status, _ = await channel.handle_http_request(
        method="POST",
        path="/v1/outbound",
        headers={"Content-Type": "application/json"},
        body=b'{"to":"did:example:peer"}',
        remote_addr="127.0.0.1:4567",
    )
    assert status == 400
