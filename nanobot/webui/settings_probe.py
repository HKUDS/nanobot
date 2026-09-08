"""Explicit, bounded model checks for guided setup."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from nanobot.config.loader import resolve_config_env_vars
from nanobot.config.schema import Config, ModelPresetConfig
from nanobot.providers.base import LLMResponse
from nanobot.providers.factory import make_provider


async def test_provider_connection(config: Config, payload: dict[str, Any]) -> dict[str, Any]:
    """Send one short prompt to exactly the requested provider, without tools or fallback."""
    provider_name = payload.get("provider")
    model = payload.get("model")
    if not isinstance(provider_name, str) or not provider_name.strip() or provider_name == "auto":
        return {"status": "error", "message": "Choose a provider before testing."}
    if not isinstance(model, str) or not model.strip() or len(model) > 512:
        return {"status": "error", "message": "Choose a valid model ID before testing."}
    started = time.monotonic()
    try:
        probe_config = config.model_copy(deep=True)
        probe_config.agents.defaults.fallback_models = []
        preset = ModelPresetConfig(provider=provider_name, model=model)
        provider = make_provider(resolve_config_env_vars(probe_config), preset=preset)
        async with asyncio.timeout(15):
            response = await provider.chat(
                [{"role": "user", "content": "Reply with a short hello."}],
                model=model, max_tokens=256,
            )
    except Exception as exc:
        # Provider exceptions can contain request headers or response bodies. Return
        # only structured categories, never the raw upstream error to the terminal.
        status = getattr(exc, "status_code", None)
        if isinstance(exc, httpx.HTTPStatusError):
            status = exc.response.status_code
        kind = "timeout" if isinstance(exc, (TimeoutError, httpx.TimeoutException)) else (
            "connection" if isinstance(exc, (ConnectionError, httpx.RequestError)) else None
        )
        response = LLMResponse(
            content=None, finish_reason="error", error_kind=kind,
            error_status_code=status if isinstance(status, int) else None,
        )
    elapsed = round(time.monotonic() - started, 1)
    if response.finish_reason not in {"error", "cancelled"} and response.content:
        return {"status": "ok", "message": response.content[:500], "elapsed_seconds": elapsed}
    status = response.error_status_code
    kind = response.error_kind
    if status in {401, 403} or kind == "authentication":
        message = "Access denied. Change connection to update credentials or sign in again."
    elif status == 404:
        message = "Model or endpoint not found. Check the endpoint or choose a different model."
    elif status == 429 or kind == "rate_limit":
        message = "Provider limit reached. Check your quota or wait before retrying."
    elif kind in {"timeout", "connection"}:
        message = "Could not reach the model. Check the endpoint and network, then retry."
    else:
        message = "No model reply received. Check connection and model access, then retry."
    return {"status": "error", "message": message, "elapsed_seconds": elapsed}
