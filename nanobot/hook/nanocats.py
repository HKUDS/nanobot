"""
NanoCats AgentHook - Sends agent events to WebSocket server
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Optional

from nanobot.agent.hook import AgentHook, AgentHookContext

logger = logging.getLogger("nanobot.hook.nanocats")


class NanoCatsHook(AgentHook):
    """
    Agent hook that broadcasts agent activities to NanoCats WebSocket server.

    Tracks:
    - Agent status changes (thinking, executing, coding, etc.)
    - Tool executions
    - Token usage
    - Errors
    """

    def __init__(self, ws_url: str = "ws://localhost:18791"):
        super().__init__()
        self.ws_url = ws_url
        self.ws: Optional[asyncio.WebSocketClientProtocol] = None
        self._connected = False
        self._pending: list[dict] = []

    async def connect(self):
        """Connect to WebSocket server"""
        try:
            import websockets

            self.ws = await websockets.connect(self.ws_url)
            self._connected = True
            logger.info("🐱 Connected to NanoCats WebSocket")

            # Send initial presence (I am here!)
            await self._send(
                {
                    "type": "agent_update",
                    "payload": {
                        "id": "main-agent",
                        "name": "Kosmos",
                        "type": "agent",
                        "status": "idle",
                        "mood": "relaxed",
                        "currentTask": "Online and ready",
                        "lastActivity": datetime.now().isoformat(),
                    },
                }
            )

            # Send pending messages
            for msg in self._pending:
                await self.ws.send(json.dumps(msg))
            self._pending.clear()
        except Exception as e:
            logger.warning(f"🐱 Failed to connect to NanoCats: {e}")
            self._connected = False

    async def disconnect(self):
        """Disconnect from WebSocket server"""
        if self.ws:
            await self.ws.close()
            self._connected = False

    async def _send(self, msg: dict):
        """Send message to WebSocket"""
        if self._connected and self.ws:
            try:
                await self.ws.send(json.dumps(msg))
            except Exception as e:
                logger.warning(f"🐱 Failed to send: {e}")
                self._connected = False
        else:
            # Queue for later
            self._pending.append(msg)

    async def before_iteration(self, context: AgentHookContext) -> None:
        """Send thinking status"""
        await self._send(
            {
                "type": "agent_update",
                "payload": {
                    "id": "main-agent",
                    "name": "Kosmos",
                    "type": "agent",
                    "status": "thinking",
                    "mood": "focused",
                    "currentTask": f"Iteration {context.iteration + 1}",
                    "lastActivity": datetime.now().isoformat(),
                    "tokensUsed": context.usage,
                },
            }
        )

    async def on_stream(self, context: AgentHookContext, delta: str) -> None:
        """Update streaming status"""
        pass  # Too noisy

    async def before_execute_tools(self, context: AgentHookContext) -> None:
        """Send tool execution status"""
        if context.tool_calls:
            tool_name = context.tool_calls[0].name
            status = self._get_status_for_tool(tool_name)

            await self._send(
                {
                    "type": "activity",
                    "payload": {
                        "id": f"{datetime.now().timestamp()}",
                        "agentId": "main-agent",
                        "agentName": "NanoBot",
                        "type": status,
                        "message": f"Executing: {tool_name}",
                        "timestamp": datetime.now().isoformat(),
                    },
                }
            )

            await self._send(
                {
                    "type": "agent_update",
                    "payload": {
                        "id": "main-agent",
                        "name": "Kosmos",
                        "type": "agent",
                        "status": status,
                        "mood": "busy",
                        "currentTask": f"{tool_name}",
                        "lastActivity": datetime.now().isoformat(),
                    },
                }
            )

    async def after_iteration(self, context: AgentHookContext) -> None:
        """Send iteration completion"""
        status = "idle"
        mood = "happy"

        if context.error:
            status = "idle"
            mood = "tired"
        elif context.tool_results:
            status = "coding"
            mood = "satisfied"

        await self._send(
            {
                "type": "agent_update",
                "payload": {
                    "id": "main-agent",
                    "name": "Kosmos",
                    "type": "agent",
                    "status": status,
                    "mood": mood,
                    "currentTask": None,
                    "lastActivity": datetime.now().isoformat(),
                    "tokensUsed": context.usage,
                },
            }
        )

    def finalize_content(self, context: AgentHookContext, content: str | None) -> str | None:
        """Finalize and send final status"""
        if content:
            asyncio.create_task(
                self._send(
                    {
                        "type": "activity",
                        "payload": {
                            "id": f"{datetime.now().timestamp()}",
                            "agentId": "main-agent",
                            "agentName": "NanoBot",
                            "type": "status",
                            "message": f"Completed: {content[:100]}..."
                            if len(content) > 100
                            else f"Completed: {content}",
                            "timestamp": datetime.now().isoformat(),
                        },
                    }
                )
            )
        return content

    def _get_status_for_tool(self, tool_name: str) -> str:
        """Map tool name to status"""
        if "read" in tool_name or "file" in tool_name:
            return "reading"
        elif "exec" in tool_name or "shell" in tool_name:
            return "executing"
        elif "search" in tool_name or "web" in tool_name:
            return "consulting"
        elif "edit" in tool_name or "write" in tool_name:
            return "coding"
        elif "spawn" in tool_name or "agent" in tool_name:
            return "thinking"
        else:
            return "executing"


def create_nanocats_hook(ws_url: str = "ws://localhost:18791") -> NanoCatsHook:
    """Factory to create NanoCats hook"""
    return NanoCatsHook(ws_url)
