"""Tests for the bearer-token middleware on /v1/* in nanobot.api.server."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from nanobot.api.server import create_app

try:
    from aiohttp.test_utils import TestClient, TestServer

    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False

pytest_plugins = ("pytest_asyncio",)


def _agent_returning(text: str) -> MagicMock:
    agent = MagicMock()
    agent.process_direct = AsyncMock(return_value=text)
    agent._connect_mcp = AsyncMock()
    agent.close_mcp = AsyncMock()
    return agent


@pytest_asyncio.fixture
async def aiohttp_client():
    clients: list[TestClient] = []

    async def _make_client(app):
        client = TestClient(TestServer(app))
        await client.start_server()
        clients.append(client)
        return client

    try:
        yield _make_client
    finally:
        for client in clients:
            await client.close()


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
@pytest.mark.asyncio
async def test_no_auth_token_keeps_v1_open(aiohttp_client) -> None:
    """When auth_token is empty the middleware is a no-op (preserves the
    existing local-only deployment shape)."""
    app = create_app(_agent_returning("ok"), model_name="m")
    client = await aiohttp_client(app)

    resp = await client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status == 200


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
@pytest.mark.asyncio
async def test_v1_requires_bearer_when_auth_token_set(aiohttp_client) -> None:
    app = create_app(_agent_returning("ok"), model_name="m", auth_token="s3cret")
    client = await aiohttp_client(app)

    deny = await client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hi"}]},
    )
    assert deny.status == 401

    bad = await client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hi"}]},
        headers={"Authorization": "Bearer wrong"},
    )
    assert bad.status == 401

    ok = await client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hi"}]},
        headers={"Authorization": "Bearer s3cret"},
    )
    assert ok.status == 200


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
@pytest.mark.asyncio
async def test_v1_models_requires_bearer(aiohttp_client) -> None:
    app = create_app(_agent_returning("ok"), model_name="m", auth_token="s3cret")
    client = await aiohttp_client(app)

    deny = await client.get("/v1/models")
    assert deny.status == 401

    ok = await client.get(
        "/v1/models", headers={"Authorization": "Bearer s3cret"}
    )
    assert ok.status == 200


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
@pytest.mark.asyncio
async def test_health_is_exempt_from_auth(aiohttp_client) -> None:
    """/health stays open for liveness probes even when auth is configured."""
    app = create_app(_agent_returning("ok"), model_name="m", auth_token="s3cret")
    client = await aiohttp_client(app)

    resp = await client.get("/health")
    assert resp.status == 200
