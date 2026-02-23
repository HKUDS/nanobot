"""HTTP handlers for the Anthropic Messages API proxy."""

import json
from typing import Any

from aiohttp import web
from loguru import logger

from nanobot.api.auth import check_auth
from nanobot.api.claude_direct import send_to_anthropic
from nanobot.providers.claude_code_auth import is_oauth_token


class MessagesHandler:
    """Handler for /v1/messages requests.

    Two modes:
    - OAuth mode: forward directly to Anthropic API with Claude Code headers
    - LiteLLM mode: convert Anthropic -> OpenAI format, call via LiteLLM, convert back
    """

    def __init__(self, proxy_config: Any, litellm_kwargs: dict[str, Any]):
        self._proxy_config = proxy_config
        self._litellm_kwargs = litellm_kwargs

        api_key = litellm_kwargs.get("api_key", "")
        if api_key and is_oauth_token(api_key):
            self._oauth_token: str | None = api_key
        else:
            self._oauth_token = None

        self._model_map: dict[str, str] = {}
        if hasattr(proxy_config, "model_map"):
            self._model_map = proxy_config.model_map or {}

    def _remap_model(self, model: str) -> str:
        """Apply model name remapping from config."""
        return self._model_map.get(model, model)

    async def handle_messages(self, request: web.Request) -> web.StreamResponse:
        """Handle POST /v1/messages."""
        # Auth check
        required_key = getattr(self._proxy_config, "api_key", "")
        auth_err = check_auth(request, required_key)
        if auth_err:
            return web.json_response({"error": {"type": "authentication_error", "message": auth_err}}, status=401)

        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response(
                {"error": {"type": "invalid_request_error", "message": "Invalid JSON body"}},
                status=400,
            )

        # Apply model remapping
        if "model" in body:
            body["model"] = self._remap_model(body["model"])

        is_stream = body.get("stream", False)

        if self._oauth_token:
            return await self._handle_oauth(body, is_stream)
        return await self._handle_litellm(body, is_stream)

    async def _handle_oauth(self, body: dict[str, Any], stream: bool) -> web.StreamResponse:
        """Forward request directly to Anthropic API (OAuth path)."""
        try:
            resp = await send_to_anthropic(body, self._oauth_token, stream=stream)

            if not stream:
                data = resp.json()
                return web.json_response(data, status=resp.status_code)

            # Streaming: pipe SSE from Anthropic directly
            response = web.StreamResponse(
                status=resp.status_code,
                headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"},
            )
            await response.prepare(request=None)  # aiohttp quirk

            try:
                async for line in resp.aiter_lines():
                    await response.write(f"{line}\n".encode())
            finally:
                await resp.aclose()
                if hasattr(resp, "_client"):
                    await resp._client.aclose()

            return response

        except Exception as e:
            logger.error("OAuth proxy error: {}", e)
            return web.json_response(
                {"error": {"type": "api_error", "message": str(e)}},
                status=502,
            )

    async def _handle_litellm(self, body: dict[str, Any], stream: bool) -> web.StreamResponse:
        """Convert Anthropic -> LiteLLM, call LLM, convert back."""
        from litellm import acompletion

        from nanobot.api.anthropic_format import (
            anthropic_request_to_litellm,
            generate_sse_events,
            litellm_response_to_anthropic,
        )

        litellm_req = anthropic_request_to_litellm(body)
        model = litellm_req.pop("model", "") or self._litellm_kwargs.get("model", "")

        kwargs = {
            **self._litellm_kwargs,
            **litellm_req,
            "model": model,
        }
        # Don't pass api_key twice
        if "api_key" not in kwargs and self._litellm_kwargs.get("api_key"):
            kwargs["api_key"] = self._litellm_kwargs["api_key"]

        try:
            if stream:
                kwargs["stream"] = True
                response = await acompletion(**kwargs)

                sse_response = web.StreamResponse(
                    headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"},
                )
                await sse_response.prepare(request=None)

                async for event_str in generate_sse_events(response, model=model):
                    await sse_response.write(event_str.encode())

                return sse_response
            else:
                response = await acompletion(**kwargs)
                anthropic_resp = litellm_response_to_anthropic(response, model=model)
                return web.json_response(anthropic_resp)
        except Exception as e:
            logger.error("LiteLLM proxy error: {}", e)
            return web.json_response(
                {"error": {"type": "api_error", "message": str(e)}},
                status=502,
            )
