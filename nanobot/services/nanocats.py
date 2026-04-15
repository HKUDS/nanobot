"""
NanoCats Service - Integrated WebSocket + API server for agent monitoring
"""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from aiohttp import web
from websockets.server import serve, WebSocketServerProtocol

from nanobot.db.nanocats import get_nanocats_db

logger = logging.getLogger("nanobot.nanocats")

PROJECTS_PATH = Path.home() / "proyectos"


class NanoCatsService:
    """Combined WebSocket + REST API for NanoCats dashboard"""

    def __init__(self, ws_port: int = 18791, api_port: int = 18792):
        self.ws_port = ws_port
        self.api_port = api_port
        self.clients: set[WebSocketServerProtocol] = set()
        self._ws_server = None
        self._api_runner = None
        self._running = False
        self._heartbeat_task = None

        # Initialize projects
        self._scan_projects()

    def _scan_projects(self):
        """Scan projects directory and save to DB"""
        db = get_nanocats_db()

        # Get current hidden status
        saved = db.get_projects(include_hidden=True)
        hidden_ids = {p["id"] for p in saved if p.get("is_hidden")}

        # Scan directory
        base = PROJECTS_PATH
        if base.exists():
            for item in base.iterdir():
                if item.is_dir() and not item.name.startswith("."):
                    if item.name not in hidden_ids:
                        project = {
                            "id": item.name,
                            "name": item.name,
                            "path": str(item),
                            "color": self._get_color(item.name),
                            "is_hidden": 0,
                        }
                        db.save_project(project)

        logger.info(f"NanoCats: loaded {len(db.get_projects(include_hidden=True))} projects")

    def _get_color(self, name: str) -> str:
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
        return colors[sum(ord(c) for c in name) % len(colors)]

    # === WebSocket Handlers ===

    async def _ws_handler(self, ws: WebSocketServerProtocol, path: str):
        self.clients.add(ws)
        logger.info(f"NanoCats: client connected from {ws.remote_address[0]}")

        # Send initial state
        db = get_nanocats_db()
        projects = db.get_projects(include_hidden=True)
        agents = db.get_agents()

        await ws.send(json.dumps({"type": "project_status", "payload": projects}))
        await ws.send(json.dumps({"type": "agent_update", "payload": agents}))

        try:
            async for msg in ws:
                try:
                    data = json.loads(msg)
                    if data.get("type") == "ping":
                        await ws.send(json.dumps({"type": "pong"}))
                except json.JSONDecodeError:
                    pass
        except Exception as e:
            logger.debug(f"NanoCats: client disconnected: {e}")
        finally:
            self.clients.discard(ws)

    async def _broadcast_ws(self, message: dict):
        """Broadcast to all WebSocket clients"""
        if not self.clients:
            return

        msg_json = json.dumps(message)
        dead = set()

        for client in self.clients:
            try:
                await client.send(msg_json)
            except Exception:
                dead.add(client)

        self.clients.difference_update(dead)

    async def send_agent_update(self, agent_data: dict):
        """Send agent status update"""
        db = get_nanocats_db()
        db.save_agent(agent_data)
        await self._broadcast_ws({"type": "agent_update", "payload": agent_data})

    async def send_activity(self, activity_data: dict):
        """Send activity event"""
        await self._broadcast_ws({"type": "activity", "payload": activity_data})

    # === REST API Handlers ===

    async def handle_projects(self, request: web.Request) -> web.Response:
        db = get_nanocats_db()
        include_hidden = request.query.get("hidden", "false").lower() == "true"
        projects = db.get_projects(include_hidden=include_hidden)
        return web.json_response(projects)

    async def handle_scan_projects(self, request: web.Request) -> web.Response:
        self._scan_projects()
        db = get_nanocats_db()
        projects = db.get_projects(include_hidden=True)
        return web.json_response(projects)

    async def handle_toggle_hidden(self, request: web.Request) -> web.Response:
        db = get_nanocats_db()
        project_id = request.match_info["project_id"]
        body = await request.json()
        hidden = body.get("hidden", True)
        db.toggle_hidden(project_id, hidden)

        # Broadcast update
        projects = db.get_projects(include_hidden=True)
        await self._broadcast_ws({"type": "project_status", "payload": projects})

        return web.json_response({"success": True, "hidden": hidden})

    async def handle_agents(self, request: web.Request) -> web.Response:
        db = get_nanocats_db()
        agents = db.get_agents()
        return web.json_response(agents)

    async def handle_save_agent(self, request: web.Request) -> web.Response:
        db = get_nanocats_db()
        agent = await request.json()
        db.save_agent(agent)
        return web.json_response({"success": True})

    async def handle_stats(self, request: web.Request) -> web.Response:
        db = get_nanocats_db()
        all_projects = db.get_projects(include_hidden=True)
        agents = db.get_agents()

        return web.json_response(
            {
                "total_projects": len(all_projects),
                "visible_projects": len([p for p in all_projects if not p.get("is_hidden")]),
                "hidden_projects": len([p for p in all_projects if p.get("is_hidden")]),
                "total_agents": len(agents),
                "active_agents": len([a for a in agents if a.get("status") != "idle"]),
            }
        )

    # === Server Lifecycle ===

    async def start(self):
        """Start both WebSocket and REST API servers"""
        if self._running:
            logger.warning("NanoCats already running")
            return

        self._running = True

        # Start WebSocket server
        self._ws_server = await serve(self._ws_handler, "0.0.0.0", self.ws_port)

        # Start REST API
        app = web.Application()
        app.router.add_get("/api/projects", self.handle_projects)
        app.router.add_post("/api/projects/scan", self.handle_scan_projects)
        app.router.add_patch("/api/projects/{project_id}/hidden", self.handle_toggle_hidden)
        app.router.add_get("/api/agents", self.handle_agents)
        app.router.add_post("/api/agents", self.handle_save_agent)
        app.router.add_get("/api/stats", self.handle_stats)

        self._api_runner = web.AppRunner(app)
        await self._api_runner.setup()
        site = web.TCPSite(self._api_runner, "0.0.0.0", self.api_port)
        await site.start()

        # Start heartbeat to send periodic updates
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        logger.info(f"🐱 NanoCats WebSocket: ws://0.0.0.0:{self.ws_port}")
        logger.info(f"🐱 NanoCats API: http://0.0.0.0:{self.api_port}")

    async def _heartbeat_loop(self):
        """Send periodic heartbeat to all connected clients"""
        db = get_nanocats_db()

        while self._running:
            await asyncio.sleep(30)

            # Get agents from database
            agents_raw = db.get_agents()

            # Transform to frontend format
            agents = []
            for a in agents_raw:
                agent = {
                    "id": a.get("id", ""),
                    "name": a.get("name", "Unknown"),
                    "type": "agent" if a.get("name") == "Kosmos" else "subagent",
                    "status": a.get("status", "idle"),
                    "mood": a.get("mood", "focused"),
                    "currentTask": a.get("current_task", ""),
                    "projectId": a.get("project_id", ""),
                    "lastActivity": a.get("last_activity", datetime.now().isoformat()),
                }
                if a.get("tokens_used"):
                    agent["tokensUsed"] = a.get("tokens_used")
                agents.append(agent)

            if agents:
                await self._broadcast_ws({"type": "agent_update", "agents": agents})
                logger.debug(f"💓 Heartbeat: {len(agents)} agents")

            # Also send project status
            projects = db.get_projects(include_hidden=True)
            await self._broadcast_ws({"type": "project_status", "projects": projects})

    async def stop(self):
        """Stop both servers"""
        self._running = False
        if self._ws_server:
            self._ws_server.close()
            await self._ws_server.wait_closed()
        if self._api_runner:
            await self._api_runner.cleanup()
        logger.info("NanoCats stopped")


# Global instance
_nanocats: Optional[NanoCatsService] = None


def get_nanocats() -> NanoCatsService:
    global _nanocats
    if _nanocats is None:
        _nanocats = NanoCatsService()
    return _nanocats


async def start_nanocats(ws_port: int = 18791, api_port: int = 18792):
    """Start NanoCats service"""
    global _nanocats
    _nanocats = NanoCatsService(ws_port, api_port)
    await _nanocats.start()
    return _nanocats
