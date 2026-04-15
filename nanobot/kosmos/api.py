"""REST API endpoints for Kosmos project/task management."""
from __future__ import annotations

import asyncio
import json
from typing import Any, Callable, Coroutine, Optional

from aiohttp import web
from loguru import logger


# Type alias for handlers
Handler = Callable[[web.Request], Coroutine[Any, Any, web.Response]]


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------

def json_response(data: Any, status: int = 200) -> web.Response:
    """Return a JSON response."""
    return web.json_response(data, status=status)


def error_response(message: str, status: int = 400) -> web.Response:
    """Return an error JSON response."""
    return web.json_response({"error": message}, status=status)


def not_found(message: str = "Not found") -> web.Response:
    """Return a 404 response."""
    return error_response(message, 404)


# ---------------------------------------------------------------------------
# Event broadcaster
# ---------------------------------------------------------------------------

class EventBroadcaster:
    """Mixin for broadcasting WebSocket events when DB changes occur."""
    
    async def broadcast_event(self, event_type: str, payload: Any):
        """Broadcast an event to all WebSocket clients.
        
        Override this in the server to integrate with WebSocket.
        """
        logger.debug("Event: {} - {}", event_type, payload)


# ---------------------------------------------------------------------------
# Project handlers
# ---------------------------------------------------------------------------

async def list_projects(request: web.Request) -> web.Response:
    """GET /api/projects - List all projects with task count."""
    db = request.app["kosmos_db"]
    include_hidden = request.query.get("include_hidden", "false").lower() == "true"
    
    projects = await request.app["db_ops"].get_projects_with_task_count(db, include_hidden)
    
    return json_response({
        "projects": projects,
        "total": len(projects),
    })


async def create_project(request: web.Request) -> web.Response:
    """POST /api/projects - Create a new project."""
    try:
        data = await request.json()
    except Exception:
        return error_response("Invalid JSON body")
    
    name = data.get("name")
    path = data.get("path")
    
    if not name or not path:
        return error_response("name and path are required")
    
    db = request.app["kosmos_db"]
    project = await request.app["db_ops"].create_project(
        db=db,
        name=name,
        path=path,
        color=data.get("color", "#6b7280"),
        is_hidden=data.get("is_hidden", False),
    )
    
    # Broadcast event
    broadcaster: EventBroadcaster = request.app.get("broadcaster")
    if broadcaster:
        await broadcaster.broadcast_event("project:created", project)
    
    return json_response(project, status=201)


async def update_project(request: web.Request) -> web.Response:
    """PATCH /api/projects/:id - Update a project."""
    project_id = request.match_info["id"]
    
    try:
        data = await request.json()
    except Exception:
        return error_response("Invalid JSON body")
    
    db = request.app["kosmos_db"]
    project = await request.app["db_ops"].update_project(db, project_id, **data)
    
    if not project:
        return not_found(f"Project {project_id} not found")
    
    # Broadcast event
    broadcaster: EventBroadcaster = request.app.get("broadcaster")
    if broadcaster:
        await broadcaster.broadcast_event("project:updated", project)
    
    return json_response(project)


async def delete_project(request: web.Request) -> web.Response:
    """DELETE /api/projects/:id - Delete a project."""
    project_id = request.match_info["id"]
    db = request.app["kosmos_db"]
    
    deleted = await request.app["db_ops"].delete_project(db, project_id)
    
    if not deleted:
        return not_found(f"Project {project_id} not found")
    
    # Broadcast event
    broadcaster: EventBroadcaster = request.app.get("broadcaster")
    if broadcaster:
        await broadcaster.broadcast_event("project:deleted", {"id": project_id})
    
    return json_response({"deleted": True})


# ---------------------------------------------------------------------------
# Task handlers
# ---------------------------------------------------------------------------

