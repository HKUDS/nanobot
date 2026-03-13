"""Dashboard Starlette routes — live agent status UI."""

from __future__ import annotations

import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_INDEX_HTML: str | None = None


def _get_index_html() -> str:
    global _INDEX_HTML
    if _INDEX_HTML is None:
        _INDEX_HTML = (_TEMPLATES_DIR / "index.html").read_text(encoding="utf-8")
    return _INDEX_HTML


def get_dashboard_app(state_getter: Callable[[], dict[str, Any] | None]) -> Starlette:
    """
    Return a Starlette app with dashboard routes.

    ``state_getter`` is a zero-argument callable that returns the live state
    dict containing:
        agent        AgentLoop
        sessions     SessionManager
        channels     ChannelManager
        cron         CronService | None
        heartbeat    HeartbeatService | None
        config       Config
        bus          MessageBus
        start_time   float  (time.monotonic() at startup)
    It may return None before the state has been initialised (e.g. on the very
    first health probe).
    """

    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"status": "healthy"})

    async def dashboard_html(request: Request) -> HTMLResponse:
        return HTMLResponse(_get_index_html())

    async def api_dashboard(request: Request) -> JSONResponse:
        state = state_getter()
        if state is None:
            return JSONResponse({"status": "initializing"}, status_code=503)
        return JSONResponse(_build_dashboard_data(state))

    async def api_session_detail(request: Request) -> JSONResponse:
        state = state_getter()
        if state is None:
            return JSONResponse({"error": "not initialized"}, status_code=503)

        key = request.path_params["key"]
        session_mgr = state.get("sessions")
        if session_mgr is None:
            return JSONResponse({"error": "no session manager"}, status_code=500)

        # Read-only: only return data for sessions that exist
        session = session_mgr._cache.get(key)
        if session is None:
            session = session_mgr._load(key)
        if session is None:
            return JSONResponse({"error": "session not found"}, status_code=404)

        messages = []
        for m in session.messages:
            entry: dict[str, Any] = {
                "role": m.get("role", ""),
                "timestamp": m.get("timestamp"),
            }
            content = m.get("content")
            if isinstance(content, str):
                entry["content"] = content[:2000] + ("\u2026" if len(content) > 2000 else "")
            elif isinstance(content, list):
                parts = []
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            parts.append(block.get("text", ""))
                        elif block.get("type") == "image_url":
                            parts.append("[image]")
                        else:
                            parts.append(str(block))
                entry["content"] = "\n".join(parts)[:2000]
            else:
                entry["content"] = ""

            if tool_calls := m.get("tool_calls"):
                calls = []
                for tc in tool_calls:
                    fn = tc.get("function", {}) if isinstance(tc, dict) else {}
                    calls.append(
                        {
                            "name": fn.get("name", "?"),
                            "arguments": fn.get("arguments", "")[:500],
                        }
                    )
                entry["tool_calls"] = calls

            if name := m.get("name"):
                entry["name"] = name
            if tool_call_id := m.get("tool_call_id"):
                entry["tool_call_id"] = tool_call_id

            messages.append(entry)

        # Compute per-session stats
        tool_counts: Counter[str] = Counter()
        for m in session.messages:
            if tc_list := m.get("tool_calls"):
                for tc in tc_list:
                    fn = tc.get("function", {}) if isinstance(tc, dict) else {}
                    name = fn.get("name", "?")
                    tool_counts[name] += 1

        return JSONResponse(
            {
                "key": session.key,
                "created_at": session.created_at.isoformat(),
                "updated_at": session.updated_at.isoformat(),
                "message_count": len(session.messages),
                "messages": messages,
                "stats": {
                    "tool_usage": dict(tool_counts.most_common(20)),
                    "consolidated": session.last_consolidated,
                    "unconsolidated": len(session.messages) - session.last_consolidated,
                },
            }
        )

    async def api_memory_file(request: Request) -> JSONResponse:
        """Return the contents of a memory file (MEMORY.md, HISTORY.md, etc.)."""
        state = state_getter()
        if state is None:
            return JSONResponse({"error": "not initialized"}, status_code=503)

        filename = request.path_params["filename"]

        # Only allow known safe filenames — no path traversal
        allowed = {"MEMORY.md", "HISTORY.md", "HEARTBEAT.md"}
        if filename not in allowed:
            return JSONResponse({"error": "file not allowed"}, status_code=403)

        agent = state.get("agent")
        workspace = getattr(agent, "workspace", None) if agent else None
        if workspace is None:
            return JSONResponse({"error": "workspace not available"}, status_code=500)

        if filename == "HEARTBEAT.md":
            filepath = workspace / filename
        else:
            filepath = workspace / "memory" / filename

        if not filepath.exists():
            return JSONResponse({"error": "file not found"}, status_code=404)

        try:
            content = filepath.read_text(encoding="utf-8")
            # Cap at 100KB to prevent huge payloads
            if len(content) > 102400:
                content = content[:102400] + "\n\n... [truncated at 100KB]"
            return JSONResponse({
                "filename": filename,
                "content": content,
                "size_bytes": filepath.stat().st_size,
            })
        except OSError:
            return JSONResponse({"error": "read error"}, status_code=500)

    async def api_tool_detail(request: Request) -> JSONResponse:
        """Return detailed tool information including parameter schema."""
        state = state_getter()
        if state is None:
            return JSONResponse({"error": "not initialized"}, status_code=503)

        name = request.path_params["name"]
        agent = state.get("agent")
        if agent is None:
            return JSONResponse({"error": "no agent"}, status_code=500)

        registry = getattr(agent, "tools", None)
        if registry is None:
            return JSONResponse({"error": "no tools"}, status_code=500)

        tool = registry.get(name)
        if tool is None:
            return JSONResponse({"error": "tool not found"}, status_code=404)

        return JSONResponse({
            "name": tool.name,
            "description": tool.description or "",
            "parameters": tool.parameters or {},
        })

    async def api_skill_detail(request: Request) -> JSONResponse:
        """Return skill content (SKILL.md)."""
        state = state_getter()
        if state is None:
            return JSONResponse({"error": "not initialized"}, status_code=503)

        name = request.path_params["name"]
        agent = state.get("agent")
        if agent is None:
            return JSONResponse({"error": "no agent"}, status_code=500)

        context = getattr(agent, "context", None)
        if context is None:
            return JSONResponse({"error": "no context"}, status_code=500)

        skills_loader = getattr(context, "skills", None)
        if skills_loader is None:
            return JSONResponse({"error": "no skills"}, status_code=500)

        content = skills_loader.load_skill(name)
        if content is None:
            return JSONResponse({"error": "skill not found"}, status_code=404)

        original_size = len(content)
        truncated = original_size > 102400
        if truncated:
            content = content[:102400] + "\n\n... [truncated at 100KB]"

        return JSONResponse({
            "name": name,
            "content": content,
            "truncated": truncated,
            "size_bytes": original_size,
        })

    async def api_mcp_detail(request: Request) -> JSONResponse:
        """Return MCP server details with tool definitions."""
        state = state_getter()
        if state is None:
            return JSONResponse({"error": "not initialized"}, status_code=503)

        server_name = request.path_params["server"]
        agent = state.get("agent")
        if agent is None:
            return JSONResponse({"error": "no agent"}, status_code=500)

        mcp_manager = getattr(agent, "_mcp_manager", None)
        if mcp_manager is None:
            return JSONResponse({"error": "no MCP manager"}, status_code=500)

        mcp_servers_cfg: dict = getattr(mcp_manager, "_servers", {})
        if server_name not in mcp_servers_cfg:
            return JSONResponse({"error": "server not found"}, status_code=404)

        cfg = mcp_servers_cfg[server_name]
        mcp_server_status: dict = getattr(mcp_manager, "_status", {})
        status = mcp_server_status.get(server_name, "not connected")

        registry = getattr(agent, "tools", None)
        mcp_tool_names = [name for name in registry._tools.keys() if name.startswith("mcp_")] if registry else []
        prefix = f"mcp_{server_name}_"
        server_tools = [n[len(prefix):] for n in mcp_tool_names if n.startswith(prefix)]

        transport = "stdio" if getattr(cfg, "command", "") else "http"
        endpoint = getattr(cfg, "command", "") or getattr(cfg, "url", "")

        return JSONResponse({
            "server": server_name,
            "status": status,
            "connected": status == "connected",
            "transport": transport,
            "endpoint": endpoint,
            "connect_timeout": getattr(cfg, "connect_timeout", 30),
            "tool_timeout": getattr(cfg, "tool_timeout", 30),
            "tools": [{"name": t, "description": "", "input_schema": {}} for t in server_tools],
        })

    routes = [
        Route("/health", health),
        Route("/", dashboard_html),
        Route("/api/dashboard", api_dashboard),
        Route("/api/session/{key:path}", api_session_detail),
        Route("/api/memory/{filename}", api_memory_file),
        Route("/api/tool/{name}", api_tool_detail),
        Route("/api/skill/{name}", api_skill_detail),
        Route("/api/mcp/{server}", api_mcp_detail),
        Mount("/static", StaticFiles(directory=str(_TEMPLATES_DIR)), name="static"),
    ]

    return Starlette(routes=routes)


