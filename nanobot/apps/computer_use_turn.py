"""Bind a native MCP window lease to a gateway-owned run, not model arguments."""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.agent.tools.context import current_tool_run

if TYPE_CHECKING:
    from mcp import ClientSession
    from mcp.types import CallToolResult


class NativeTurnTransport:
    def __init__(self, session: ClientSession):
        self.session = session
        self.scopes: set[str] = set()

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> CallToolResult:
        scope = current_tool_run()
        if scope is None:
            raise RuntimeError("Computer Use needs a gateway-owned agent run.")
        if scope.id not in self.scopes:
            self.scopes.add(scope.id)
            scope.cleanup.push_async_callback(self.finish, scope.id)
        return await self.session.call_tool(name, arguments=arguments, meta={"nanobot/turn": scope.id})

    async def finish(self, scope: str) -> None:
        self.scopes.discard(scope)
        try:
            async with asyncio.timeout(5):
                await self.session.call_tool("nanobot_finish_turn", arguments={}, meta={"nanobot/turn": scope})
        except Exception:
            # A closed MCP process also closes all native channels. If the
            # process is stalled instead, native idle expiry remains bounded.
            logger.warning("Computer Use task cleanup could not be acknowledged; no action was retried.")