async def list_tasks(request: web.Request) -> web.Response:
    """GET /api/tasks - List all tasks, optionally filtered by project_id."""
    db = request.app["kosmos_db"]
    project_id = request.query.get("project_id")

    tasks = await request.app["db_ops"].get_tasks_with_comment_count(db, project_id)

    return json_response({
        "tasks": tasks,
        "total": len(tasks),
    })


async def get_task(request: web.Request) -> web.Response:
    """GET /api/tasks/:id - Get a single task."""
    task_id = request.match_info["id"]
    db = request.app["kosmos_db"]
    
    task = await request.app["db_ops"].get_task(db, task_id)
    
    if not task:
        return not_found(f"Task {task_id} not found")
    
    return json_response(task)


async def create_task(request: web.Request) -> web.Response:
    """POST /api/tasks - Create a new task."""
    try:
        data = await request.json()
    except Exception:
        return error_response("Invalid JSON body")
    
    project_id = data.get("project_id")
    title = data.get("title")
    
    if not project_id or not title:
        return error_response("project_id and title are required")
    
    db = request.app["kosmos_db"]
    task = await request.app["db_ops"].create_task(
        db=db,
        project_id=project_id,
        title=title,
        description=data.get("description"),
        status=data.get("status", "todo"),
        assigned_to=data.get("assigned_to"),
        priority=data.get("priority", "medium"),
    )
    
    # Broadcast event
    broadcaster: EventBroadcaster = request.app.get("broadcaster")
    if broadcaster:
        await broadcaster.broadcast_event("task:created", task)
    
    return json_response(task, status=201)


async def update_task(request: web.Request) -> web.Response:
    """PATCH /api/tasks/:id - Update a task."""
    task_id = request.match_info["id"]
    
    try:
        data = await request.json()
    except Exception:
        return error_response("Invalid JSON body")
    
    db = request.app["kosmos_db"]
    task = await request.app["db_ops"].update_task(db, task_id, **data)
    
    if not task:
        return not_found(f"Task {task_id} not found")
    
    # Broadcast event
    broadcaster: EventBroadcaster = request.app.get("broadcaster")
    if broadcaster:
        await broadcaster.broadcast_event("task:updated", task)
    
    return json_response(task)


async def delete_task(request: web.Request) -> web.Response:
    """DELETE /api/tasks/:id - Delete a task."""
    task_id = request.match_info["id"]
    db = request.app["kosmos_db"]

    deleted = await request.app["db_ops"].delete_task(db, task_id)

    if not deleted:
        return not_found(f"Task {task_id} not found")

    # Broadcast event
    broadcaster: EventBroadcaster = request.app.get("broadcaster")
    if broadcaster:
        await broadcaster.broadcast_event("task:deleted", {"id": task_id})

    return json_response({"deleted": True})


# ---------------------------------------------------------------------------
# Task Comment handlers
# ---------------------------------------------------------------------------

async def list_task_comments(request: web.Request) -> web.Response:
    """GET /api/tasks/:id/comments - Get all comments for a task."""
    task_id = request.match_info["id"]
    db = request.app["kosmos_db"]

    comments = await request.app["db_ops"].get_task_comments(db, task_id)

    return json_response({
        "comments": comments,
        "total": len(comments),
    })


async def create_task_comment(request: web.Request) -> web.Response:
    """POST /api/tasks/:id/comments - Create a new comment for a task."""
    task_id = request.match_info["id"]

    try:
        data = await request.json()
    except Exception:
        return error_response("Invalid JSON body")

    agent_id = data.get("agent_id")
    agent_name = data.get("agent_name", "Unknown")
    comment = data.get("comment")

    if not agent_id or not comment:
        return error_response("agent_id and comment are required")

    db = request.app["kosmos_db"]
    new_comment = await request.app["db_ops"].create_task_comment(
        db=db,
        task_id=task_id,
        agent_id=agent_id,
        agent_name=agent_name,
        comment=comment,
    )

    # Broadcast event
    broadcaster: EventBroadcaster = request.app.get("broadcaster")
    if broadcaster:
        await broadcaster.broadcast_event("task:comment_created", new_comment)

    return json_response(new_comment, status=201)


