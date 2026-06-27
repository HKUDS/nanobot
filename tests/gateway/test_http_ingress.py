import asyncio
import functools
import random
import socket

import httpx
import pytest

from nanobot.bus.queue import MessageBus
from nanobot.config.schema import WebhookRouteConfig, WebhooksConfig
from nanobot.gateway.http import run_gateway_http_ingress
from nanobot.webhooks import WebhookRouter


def _free_port() -> int:
    for _ in range(100):
        port = random.randint(30_000, 60_000)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError("could not find a free localhost port")


async def _request(method: str, url: str, **kwargs) -> httpx.Response:
    return await asyncio.to_thread(
        functools.partial(
            httpx.request,
            method,
            url,
            timeout=5.0,
            trust_env=False,
            **kwargs,
        )
    )


@pytest.mark.asyncio
async def test_gateway_http_ingress_serves_health() -> None:
    port = _free_port()
    task = asyncio.create_task(
        run_gateway_http_ingress(host="127.0.0.1", port=port),
    )
    await asyncio.sleep(0.2)
    try:
        response = await _request("GET", f"http://127.0.0.1:{port}/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_gateway_http_ingress_accepts_webhook_and_queues_message() -> None:
    port = _free_port()
    bus = MessageBus()
    router = WebhookRouter(
        WebhooksConfig(
            routes={
                "deploy": WebhookRouteConfig(
                    auth="secret",
                    secret="topsecret",
                    to="telegram:ops",
                    prompt="Deploy {{ event.service }}",
                )
            }
        ),
        bus,
    )
    task = asyncio.create_task(
        run_gateway_http_ingress(host="127.0.0.1", port=port, webhook_router=router),
    )
    await asyncio.sleep(0.2)
    try:
        response = await _request(
            "POST",
            f"http://127.0.0.1:{port}/webhooks/deploy",
            headers={"Authorization": "Bearer topsecret"},
            json={"service": "api"},
        )

        assert response.status_code == 202
        assert response.json()["queued"] is True
        msg = await asyncio.wait_for(bus.consume_inbound(), timeout=1)
        assert msg.channel == "telegram"
        assert msg.chat_id == "ops"
        assert msg.content == "Deploy api"
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_gateway_http_ingress_rejects_oversized_webhook_before_queueing() -> None:
    port = _free_port()
    bus = MessageBus()
    router = WebhookRouter(
        WebhooksConfig(
            routes={
                "small": WebhookRouteConfig(
                    auth="none",
                    to="telegram:ops",
                    max_body_bytes=1024,
                )
            }
        ),
        bus,
    )
    task = asyncio.create_task(
        run_gateway_http_ingress(host="127.0.0.1", port=port, webhook_router=router),
    )
    await asyncio.sleep(0.2)
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(
            b"POST /webhooks/small HTTP/1.1\r\n"
            b"Host: 127.0.0.1\r\n"
            b"Content-Length: 2048\r\n"
            b"\r\n"
        )
        await writer.drain()
        data = await asyncio.wait_for(reader.read(4096), timeout=2)
        writer.close()
        await writer.wait_closed()

        assert data.startswith(b"HTTP/1.0 413 ")
        assert b"Request body too large" in data
        assert bus.inbound_size == 0
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_gateway_http_ingress_rejects_chunked_webhook_body() -> None:
    port = _free_port()
    bus = MessageBus()
    router = WebhookRouter(
        WebhooksConfig(
            routes={
                "chunked": WebhookRouteConfig(
                    auth="none",
                    to="telegram:ops",
                )
            }
        ),
        bus,
    )
    task = asyncio.create_task(
        run_gateway_http_ingress(host="127.0.0.1", port=port, webhook_router=router),
    )
    await asyncio.sleep(0.2)
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(
            b"POST /webhooks/chunked HTTP/1.1\r\n"
            b"Host: 127.0.0.1\r\n"
            b"Transfer-Encoding: chunked\r\n"
            b"\r\n"
            b"2\r\n{}\r\n0\r\n\r\n"
        )
        await writer.drain()
        data = await asyncio.wait_for(reader.read(4096), timeout=2)
        writer.close()
        await writer.wait_closed()

        assert data.startswith(b"HTTP/1.0 501 ")
        assert b"Transfer-Encoding is not supported" in data
        assert bus.inbound_size == 0
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_gateway_http_ingress_times_out_partial_request() -> None:
    port = _free_port()
    task = asyncio.create_task(
        run_gateway_http_ingress(host="127.0.0.1", port=port, read_timeout_s=0.1),
    )
    await asyncio.sleep(0.2)
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(
            b"POST /webhooks/slow HTTP/1.1\r\n"
            b"Host: 127.0.0.1\r\n"
        )
        await writer.drain()
        data = await asyncio.wait_for(reader.read(4096), timeout=2)
        writer.close()
        await writer.wait_closed()

        assert data.startswith(b"HTTP/1.0 408 ")
        assert b"Request timed out" in data
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