# ---------------------------------------------------------------------------
# Data builders
# ---------------------------------------------------------------------------


def _build_dashboard_data(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "identity": _build_identity(state),
        "activity": _build_activity(state),
        "tools": _build_tools(state),
        "skills": _build_skills(state),
        "channels": _build_channels(state),
        "cron": _build_cron(state),
        "system": _build_system(state),
        "memory": _build_memory(state),
    }


def _build_identity(state: dict[str, Any]) -> dict[str, Any]:
    config = state.get("config")
    agent = state.get("agent")
    start_time = state.get("start_time", time.monotonic())
    uptime = int(time.monotonic() - start_time)

    name = getattr(config, "name", "nanobot") if config else "nanobot"
    model = getattr(agent, "model", "unknown") if agent else "unknown"

    active_tasks: dict = getattr(agent, "_active_tasks", {}) if agent else {}
    active_count = sum(
        1 for tasks in active_tasks.values() for t in tasks if not t.done()
    )
    status = "processing" if active_count > 0 else "idle"

    return {
        "name": name,
        "model": model,
        "uptime_seconds": uptime,
        "status": status,
        "active_count": active_count,
    }


def _build_activity(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Build a rich activity feed from sessions.

    Each entry contains: session key, active status, user prompt preview,
    tool usage summary, message counts by role, and timestamps.
    """
    session_mgr = state.get("sessions")
    agent = state.get("agent")
    if session_mgr is None:
        return []

    active_tasks: dict = getattr(agent, "_active_tasks", {}) if agent else {}
    active_keys = {
        key for key, tasks in active_tasks.items() if any(not t.done() for t in tasks)
    }

    entries = []

    for info in session_mgr.list_sessions():
        key = info.get("key", "")

        # Try to get session from cache (read-only, no side effects)
        session = session_mgr._cache.get(key)
        msg_count = 0
        user_prompt = ""
        last_response = ""
        tools_used: Counter[str] = Counter()
        role_counts: dict[str, int] = {"user": 0, "assistant": 0, "tool": 0}
        channel = ""
        error = False

        if session:
            msg_count = len(session.messages)

            # Extract channel from session key
            if ":" in key:
                channel = key.split(":")[0]

            # Find the last user message (the prompt that triggered this)
            for m in reversed(session.messages):
                role = m.get("role", "")
                content = m.get("content")
                if role == "user" and isinstance(content, str) and content.strip():
                    user_prompt = content[:200] + ("\u2026" if len(content) > 200 else "")
                    break

            # Find the last assistant response
            for m in reversed(session.messages):
                role = m.get("role", "")
                content = m.get("content")
                if role == "assistant" and isinstance(content, str) and content.strip():
                    last_response = content[:200] + ("\u2026" if len(content) > 200 else "")
                    break

            # Count tools and roles
            for m in session.messages:
                role = m.get("role", "")
                if role in role_counts:
                    role_counts[role] += 1
                if tc_list := m.get("tool_calls"):
                    for tc in tc_list:
                        fn = tc.get("function", {}) if isinstance(tc, dict) else {}
                        tools_used[fn.get("name", "?")] += 1

                # Check for errors
                content = m.get("content")
                if role == "assistant" and isinstance(content, str):
                    if "maximum number of tool call iterations" in content:
                        error = True
        else:
            # Not in cache — get basic info from file metadata
            file_path = info.get("path")
            if file_path:
                try:
                    with open(file_path, encoding="utf-8") as _f:
                        msg_count = max(0, sum(1 for _ in _f) - 1)
                except OSError:
                    pass
            if ":" in key:
                channel = key.split(":")[0]

        # Compute iteration estimate: each assistant turn with tool_calls = 1 iteration
        iterations = role_counts.get("assistant", 0)

        entries.append(
            {
                "key": key,
                "channel": channel,
                "active": key in active_keys,
                "created_at": info.get("created_at"),
                "updated_at": info.get("updated_at"),
                "message_count": msg_count,
                "user_prompt": user_prompt,
                "last_response": last_response,
                "iterations": iterations,
                "tools_used": dict(tools_used.most_common(10)),
                "role_counts": role_counts,
                "error": error,
            }
        )

    return entries


def _build_tools(state: dict[str, Any]) -> dict[str, Any]:
    agent = state.get("agent")
    if agent is None:
        return {"builtin": [], "mcp": []}

    registry = getattr(agent, "tools", None)
    builtin: list[dict[str, Any]] = []
    if registry:
        for name, tool in registry._tools.items():
            if not name.startswith("mcp_"):
                builtin.append({
                    "name": name,
                    "description": tool.description[:200] if tool.description else "",
                })

    mcp_tool_names = [name for name in registry._tools.keys() if name.startswith("mcp_")] if registry else []

    mcp_manager = getattr(agent, "_mcp_manager", None)
    mcp_servers_cfg: dict = {}
    mcp_server_status: dict[str, str] = {}

    if mcp_manager:
        mcp_servers_cfg = getattr(mcp_manager, "_servers", {})
        mcp_server_status = getattr(mcp_manager, "_status", {})

    mcp: list[dict[str, Any]] = []
    for server_name, cfg in mcp_servers_cfg.items():
        prefix = f"mcp_{server_name}_"
        server_tools = [n[len(prefix):] for n in mcp_tool_names if n.startswith(prefix)]
        transport = "stdio" if getattr(cfg, "command", "") else "http"
        endpoint = getattr(cfg, "command", "") or getattr(cfg, "url", "")
        status = mcp_server_status.get(server_name, "not connected")
        mcp.append(
            {
                "server": server_name,
                "status": status,
                "connected": status == "connected",
                "transport": transport,
                "endpoint": endpoint,
                "tools": server_tools,
                "tool_count": len(server_tools),
                "tool_timeout": getattr(cfg, "tool_timeout", 30),
                "connect_timeout": getattr(cfg, "connect_timeout", 30),
            }
        )

    known_prefixes = {f"mcp_{s}_" for s in mcp_servers_cfg}
    orphaned = [n for n in mcp_tool_names if not any(n.startswith(p) for p in known_prefixes)]
    if orphaned:
        mcp.append(
            {
                "server": "(unknown)",
                "connected": True,
                "transport": "unknown",
                "endpoint": "",
                "tools": orphaned,
                "tool_count": len(orphaned),
                "tool_timeout": 30,
                "connect_timeout": 30,
            }
        )

    return {"builtin": builtin, "mcp": mcp}


def _build_skills(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Build skills list for dashboard."""
    agent = state.get("agent")
    if agent is None:
        return []

    context = getattr(agent, "context", None)
    if context is None:
        return []

    skills_loader = getattr(context, "skills", None)
    if skills_loader is None:
        return []

    skills_list = skills_loader.list_skills(filter_unavailable=False)
    result = []
    for s in skills_list:
        name = s.get("name", "")
        meta = skills_loader.get_skill_metadata(name) or {}
        skill_meta = skills_loader._parse_nanobot_metadata(meta.get("metadata", ""))

        result.append({
            "name": name,
            "description": meta.get("description") or skill_meta.get("description") or name,
            "source": s.get("source", "unknown"),
            "available": skills_loader._check_requirements(skill_meta),
            "always": bool(skill_meta.get("always") or meta.get("always")),
            "path": s.get("path", ""),
        })
    return result


def _build_channels(state: dict[str, Any]) -> dict[str, Any]:
    channels_mgr = state.get("channels")
    if channels_mgr is None:
        return {}
    return channels_mgr.get_status()


def _build_cron(state: dict[str, Any]) -> dict[str, Any]:
    cron = state.get("cron")
    if cron is None:
        return {"enabled": False, "jobs": []}

    s = cron.status()
    jobs_list = []
    try:
        for job in cron.list_jobs(include_disabled=True):
            jobs_list.append({
                "id": job.id,
                "name": job.name,
                "enabled": job.enabled,
                "schedule_kind": job.schedule.kind,
                "schedule_expr": job.schedule.expr or (
                    f"every {job.schedule.every_ms // 1000}s" if job.schedule.every_ms else None
                ),
                "next_run_ms": job.state.next_run_at_ms,
                "last_run_ms": job.state.last_run_at_ms,
                "last_status": job.state.last_status,
                "last_error": job.state.last_error,
            })
    except Exception:
        pass

    return {
        "enabled": s.get("enabled", False),
        "jobs_count": s.get("jobs", 0),
        "next_run_ms": s.get("next_wake_at_ms"),
        "jobs": jobs_list,
    }


def _build_system(state: dict[str, Any]) -> dict[str, Any]:
    bus = state.get("bus")
    heartbeat = state.get("heartbeat")

    inbound_depth = bus.inbound.qsize() if bus and hasattr(bus, "inbound") else 0
    outbound_depth = bus.outbound.qsize() if bus and hasattr(bus, "outbound") else 0

    hb_enabled = getattr(heartbeat, "enabled", False) if heartbeat else False
    hb_interval = getattr(heartbeat, "interval_s", 0) if heartbeat else 0
    hb_running = getattr(heartbeat, "_running", False) if heartbeat else False

    return {
        "inbound_queue_depth": inbound_depth,
        "outbound_queue_depth": outbound_depth,
        "heartbeat_enabled": hb_enabled,
        "heartbeat_interval_s": hb_interval,
        "heartbeat_running": hb_running,
    }


def _build_memory(state: dict[str, Any]) -> dict[str, Any]:
    """Build memory system status."""
    agent = state.get("agent")
    workspace = getattr(agent, "workspace", None) if agent else None
    if workspace is None:
        return {"available": False, "files": []}

    files = []
    for name, path in [
        ("MEMORY.md", workspace / "memory" / "MEMORY.md"),
        ("HISTORY.md", workspace / "memory" / "HISTORY.md"),
        ("HEARTBEAT.md", workspace / "HEARTBEAT.md"),
    ]:
        if path.exists():
            try:
                stat = path.stat()
                files.append({
                    "name": name,
                    "size_bytes": stat.st_size,
                    "modified": stat.st_mtime,
                })
            except OSError:
                pass

    return {
        "available": True,
        "files": files,
    }
