"""
NanoCats WebSocket Server - Real-time agent monitoring
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, Set

from websockets.server import WebSocketServerProtocol, serve

logger = logging.getLogger("nanobot.websocket")

PROJECTS_PATH = Path.home() / "proyectos"


class NanoCatsWebSocket:
    def __init__(self, host: str = "0.0.0.0", port: int = 18791):
        self.host = host
        self.port = port
        self.clients: Set[WebSocketServerProtocol] = set()
        self.agents: Dict[str, Any] = {}
        self.projects: Dict[str, Any] = {}

        # Initialize projects from directory
        self._scan_projects()

    def _scan_projects(self):
        """Scan projects directory"""
        from nanobot.db.nanocats import get_nanocats_db

        db = get_nanocats_db()

        # Check if we have saved projects
        saved_projects = db.get_projects(include_hidden=True)

        if saved_projects:
            # Use saved projects
            for p in saved_projects:
                self.projects[p["id"]] = p
        else:
            # Scan directory and save
            base = PROJECTS_PATH
            if base.exists():
                for item in base.iterdir():
                    if item.is_dir() and not item.name.startswith("."):
                        project = {
                            "id": item.name,
                            "name": item.name,
                            "path": str(item),
                            "color": self._get_project_color(item.name),
                            "is_hidden": False,
                        }
                        self.projects[item.name] = project
                        db.save_project(project)

        logger.info(f"Loaded {len(self.projects)} projects")

    def _get_project_color(self, name: str) -> str:
        """Generate color based on project name"""
        colors = [
            "#f472b6",
            "#ec4899",
            "#db2777",
            "#a78bfa",
            "#8b5cf6",
            "#7c3aed",
            "#60a5fa",
            "#3b82f6",
            "#2563eb",
            "#34d399",
            "#10b981",
            "#059669",
            "#fbbf24",
            "#f59e0b",
            "#d97706",
            "#f87171",
            "#ef4444",
            "#dc2626",
        ]
        hash_val = sum(ord(c) for c in name)
        return colors[hash_val % len(colors)]

    async def broadcast(self, message: Dict[str, Any]):
        """Broadcast message to all connected clients"""
        if not self.clients:
            return

        dead_clients = set()
        msg_json = json.dumps(message)

        for client in self.clients:
            try:
                await client.send(msg_json)
            except Exception as e:
                logger.warning(f"Failed to send to client: {e}")
                dead_clients.add(client)

        # Remove dead clients
        self.clients.difference_update(dead_clients)

    async def send_agent_update(self, agent_data: Dict[str, Any]):
        """Send agent status update"""
        self.agents[agent_data["id"]] = agent_data
        await self.broadcast({"type": "agent_update", "payload": agent_data})

    async def send_activity(self, activity_data: Dict[str, Any]):
        """Send activity event"""
        await self.broadcast({"type": "activity", "payload": activity_data})

    async def send_projects(self, projects_data: list):
        """Send projects list"""
        self.projects = {p["id"]: p for p in projects_data}
        await self.broadcast({"type": "project_status", "payload": projects_data})

    async def handler(self, ws: WebSocketServerProtocol, path: str):
        """Handle WebSocket connection"""
        self.clients.add(ws)
        logger.info(f"NanoCats client connected from {ws.remote_address[0]}")

        # Send initial state
        try:
            await ws.send(
                json.dumps({"type": "agent_update", "payload": list(self.agents.values())})
            )
            await ws.send(
                json.dumps({"type": "project_status", "payload": list(self.projects.values())})
            )
        except Exception as e:
            logger.warning(f"Failed to send initial state: {e}")

        try:
            async for message in ws:
                try:
                    data = json.loads(message)
                    # Handle incoming messages (ping/pong, etc)
                    if data.get("type") == "ping":
                        await ws.send(json.dumps({"type": "pong"}))
                except json.JSONDecodeError:
                    pass
        except Exception as e:
            logger.warning(f"WebSocket error: {e}")
        finally:
            self.clients.discard(ws)
            logger.info("NanoCats client disconnected")

    async def start(self):
        """Start WebSocket server"""
        logger.info(f"Starting NanoCats WebSocket server on ws://{self.host}:{self.port}")
        async with serve(self.handler, self.host, self.port):
            await asyncio.Future()  # Run forever

    def run(self):
        """Run the WebSocket server"""
        asyncio.run(self.start())


# Global instance
_nanocats_ws: NanoCatsWebSocket = None


def get_nanocats_ws() -> NanoCatsWebSocket:
    global _nanocats_ws
    return _nanocats_ws


async def send_agent_update(agent_data: Dict[str, Any]):
    global _nanocats_ws
    if _nanocats_ws:
        await _nanocats_ws.send_agent_update(agent_data)


async def send_activity(activity_data: Dict[str, Any]):
    global _nanocats_ws
    if _nanocats_ws:
        await _nanocats_ws.send_activity(activity_data)


def start_nanocats_ws(host: str = "0.0.0.0", port: int = 18791):
    global _nanocats_ws
    _nanocats_ws = NanoCatsWebSocket(host, port)

    async def run_server():
        async with serve(_nanocats_ws.handler, host, port):
            await asyncio.Future()

    import threading

    thread = threading.Thread(target=lambda: asyncio.run(run_server()), daemon=True)
    thread.start()
    logger.info(f"NanoCats WebSocket started on ws://{host}:{port}")
    return _nanocats_ws
