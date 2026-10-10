import asyncio
import json
import socket
import time

import httpx
import pytest

from nanobot.bus.queue import MessageBus
from nanobot.config.schema import DirectDeliveryConfig
from nanobot.gateway.direct_delivery import run_direct_delivery_server, signed_delivery_headers


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def _wait_ready(url: str) -> None:
    for _ in range(50):
        try:
            async with httpx.AsyncClient() as client:
                await client.post(url, content=b"{}")
            return
        except httpx.ConnectError:
            await asyncio.sleep(0.01)
    raise AssertionError("direct delivery server did not start")


@pytest.fixture
def config() -> DirectDeliveryConfig:
    return DirectDeliveryConfig(
        enabled=True,
        host="127.0.0.1",
        port=_free_port(),
        path="/deliver",
        secret="test-secret",
        channel="telegram",
        chat_id="12345",
    )


@pytest.mark.asyncio
async def test_signed_request_publishes_only_to_outbound_bus(config: DirectDeliveryConfig) -> None:
    bus = MessageBus()
    task = asyncio.create_task(run_direct_delivery_server(config, bus))
    url = f"http://{config.host}:{config.port}{config.path}"
    try:
        await _wait_ready(url)
        body = json.dumps({"content": "Build complete"}).encode()
        headers = signed_delivery_headers(config.secret, "request-1", body)
        async with httpx.AsyncClient() as client:
            response = await client.post(url, content=body, headers=headers)

        assert response.status_code == 200
        message = await asyncio.wait_for(bus.consume_outbound(), timeout=1)
        assert (message.channel, message.chat_id, message.content) == (
            "telegram", "12345", "Build complete"
        )
        assert message.metadata == {"direct_delivery": True, "request_id": "request-1"}
        assert bus.inbound_size == 0
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_rejects_bad_signatures_stale_and_replayed_requests(
    config: DirectDeliveryConfig,
) -> None:
    bus = MessageBus()
    task = asyncio.create_task(run_direct_delivery_server(config, bus))
    url = f"http://{config.host}:{config.port}{config.path}"
    body = json.dumps({"content": "Do not duplicate"}).encode()
    try:
        await _wait_ready(url)
        async with httpx.AsyncClient() as client:
            bad = await client.post(
                url,
                content=body,
                headers=signed_delivery_headers("wrong", "bad", body),
            )
            stale = await client.post(url, content=body, headers=signed_delivery_headers(
                config.secret, "stale", body,
                timestamp=int(time.time()) - config.max_age_seconds - 1,
            ))
            headers = signed_delivery_headers(config.secret, "same", body)
            accepted = await client.post(url, content=body, headers=headers)
            replayed = await client.post(url, content=body, headers=headers)

        assert bad.status_code == 401
        assert stale.status_code == 401
        assert accepted.status_code == 200
        assert replayed.status_code == 409
        await asyncio.wait_for(bus.consume_outbound(), timeout=1)
        assert bus.outbound_size == 0
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_rejects_invalid_payloads_and_oversized_bodies(config: DirectDeliveryConfig) -> None:
    config.max_body_bytes = 30
    bus = MessageBus()
    task = asyncio.create_task(run_direct_delivery_server(config, bus))
    url = f"http://{config.host}:{config.port}{config.path}"
    try:
        await _wait_ready(url)
        invalid = json.dumps({"content": ""}).encode()
        oversized = json.dumps({"content": "x" * 50}).encode()
        async with httpx.AsyncClient() as client:
            empty = await client.post(
                url,
                content=invalid,
                headers=signed_delivery_headers(config.secret, "empty", invalid),
            )
            large = await client.post(
                url,
                content=oversized,
                headers=signed_delivery_headers(config.secret, "large", oversized),
            )
        assert empty.status_code == 400
        assert large.status_code == 413
        assert bus.outbound_size == 0
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
