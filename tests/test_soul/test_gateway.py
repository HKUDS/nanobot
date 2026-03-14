"""Tests for nanobot.soul.gateway module."""

import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from nanobot.soul.workspace import AgentWorkspace
from nanobot.soul.gateway import (
    ConnectedClient,
    SoulMemoryGateway,
    make_result,
    make_error,
    make_event,
    JSONRPC_VERSION,
    PARSE_ERROR,
    METHOD_NOT_FOUND,
)


@pytest.fixture
def workspace(tmp_path):
    ws_dir = tmp_path / "main"
    ws = AgentWorkspace(agent_id="main", workspace_dir=ws_dir)
    ws.ensure_soul()
    (ws_dir / "MEMORY.md").write_text("# Memory\n\nTest memory content.\n", encoding="utf-8")
    return ws


@pytest.fixture
def gateway(workspace):
    return SoulMemoryGateway(
        host="127.0.0.1",
        port=0,
        workspaces={"main": workspace},
        token="",
    )


@pytest.fixture
def mock_client():
    client = ConnectedClient(
        client_id="test-001",
        ws=AsyncMock(),
        channel="test",
        sender="user",
    )
    return client


class TestJsonRpcHelpers:
    """Tests for JSON-RPC message helpers."""

    def test_make_result(self):
        msg = json.loads(make_result("r-1", {"status": "ok"}))
        assert msg["jsonrpc"] == JSONRPC_VERSION
        assert msg["id"] == "r-1"
        assert msg["result"]["status"] == "ok"

    def test_make_error(self):
        msg = json.loads(make_error("r-2", PARSE_ERROR, "bad json"))
        assert msg["error"]["code"] == PARSE_ERROR
        assert msg["error"]["message"] == "bad json"

    def test_make_event(self):
        msg = json.loads(make_event("connected", {"client_id": "abc"}))
        assert msg["method"] == "event"
        assert msg["params"]["type"] == "connected"
        assert msg["params"]["client_id"] == "abc"


class TestSoulMemoryGateway:
    """Tests for SoulMemoryGateway RPC handlers."""

    @pytest.mark.asyncio
    async def test_health(self, gateway, mock_client):
        result = await gateway._handle_health(mock_client, {})
        assert result["status"] == "ok"
        assert "soul" in result["features"]
        assert "memory" in result["features"]
        assert "main" in result["agents"]

    @pytest.mark.asyncio
    async def test_soul_get_existing(self, gateway, mock_client):
        result = await gateway._handle_soul_get(mock_client, {"agent_id": "main"})
        assert result["exists"] is True
        assert "SOUL.md" in result["soul"]

    @pytest.mark.asyncio
    async def test_soul_get_missing_agent(self, gateway, mock_client):
        result = await gateway._handle_soul_get(mock_client, {"agent_id": "nonexistent"})
        assert result["exists"] is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_memory_status(self, gateway, mock_client):
        result = await gateway._handle_memory_status(mock_client, {"agent_id": "main"})
        assert result["agent_id"] == "main"
        assert result["memory_md_chars"] > 0
        assert "workspace" in result

    @pytest.mark.asyncio
    async def test_memory_status_missing_agent(self, gateway, mock_client):
        result = await gateway._handle_memory_status(mock_client, {"agent_id": "ghost"})
        assert "error" in result

    def test_authenticate_no_token(self, gateway):
        assert gateway._authenticate({}) is True

    def test_authenticate_with_token(self, tmp_path):
        ws = AgentWorkspace(agent_id="main", workspace_dir=tmp_path / "main")
        gw = SoulMemoryGateway(token="secret", workspaces={"main": ws})
        headers = {"Authorization": "Bearer secret"}
        assert gw._authenticate(headers) is True

    def test_authenticate_wrong_token(self, tmp_path):
        ws = AgentWorkspace(agent_id="main", workspace_dir=tmp_path / "main")
        gw = SoulMemoryGateway(token="secret", workspaces={"main": ws})
        headers = {"Authorization": "Bearer wrong"}
        assert gw._authenticate(headers) is False


class TestConnectedClient:
    """Tests for ConnectedClient dataclass."""

    def test_defaults(self):
        client = ConnectedClient(client_id="c1", ws=None)
        assert client.channel == ""
        assert client.sender == ""
        assert client.peer_kind == "direct"
        assert client.guild_id is None
