"""HTTP API channel for programmatic access to nanobot."""

from __future__ import annotations

from typing import Any

from loguru import logger
from pydantic import BaseModel

from nanobot.agent.loop import AgentLoop
from nanobot.config.schema import HTTPAPIConfig


class ChatRequest(BaseModel):
    """POST /api/v1/chat request body."""
    message: str
    session_key: str = "api:default"
    channel: str = "api"
    chat_id: str = "default"


class ChatResponse(BaseModel):
    """POST /api/v1/chat response body."""
    response: str
    session_key: str


class HTTPAPIChannel:
    """HTTP API channel — exposes nanobot as a REST endpoint.

    Follows the same pattern as other nanobot channels (Telegram, Discord, etc.)
    but uses HTTP request/response instead of a message bus.
    """

    def __init__(self, config: HTTPAPIConfig, agent_loop: AgentLoop) -> None:
        self.config = config
        self.agent = agent_loop
        self._app: Any = None  # lazily created

    def _create_app(self) -> Any:
        """Create the FastAPI application with routes."""
        from fastapi import FastAPI, HTTPException, Request
        from fastapi.responses import JSONResponse

        app = FastAPI(title="nanobot API", version="1.0.0")

        @app.get("/api/v1/health")
        async def health() -> dict:
            return {"status": "ok"}

        @app.post("/api/v1/chat", response_model=ChatResponse)
        async def chat(req: ChatRequest, request: Request) -> ChatResponse:
            self._check_auth(request)
            response = await self.agent.process_direct(
                content=req.message,
                session_key=req.session_key,
                channel=req.channel,
                chat_id=req.chat_id,
            )
            return ChatResponse(response=response, session_key=req.session_key)

        return app

    def _check_auth(self, request: Any) -> None:
        """Validate bearer token if auth_token is configured."""
        from fastapi import HTTPException

        if not self.config.auth_token:
            return  # No auth required

        auth_header = request.headers.get("authorization", "")
        if not auth_header:
            raise HTTPException(status_code=401, detail="Authorization header required")

        parts = auth_header.split(" ", 1)
        if len(parts) != 2 or parts[0].lower() != "bearer":
            raise HTTPException(status_code=401, detail="Invalid authorization format (expected 'Bearer <token>')")

        if parts[1] != self.config.auth_token:
            raise HTTPException(status_code=403, detail="Invalid token")

    async def start(self, host: str, port: int) -> None:
        """Start the HTTP API server."""
        import uvicorn

        self._app = self._create_app()
        logger.info(f"HTTP API starting on {host}:{port}")
        config = uvicorn.Config(self._app, host=host, port=port, log_level="info")
        server = uvicorn.Server(config)
        await server.serve()
