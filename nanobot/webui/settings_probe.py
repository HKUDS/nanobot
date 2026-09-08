"""Explicit, bounded model checks for guided setup."""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any, cast

import httpx

from nanobot.config.loader import resolve_config_env_vars
from nanobot.config.schema import Config, ModelPresetConfig
from nanobot.providers.base import LLMResponse
from nanobot.providers.factory import make_provider


async def test_provider_connection(config: Config, payload: dict[str, Any]) -> dict[str, Any]:
    """Send one short prompt to exactly the requested provider, without tools or fallback."""
    if payload.get("check_credentials") is True:
        return await check_oauth_access(config, payload)
    preset_name = payload.get("preset_name")
    if preset_name is not None:
        if not isinstance(preset_name, str) or preset_name not in config.model_presets:
            return {"status": "error", "message": "Save a valid preset before testing."}
        preset = config.model_presets[preset_name].model_copy(deep=True)
        model = preset.model
    else:
        provider_name = payload.get("provider")
        model = payload.get("model")
        if not isinstance(provider_name, str) or not provider_name.strip() or provider_name == "auto":
            return {"status": "error", "message": "Choose a provider before testing."}
        if not isinstance(model, str) or not model.strip() or len(model) > 512:
            return {"status": "error", "message": "Choose a valid model ID before testing."}
        preset = ModelPresetConfig(provider=provider_name, model=model)
    started = time.monotonic()
    try:
        probe_config = config.model_copy(deep=True)
        probe_config.agents.defaults.fallback_models = []
        provider = make_provider(resolve_config_env_vars(probe_config), preset=preset)
        async with asyncio.timeout(15):
            response = await provider.chat(
                [{"role": "user", "content": "Reply with a short hello."}],
                model=model, max_tokens=min(preset.max_tokens, 256),
                temperature=preset.temperature, reasoning_effort=preset.reasoning_effort,
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


async def check_oauth_access(config: Config, payload: dict[str, Any]) -> dict[str, Any]:
    """Check the live authenticated catalog, never a cached or built-in fallback."""
    name = payload.get("provider")
    if name not in ("xai_grok", "openai_codex", "github_copilot"):
        return {"status": "error", "message": "Account checks are unavailable for this provider."}
    resolved = resolve_config_env_vars(config.model_copy(deep=True))
    proxy = getattr(resolved.providers, name).proxy or None
    try:
        if name == "xai_grok":
            from nanobot.providers.xai_grok_provider import check_xai_grok_access
            check = check_xai_grok_access
        elif name == "openai_codex":
            from nanobot.providers.openai_codex_provider import check_openai_codex_access
            check = check_openai_codex_access
        else:
            from nanobot.providers.github_copilot_provider import check_github_copilot_access
            check = check_github_copilot_access
        async with asyncio.timeout(18):
            await asyncio.to_thread(check, proxy)
        return {"status": "available", "message": "Account accepted by the model catalog. Test a preset to check a model reply."}
    except Exception as exc:
        status = getattr(exc, "status_code", None)
        if isinstance(exc, httpx.HTTPStatusError):
            status = exc.response.status_code
        # oauth-cli-kit currently wraps refresh failures in an unstructured RuntimeError.
        # Parse only its fixed prefix and OAuth error code; never return the response body.
        oauth_error = getattr(exc, "oauth_error", None)
        refresh = re.match(r"^Token refresh failed: (\d{3}) (.*)$", str(exc), re.DOTALL)
        if refresh:
            status = int(refresh[1])
            try:
                body = json.loads(refresh[2])
                oauth_error = cast(dict[str, Any], body).get("error") if isinstance(body, dict) else None
            except ValueError:
                pass
        missing = str(exc) in (
            "OAuth credentials not found. Please run the login command.",
            "GitHub Copilot is not logged in",
        )
        if missing or status in (401, 403) or oauth_error == "invalid_grant":
            return {"status": "signin_required", "message": "Credentials rejected. Sign in again."}
        if isinstance(exc, (TimeoutError, httpx.RequestError)) or isinstance(exc.__cause__, httpx.RequestError):
            return {"status": "unreachable", "message": "Could not reach the provider. Check the network and retry."}
        return {"status": "error", "message": "Account check failed. Retry or sign in again."}
