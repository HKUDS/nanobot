"""HTTP handlers for the Anthropic Messages API proxy."""

import json
from typing import Any

from aiohttp import web
from loguru import logger

from nanobot.api.anthropic_format import (
    anthropic_request_to_litellm,
    generate_sse_events,
    litellm_response_to_anthropic,
)
from nanobot.api.auth import check_auth
from nanobot.api.claude_direct import (
    anthropic_direct_request,
    anthropic_direct_stream,
    is_oauth_token,
)


class MessagesHandler:
    """Handler for POST /v1/messages — Anthropic Messages API proxy.

    Supports two modes:
    - **OAuth mode**: When the API key is a Claude Code OAuth token (sk-ant-oat...),
      requests go directly to api.anthropic.com with the correct Claude Code headers.
    - **LiteLLM mode**: For regular API keys, requests go through litellm to any
      configured backend provider.
    """

    def __init__(
        self,
        proxy_config: Any,
        litellm_kwargs: dict[str, Any],
    ):
        self.proxy_config = proxy_config
        self.litellm_kwargs = litellm_kwargs
        self._oauth_token: str | None = None

        # Detect if we're using an OAuth token
        api_key = litellm_kwargs.get("api_key", "")
        if api_key and is_oauth_token(api_key):
            self._oauth_token = api_key
            logger.info("Proxy using Claude Code OAuth (direct Anthropic API)")
        else:
            logger.info("Proxy using LiteLLM (multi-provider)")

    def _resolve_model(self, model: str) -> str:
        """Apply model mapping from config."""
        if self.proxy_config.model_map and model in self.proxy_config.model_map:
            mapped = self.proxy_config.model_map[model]
            logger.debug(f"Model mapped: {model} -> {mapped}")
            return mapped
        if self.proxy_config.default_model:
            return self.proxy_config.default_model
        return model

    async def handle_messages(self, request: web.Request) -> web.Response | web.StreamResponse:
        """Handle POST /v1/messages."""
        # Auth
        auth_error = check_auth(request, self.proxy_config.api_key)
        if auth_error:
            return web.json_response(
                {"type": "error", "error": {"type": "authentication_error", "message": auth_error}},
                status=401,
            )

        # Parse body
        try:
            body = await request.json()
        except (json.JSONDecodeError, Exception):
            return web.json_response(
                {"type": "error", "error": {"type": "invalid_request_error", "message": "Invalid JSON body"}},
                status=400,
            )

        if "model" not in body or "messages" not in body:
            return web.json_response(
                {"type": "error", "error": {"type": "invalid_request_error", "message": "model and messages are required"}},
                status=400,
            )

        # Model mapping
        original_model = body["model"]
        body["model"] = self._resolve_model(original_model)

        is_stream = body.get("stream", False)

        try:
            # OAuth path: direct Anthropic API with Claude Code headers
            if self._oauth_token:
                if is_stream:
                    return await self._handle_oauth_streaming(request, body)
                else:
                    return await self._handle_oauth_non_streaming(body)

            # LiteLLM path: multi-provider routing
            litellm_kwargs = anthropic_request_to_litellm(body)
            for key, value in self.litellm_kwargs.items():
                if key not in litellm_kwargs and value is not None:
                    litellm_kwargs[key] = value
            is_stream = litellm_kwargs.pop("stream", False)

            if is_stream:
                return await self._handle_litellm_streaming(request, litellm_kwargs, original_model)
            else:
                return await self._handle_litellm_non_streaming(litellm_kwargs, original_model)

        except Exception as e:
            logger.error(f"Proxy error: {e}")
            return web.json_response(
                {"type": "error", "error": {"type": "api_error", "message": str(e)}},
                status=500,
            )

    # ------------------------------------------------------------------
    # OAuth direct path (Claude Code login)
    # ------------------------------------------------------------------

    async def _handle_oauth_non_streaming(self, body: dict[str, Any]) -> web.Response:
        """Non-streaming via direct Anthropic API."""
        resp = await anthropic_direct_request(self._oauth_token, body)
        return web.Response(
            status=resp.status_code,
            body=resp.content,
            content_type="application/json",
        )

    async def _handle_oauth_streaming(
        self, request: web.Request, body: dict[str, Any]
    ) -> web.StreamResponse:
        """Streaming via direct Anthropic API — pass-through SSE."""
        response = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
        await response.prepare(request)

        async for line in anthropic_direct_stream(self._oauth_token, body):
            await response.write(line.encode("utf-8"))

        await response.write_eof()
        return response

    # ------------------------------------------------------------------
    # LiteLLM path (regular API keys, multi-provider)
    # ------------------------------------------------------------------

    async def _handle_litellm_non_streaming(
        self, kwargs: dict[str, Any], original_model: str
    ) -> web.Response:
        from litellm import acompletion

        response = await acompletion(**kwargs)
        anthropic_response = litellm_response_to_anthropic(response, original_model)
        return web.json_response(anthropic_response)

    async def _handle_litellm_streaming(
        self, request: web.Request, kwargs: dict[str, Any], original_model: str
    ) -> web.StreamResponse:
        from litellm import acompletion

        kwargs["stream"] = True
        stream = await acompletion(**kwargs)

        response = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
        await response.prepare(request)

        async for event_str in generate_sse_events(stream, original_model):
            await response.write(event_str.encode("utf-8"))

        await response.write_eof()
        return response
