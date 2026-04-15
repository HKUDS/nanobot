"""
NanoCats API - REST endpoints for the web UI
"""
import json
import logging
from pathlib import Path
from typing import Optional
from aiohttp import web

from nanobot.db.nanocats import get_nanocats_db

logger = logging.getLogger("nanocats.api")

routes = web.RouteTableDef()

PROJECTS_PATH = Path.home() / "proyectos"


@routes.get("/api/projects")
async def get_projects(request: web.Request) -> web.Response:
    """Get all projects (optionally filtered by hidden status)"""
    db = get_nanocats_db()
    include_hidden = request.query.get("hidden", "false").lower() == "true"
    
    projects = db.get_projects(include_hidden=include_hidden)
    
    # If no projects in DB, scan the directory
    if not projects:
        projects = db.scan_projects(str(PROJECTS_PATH))
        for p in projects:
            db.save_project(p)
        projects = db.get_projects(include_hidden=include_hidden)
    
    return web.json_response(projects)


@routes.post("/api/projects/scan")
async def scan_projects(request: web.Request) -> web.Response:
    """Rescan projects directory"""
    db = get_nanocats_db()
    include_hidden = request.query.get("include_hidden", "true").lower() == "true"
    
    # Get current hidden status
    current_projects = db.get_projects(include_hidden=True)
    hidden_ids = {p["id"] for p in current_projects if p.get("is_hidden")}
    
    # Scan directory
    new_projects = db.scan_projects(str(PROJECTS_PATH))
    
    # Preserve hidden status
    for p in new_projects:
        p["is_hidden"] = 1 if p["id"] in hidden_ids else 0
        db.save_project(p)
    
    projects = db.get_projects(include_hidden=include_hidden)
    return web.json_response(projects)


@routes.patch("/api/projects/{project_id}/hidden")
async def toggle_hidden(request: web.Request) -> web.Response:
    """Toggle project hidden status"""
    db = get_nanocats_db()
    project_id = request.match_info["project_id"]
    
    body = await request.json()
    hidden = body.get("hidden", True)
    
    db.toggle_hidden(project_id, hidden)
    
    return web.json_response({"success": True, "hidden": hidden})


@routes.get("/api/agents")
async def get_agents(request: web.Request) -> web.Response:
    """Get saved agent states"""
    db = get_nanocats_db()
    agents = db.get_agents()
    return web.json_response(agents)


@routes.post("/api/agents")
async def save_agent(request: web.Request) -> web.Response:
    """Save agent state"""
    db = get_nanocats_db()
    agent = await request.json()
    db.save_agent(agent)
    return web.json_response({"success": True})


@routes.get("/api/settings/{key}")
async def get_setting(request: web.Request) -> web.Response:
    """Get a setting value"""
    db = get_nanocats_db()
    key = request.match_info["key"]
    value = db.get_setting(key)
    return web.json_response({"key": key, "value": value})


@routes.put("/api/settings/{key}")
async def set_setting(request: web.Request) -> web.Response:
    """Set a setting value"""
    db = get_nanocats_db()
    key = request.match_info["key"]
    body = await request.json()
    value = body.get("value", "")
    db.set_setting(key, value)
    return web.json_response({"success": True})


@routes.get("/api/stats")
async def get_stats(request: web.Request) -> web.Response:
    """Get usage statistics"""
    db = get_nanocats_db()
    
    # Count projects
    all_projects = db.get_projects(include_hidden=True)
    visible_projects = [p for p in all_projects if not p.get("is_hidden")]
    hidden_projects = [p for p in all_projects if p.get("is_hidden")]
    
    # Count agents
    agents = db.get_agents()
    active_agents = [a for a in agents if a.get("status") != "idle"]
    
    return web.json_response({
        "total_projects": len(all_projects),
        "visible_projects": len(visible_projects),
        "hidden_projects": len(hidden_projects),
        "total_agents": len(agents),
        "active_agents": len(active_agents)
    })


def create_app() -> web.Application:
    """Create aiohttp application"""
    app = web.Application()
    app.add_routes(routes)
    return app


async def start_api(host: str = "0.0.0.0", port: int = 18792):
    """Start the API server"""
    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    logger.info(f"NanoCats API started on http://{host}:{port}")
    return runner
