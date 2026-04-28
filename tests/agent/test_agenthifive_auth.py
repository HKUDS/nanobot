import base64
import json
import time

import pytest

from agenthifive_nanobot.auth import AgentTokenManager, build_runtime_config_from_mcp_server
from nanobot.config.schema import MCPServerConfig


def _fake_jwk() -> dict[str, str]:
    return {
        "kty": "EC",
        "crv": "P-256",
        "x": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "y": "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB",
        "d": "CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC",
    }


def test_build_runtime_config_from_mcp_server_prefers_agent_auth():
    encoded = base64.b64encode(json.dumps(_fake_jwk()).encode("utf-8")).decode("utf-8")
    server = MCPServerConfig.model_validate(
        {
            "type": "stdio",
            "command": "agenthifive-mcp",
            "env": {
                "AGENTHIFIVE_BASE_URL": "https://app.agenthifive.com",
                "AGENTHIFIVE_AGENT_ID": "agt_123",
                "AGENTHIFIVE_PRIVATE_KEY": encoded,
                "AGENTHIFIVE_POLL_INTERVAL_MS": "7000",
            },
        }
    )

    runtime = build_runtime_config_from_mcp_server(server)

    assert runtime.base_url == "https://app.agenthifive.com"
    assert runtime.auth.mode == "agent"
    assert runtime.auth.agent_id == "agt_123"
    assert runtime.auth.private_key["kty"] == "EC"
    assert runtime.poll_interval == 7.0


def test_build_runtime_config_from_mcp_server_supports_bearer_auth():
    server = MCPServerConfig.model_validate(
        {
            "type": "stdio",
            "command": "agenthifive-mcp",
            "env": {
                "AGENTHIFIVE_BASE_URL": "https://app.agenthifive.com",
                "AGENTHIFIVE_BEARER_TOKEN": "ah5t_demo",
            },
        }
    )

    runtime = build_runtime_config_from_mcp_server(server)

    assert runtime.auth.mode == "bearer"
    assert runtime.auth.token == "ah5t_demo"


@pytest.mark.asyncio
async def test_agent_token_manager_reuses_cached_token_until_refresh_window(monkeypatch):
    monkeypatch.setattr("agenthifive_nanobot.auth.ECAlgorithm.from_jwk", lambda _raw: object())

    manager = AgentTokenManager(
        base_url="https://app.agenthifive.com",
        agent_id="agt_123",
        private_key=_fake_jwk(),
    )

    calls: list[str] = []

    async def fake_exchange():
        calls.append("x")
        return (f"ah5t_{len(calls)}", 120)

    monkeypatch.setattr(manager, "_exchange_token", fake_exchange)

    token1 = await manager.get_token()
    token2 = await manager.get_token()
    assert token1 == token2 == "ah5t_1"
    assert len(calls) == 1

    manager._expires_at = time.time() + 30
    token3 = await manager.get_token()
    assert token3 == "ah5t_2"
    assert len(calls) == 2
