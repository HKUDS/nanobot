import asyncio
import contextlib

import httpx
import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.webhook import WebhookChannel
from nanobot.config.schema import WebhookConfig


def _make_channel(
    *,
    token: str = "",
    allow_from: list[str] | None = None,
    webhook_port: int = 18794,
) -> WebhookChannel:
    cfg = WebhookConfig(
        enabled=True,
        webhook_host="127.0.0.1",
        webhook_port=webhook_port,
        webhook_path="/v1/inbound",
        send_path="/v1/outbound",
        connector_url="http://127.0.0.1:19400/v1/outbound",
        token=token,
        allow_from=list(allow_from or []),
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
async def test_bearer_auth_token_is_enforced_when_configured() -> None:
    channel = _make_channel(token="secret-token")

    status, response = await channel.handle_http_request(
        method="POST",
        path="/v1/inbound",
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer secret-token",
            "x-webhook-sender-id": "did:example:sender",
        },
        body=b'{"content":"hello"}',
        remote_addr="127.0.0.1:4567",
    )
    assert status == 202
    assert response == {"status": "accepted"}

    status, _ = await channel.handle_http_request(
        method="POST",
        path="/v1/inbound",
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer wrong-token",
            "x-webhook-sender-id": "did:example:sender",
        },
        body=b'{"content":"hello"}',
        remote_addr="127.0.0.1:4567",
    )
    assert status == 403


@pytest.mark.asyncio
async def test_inbound_route_enforces_allow_from_sender_ids() -> None:
    channel = _make_channel(allow_from=["did:example:allowed"])

    status, response = await channel.handle_http_request(
        method="POST",
        path="/v1/inbound",
        headers={
            "Content-Type": "application/json",
            "x-webhook-sender-id": "did:example:allowed",
        },
        body=b'{"content":"hello"}',
        remote_addr="127.0.0.1:4567",
    )
    assert status == 202
    assert response == {"status": "accepted"}

    status, response = await channel.handle_http_request(
        method="POST",
        path="/v1/inbound",
        headers={
            "Content-Type": "application/json",
            "x-webhook-sender-id": "did:example:blocked",
        },
        body=b'{"content":"hello"}',
        remote_addr="127.0.0.1:4567",
    )
    assert status == 403
    assert response == {"error": "Sender not allowed"}


@pytest.mark.asyncio
async def test_webhook_server_start_and_stop_lifecycle() -> None:
    channel = _make_channel(webhook_port=0)
    start_task = asyncio.create_task(channel.start())

    base_url = ""
    for _ in range(40):
        if channel._server is None:
            await asyncio.sleep(0.05)
            continue
        host, port = channel._server.server_address
        base_url = f"http://{host}:{port}"
        try:
            async with httpx.AsyncClient(timeout=0.5) as client:
                response = await client.get(f"{base_url}/v1/inbound")
            if response.status_code == 405:
                break
        except httpx.HTTPError:
            pass
        await asyncio.sleep(0.05)
    else:
        if not start_task.done():
            start_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await start_task
        pytest.fail("webhook server did not start listening in time")

    await channel.stop()
    await asyncio.wait_for(start_task, timeout=2)

    for _ in range(40):
        try:
            async with httpx.AsyncClient(timeout=0.5) as client:
                await client.get(f"{base_url}/v1/inbound")
        except httpx.HTTPError:
            break
        await asyncio.sleep(0.05)
    else:
        pytest.fail("webhook server is still accepting connections after stop")


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
