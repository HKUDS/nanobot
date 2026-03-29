"""Nanobot Web UI - FastAPI-based web interface with static files."""

import json
import os
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException, Response
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from nanobot.config.loader import get_config_path, load_config, save_config
from nanobot.config.schema import Config


def ensure_config_exists(config_path: Path) -> bool:
    """Ensure config file exists, create default if missing."""
    if config_path.exists():
        return True

    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config = Config()
        save_config(config, config_path)
        return True
    except Exception as e:
        print(f"Warning: Could not create config file: {e}")
        return False


def ensure_workspace_exists(workspace_path: Path) -> bool:
    """Ensure workspace directory exists."""
    try:
        workspace_path.mkdir(parents=True, exist_ok=True)
        return True
    except Exception as e:
        print(f"Warning: Could not create workspace directory: {e}")
        return False


class ChatRequest(BaseModel):
    """Request model for chat endpoint."""
    message: str
    session_id: str = "web:default"


class AuthVerifyRequest(BaseModel):
    """Request model for auth verification."""
    token: str = ""


def create_app(config_path: Path | None = None, workspace_path: Path | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Nanobot Web UI",
        description="Web interface for Nanobot personal AI assistant",
        version="0.1.4.post5",
    )

    # Configuration
    auth_token = os.environ.get("NANOBOT_WEB_AUTH_TOKEN", "")

    # Store config paths in app state
    config_path = config_path or get_config_path()
    app.state.config_path = config_path
    app.state.workspace_path = workspace_path
    app.state.auth_token = auth_token

    # Ensure config and workspace exist
    config_exists = ensure_config_exists(config_path)
    if workspace_path:
        ensure_workspace_exists(workspace_path)

    # Log config status
    if config_exists:
        print(f"✓ Config loaded from: {config_path}")
    else:
        print(f"⚠ Config file missing and could not be created: {config_path}")

    # Register API routes FIRST (before static files)
    register_api_routes(app)
    register_auth_routes(app)

    # Setup paths
    base_path = Path(__file__).parent.parent
    template_path = base_path / "templates" / "web"
    static_path = base_path / "static"

    # Mount static files (CSS, JS, images)
    if static_path.exists():
        app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

    # Mount HTML templates as static files (catches all other routes)
    if template_path.exists():
        app.mount("/", StaticFiles(directory=str(template_path), html=True), name="templates")

    return app


async def check_auth(request: Request):
    """Check authentication and raise HTTPException if unauthorized."""
    auth_token = request.headers.get("X-Auth-Token") or request.query_params.get("token")
    expected_token = request.app.state.auth_token

    # If no token is configured, allow access (for local dev)
    if not expected_token:
        return

    if not auth_token or auth_token != expected_token:
        raise HTTPException(status_code=401, detail="Unauthorized")


