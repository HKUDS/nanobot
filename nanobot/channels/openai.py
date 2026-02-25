"""OpenAI-compatible HTTP API channel using FastAPI."""

import asyncio
import json
import time
import uuid
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from nanobot.bus.events import MessageType, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import OpenAIConfig

SENDER_ID = "default"
CHAT_ID = "1"


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="allow")
    content: str


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    messages: list[ChatMessage] = Field(..., min_length=1)
    stream: bool = False


def _error_body(
    message: str,
    error_type: str,
    param: str | None = None,
    code: str | None = None,
) -> dict:
    """Build an OpenAI-style error response body."""
    return {"error": {"message": message, "type": error_type, "param": param, "code": code}}


class OpenAIAPIError(HTTPException):
    """HTTPException subclass that renders OpenAI-style error bodies."""

    def __init__(
        self,
        status_code: int,
        message: str,
        error_type: str,
        param: str | None = None,
        code: str | None = None,
    ):
        super().__init__(status_code=status_code)
        self.message = message
        self.error_type = error_type
        self.param = param
        self.code = code


_bearer = HTTPBearer(auto_error=False)


async def _verify_api_key(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    """Validate Bearer token against the configured API key."""
    api_key = getattr(app.state, "api_key", "")
    if not api_key:
        return
    if credentials is None or credentials.credentials != api_key:
        raise OpenAIAPIError(
            401,
            "Incorrect API key provided",
            "authentication_error",
            code="invalid_api_key",
        )


app = FastAPI(title="Nanobot OpenAI-compatible API", dependencies=[Depends(_verify_api_key)])


@app.exception_handler(RequestValidationError)
async def _validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    first = exc.errors()[0]
    param = ".".join(
        str(loc) for loc in first.get("loc", []) if isinstance(loc, str) and loc != "body"
    )
    return JSONResponse(
        status_code=400,
        content=_error_body(
            message=first.get("msg", "Validation error"),
            error_type="invalid_request_error",
            param=param or None,
            code=None,
        ),
    )


@app.exception_handler(OpenAIAPIError)
async def _openai_error_handler(request: Request, exc: OpenAIAPIError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_body(exc.message, exc.error_type, exc.param, exc.code),
    )


@app.post("/v1/chat/completions")
async def chat_completions(body: ChatCompletionRequest):
    try:
        response_text = await app.state.handle_message(body.messages[-1].content)
    except asyncio.TimeoutError:
        raise OpenAIAPIError(504, "Request timed out", "server_error")

    # Build chunk response
    response: dict[str, Any] = {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": "nanobot",
        "choices": [
            {
                "index": 0,
                "delta": {"role": "assistant", "content": response_text},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }

    if body.stream:

        async def generate():
            yield f"data: {json.dumps(response)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream")

    # Transform to non-streaming response
    response["object"] = "chat.completion"
    response["choices"][0]["message"] = response["choices"][0].pop("delta")

    return JSONResponse(content=response)


@app.get("/v1/models")
async def list_models() -> JSONResponse:
    return JSONResponse(
        content={
            "object": "list",
            "data": [{"id": "nanobot", "object": "model", "created": 0, "owned_by": "nanobot"}],
        }
    )


class OpenAIChannel(BaseChannel):
    """
    Channel that exposes an OpenAI-compatible /v1/chat/completions endpoint.

    This allows nanobot to be used with any OpenAI-compatible frontend
    (Open WebUI, ChatBox, etc.).
    """

    name = "openai"

    def __init__(self, config: OpenAIConfig, bus: MessageBus):
        super().__init__(config=config, bus=bus)
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=1)
        self._server: uvicorn.Server | None = None
        app.state.api_key = config.api_key
        app.state.handle_message = self._dispatch

    async def start(self) -> None:
        """Start the uvicorn ASGI server."""
        self._running = True
        uv_config = uvicorn.Config(
            app,
            host=self.config.host,
            port=self.config.port,
            log_level="warning",
        )
        self._server = uvicorn.Server(uv_config)
        logger.info(f"OpenAI-compatible API listening on {self.config.host}:{self.config.port}")
        await self._server.serve()

    async def stop(self) -> None:
        """Shut down the ASGI server."""
        self._running = False
        if self._server:
            self._server.should_exit = True
            self._server = None
        logger.info("OpenAI-compatible API stopped")

    async def _dispatch(self, content: str) -> str:
        """Drain stale responses, publish to bus, and wait for the reply."""
        try:
            self._queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
        await self._handle_message(sender_id=SENDER_ID, chat_id=CHAT_ID, content=content)
        return await asyncio.wait_for(self._queue.get(), timeout=20)

    async def send(self, msg: OutboundMessage) -> None:
        """Deliver a response to the waiting HTTP request."""
        if msg.type == MessageType.PROGRESS:
            return
        try:
            self._queue.put_nowait(msg.content)
        except asyncio.QueueFull:
            logger.warning("OpenAI channel: no HTTP request waiting, discarding response")
