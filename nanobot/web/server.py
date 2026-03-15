"""FastAPI web server for nanobot web interface."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel


_STATIC_DIR = Path(__file__).parent / "static"


class ChatRequest(BaseModel):
    message: str
    session_id: str = "web:default"


def create_app(config_path: str | None = None, workspace: str | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus
    from nanobot.cli.commands import _load_runtime_config, _make_provider
    from nanobot.config.paths import get_cron_dir
    from nanobot.cron.service import CronService
    from nanobot.session.manager import SessionManager
    from nanobot.utils.helpers import sync_workspace_templates

    cfg = _load_runtime_config(config_path, workspace)
    sync_workspace_templates(cfg.workspace_path)

    bus = MessageBus()
    provider = _make_provider(cfg)

    cron_store_path = get_cron_dir() / "jobs.json"
    cron = CronService(cron_store_path)

    session_manager = SessionManager(cfg.workspace_path)

    agent = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=cfg.workspace_path,
        model=cfg.agents.defaults.model,
        max_iterations=cfg.agents.defaults.max_tool_iterations,
        context_window_tokens=cfg.agents.defaults.context_window_tokens,
        web_search_config=cfg.tools.web.search,
        web_proxy=cfg.tools.web.proxy or None,
        exec_config=cfg.tools.exec,
        cron_service=cron,
        restrict_to_workspace=cfg.tools.restrict_to_workspace,
        session_manager=session_manager,
        mcp_servers=cfg.tools.mcp_servers,
        channels_config=cfg.channels,
    )

    app = FastAPI(title="nanobot web", docs_url=None, redoc_url=None)

    @app.on_event("startup")
    async def _startup() -> None:
        await agent._connect_mcp()

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        await agent.close_mcp()

    # ------------------------------------------------------------------
    # Chat endpoint — SSE streaming
    # ------------------------------------------------------------------

    @app.post("/api/chat")
    async def chat(request: ChatRequest) -> StreamingResponse:
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

        async def on_progress(content: str, *, tool_hint: bool = False) -> None:
            await queue.put({"type": "progress", "content": content, "tool_hint": tool_hint})

        async def _run_agent() -> None:
            try:
                response = await agent.process_direct(
                    request.message,
                    session_key=request.session_id,
                    channel="web",
                    chat_id="browser",
                    on_progress=on_progress,
                )
                await queue.put({"type": "done", "content": response or ""})
            except Exception as exc:  # noqa: BLE001
                await queue.put({"type": "error", "content": str(exc)})
            finally:
                await queue.put(None)  # sentinel

        async def stream() -> Any:
            task = asyncio.create_task(_run_agent())
            try:
                while True:
                    item = await queue.get()
                    if item is None:
                        break
                    yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
            finally:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    # ------------------------------------------------------------------
    # Session endpoints
    # ------------------------------------------------------------------

    @app.get("/api/sessions")
    async def list_sessions() -> list[dict[str, Any]]:
        return session_manager.list_sessions()

    @app.get("/api/sessions/{session_id:path}")
    async def get_session(session_id: str) -> dict[str, Any]:
        session = session_manager.get_or_create(session_id)
        return {
            "key": session.key,
            "messages": session.get_history(max_messages=0),
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
        }

    @app.delete("/api/sessions/{session_id:path}")
    async def delete_session(session_id: str) -> dict[str, str]:
        path = session_manager._get_session_path(session_id)
        if not path.exists():
            raise HTTPException(status_code=404, detail="Session not found")
        path.unlink()
        session_manager.invalidate(session_id)
        return {"status": "deleted"}

    # ------------------------------------------------------------------
    # Static files / SPA
    # ------------------------------------------------------------------

    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(_STATIC_DIR / "index.html")

    return app