def register_api_routes(app: FastAPI):
    """Register API routes."""

    @app.get("/api/config")
    async def get_config(request: Request):
        """Get current configuration."""
        await check_auth(request)
        try:
            config = load_config(request.app.state.config_path)
            config_dict = config.model_dump(mode="json", by_alias=True)
            return config_dict
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/api/config")
    async def save_config_route(request: Request):
        """Save configuration."""
        await check_auth(request)
        try:
            data = await request.json()
            if not data:
                raise HTTPException(status_code=400, detail="No data provided")

            config = load_config(request.app.state.config_path)
            update_config_from_dict(config, data)
            save_config(config, request.app.state.config_path)

            return {"success": True, "message": "Configuration saved"}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/status")
    async def get_status(request: Request):
        """Get system status."""
        await check_auth(request)
        try:
            config_path = request.app.state.config_path
            config = load_config(config_path)

            status = {
                "config_exists": config_path.exists(),
                "workspace_exists": config.workspace_path.exists() if config.workspace_path else False,
                "model": config.agents.defaults.model if config.agents.defaults else "Not configured",
                "providers": {},
                "channels": {},
                "gateway": {
                    "port": config.gateway.port if config.gateway else 18790,
                    "heartbeat_enabled": config.gateway.heartbeat.enabled if config.gateway and config.gateway.heartbeat else True,
                    "heartbeat_interval": config.gateway.heartbeat.interval_s if config.gateway and config.gateway.heartbeat else 1800,
                },
                "tools": {
                    "web_search_provider": config.tools.web.search.provider if config.tools and config.tools.web and config.tools.web.search else "brave",
                    "exec_enabled": config.tools.exec.enable if config.tools and config.tools.exec else True,
                    "restrict_to_workspace": config.tools.restrict_to_workspace if config.tools else False,
                }
            }

            # Check provider status
            try:
                from nanobot.providers.registry import PROVIDERS
                for spec in PROVIDERS:
                    p = getattr(config.providers, spec.name, None)
                    if p is None:
                        continue
                    if spec.is_oauth:
                        status["providers"][spec.name] = {"status": "oauth", "configured": True}
                    elif spec.is_local:
                        status["providers"][spec.name] = {
                            "status": "local",
                            "configured": bool(p.api_base),
                            "api_base": p.api_base
                        }
                    else:
                        status["providers"][spec.name] = {
                            "status": "api_key",
                            "configured": bool(p.api_key)
                        }
            except Exception as e:
                print(f"Warning: Could not load providers: {e}")
                status["providers"] = {"error": "Could not load providers"}

            # Check channel status
            try:
                from nanobot.channels.registry import discover_all
                all_channels = discover_all()
                for name, cls in all_channels.items():
                    section = getattr(config.channels, name, None)
                    if section is None:
                        enabled = False
                    elif isinstance(section, dict):
                        enabled = section.get("enabled", False)
                    else:
                        enabled = getattr(section, "enabled", False)
                    status["channels"][name] = {
                        "display_name": cls.display_name,
                        "enabled": enabled
                    }
            except Exception as e:
                print(f"Warning: Could not load channels: {e}")
                status["channels"] = {"error": "Could not load channels"}

            return status
        except Exception as e:
            print(f"Error in /api/status: {e}")
            import traceback
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/providers")
    async def get_providers(request: Request):
        """Get available providers and their models."""
        await check_auth(request)
        try:
            from nanobot.providers.registry import PROVIDERS

            providers = []
            for spec in PROVIDERS:
                providers.append({
                    "name": spec.name,
                    "display_name": spec.label,
                    "is_oauth": spec.is_oauth,
                    "is_local": spec.is_local,
                    "is_gateway": spec.is_gateway,
                    "keywords": spec.keywords,
                    "default_api_base": spec.default_api_base,
                })

            return {"providers": providers}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/models/suggestions")
    async def get_model_suggestions(request: Request, provider: str = ""):
        """Get model suggestions."""
        await check_auth(request)
        try:
            from nanobot.cli.models import get_model_suggestions
            suggestions = get_model_suggestions(provider)
            return {"models": suggestions}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/channels")
    async def get_channels(request: Request):
        """Get available channels."""
        await check_auth(request)
        try:
            from nanobot.channels.registry import discover_all

            config = load_config(request.app.state.config_path)
            all_channels = discover_all()

            channels = []
            for name, cls in all_channels.items():
                section = getattr(config.channels, name, None) or {}
                if isinstance(section, dict):
                    enabled = section.get("enabled", False)
                    config_data = section
                else:
                    enabled = getattr(section, "enabled", False)
                    config_data = {}

                channels.append({
                    "name": name,
                    "display_name": cls.display_name,
                    "enabled": enabled,
                    "config": config_data,
                    "has_login": hasattr(cls, "login"),
                })

            return {"channels": channels}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/api/chat")
    async def chat(request: Request, stream: bool = False):
        """Send a message to the agent.
        
        Args:
            stream: If True, returns streaming SSE response. If False, returns complete response.
        """
        await check_auth(request)
        try:
            data = await request.json()
            message = data.get("message", "")
            session_id = data.get("session_id", "web:default")

            if not message:
                raise HTTPException(status_code=400, detail="Message is required")

            if stream:
                return StreamingResponse(
                    stream_agent_message(message, session_id, request.app.state.config_path),
                    media_type="text/event-stream",
                    headers={
                        "Cache-Control": "no-cache",
                        "X-Accel-Buffering": "no",
                        "Connection": "keep-alive",
                    }
                )
            else:
                response = await run_agent_message(
                    message,
                    session_id,
                    request.app.state.config_path
                )

                return {
                    "success": True,
                    "response": response.content if response else "",
                    "metadata": response.metadata if response else {}
                }
        except HTTPException:
            raise
        except Exception as e:
            print(f"Error in /api/chat: {e}")
            import traceback
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/api/chat/stream")
    async def chat_stream(request: Request):
        """Stream a message to the agent using SSE (deprecated, use /api/chat?stream=true)."""
        await check_auth(request)

        data = await request.json()
        message = data.get("message", "")
        session_id = data.get("session_id", "web:default")

        if not message:
            raise HTTPException(status_code=400, detail="Message is required")

        return StreamingResponse(
            stream_agent_message(message, session_id, request.app.state.config_path),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            }
        )

    # Health check endpoint (not authenticated for monitoring)
    @app.get("/health")
    async def health():
        """Health check endpoint for Koyeb."""
        return {
            "status": "healthy",
            "version": "0.1.4.post5"
        }


