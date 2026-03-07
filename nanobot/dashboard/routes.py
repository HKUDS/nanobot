"""Dashboard Starlette routes — live agent status UI."""

from __future__ import annotations

import time
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

        session = session_mgr.get_or_create(key)
        messages = []
        for m in session.messages:
            entry: dict[str, Any] = {
                "role": m.get("role", ""),
                "timestamp": m.get("timestamp"),
            }
            content = m.get("content")
            # Truncate very large tool results / images
            if isinstance(content, str):
                entry["content"] = content[:2000] + ("…" if len(content) > 2000 else "")
            elif isinstance(content, list):
                # Multi-modal content — extract text parts
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

            # Tool call info
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

        return JSONResponse(
            {
                "key": session.key,
                "created_at": session.created_at.isoformat(),
                "updated_at": session.updated_at.isoformat(),
                "message_count": len(session.messages),
                "messages": messages,
            }
        )

    routes = [
        Route("/health", health),
        Route("/", dashboard_html),
        Route("/api/dashboard", api_dashboard),
        Route("/api/session/{key:path}", api_session_detail),
        Mount("/static", StaticFiles(directory=str(_TEMPLATES_DIR)), name="static"),
    ]

    return Starlette(routes=routes)


# ---------------------------------------------------------------------------
# Data builders
# ---------------------------------------------------------------------------


def _build_dashboard_data(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "identity": _build_identity(state),
        "sessions": _build_sessions(state),
        "tools": _build_tools(state),
        "channels": _build_channels(state),
        "cron": _build_cron(state),
        "system": _build_system(state),
    }


def _build_identity(state: dict[str, Any]) -> dict[str, Any]:
    config = state.get("config")
    agent = state.get("agent")
    start_time = state.get("start_time", time.monotonic())
    uptime = int(time.monotonic() - start_time)

    name = getattr(config, "name", "nanobot") if config else "nanobot"
    model = getattr(agent, "model", "unknown") if agent else "unknown"

    # Is the agent currently processing anything?
    active_tasks: dict = getattr(agent, "_active_tasks", {}) if agent else {}
    busy = any(tasks for tasks in active_tasks.values() if any(not t.done() for t in tasks))
    status = "processing" if busy else "idle"

    return {
        "name": name,
        "model": model,
        "uptime_seconds": uptime,
        "status": status,
    }


def _build_sessions(state: dict[str, Any]) -> list[dict[str, Any]]:
    session_mgr = state.get("sessions")
    agent = state.get("agent")
    if session_mgr is None:
        return []

    active_tasks: dict = getattr(agent, "_active_tasks", {}) if agent else {}
    active_keys = {key for key, tasks in active_tasks.items() if any(not t.done() for t in tasks)}

    sessions = []
    for info in session_mgr.list_sessions():
        key = info.get("key", "")

        # Peek at the last few messages to get a preview and count
        session = session_mgr._cache.get(key)
        msg_count = 0
        last_preview = ""
        if session:
            msg_count = len(session.messages)
            for m in reversed(session.messages):
                content = m.get("content")
                if isinstance(content, str) and content.strip():
                    last_preview = content[:120] + ("…" if len(content) > 120 else "")
                    break
        else:
            # Session not in memory cache — estimate message count from the
            # file path stored in the listing (line count minus the metadata line).
            file_path = info.get("path")
            if file_path:
                try:
                    with open(file_path, encoding="utf-8") as _f:
                        msg_count = max(0, sum(1 for _ in _f) - 1)
                except OSError:
                    pass

        sessions.append(
            {
                "key": key,
                "created_at": info.get("created_at"),
                "updated_at": info.get("updated_at"),
                "message_count": msg_count,
                "active": key in active_keys,
                "last_preview": last_preview,
            }
        )

    return sessions


def _build_tools(state: dict[str, Any]) -> dict[str, Any]:
    agent = state.get("agent")
    if agent is None:
        return {"builtin": [], "mcp": []}

    registry = getattr(agent, "tools", None)
    tool_names: list[str] = registry.tool_names if registry else []

    builtin = [n for n in tool_names if not n.startswith("mcp_")]
    mcp_tool_names = [n for n in tool_names if n.startswith("mcp_")]

    # Group MCP tools by server name (prefix: mcp_{server}_{tool})
    mcp_servers_cfg: dict = getattr(agent, "_mcp_servers", {})
    mcp_connected: bool = getattr(agent, "_mcp_connected", False)

    mcp: list[dict[str, Any]] = []
    for server_name, cfg in mcp_servers_cfg.items():
        prefix = f"mcp_{server_name}_"
        server_tools = [n[len(prefix) :] for n in mcp_tool_names if n.startswith(prefix)]
        transport = "stdio" if getattr(cfg, "command", "") else "http"
        endpoint = getattr(cfg, "command", "") or getattr(cfg, "url", "")
        mcp.append(
            {
                "server": server_name,
                "connected": mcp_connected,
                "transport": transport,
                "endpoint": endpoint,
                "tools": server_tools,
                "tool_count": len(server_tools),
                "tool_timeout": getattr(cfg, "tool_timeout", 30),
            }
        )

    # If there are mcp_* tools registered for servers not in config (shouldn't
    # happen, but be defensive), show them under an "unknown" group.
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
            }
        )

    return {"builtin": builtin, "mcp": mcp}


def _build_channels(state: dict[str, Any]) -> dict[str, Any]:
    channels_mgr = state.get("channels")
    if channels_mgr is None:
        return {}
    return channels_mgr.get_status()


def _build_cron(state: dict[str, Any]) -> dict[str, Any]:
    cron = state.get("cron")
    if cron is None:
        return {"enabled": False, "jobs_count": 0, "next_run_ms": None}
    s = cron.status()
    return {
        "enabled": s.get("enabled", False),
        "jobs_count": s.get("jobs", 0),
        "next_run_ms": s.get("next_wake_at_ms"),
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
