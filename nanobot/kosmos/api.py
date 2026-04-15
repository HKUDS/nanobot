"""REST API endpoints for Kosmos project/task management."""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Coroutine

from aiohttp import web
from loguru import logger

# Type alias for handlers
Handler = Callable[[web.Request], Coroutine[Any, Any, web.Response]]

_STATUS_ALIASES = {
    "in_progress": "progress",
    "in-progress": "progress",
    "in progress": "progress",
}


def _normalize_status(value: str | None) -> str:
    status = str(value or "").strip().lower()
    if not status:
        return ""
    return _STATUS_ALIASES.get(status, status)


def _can_transition(current: str, target: str) -> bool:
    if current == target:
        return True
    allowed = {
        "todo": {"progress"},
        "progress": {"qa", "todo"},
        "qa": {"release", "todo"},
        "release": {"done", "todo", "release"},
        "done": set(),
    }
    return target in allowed.get(current, set())


def _normalize_and_validate_project_path(path_value: Any) -> tuple[str | None, str | None]:
    raw = str(path_value or "").strip()
    if not raw:
        return None, "name and path are required"

    path_obj = Path(raw).expanduser()
    if not path_obj.is_absolute():
        return None, "Project path must be absolute"

    normalized = str(path_obj.resolve(strict=False))
    normalized_path = Path(normalized)

    if not normalized_path.exists():
        return None, f"Project path does not exist: {normalized}"
    if not normalized_path.is_dir():
        return None, f"Project path is not a directory: {normalized}"

    return normalized, None


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

    return json_response(
        {
            "projects": projects,
            "total": len(projects),
        }
    )