def register_auth_routes(app: FastAPI):
    """Register authentication routes."""

    @app.get("/api/auth/check")
    async def check_auth():
        """Check if authentication is required."""
        auth_token = app.state.auth_token
        return {
            "auth_required": bool(auth_token),
            "authenticated": not bool(auth_token)
        }

    @app.post("/api/auth/verify")
    async def verify_auth(request: Request):
        """Verify authentication token."""
        data = await request.json()
        token = data.get("token", "")
        expected_token = app.state.auth_token

        if not expected_token:
            return {"authenticated": True}

        if token == expected_token:
            return {"authenticated": True}
        else:
            raise HTTPException(status_code=401, detail="Invalid token")


async def stream_agent_message(message: str, session_id: str, config_path: Path):
    """Stream agent message processing with SSE."""
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus
    from nanobot.cron.service import CronService
    from nanobot.cli.commands import _make_provider
    import asyncio

    config = load_config(config_path)
    bus = MessageBus()
    provider = _make_provider(config)

    cron_store_path = config.workspace_path / "cron" / "jobs.json"
    cron = CronService(cron_store_path)

    agent_loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        model=config.agents.defaults.model,
        max_iterations=config.agents.defaults.max_tool_iterations,
        context_window_tokens=config.agents.defaults.context_window_tokens,
        web_search_config=config.tools.web.search,
        web_proxy=config.tools.web.proxy or None,
        exec_config=config.tools.exec,
        cron_service=cron,
        restrict_to_workspace=config.tools.restrict_to_workspace,
        mcp_servers=config.tools.mcp_servers,
        channels_config=config.channels,
        timezone=config.agents.defaults.timezone,
    )

    accumulated_content = ""
    metadata = {}

    try:
        stream_queue = asyncio.Queue()
        
        async def on_stream_cb(delta: str):
            """Callback for streaming content chunks."""
            await stream_queue.put(('content', delta))
        
        async def on_stream_end_cb(resuming: bool = False):
            """Callback when streaming ends."""
            await stream_queue.put(('stream_end', {'resuming': resuming}))
        
        async def run_agent():
            """Run agent processing in background."""
            nonlocal accumulated_content, metadata
            try:
                response = await agent_loop.process_direct(
                    message,
                    session_id,
                    on_progress=lambda c, t=False: None,
                    on_stream=on_stream_cb,
                    on_stream_end=on_stream_end_cb,
                )
                if response:
                    metadata['final_content'] = response.content
                    metadata['metadata'] = getattr(response, 'metadata', {})
                await stream_queue.put(('done', None))
            except Exception as e:
                await stream_queue.put(('error', str(e)))

        # Start agent processing in background
        agent_task = asyncio.create_task(run_agent())
        
        try:
            while True:
                event_type, data = await stream_queue.get()
                
                if event_type == 'content':
                    accumulated_content += data
                    yield f"data: {json.dumps({'type': 'content', 'content': data})}\n\n"
                elif event_type == 'stream_end':
                    yield f"data: {json.dumps({'type': 'stream_end', **data})}\n\n"
                elif event_type == 'done':
                    yield f"data: {json.dumps({'type': 'done', 'content': accumulated_content, 'metadata': metadata})}\n\n"
                    yield "data: [DONE]\n\n"
                    break
                elif event_type == 'error':
                    yield f"data: {json.dumps({'type': 'error', 'error': data})}\n\n"
                    yield "data: [DONE]\n\n"
                    break
        finally:
            await agent_task
            
    finally:
        await agent_loop.close_mcp()