# ---------------------------------------------------------------------------
# Agent handlers (in-memory, from WebSocket events)
# ---------------------------------------------------------------------------

async def list_agents(request: web.Request) -> web.Response:
    """GET /api/agents - List agents from WebSocket state."""
    agents = request.app.get("agents", {})
    return json_response({
        "agents": list(agents.values()),
        "total": len(agents),
    })


async def agent_heartbeat(request: web.Request) -> web.Response:
    """POST /api/agents/:id/heartbeat - Trigger heartbeat for an agent."""
    agent_id = request.match_info["id"]
    
    agents = request.app.get("agents", {})
    agent = agents.get(agent_id)
    
    if not agent:
        return not_found(f"Agent {agent_id} not found")
    
    # Broadcast heartbeat event to WebSocket clients
    broadcaster: EventBroadcaster = request.app.get("broadcaster")
    if broadcaster:
        await broadcaster.broadcast_event("agent_heartbeat", {
            "agent_id": agent_id,
            "timestamp": asyncio.get_event_loop().time(),
        })
    
    return json_response({"status": "ok", "agent_id": agent_id})


# ---------------------------------------------------------------------------
# Settings handlers
# ---------------------------------------------------------------------------

async def get_settings(request: web.Request) -> web.Response:
    """GET /api/settings - Get all settings."""
    db = request.app["kosmos_db"]
    settings = await request.app["db_ops"].get_settings(db)
    return json_response(settings)


async def update_setting(request: web.Request) -> web.Response:
    """PATCH /api/settings/:key - Update a setting."""
    key = request.match_info["key"]
    
    try:
        data = await request.json()
    except Exception:
        return error_response("Invalid JSON body")
    
    if "value" not in data:
        return error_response("value is required")
    
    db = request.app["kosmos_db"]
    setting = await request.app["db_ops"].update_setting(db, key, data["value"])
    
    # Broadcast event
    broadcaster: EventBroadcaster = request.app.get("broadcaster")
    if broadcaster:
        await broadcaster.broadcast_event("setting:updated", setting)
    
    return json_response(setting)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

async def health_check(request: web.Request) -> web.Response:
    """GET /health - Health check endpoint."""
    return json_response({"status": "ok", "service": "kosmos"})


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------

ROUTES = [
    # Projects
    ("GET", "/api/projects", list_projects),
    ("POST", "/api/projects", create_project),
    ("PATCH", "/api/projects/{id}", update_project),
    ("DELETE", "/api/projects/{id}", delete_project),
    
    # Tasks
    ("GET", "/api/tasks", list_tasks),
    ("GET", "/api/tasks/{id}", get_task),
    ("GET", "/api/tasks/{id}/comments", list_task_comments),
    ("POST", "/api/tasks/{id}/comments", create_task_comment),
    ("POST", "/api/tasks", create_task),
    ("PATCH", "/api/tasks/{id}", update_task),
    ("DELETE", "/api/tasks/{id}", delete_task),
    
    # Agents
    ("GET", "/api/agents", list_agents),
    ("POST", "/api/agents/{id}/heartbeat", agent_heartbeat),
    
    # Settings
    ("GET", "/api/settings", get_settings),
    ("PATCH", "/api/settings/{key}", update_setting),
    
    # Health
    ("GET", "/health", health_check),
]


def add_routes(app: web.Application) -> None:
    """Add all Kosmos API routes to the application."""
    for method, path, handler in ROUTES:
        if method == "GET":
            app.router.add_get(path, handler)
        elif method == "POST":
            app.router.add_post(path, handler)
        elif method == "PATCH":
            app.router.add_patch(path, handler)
        elif method == "DELETE":
            app.router.add_delete(path, handler)
