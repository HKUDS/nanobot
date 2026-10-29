"""Langfuse settings and credential-only connection checks."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import re
from typing import Any, Literal, NotRequired, TypedDict, cast
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from nanobot.config.schema import Config
from nanobot.observability.config import (
    LangfuseConfig,
    editable_langfuse_config,
    resolve_langfuse_config,
)
from nanobot.observability.langfuse import (
    get_running_langfuse_active,
    get_running_langfuse_available,
    get_running_langfuse_config,
)
from nanobot.optional_features import extra_installed, optional_dependency_groups
from nanobot.security.network import (
    PinnedDNSAsyncTransport,
    UnsafeURLRequestError,
    httpx_env_proxy_mounts,
    validate_url_target,
)
from nanobot.webui.settings_contracts import WebUISettingsError
from nanobot.webui.settings_models import mask_secret_hint


class LangfuseSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    enabled: bool
    base_url: str = Field(max_length=2048)
    public_key: str | None = Field(default=None, max_length=4096, repr=False)
    secret_key: str | None = Field(default=None, max_length=4096, repr=False)


ConnectionErrorCode = Literal[
    "missing_credentials", "invalid_url", "blocked_url", "invalid_credentials", "unreachable", "timeout",
]


class ConnectionTestResult(TypedDict):
    ok: bool
    error: NotRequired[ConnectionErrorCode]


def parse_observability_update(payload: object) -> LangfuseSettingsUpdate:
    try:
        return LangfuseSettingsUpdate.model_validate(payload)
    except ValidationError:
        # Pydantic diagnostics include input values, which can contain credentials.
        raise WebUISettingsError("Invalid Langfuse settings") from None


def langfuse_installed() -> bool:
    return extra_installed("langfuse", optional_dependency_groups()["langfuse"])


def observability_settings_payload(config: Config) -> dict[str, Any]:
    raw = editable_langfuse_config(config)
    effective = resolve_langfuse_config(config)
    running = get_running_langfuse_config()
    available = importlib.util.find_spec("langfuse") is not None
    return {
        "provider": "langfuse",
        "enabled": raw.enabled,
        "configured": effective.configured,
        "base_url": raw.base_url,
        "public_key_hint": mask_secret_hint(effective.public_key),
        "secret_key_hint": mask_secret_hint(effective.secret_key),
        "source": "environment" if config.observability.langfuse is None else "config",
        "uses_environment": any("${" in value for value in (raw.base_url, raw.public_key, raw.secret_key)),
        "active_enabled": bool(get_running_langfuse_active()),
        "requires_restart": running is not None and (
            running != effective or available != get_running_langfuse_available()
        ),
    }


def _candidate_config(config: Config, update: LangfuseSettingsUpdate) -> tuple[Config, LangfuseConfig]:
    raw = editable_langfuse_config(config).model_copy(update=update.model_dump(exclude_none=True))
    candidate = config.model_copy(update={
        "observability": config.observability.model_copy(update={"langfuse": raw}),
    })
    return candidate, raw


def _valid_base_url(value: str) -> bool:
    if not value or any(character.isspace() or ord(character) < 32 for character in value):
        return False
    try:
        url = urlsplit(value)
        return bool(
            url.scheme in {"http", "https"} and url.hostname and url.port != 0
            and url.username is None and url.password is None
            and not url.query and not url.fragment
        )
    except ValueError:
        return False


def update_observability_settings(config: Config, update: LangfuseSettingsUpdate) -> bool:
    candidate, raw = _candidate_config(config, update)
    # Startup resolves references strictly, including disabled integrations.
    # Do not persist a draft that would make the next restart fail to load.
    for value, code in (
        (raw.base_url, "langfuse_invalid_url"),
        (raw.public_key, "langfuse_missing_credentials"),
        (raw.secret_key, "langfuse_missing_credentials"),
    ):
        if any(name not in os.environ for name in re.findall(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", value)):
            raise WebUISettingsError(code)
    effective = resolve_langfuse_config(candidate)
    if raw.enabled:
        if not effective.configured:
            raise WebUISettingsError("langfuse_missing_credentials")
        if not _valid_base_url(effective.base_url):
            raise WebUISettingsError("langfuse_invalid_url")
        if not langfuse_installed():
            raise WebUISettingsError("langfuse_support_required")
    changed = config.observability.langfuse != raw
    config.observability.langfuse = raw
    return changed


async def probe_langfuse_connection(config: Config, update: LangfuseSettingsUpdate) -> ConnectionTestResult:
    candidate, _raw = _candidate_config(config, update)
    effective = resolve_langfuse_config(candidate)
    if not effective.configured:
        return {"ok": False, "error": "missing_credentials"}
    if not _valid_base_url(effective.base_url):
        return {"ok": False, "error": "invalid_url"}
    url = effective.base_url.rstrip("/") + "/api/public/projects"
    try:
        async with asyncio.timeout(10):
            safe, error = await asyncio.to_thread(validate_url_target, url)
            if not safe:
                return {"ok": False, "error": "blocked_url" if error.startswith("Blocked") else "unreachable"}
            async with httpx.AsyncClient(
                transport=PinnedDNSAsyncTransport(),
                mounts=httpx_env_proxy_mounts(),
                trust_env=False,
                follow_redirects=False,
                timeout=10,
            ) as client:
                # Do not initialize the SDK: its singleton/exporter belongs to the running agent.
                async with client.stream("GET", url, auth=httpx.BasicAuth(
                    effective.public_key, effective.secret_key,
                )) as response:
                    if response.status_code in {401, 403}:
                        return {"ok": False, "error": "invalid_credentials"}
                    if response.status_code != 200:
                        return {"ok": False, "error": "unreachable"}
                    body = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=16_384):
                        body.extend(chunk)
                        if len(body) > 65_536:
                            return {"ok": False, "error": "unreachable"}
                    # Verify the public API shape instead of accepting a proxy/login page's HTTP 200.
                    result: object = json.loads(body)
    except (TimeoutError, httpx.TimeoutException):
        return {"ok": False, "error": "timeout"}
    except UnsafeURLRequestError:
        return {"ok": False, "error": "blocked_url"}
    except (httpx.HTTPError, ValueError):
        return {"ok": False, "error": "unreachable"}
    if isinstance(result, dict):
        projects = cast(dict[str, object], result).get("data")
        if isinstance(projects, list) and any(
            isinstance(item, dict) and isinstance(cast(dict[str, object], item).get("id"), str)
            for item in cast(list[object], projects)
        ):
            return {"ok": True}
    return {"ok": False, "error": "unreachable"}