async def run_agent_message(message: str, session_id: str, config_path: Path):
    """Run agent message processing in async context."""
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus
    from nanobot.cron.service import CronService
    from nanobot.cli.commands import _make_provider

    config = load_config(config_path)
    bus = MessageBus()
    provider = _make_provider(config)

    cron_store_path = config.workspace_path / "cron" / "jobs.json"
    cron = CronService(cron_store_path)

    agent_loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        model=config.agents.defaults.model,
        max_iterations=config.agents.defaults.max_tool_iterations,
        context_window_tokens=config.agents.defaults.context_window_tokens,
        web_search_config=config.tools.web.search,
        web_proxy=config.tools.web.proxy or None,
        exec_config=config.tools.exec,
        cron_service=cron,
        restrict_to_workspace=config.tools.restrict_to_workspace,
        mcp_servers=config.tools.mcp_servers,
        channels_config=config.channels,
        timezone=config.agents.defaults.timezone,
    )

    try:
        response = await agent_loop.process_direct(
            message,
            session_id,
            on_progress=lambda c, t=False: None,
        )
        return response
    finally:
        await agent_loop.close_mcp()


def update_config_from_dict(config: Config, data: dict):
    """Update config object from dictionary data."""
    for key, value in data.items():
        snake_key = key
        for i, char in enumerate(key):
            if char.isupper() and (i == 0 or not key[i-1].isupper()):
                snake_key = key[:i].lower() + "_" + key[i:]
                break

        if hasattr(config, snake_key):
            attr = getattr(config, snake_key)
            if isinstance(attr, dict) and isinstance(value, dict):
                attr.update(value)
            elif isinstance(attr, (list, tuple)) and isinstance(value, (list, tuple)):
                setattr(config, snake_key, value)
            elif hasattr(attr, "model_dump"):
                if isinstance(value, dict):
                    for sub_key, sub_value in value.items():
                        sub_snake = sub_key
                        for j, c in enumerate(sub_key):
                            if c.isupper() and (j == 0 or not sub_key[j-1].isupper()):
                                sub_snake = sub_key[:j].lower() + "_" + sub_key[j:]
                                break
                        if hasattr(attr, sub_snake):
                            setattr(attr, sub_snake, sub_value)
            else:
                setattr(config, snake_key, value)


# Global app instance for CLI
_app_instance = None


def get_app(config_path: Path | None = None, workspace_path: Path | None = None) -> FastAPI:
    """Get or create the FastAPI app instance."""
    global _app_instance
    if _app_instance is None:
        _app_instance = create_app(config_path, workspace_path)
    return _app_instance


def run_server(host: str = "0.0.0.0", port: int = 18790, config_path: Path | None = None,
             workspace_path: Path | None = None, debug: bool = False):
    """Run the FastAPI development server using uvicorn."""
    import uvicorn
    
    app = get_app(config_path, workspace_path)
    
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="debug" if debug else "info",
        reload=debug,
    )