async def create_project(request: web.Request) -> web.Response:
    """POST /api/projects - Create a new project."""
    try:
        data = await request.json()
    except Exception:
        return error_response("Invalid JSON body")

    name = str(data.get("name") or "").strip()
    path = data.get("path")

    if not name or not path:
        return error_response("name and path are required")

    normalized_path, validation_error = _normalize_and_validate_project_path(path)
    if validation_error:
        return error_response(validation_error, status=400)

    db = request.app["kosmos_db"]
    project = await request.app["db_ops"].create_project(
        db=db,
        name=name,
        path=normalized_path,
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

    if "path" in data:
        normalized_path, validation_error = _normalize_and_validate_project_path(data.get("path"))
        if validation_error:
            return error_response(validation_error, status=400)
        data["path"] = normalized_path

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

    return json_response(
        {
            "tasks": tasks,
            "total": len(tasks),
        }
    )


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


async def transition_task(request: web.Request) -> web.Response:
    """POST /api/tasks/:id/transition - Transition workflow status with optional comment."""
    task_id = request.match_info["id"]
    db = request.app["kosmos_db"]

    try:
        data = await request.json()
    except Exception:
        return error_response("Invalid JSON body")

    target_status = _normalize_status(data.get("to_status"))
    if not target_status:
        return error_response("to_status is required")

    task = await request.app["db_ops"].get_task(db, task_id)
    if not task:
        return not_found(f"Task {task_id} not found")

    current_status = _normalize_status(task.get("status"))
    if not _can_transition(current_status, target_status):
        return error_response(
            f"Invalid transition: {current_status or 'unknown'} -> {target_status}",
            status=409,
        )

    if target_status == "done" and not bool(task.get("release_approved")):
        return error_response(
            "Task cannot move to done without release approval",
            status=409,
        )

    updates: dict[str, Any] = {"status": target_status}
    if "assigned_to" in data:
        updates["assigned_to"] = data.get("assigned_to")

    if target_status == "todo":
        updates.update(
            {
                "release_approved": False,
                "approved_by": None,
                "approved_branch": None,
                "approved_push": False,
                "approved_at": None,
            }
        )

    updated_task = await request.app["db_ops"].update_task(db, task_id, **updates)
    if not updated_task:
        return not_found(f"Task {task_id} not found")

    broadcaster: EventBroadcaster = request.app.get("broadcaster")
    if broadcaster:
        await broadcaster.broadcast_event("task:updated", updated_task)

    comment_text = str(data.get("comment_text") or "").strip()
    if comment_text:
        agent_id = str(data.get("agent_id") or "").strip() or "system"
        agent_name = str(data.get("agent_name") or "").strip() or agent_id
        comment = await request.app["db_ops"].create_task_comment(
            db=db,
            task_id=task_id,
            agent_id=agent_id,
            agent_name=agent_name,
            comment=comment_text,
        )
        if broadcaster:
            await broadcaster.broadcast_event("task:comment_created", comment)

    return json_response(updated_task)


async def approve_release(request: web.Request) -> web.Response:
    """POST /api/tasks/:id/approve_release - Human approval for release stage."""
    task_id = request.match_info["id"]
    db = request.app["kosmos_db"]

    try:
        data = await request.json()
    except Exception:
        return error_response("Invalid JSON body")

    approved_by = str(data.get("approved_by") or "").strip()
    branch = str(data.get("branch") or "").strip()
    push = bool(data.get("push", False))
    if not approved_by or not branch:
        return error_response("approved_by and branch are required")

    task = await request.app["db_ops"].get_task(db, task_id)
    if not task:
        return not_found(f"Task {task_id} not found")
    if _normalize_status(task.get("status")) != "release":
        return error_response("Task must be in release status", status=409)

    updated_task = await request.app["db_ops"].update_task(
        db,
        task_id,
        release_approved=True,
        approved_by=approved_by,
        approved_branch=branch,
        approved_push=push,
        approved_at=datetime.utcnow().isoformat(),
    )
    if not updated_task:
        return not_found(f"Task {task_id} not found")

    broadcaster: EventBroadcaster = request.app.get("broadcaster")
    if broadcaster:
        await broadcaster.broadcast_event("task:updated", updated_task)

    comment_text = str(data.get("comment_text") or "").strip()
    if comment_text:
        comment = await request.app["db_ops"].create_task_comment(
            db=db,
            task_id=task_id,
            agent_id=approved_by,
            agent_name=approved_by,
            comment=comment_text,
        )
        if broadcaster:
            await broadcaster.broadcast_event("task:comment_created", comment)

    return json_response(updated_task)


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

    return json_response(
        {
            "comments": comments,
            "total": len(comments),
        }
    )


async def create_task_comment(request: web.Request) -> web.Response:
    """POST /api/tasks/:id/comments - Create a new comment for a task."""
    task_id = request.match_info["id"]

    try:
        data = await request.json()
    except Exception:
        return error_response("Invalid JSON body")

    agent_id = str(data.get("agent_id") or "").strip()
    agent_name = str(data.get("agent_name") or "").strip()
    comment = str(data.get("comment") or data.get("comment_text") or "").strip()

    if not agent_id or not comment:
        return error_response("agent_id and comment are required")

    db = request.app["kosmos_db"]
    task = await request.app["db_ops"].get_task(db, task_id)
    if not task:
        return not_found(f"Task {task_id} not found")

    assigned_to = str(task.get("assigned_to") or "").strip()
    if assigned_to:
        allowed = {assigned_to.lower()}
        if agent_name:
            allowed.add(agent_name.lower())
        if agent_id.lower() not in allowed and (
            not agent_name or agent_name.lower() not in allowed
        ):
            return error_response(
                "agent_id must match task assigned_to",
                status=409,
            )

    if not agent_name:
        agent_name = agent_id

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
    return json_response(
        {
            "agents": list(agents.values()),
            "total": len(agents),
        }
    )


async def upsert_agent(request: web.Request) -> web.Response:
    """POST /api/agents - Upsert agent identity in memory."""
    try:
        data = await request.json()
    except Exception:
        return error_response("Invalid JSON body")

    agent_id = str(data.get("id") or "").strip()
    agent_name = str(data.get("name") or "").strip()
    if not agent_id or not agent_name:
        return error_response("id and name are required")

    status = str(data.get("status") or "working")
    mood = str(data.get("mood") or "focused")
    current_task = str(data.get("currentTask") or "")

    # Despawn semantics: resting + sleepy + empty task removes agent from memory.
    if (
        status.strip().lower() == "resting"
        and mood.strip().lower() == "sleepy"
        and not current_task.strip()
    ):
        agents = request.app.get("agents", {})
        removed = bool(agents.pop(agent_id, None))
        broadcaster: EventBroadcaster = request.app.get("broadcaster")
        if broadcaster and removed:
            await broadcaster.broadcast_event("agent_removed", {"id": agent_id})
        return json_response({"id": agent_id, "removed": removed})

    agent = {
        "id": agent_id,
        "name": agent_name,
        "type": str(data.get("type") or "agent"),
        "status": status,
        "mood": mood,
        "currentTask": current_task,
        "projectId": str(data.get("projectId") or ""),
        "lastActivity": str(data.get("lastActivity") or datetime.utcnow().isoformat()),
    }

    agents = request.app.get("agents", {})
    agents[agent_id] = agent

    broadcaster: EventBroadcaster = request.app.get("broadcaster")
    if broadcaster:
        await broadcaster.broadcast_event("agent_update", agent)

    return json_response(agent)


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
        await broadcaster.broadcast_event(
            "agent_heartbeat",
            {
                "agent_id": agent_id,
                "timestamp": asyncio.get_event_loop().time(),
            },
        )

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


async def publish_activity(request: web.Request) -> web.Response:
    """POST /api/events/activity - Broadcast an activity event."""
    try:
        payload = await request.json()
    except Exception:
        return error_response("Invalid JSON body")

    if not isinstance(payload, dict):
        return error_response("Activity payload must be an object")

    broadcaster: EventBroadcaster = request.app.get("broadcaster")
    if broadcaster:
        await broadcaster.broadcast_event("activity", payload)

    return json_response({"status": "ok"}, status=202)


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
    ("POST", "/api/tasks/{id}/transition", transition_task),
    ("POST", "/api/tasks/{id}/approve_release", approve_release),
    ("POST", "/api/tasks", create_task),
    ("PATCH", "/api/tasks/{id}", update_task),
    ("DELETE", "/api/tasks/{id}", delete_task),
    # Agents
    ("GET", "/api/agents", list_agents),
    ("POST", "/api/agents", upsert_agent),
    ("POST", "/api/agents/{id}/heartbeat", agent_heartbeat),
    # Settings
    ("GET", "/api/settings", get_settings),
    ("PATCH", "/api/settings/{key}", update_setting),
    # Events
    ("POST", "/api/events/activity", publish_activity),
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
