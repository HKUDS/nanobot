"""Gateway HTTP Server with Web UI."""

import asyncio
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from nanobot.config.loader import load_config, save_config


class GatewayServer:
    """FastAPI server for gateway web UI."""

    def __init__(self, port: int = 18790, host: str | None = None):
        self.port = port
        self.host = host or self._detect_host()
        self.app = FastAPI(title="Nanobot Gateway", docs_url=None, redoc_url=None)
        self._setup_routes()
        self._setup_middleware()

    def _detect_host(self) -> str:
        """Detect whether to bind to localhost or all interfaces."""
        import os
        if os.environ.get("NANOBOT_DOCKER") == "1":
            return "0.0.0.0"
        if Path("/.dockerenv").exists():
            return "0.0.0.0"
        return "127.0.0.1"

    def _setup_middleware(self):
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    def _setup_routes(self):
        self.app.get("/")(self.index)
        self.app.get("/ui")(self.index)
        self.app.post("/api/auth/login")(self.login)
        self.app.post("/api/auth/logout")(self.logout)
        self.app.get("/api/config")(self.get_config)
        self.app.put("/api/config")(self.put_config)
        self.app.post("/api/config/reload")(self.reload_config)
        self.app.get("/api/status")(self.get_status)

    async def index(self) -> HTMLResponse:
        ui_path = Path(__file__).parent / "ui" / "index.html"
        if ui_path.exists():
            return HTMLResponse(content=ui_path.read_text(encoding="utf-8"))
        return HTMLResponse(
            content="<html><body><h1>UI not found</h1></body></html>",
            status_code=404,
        )

    async def login(self, request: Request) -> JSONResponse:
        body = await request.json()
        token = body.get("token", "")

        config = load_config()
        stored_token = config.gateway.auth.token

        if token == stored_token and stored_token:
            return JSONResponse({"authenticated": True, "token": stored_token})

        return JSONResponse({"authenticated": False, "error": "Invalid token"}, status_code=401)

    async def logout(self) -> JSONResponse:
        return JSONResponse({"success": True})

    async def get_config(self, request: Request) -> JSONResponse:
        auth = await self._check_auth(request)
        if not auth:
            return JSONResponse({"error": "Unauthorized"}, status_code=401)

        config = load_config()
        exposed = self._filter_config(config.model_dump(by_alias=True))
        return JSONResponse(exposed)

    async def put_config(self, request: Request) -> JSONResponse:
        auth = await self._check_auth(request)
        if not auth:
            return JSONResponse({"error": "Unauthorized"}, status_code=401)

        body = await request.json()

        try:
            current_config = load_config()
            merged = self._merge_config(current_config.model_dump(by_alias=True), body)
            from nanobot.config.schema import Config

            new_config = Config.model_validate(merged)
            save_config(new_config)
            return JSONResponse({"success": True})
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    async def reload_config(self, request: Request) -> JSONResponse:
        auth = await self._check_auth(request)
        if not auth:
            return JSONResponse({"error": "Unauthorized"}, status_code=401)

        try:
            load_config(force_reload=True)
            return JSONResponse({"success": True})
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    async def get_status(self, request: Request) -> JSONResponse:
        auth = await self._check_auth(request)
        if not auth:
            return JSONResponse({"error": "Unauthorized"}, status_code=401)

        config = load_config()
        workspace = config.workspace_path

        status: dict[str, Any] = {
            "workspace": str(workspace),
            "gateway": {
                "port": config.gateway.port,
                "heartbeat": {
                    "enabled": config.gateway.heartbeat.enabled,
                    "interval_s": config.gateway.heartbeat.interval_s,
                },
            },
            "agents": {
                "model": config.agents.defaults.model,
                "temperature": config.agents.defaults.temperature,
            },
            "channels": {},
            "providers": [],
        }

        for channel_name in [
            "telegram",
            "discord",
            "whatsapp",
            "slack",
            "feishu",
            "dingtalk",
            "email",
            "matrix",
        ]:
            channel_config = getattr(config.channels, channel_name, None)
            if channel_config:
                status["channels"][channel_name] = {"enabled": channel_config.enabled}

        for provider_name in [
            "openrouter",
            "openai",
            "anthropic",
            "deepseek",
            "custom",
            "azure_openai",
        ]:
            provider_config = getattr(config.providers, provider_name, None)
            if provider_config and provider_config.api_key:
                status["providers"].append(provider_name)

        cron_path = workspace / "cron" / "jobs.json"
        if cron_path.exists():
            import json

            try:
                jobs = json.loads(cron_path.read_text(encoding="utf-8"))
                status["cron"] = {"jobs": len(jobs)}
            except:
                status["cron"] = {"jobs": 0}
        else:
            status["cron"] = {"jobs": 0}

        return JSONResponse(status)

    async def _check_auth(self, request: Request) -> bool:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
        else:
            return False

        config = load_config()
        return token == config.gateway.auth.token

    def _filter_config(self, config: dict) -> dict:
        exposed = {
            "agents": {
                "defaults": {
                    "model": config.get("agents", {}).get("defaults", {}).get("model"),
                    "temperature": config.get("agents", {}).get("defaults", {}).get("temperature"),
                    "maxTokens": config.get("agents", {}).get("defaults", {}).get("maxTokens"),
                    "maxToolIterations": config.get("agents", {})
                    .get("defaults", {})
                    .get("maxToolIterations"),
                    "memoryWindow": config.get("agents", {})
                    .get("defaults", {})
                    .get("memoryWindow"),
                    "reasoningEffort": config.get("agents", {})
                    .get("defaults", {})
                    .get("reasoningEffort"),
                }
            },
            "channels": config.get("channels", {}),
            "providers": {},
            "tools": config.get("tools", {}),
            "gateway": config.get("gateway", {}),
        }

        for provider_name in [
            "openrouter",
            "openai",
            "anthropic",
            "deepseek",
            "custom",
            "azure_openai",
        ]:
            if provider_name in config.get("providers", {}):
                p = config["providers"][provider_name]
                exposed["providers"][provider_name] = {
                    "apiKey": p.get("apiKey"),
                    "apiBase": p.get("apiBase"),
                    "extraHeaders": p.get("extraHeaders"),
                }

        return exposed

    def _merge_config(self, current: dict, updates: dict) -> dict:
        result = current.copy()

        for key in ["agents", "channels", "providers", "tools", "gateway"]:
            if key in updates:
                if key not in result:
                    result[key] = {}
                result[key] = self._deep_merge(result[key], updates[key])

        return result

    def _deep_merge(self, base: dict, updates: dict) -> dict:
        result = base.copy()
        for k, v in updates.items():
            if isinstance(v, dict) and k in result and isinstance(result[k], dict):
                result[k] = self._deep_merge(result[k], v)
            elif v is not None:
                result[k] = v
        return result

    def run(self):
        import uvicorn
        uvicorn.run(self.app, host=self.host, port=self.port, log_level="warning")


def run_server(port: int = 18790):
    server = GatewayServer(port)
    server.run()
