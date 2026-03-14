"""SoulMemoryGateway: WebSocket gateway server with Soul & Memory support.

Provides a JSON-RPC WebSocket server that routes messages to agents with
Soul persona injection and Memory tool support.

Reference: OpenClaw src/gateway/server.impl.ts

RPC Methods:
  Inherited from base gateway:
    - health: Health check (extended with features list)
    - chat.send: Send message (uses soul+memory agent)
    - chat.history: Session history
    - routing.resolve: Route diagnostics (extended with soul/memory status)
    - routing.bindings: List binding rules
    - sessions.list: List active sessions

  New in s06:
    - memory.status: Query agent memory status
    - soul.get: View agent SOUL.md content
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.soul.workspace import AgentWorkspace
from nanobot.soul.tools import MemoryManager, get_memory_manager

try:
    import websockets
    from websockets.asyncio.server import ServerConnection
    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False


# JSON-RPC constants
JSONRPC_VERSION = "2.0"
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INTERNAL_ERROR = -32603
AUTH_ERROR = -32000


def make_result(id: str | int, result: Any) -> str:
    return json.dumps({"jsonrpc": JSONRPC_VERSION, "id": id, "result": result})


def make_error(id: str | int | None, code: int, message: str) -> str:
    return json.dumps({"jsonrpc": JSONRPC_VERSION, "id": id, "error": {"code": code, "message": message}})


def make_event(event_type: str, data: dict) -> str:
    return json.dumps({"jsonrpc": JSONRPC_VERSION, "method": "event", "params": {"type": event_type, **data}})


@dataclass
class ConnectedClient:
    """Tracks a connected WebSocket client."""
    client_id: str
    ws: Any  # WebSocket connection
    channel: str = ""
    sender: str = ""
    peer_kind: str = "direct"
    guild_id: str | None = None
    account_id: str | None = None


@dataclass
class AgentConfig:
    """Minimal agent configuration for routing."""
    id: str
    model: str = "deepseek-chat"
    system_prompt: str = ""
    tools: list[str] = field(default_factory=list)


class SoulMemoryGateway:
    """WebSocket gateway server with Soul & Memory integration.

    Handles JSON-RPC requests over WebSocket, routing messages to agents
    that have soul persona and memory tools injected.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 18789,
        workspaces: dict[str, AgentWorkspace] | None = None,
        token: str = "",
    ) -> None:
        if not HAS_WEBSOCKETS:
            raise ImportError("websockets package required: pip install websockets")

        self.host = host
        self.port = port
        self.token = token
        self.workspaces = workspaces or {}
        self.clients: dict[str, ConnectedClient] = {}
        self._methods: dict[str, Any] = {
            "health": self._handle_health,
            "soul.get": self._handle_soul_get,
            "memory.status": self._handle_memory_status,
        }

    def _authenticate(self, headers: Any) -> bool:
        """Validate Bearer token if configured."""
        if not self.token:
            return True
        auth = headers.get("Authorization", "")
        return auth == f"Bearer {self.token}"

    async def _handle_connection(self, ws: Any) -> None:
        """Handle a single WebSocket connection lifecycle."""
        client_id = str(uuid.uuid4())[:8]
        client = ConnectedClient(client_id=client_id, ws=ws)
        self.clients[client_id] = client

        # Send welcome event
        await ws.send(make_event("connected", {"client_id": client_id}))
        logger.info("Client connected: {}", client_id)

        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    await ws.send(make_error(None, PARSE_ERROR, "Invalid JSON"))
                    continue

                req_id = msg.get("id")
                method = msg.get("method", "")
                params = msg.get("params", {})

                handler = self._methods.get(method)
                if not handler:
                    await ws.send(make_error(req_id, METHOD_NOT_FOUND, f"Unknown method: {method}"))
                    continue

                try:
                    result = await handler(client, params)
                    await ws.send(make_result(req_id, result))
                except Exception as e:
                    logger.exception("RPC error in {}: {}", method, e)
                    await ws.send(make_error(req_id, INTERNAL_ERROR, str(e)))
        finally:
            self.clients.pop(client_id, None)
            logger.info("Client disconnected: {}", client_id)

    async def _handle_health(self, client: ConnectedClient, params: dict) -> dict:
        """Health check with Soul/Memory feature flags."""
        return {
            "status": "ok",
            "features": ["soul", "memory"],
            "agents": list(self.workspaces.keys()),
            "clients": len(self.clients),
        }

    async def _handle_soul_get(self, client: ConnectedClient, params: dict) -> dict:
        """View an agent's SOUL.md content."""
        agent_id = params.get("agent_id", "")
        ws = self.workspaces.get(agent_id)
        if ws is None:
            return {"agent_id": agent_id, "soul": "", "exists": False, "error": "Agent not found"}
        soul = ws.read_soul()
        return {"agent_id": agent_id, "soul": soul, "exists": ws.has_soul()}

    async def _handle_memory_status(self, client: ConnectedClient, params: dict) -> dict:
        """Query an agent's memory status."""
        agent_id = params.get("agent_id", "")
        ws = self.workspaces.get(agent_id)
        if ws is None:
            return {"agent_id": agent_id, "error": "Agent not found"}
        mgr = get_memory_manager(agent_id, ws.workspace_dir)
        evergreen = mgr.load_evergreen()
        recent = mgr.get_recent_daily(days=7)
        return {
            "agent_id": agent_id,
            "workspace": str(ws.workspace_dir),
            "memory_md_chars": len(evergreen),
            "recent_daily_count": len(recent),
            "recent_daily": [
                {"date": e["date"], "lines": e["content"].count("\n") + 1}
                for e in recent
            ],
        }

    async def start(self) -> None:
        """Start the WebSocket gateway server."""
        logger.info("Starting SoulMemoryGateway on {}:{}", self.host, self.port)

        async with websockets.serve(
            self._handle_connection,
            self.host,
            self.port,
        ):
            logger.info("Gateway ready on ws://{}:{}", self.host, self.port)
            await asyncio.Future()  # run forever
