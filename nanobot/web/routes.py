"""All HTTP and WebSocket routes for the nanobot web API.

Routes are organised into sections with clear separators:
    Health      /api/ping
    Chat        /api/chat   (HTTP)
    WebSocket   /ws/{session_id}
    Sessions    /api/sessions
    Status      /api/status
    Cron        /api/cron/jobs
    Skills      /api/skills
    Workspace   /api/workspace

Shared services are accessed via FastAPI dependency functions (get_*) rather
than reading app.state directly in route bodies, keeping routes testable and
decoupled from the application lifecycle.
"""

from __future__ import annotations

import io
import json
import shutil
import zipfile
from pathlib import Path
from typing import Annotated, Any

import datetime

from fastapi import (
    Depends,
    FastAPI,
    File,
    HTTPException,
    Request,
    Response,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, StreamingResponse
from loguru import logger

from nanobot.channels.web import WebChannel
from nanobot.config.schema import Config
from nanobot.cron.service import CronService
from nanobot.cron.types import CronSchedule
from nanobot.session.manager import SessionManager
from nanobot.web.models import AddCronJobRequest, ChatRequest, ToggleCronJobRequest
from nanobot.web.utils import (
    EDITABLE_EXTENSIONS,
    MAX_EDITABLE_BYTES,
    build_tree,
    filter_messages_for_display,
    is_editable_extension,
    serialize_job,
)


# ---------------------------------------------------------------------------
# Dependency providers — route functions use these instead of app.state directly
# ---------------------------------------------------------------------------


def get_web_channel(request: Request) -> WebChannel:
    return request.app.state.web_channel


def get_session_manager(request: Request) -> SessionManager:
    return request.app.state.session_manager


def get_config(request: Request) -> Config:
    return request.app.state.config


def get_cron_service(request: Request) -> CronService:
    return request.app.state.cron_service


# Type aliases for annotated dependencies
_WebChannel = Annotated[WebChannel, Depends(get_web_channel)]
_SessionManager = Annotated[SessionManager, Depends(get_session_manager)]
_Config = Annotated[Config, Depends(get_config)]
_CronService = Annotated[CronService, Depends(get_cron_service)]


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def register_routes(app: FastAPI) -> None:
    """Attach all API routes to *app*."""

    # =========================================================================
    # Health
    # =========================================================================

    @app.get("/api/ping", tags=["health"])
    async def ping() -> dict[str, str]:
        return {"message": "pong"}

    # =========================================================================
    # Chat (HTTP)
    # =========================================================================

    @app.post("/api/chat", tags=["chat"])
    async def chat(
        req: ChatRequest,
        wc: _WebChannel,
    ) -> dict[str, str]:
        """Accept a chat message from the browser and forward it to the agent."""
        session_key = req.session_id
        # Normalise session_key: "web:default" → chat_id "default"
        chat_id = session_key.split(":", 1)[-1] if ":" in session_key else session_key
        await wc.handle_ws_message(chat_id, req.message)
        await wc.notify_thinking(chat_id)
        return {"status": "accepted", "session_id": session_key}

    # =========================================================================
    # WebSocket
    # =========================================================================

    @app.websocket("/ws/{session_id}")
    async def websocket_endpoint(websocket: WebSocket, session_id: str) -> None:
        """Persistent WebSocket connection for a browser session.

        Message types sent by the browser:
            {"type": "ping"}                         → {"type": "pong"}
            {"type": "message", "content": "..."}    → forwarded to agent
        """
        wc: WebChannel = websocket.app.state.web_channel
        await websocket.accept()
        wc.register(session_id, websocket)

        try:
            while True:
                raw = await websocket.receive_text()
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                if data.get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
                    continue

                if data.get("type") == "message":
                    content = data.get("content", "").strip()
                    if not content:
                        continue
                    await wc.handle_ws_message(session_id, content)
                    await wc.notify_thinking(session_id)

        except WebSocketDisconnect:
            logger.debug("WS disconnected: session={}", session_id)
        except Exception as exc:
            logger.error("WS error: session={} err={}", session_id, exc)
        finally:
            wc.unregister(session_id, websocket)

    # =========================================================================
    # Sessions
    # =========================================================================

    @app.get("/api/sessions", tags=["sessions"])
    async def list_sessions(sm: _SessionManager) -> list[Any]:
        return sm.list_sessions()

    @app.get("/api/sessions/{key:path}", tags=["sessions"])
    async def get_session(key: str, sm: _SessionManager) -> dict[str, Any]:
        session = sm.get_or_create(key)
        return {
            "key": session.key,
            "messages": filter_messages_for_display(session.messages),
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
        }

    @app.delete("/api/sessions/{key:path}", tags=["sessions"])
    async def delete_session(key: str, sm: _SessionManager) -> dict[str, bool]:
        path = sm._get_session_path(key)
        if path.exists():
            path.unlink()
            sm.invalidate(key)
            return {"ok": True}
        # Session may only be in memory
        if key in sm._cache:
            sm.invalidate(key)
            return {"ok": True}
        raise HTTPException(status_code=404, detail="Session not found")

    # =========================================================================
    # Status
    # =========================================================================

    @app.get("/api/status", tags=["status"])
    async def get_status(config: _Config, cron: _CronService) -> dict[str, Any]:
        from nanobot.config.loader import get_config_path

        config_path = get_config_path()
        workspace_path = config.workspace_path.resolve()
        providers_dump = config.providers.model_dump()
        providers_list = [
            {
                "name": name,
                "has_key": bool(
                    p.get("api_key")
                    if isinstance(p, dict)
                    else getattr(p, "api_key", None)
                ),
            }
            for name, p in providers_dump.items()
        ]
        return {
            "config_path": str(config_path),
            "config_exists": config_path.exists(),
            "workspace": str(workspace_path),
            "workspace_exists": workspace_path.exists(),
            "providers": providers_list,
            "cron": cron.status(),
        }

    # =========================================================================
    # Cron jobs
    # =========================================================================

    @app.get("/api/cron/jobs", tags=["cron"])
    async def list_cron_jobs(
        cron: _CronService,
        include_disabled: bool = False,
    ) -> list[dict[str, Any]]:
        return [
            serialize_job(j) for j in cron.list_jobs(include_disabled=include_disabled)
        ]

    @app.post("/api/cron/jobs", tags=["cron"])
    async def add_cron_job(
        req: AddCronJobRequest,
        cron: _CronService,
    ) -> dict[str, Any]:
        if req.every_seconds is not None:
            schedule = CronSchedule(kind="every", every_ms=req.every_seconds * 1000)
        elif req.cron_expr is not None:
            schedule = CronSchedule(kind="cron", expr=req.cron_expr)
        elif req.at_iso is not None:
            dt = datetime.datetime.fromisoformat(req.at_iso)
            schedule = CronSchedule(kind="at", at_ms=int(dt.timestamp() * 1000))
        else:
            raise HTTPException(
                status_code=400,
                detail="Must specify one of: every_seconds, cron_expr, or at_iso",
            )
        job = cron.add_job(
            name=req.name,
            schedule=schedule,
            message=req.message,
            deliver=req.deliver,
            channel=req.channel,
            to=req.to,
        )
        return serialize_job(job)

    @app.delete("/api/cron/jobs/{job_id}", tags=["cron"])
    async def remove_cron_job(job_id: str, cron: _CronService) -> dict[str, bool]:
        if cron.remove_job(job_id):
            return {"ok": True}
        raise HTTPException(status_code=404, detail="Job not found")

    @app.put("/api/cron/jobs/{job_id}/toggle", tags=["cron"])
    async def toggle_cron_job(
        job_id: str,
        req: ToggleCronJobRequest,
        cron: _CronService,
    ) -> dict[str, Any]:
        job = cron.enable_job(job_id, enabled=req.enabled)
        if job:
            return serialize_job(job)
        raise HTTPException(status_code=404, detail="Job not found")

    @app.post("/api/cron/jobs/{job_id}/run", tags=["cron"])
    async def run_cron_job(job_id: str, cron: _CronService) -> dict[str, bool]:
        if await cron.run_job(job_id, force=True):
            return {"ok": True}
        raise HTTPException(status_code=404, detail="Job not found")

    # =========================================================================
    # Skills
    # =========================================================================

    @app.get("/api/skills", tags=["skills"])
    async def list_skills(config: _Config) -> list[dict[str, Any]]:
        from nanobot.agent.skills import SkillsLoader

        loader = SkillsLoader(config.workspace_path)
        raw = loader.list_skills(filter_unavailable=False)
        result: list[dict[str, Any]] = []
        for s in raw:
            meta = loader.get_skill_metadata(s["name"]) or {}
            available = loader._check_requirements(loader._get_skill_meta(s["name"]))
            result.append(
                {
                    "name": s["name"],
                    "description": meta.get("description", s["name"]),
                    "source": s["source"],
                    "available": available,
                    "path": s["path"],
                }
            )
        return result

    @app.delete("/api/skills/{name}", tags=["skills"])
    async def delete_skill(name: str, config: _Config) -> dict[str, bool]:
        skills_dir = (Path(config.workspace_path) / "skills").resolve()
        skill_path = (skills_dir / name).resolve()

        # Security: prevent path traversal out of skills directory
        try:
            skill_path.relative_to(skills_dir)
        except ValueError:
            raise HTTPException(status_code=403, detail="Access denied")

        if not name or name.strip() in ("", "."):
            raise HTTPException(status_code=400, detail="Invalid skill name")
        if skill_path == skills_dir:
            raise HTTPException(status_code=400, detail="Cannot delete skills root")
        if not skill_path.exists() or not skill_path.is_dir():
            raise HTTPException(status_code=404, detail="Skill not found")

        shutil.rmtree(skill_path)
        return {"ok": True}

    @app.get("/api/skills/{name}/download", tags=["skills"])
    async def download_skill_zip(name: str, config: _Config) -> StreamingResponse:
        skills_dir = (Path(config.workspace_path) / "skills").resolve()
        skill_path = (skills_dir / name).resolve()

        # Security: prevent path traversal
        try:
            skill_path.relative_to(skills_dir)
        except ValueError:
            raise HTTPException(status_code=403, detail="Access denied")

        if not name or name.strip() in ("", "."):
            raise HTTPException(status_code=400, detail="Invalid skill name")
        if not skill_path.exists() or not skill_path.is_dir():
            raise HTTPException(status_code=404, detail="Skill not found")

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for file in skill_path.rglob("*"):
                if file.is_file():
                    zf.write(file, file.relative_to(skills_dir))
        buf.seek(0)

        return StreamingResponse(
            buf,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{name}.zip"'},
        )

    # =========================================================================
    # Workspace
    # =========================================================================

    @app.get("/api/workspace", tags=["workspace"])
    async def list_workspace_files(config: _Config) -> list[Any]:
        workspace_dir = Path(config.workspace_path).resolve()
        if not workspace_dir.exists():
            return []
        return build_tree(workspace_dir, workspace_dir, {"skills"})

    @app.get("/api/workspace/content/{file_path:path}", tags=["workspace"])
    async def read_workspace_file_content(
        file_path: str, config: _Config
    ) -> dict[str, Any]:
        """Return the UTF-8 text content of an editable workspace file."""
        workspace_dir = Path(config.workspace_path).resolve()

        ws_str = str(workspace_dir)
        if file_path.startswith(ws_str):
            file_path = file_path[len(ws_str) :].lstrip("/")

        target_path = (workspace_dir / file_path).resolve()

        try:
            target_path.relative_to(workspace_dir)
        except ValueError:
            raise HTTPException(status_code=403, detail="Access denied")

        if not target_path.exists():
            raise HTTPException(status_code=404, detail="File not found")
        if not target_path.is_file():
            raise HTTPException(status_code=400, detail="Path is not a file")
        if not is_editable_extension(target_path):
            raise HTTPException(
                status_code=415,
                detail=f"File type not editable. Allowed: {sorted(EDITABLE_EXTENSIONS)}",
            )

        size = target_path.stat().st_size
        if size > MAX_EDITABLE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"File too large for in-browser editing ({size} bytes, max {MAX_EDITABLE_BYTES})",
            )

        try:
            content = target_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = target_path.read_text(encoding="utf-8", errors="replace")

        import mimetypes as _mimetypes
        mime, _ = _mimetypes.guess_type(target_path.name)

        return {
            "path": str(target_path.relative_to(workspace_dir)),
            "content": content,
            "content_type": mime or "text/plain",
        }

    @app.put("/api/workspace/content/{file_path:path}", status_code=204, tags=["workspace"])
    async def write_workspace_file_content(
        file_path: str, request: Request, config: _Config
    ) -> Response:
        """Overwrite an existing editable workspace file with plain-text body."""
        workspace_dir = Path(config.workspace_path).resolve()

        ws_str = str(workspace_dir)
        if file_path.startswith(ws_str):
            file_path = file_path[len(ws_str) :].lstrip("/")

        target_path = (workspace_dir / file_path).resolve()

        try:
            target_path.relative_to(workspace_dir)
        except ValueError:
            raise HTTPException(status_code=403, detail="Access denied")

        if not target_path.exists():
            raise HTTPException(status_code=404, detail="File not found")
        if not target_path.is_file():
            raise HTTPException(status_code=400, detail="Path is not a file")
        if not is_editable_extension(target_path):
            raise HTTPException(status_code=415, detail="File type not editable")

        body = await request.body()
        if len(body) > MAX_EDITABLE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Content too large (max {MAX_EDITABLE_BYTES} bytes)",
            )

        # Support both raw text and JSON { "content": "..." }
        ct = request.headers.get("content-type", "")
        if "application/json" in ct:
            import json as _json
            try:
                payload = _json.loads(body)
                text = payload.get("content", "")
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid JSON body")
        else:
            try:
                text = body.decode("utf-8")
            except UnicodeDecodeError:
                raise HTTPException(status_code=400, detail="Body must be UTF-8 text")

        target_path.write_text(text, encoding="utf-8")
        return Response(status_code=204)

    @app.get("/api/workspace/{file_path:path}", tags=["workspace"])
    async def download_workspace_file(file_path: str, config: _Config) -> FileResponse:
        workspace_dir = Path(config.workspace_path).resolve()

        # Frontend may send the full absolute path; strip workspace prefix if present.
        ws_str = str(workspace_dir)
        if file_path.startswith(ws_str):
            file_path = file_path[len(ws_str) :].lstrip("/")

        target_path = (workspace_dir / file_path).resolve()

        # Security: prevent directory traversal
        try:
            target_path.relative_to(workspace_dir)
        except ValueError:
            raise HTTPException(status_code=403, detail="Access denied")

        if not target_path.is_file():
            raise HTTPException(status_code=404, detail="File not found")

        return FileResponse(path=target_path, filename=target_path.name)

    @app.delete("/api/workspace/{file_path:path}", tags=["workspace"])
    async def delete_workspace_path(file_path: str, config: _Config) -> Response:
        workspace_dir = Path(config.workspace_path).resolve()

        # Reject attempts to delete the workspace root
        if not file_path or file_path.strip("/") in ("", "."):
            raise HTTPException(status_code=400, detail="Cannot delete workspace root")

        ws_str = str(workspace_dir)
        if file_path.startswith(ws_str):
            file_path = file_path[len(ws_str) :].lstrip("/")

        target_path = (workspace_dir / file_path).resolve()

        # Security: prevent directory traversal
        try:
            target_path.relative_to(workspace_dir)
        except ValueError:
            raise HTTPException(status_code=403, detail="Access denied")

        if target_path == workspace_dir:
            raise HTTPException(status_code=400, detail="Cannot delete workspace root")
        if not target_path.exists():
            raise HTTPException(status_code=404, detail="Path not found")

        if target_path.is_file():
            target_path.unlink()
        else:
            shutil.rmtree(target_path)

        return Response(status_code=204)

    @app.post("/api/workspace/upload", status_code=201, tags=["workspace"])
    async def upload_workspace_file(
        config: _Config,
        file: UploadFile = File(...),
        relative_path: str = "",
    ) -> dict[str, str]:
        workspace_dir = Path(config.workspace_path).resolve()

        clean_rel = relative_path.strip().strip("/")
        target_dir = (
            (workspace_dir / clean_rel).resolve() if clean_rel else workspace_dir
        )

        # Security: prevent directory traversal
        try:
            target_dir.relative_to(workspace_dir)
        except ValueError:
            raise HTTPException(status_code=403, detail="Access denied")

        if target_dir.exists() and target_dir.is_file():
            raise HTTPException(
                status_code=400, detail="Target path is a file, not a directory"
            )

        if target_dir != workspace_dir and not target_dir.exists():
            target_dir.mkdir(parents=True, exist_ok=True)

        # Sanitize filename to prevent traversal via filename itself
        filename = Path(file.filename).name if file.filename else ""
        if not filename:
            raise HTTPException(status_code=400, detail="Invalid filename")

        dest = (target_dir / filename).resolve()

        # Final destination check
        try:
            dest.relative_to(workspace_dir)
        except ValueError:
            raise HTTPException(status_code=403, detail="Access denied")

        content = await file.read()
        dest.write_bytes(content)

        return {"path": str(dest.relative_to(workspace_dir))}

    @app.post("/api/workspace/upload-zip", status_code=201, tags=["workspace"])
    async def upload_workspace_zip(
        config: _Config,
        file: UploadFile = File(...),
    ) -> dict[str, int]:
        # Hard limits: 500 files, 100 MB uncompressed
        MAX_FILE_COUNT = 500
        MAX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024

        workspace_dir = Path(config.workspace_path).resolve()

        content = await file.read()
        try:
            zf = zipfile.ZipFile(io.BytesIO(content))
        except zipfile.BadZipFile:
            raise HTTPException(status_code=400, detail="Invalid ZIP file")

        members = zf.infolist()

        if len(members) > MAX_FILE_COUNT:
            raise HTTPException(
                status_code=413,
                detail=f"ZIP contains too many files (max {MAX_FILE_COUNT})",
            )
        total_size = sum(m.file_size for m in members)
        if total_size > MAX_UNCOMPRESSED_BYTES:
            raise HTTPException(
                status_code=413, detail="ZIP uncompressed size exceeds 100 MB limit"
            )

        # Security: validate every entry for path traversal before extracting
        for member in members:
            dest = (workspace_dir / member.filename).resolve()
            try:
                dest.relative_to(workspace_dir)
            except ValueError:
                raise HTTPException(
                    status_code=403, detail=f"Access denied: {member.filename}"
                )

        zf.extractall(workspace_dir)
        return {"extracted": len(members)}
