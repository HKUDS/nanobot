"""Settings REST helpers for the WebUI HTTP surface.

The WebSocket channel owns transport/authentication. This module owns the
settings payload shape and the allowlisted config mutations exposed to WebUI.
"""

from __future__ import annotations

import os
import re
import time
from contextlib import suppress
from typing import Any, Literal
from zoneinfo import ZoneInfo

import httpx

from blackcat.audio.transcription import resolve_transcription_config
from blackcat.config.loader import get_config_path, load_config, save_config
from blackcat.config.schema import ModelPresetConfig
from blackcat.providers.image_generation import (
    get_image_gen_provider,
    image_gen_provider_names,
)
from blackcat.providers.registry import PROVIDERS, find_by_name
from blackcat.security.workspace_access import workspace_sandbox_status
from blackcat.webui.token_usage import token_usage_payload
from blackcat.webui.workspaces import (
    read_webui_default_access_mode,
    write_webui_default_access_mode,
)

QueryParams = dict[str, list[str]]
RuntimeSurface = Literal["browser", "native"]

_RUNTIME_CAPABILITIES = {
    "can_restart_engine": False,
    "can_pick_folder": False,
    "can_open_logs": False,
    "can_export_diagnostics": False,
}

_NATIVE_RUNTIME_CAPABILITIES = {
    **_RUNTIME_CAPABILITIES,
    "can_restart_engine": True,
    "can_pick_folder": True,
    "can_open_logs": True,
    "can_export_diagnostics": True,
}

_BROWSER_RESTART_BEHAVIOR_BY_SECTION = {
    "appearance": "none",
    "models": "none",
    "providers": "none",
    "runtime": "engineRestart",
    "browser": "engineRestart",
    "image": "engineRestart",
    "apps": "engineRestart",
    "advanced": "appRestart",
}

_NATIVE_RESTART_BEHAVIOR_BY_SECTION = {
    **_BROWSER_RESTART_BEHAVIOR_BY_SECTION,
    "runtime": "engineRestart",
    "browser": "engineRestart",
    "image": "engineRestart",
    "apps": "engineRestart",
}

_WEB_SEARCH_PROVIDER_OPTIONS: tuple[dict[str, str], ...] = (
    {"name": "duckduckgo", "label": "DuckDuckGo", "credential": "none"},
    {"name": "brave", "label": "Brave Search", "credential": "api_key"},
    {"name": "tavily", "label": "Tavily", "credential": "api_key"},
    {"name": "searxng", "label": "SearXNG", "credential": "base_url"},
    {"name": "jina", "label": "Jina", "credential": "api_key"},
    {"name": "kagi", "label": "Kagi", "credential": "api_key"},
    {"name": "olostep", "label": "Olostep", "credential": "api_key"},
    {"name": "volcengine", "label": "Volcengine Search", "credential": "api_key"},
)
_WEB_SEARCH_PROVIDER_BY_NAME = {
    provider["name"]: provider for provider in _WEB_SEARCH_PROVIDER_OPTIONS
}

_IMAGE_GENERATION_ASPECT_RATIOS = {
    "1:1",
    "3:4",
    "9:16",
    "4:3",
    "16:9",
    "3:2",
    "2:3",
    "21:9",
}
_TRANSCRIPTION_PROVIDERS = ("groq", "openai")
_CONTEXT_WINDOW_TOKEN_OPTIONS = {65_536, 262_144}
_MODEL_CONFIGURATION_SLUG_RE = re.compile(r"[^a-z0-9_-]+")
_ENV_REF_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

_MODEL_LIST_UNSUPPORTED_BACKENDS = {
    "anthropic",
    "azure_openai",
    "bedrock",
    "github_copilot",
    "openai_codex",
}

_MODEL_LIST_CATALOG_PROVIDERS = {
    "aihubmix",
    "byteplus",
    "byteplus_coding_plan",
    "huggingface",
    "novita",
    "openrouter",
    "siliconflow",
    "volcengine",
    "volcengine_coding_plan",
}

_MODEL_LIST_OFFICIAL_PROVIDERS = {
    "ant_ling",
    "dashscope",
    "deepseek",
    "gemini",
    "groq",
    "longcat",
    "minimax",
    "minimax_anthropic",
    "mistral",
    "moonshot",
    "nvidia",
    "openai",
    "qianfan",
    "skywork",
    "stepfun",
    "xiaomi_mimo",
    "zhipu",
}


class WebUISettingsError(ValueError):
    """User-facing settings validation failure."""

    def __init__(self, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def _normalize_surface(surface: str | None) -> RuntimeSurface:
    return "native" if surface in {"native", "desktop"} else "browser"


def runtime_capabilities(
    surface: str | None = "browser",
    overrides: dict[str, Any] | None = None,
) -> dict[str, bool]:
    """Return the capability flags exposed to the WebUI runtime."""
    base = (
        _NATIVE_RUNTIME_CAPABILITIES
        if _normalize_surface(surface) == "native"
        else _RUNTIME_CAPABILITIES
    )
    result = dict(base)
    for key, value in (overrides or {}).items():
        if key in result:
            result[key] = bool(value)
    return result


def restart_behavior_by_section(surface: str | None = "browser") -> dict[str, str]:
    return dict(
        _NATIVE_RESTART_BEHAVIOR_BY_SECTION
        if _normalize_surface(surface) == "native"
        else _BROWSER_RESTART_BEHAVIOR_BY_SECTION
    )


def decorate_settings_payload(
    payload: dict[str, Any],
    *,
    surface: str | None = "browser",
    runtime_capability_overrides: dict[str, Any] | None = None,
    restart_required_sections: list[str] | None = None,
    apply_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach runtime-surface metadata without changing the core settings shape."""
    surface_value = _normalize_surface(surface)
    sections = restart_required_sections
    if sections is None:
        raw_sections = payload.get("restart_required_sections") or []
        sections = [str(section) for section in raw_sections if isinstance(section, str)]
    sections = sorted(dict.fromkeys(sections))
    result = dict(payload)
    result["surface"] = surface_value
    result["runtime_surface"] = surface_value
    result["runtime_capabilities"] = runtime_capabilities(
        surface_value,
        runtime_capability_overrides,
    )
    result["restart_behavior_by_section"] = restart_behavior_by_section(surface_value)
    result["restart_required_sections"] = sections
    if sections:
        result["requires_restart"] = True
    else:
        result["requires_restart"] = bool(result.get("requires_restart", False))
    result["apply_state"] = apply_state or {
        "status": "pending" if result["requires_restart"] else "idle",
        "sections": sections,
    }
    return result


def _query_first(query: QueryParams, key: str) -> str | None:
    values = query.get(key)
    return values[0] if values else None


def _query_first_alias(query: QueryParams, snake: str, camel: str) -> str | None:
    value = _query_first(query, snake)
    return _query_first(query, camel) if value is None else value


def _mask_secret_hint(secret: str | None) -> str | None:
    if not secret:
        return None
    if len(secret) <= 8:
        return "••••"
    return f"{secret[:4]}••••{secret[-4:]}"


def _resolve_env_placeholders(value: str | None) -> str | None:
    if not value:
        return None
    missing = False

    def replace(match: re.Match[str]) -> str:
        nonlocal missing
        env_value = os.environ.get(match.group(1))
        if env_value is None:
            missing = True
            return ""
        return env_value

    resolved = _ENV_REF_RE.sub(replace, value).strip()
    if missing and not resolved:
        return None
    return resolved or None


def _provider_requires_api_key(spec: Any) -> bool:
    if spec.name == "azure_openai":
        return False
    if spec.is_oauth:
        return False
    if spec.is_local or spec.is_direct:
        return False
    return True


def _oauth_provider_status(spec: Any) -> dict[str, Any]:
    if not getattr(spec, "is_oauth", False):
        return {"configured": False, "account": None, "expires_at": None, "login_supported": False}

    if spec.name == "openai_codex":
        try:
            from oauth_cli_kit import get_token as get_codex_token
        except Exception:
            return {
                "configured": False,
                "account": None,
                "expires_at": None,
                "login_supported": False,
            }
        token = None
        with suppress(Exception):
            token = get_codex_token()
        expires_at = getattr(token, "expires", None) if token else None
        return {
            "configured": bool(token and token.access),
            "account": getattr(token, "account_id", None) if token else None,
            "expires_at": expires_at,
            "login_supported": True,
        }

    if spec.name == "github_copilot":
        try:
            from blackcat.providers.github_copilot_provider import get_github_copilot_login_status
        except Exception:
            return {
                "configured": False,
                "account": None,
                "expires_at": None,
                "login_supported": False,
            }
        token = None
        with suppress(Exception):
            token = get_github_copilot_login_status()
        return {
            "configured": bool(token and token.access and token.expires > int(time.time() * 1000)),
            "account": getattr(token, "account_id", None) if token else None,
            "expires_at": getattr(token, "expires", None) if token else None,
            "login_supported": True,
        }

    return {"configured": False, "account": None, "expires_at": None, "login_supported": False}


def _provider_configured_for_settings(spec: Any, provider_config: Any) -> bool:
    if spec.is_oauth:
        return bool(_oauth_provider_status(spec)["configured"])
    if spec.name == "azure_openai":
        return bool(provider_config.api_base)
    if _provider_requires_api_key(spec):
        return bool(provider_config.api_key)
    return bool(
        provider_config.api_key
        or provider_config.api_base
        or getattr(provider_config, "region", None)
        or getattr(provider_config, "profile", None)
    )


def _model_catalog_kind(spec: Any) -> str:
    if spec.name in _MODEL_LIST_CATALOG_PROVIDERS:
        return "catalog"
    if spec.name in _MODEL_LIST_OFFICIAL_PROVIDERS:
        return "official"
    if spec.is_local:
        return "local"
    if spec.is_direct:
        return "custom"
    if spec.is_gateway:
        return "catalog"
    return "official"


def _model_id_from_row(row: Any) -> str | None:
    if isinstance(row, str):
        return row.strip() or None
    if not isinstance(row, dict):
        return None
    for key in ("id", "name", "model"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _model_context_window(row: Any) -> int | None:
    if not isinstance(row, dict):
        return None
    for key in (
        "context_window",
        "context_length",
        "max_context_length",
        "max_model_len",
        "max_input_tokens",
    ):
        value = row.get(key)
        if isinstance(value, int) and value > 0:
            return value
        if isinstance(value, float) and value > 0:
            return int(value)
    return None


def _model_row_payload(row: Any) -> dict[str, Any] | None:
    model_id = _model_id_from_row(row)
    if not model_id:
        return None
    label: str | None = None
    owned_by: str | None = None
    if isinstance(row, dict):
        raw_label = row.get("display_name") or row.get("label") or row.get("name")
        if isinstance(raw_label, str) and raw_label.strip() and raw_label.strip() != model_id:
            label = raw_label.strip()
        raw_owner = row.get("owned_by") or row.get("owner") or row.get("organization")
        if isinstance(raw_owner, str) and raw_owner.strip():
            owned_by = raw_owner.strip()
    return {
        "id": model_id,
        "label": label,
        "owned_by": owned_by,
        "context_window": _model_context_window(row),
    }


def _extract_model_rows(body: Any) -> list[dict[str, Any]]:
    raw_rows = body.get("data") if isinstance(body, dict) else body
    if not isinstance(raw_rows, list):
        return []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_row in raw_rows:
        row = _model_row_payload(raw_row)
        if row is None or row["id"] in seen:
            continue
        seen.add(row["id"])
        rows.append(row)
    return rows


def provider_models_payload(query: QueryParams) -> dict[str, Any]:
    """Fetch an OpenAI-compatible provider's model list for Settings.

    The result is advisory only: users can always type a custom model id. This
    helper deliberately avoids mutating config so probing model lists never
    changes runtime behavior.
    """
    provider_name = (_query_first(query, "provider") or "").strip()
    if not provider_name:
        raise WebUISettingsError("provider is required")
    spec = find_by_name(provider_name)
    if spec is None:
        raise WebUISettingsError("unknown provider")

    base_payload: dict[str, Any] = {
        "provider": spec.name,
        "label": spec.label,
        "catalog_kind": _model_catalog_kind(spec),
        "models": [],
        "model_count": 0,
        "message": None,
        "fetched_at": time.time(),
    }
    if (
        spec.backend in _MODEL_LIST_UNSUPPORTED_BACKENDS
        and spec.name != "minimax_anthropic"
    ) or spec.is_oauth:
        return {
            **base_payload,
            "status": "unsupported",
            "catalog_kind": "unsupported",
            "message": "Model list is not available for this provider. Type a model ID manually.",
        }

    config = load_config()
    provider_config = getattr(config.providers, spec.name, None)
    if provider_config is None:
        raise WebUISettingsError("unknown provider")

    api_base = _resolve_env_placeholders(provider_config.api_base) or spec.default_api_base
    if spec.name == "openai" and not api_base:
        api_base = "https://api.openai.com/v1"
    if not api_base:
        return {
            **base_payload,
            "status": "missing_api_base",
            "message": "Configure an API base URL to load models.",
        }

    api_key = _resolve_env_placeholders(provider_config.api_key)
    if _provider_requires_api_key(spec) and not api_key:
        return {
            **base_payload,
            "status": "not_configured",
            "message": "Configure this provider before loading models.",
        }

    headers = {"Accept": "application/json"}
    if api_key:
        if spec.name == "minimax_anthropic":
            headers["X-Api-Key"] = api_key
        else:
            headers["Authorization"] = f"Bearer {api_key}"

    models_url = f"{api_base.rstrip('/')}/models"
    if spec.name == "minimax_anthropic" and not api_base.rstrip("/").endswith("/v1"):
        models_url = f"{api_base.rstrip('/')}/v1/models"

    try:
        response = httpx.get(
            models_url,
            headers=headers,
            timeout=10.0,
            follow_redirects=False,
        )
        response.raise_for_status()
        rows = _extract_model_rows(response.json())
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status in {401, 403}:
            return {
                **base_payload,
                "status": "not_configured",
                "message": "The provider rejected the configured credential.",
            }
        return {
            **base_payload,
            "status": "error",
            "message": f"Model list request failed with HTTP {status}.",
        }
    except (httpx.HTTPError, ValueError) as exc:
        return {
            **base_payload,
            "status": "error",
            "message": f"Could not load models: {exc}",
        }

    return {
        **base_payload,
        "status": "available",
        "models": rows,
        "model_count": len(rows),
    }


def _parse_bool(value: str, field: str) -> bool:
    normalized = value.strip().lower()
    if normalized not in {"1", "0", "true", "false", "yes", "no"}:
        raise WebUISettingsError(f"{field} must be boolean")
    return normalized in {"1", "true", "yes"}


def _parse_context_window_tokens(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except ValueError:
        raise WebUISettingsError("context_window_tokens must be an integer") from None
    if parsed not in _CONTEXT_WINDOW_TOKEN_OPTIONS:
        raise WebUISettingsError("context_window_tokens must be 65536 or 262144")
    return parsed


def _model_configuration_slug(label: str) -> str:
    normalized = _MODEL_CONFIGURATION_SLUG_RE.sub("-", label.strip().lower())
    normalized = normalized.strip("-_")
    if not normalized:
        raise WebUISettingsError("configuration name is required")
    if normalized == "default":
        raise WebUISettingsError("configuration name is reserved")
    if len(normalized) > 48:
        normalized = normalized[:48].rstrip("-_")
    return normalized


def _validate_configured_provider(config: Any, provider: str) -> None:
    if provider == "auto":
        return
    spec = find_by_name(provider)
    if spec is None:
        raise WebUISettingsError("unknown provider")
    provider_config = getattr(config.providers, provider, None)
    if (
        provider_config is None
        or not _provider_configured_for_settings(spec, provider_config)
    ):
        raise WebUISettingsError("provider is not configured")


def _image_generation_provider_rows(config: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name in image_gen_provider_names():
        spec = find_by_name(name)
        provider_config = getattr(config.providers, name, None)
        configured = (
            _provider_configured_for_settings(spec, provider_config)
            if spec is not None and provider_config is not None
            else bool(getattr(provider_config, "api_key", None))
        )
        rows.append(
            {
                "name": name,
                "label": spec.label if spec is not None else name,
                "configured": configured,
                "auth_type": "oauth" if spec is not None and spec.is_oauth else "api_key",
                "api_key_hint": _mask_secret_hint(
                    getattr(provider_config, "api_key", None)
                ),
                "api_base": getattr(provider_config, "api_base", None),
                "default_api_base": (
                    spec.default_api_base if spec and spec.default_api_base else None
                ),
            }
        )
    return rows


def _transcription_provider_rows(config: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name in _TRANSCRIPTION_PROVIDERS:
        spec = find_by_name(name)
        provider_config = getattr(config.providers, name, None)
        rows.append({
            "name": name,
            "label": spec.label if spec is not None else name,
            "configured": bool(getattr(provider_config, "api_key", None)),
            "api_key_hint": _mask_secret_hint(getattr(provider_config, "api_key", None)),
            "api_base": getattr(provider_config, "api_base", None),
            "default_api_base": spec.default_api_base if spec and spec.default_api_base else None,
        })
    return rows


def settings_payload(
    *,
    requires_restart: bool = False,
    surface: str | None = "browser",
    runtime_capability_overrides: dict[str, Any] | None = None,
    restart_required_sections: list[str] | None = None,
    apply_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config = load_config()
    defaults = config.agents.defaults
    active_preset_name = defaults.model_preset or "default"
    try:
        effective_preset = config.resolve_preset()
    except Exception:
        effective_preset = config.resolve_default_preset()
        active_preset_name = "default"

    provider_name = (
        config.get_provider_name(effective_preset.model, preset=effective_preset)
        or effective_preset.provider
    )
    provider = config.get_provider(effective_preset.model, preset=effective_preset)
    selected_provider = provider_name
    if effective_preset.provider != "auto":
        spec = find_by_name(effective_preset.provider)
        selected_provider = spec.name if spec else provider_name

    providers = []
    for spec in PROVIDERS:
        provider_config = getattr(config.providers, spec.name, None)
        if provider_config is None:
            continue
        oauth_status = _oauth_provider_status(spec) if spec.is_oauth else None
        row = {
            "name": spec.name,
            "label": spec.label,
            "configured": (
                bool(oauth_status["configured"])
                if oauth_status is not None
                else _provider_configured_for_settings(spec, provider_config)
            ),
            "auth_type": "oauth" if spec.is_oauth else "api_key",
            "api_key_required": _provider_requires_api_key(spec),
            "api_key_hint": _mask_secret_hint(provider_config.api_key),
            "api_base": provider_config.api_base,
            "default_api_base": spec.default_api_base or None,
        }
        if oauth_status is not None:
            row["oauth_account"] = oauth_status["account"]
            row["oauth_expires_at"] = oauth_status["expires_at"]
            row["oauth_login_supported"] = oauth_status["login_supported"]
        if spec.name == "openai":
            row["api_type"] = provider_config.api_type
        providers.append(row)

    search_config = config.tools.web.search
    image_config = config.tools.image_generation
    transcription = resolve_transcription_config(config)
    search_provider = (
        search_config.provider
        if search_config.provider in _WEB_SEARCH_PROVIDER_BY_NAME
        else "duckduckgo"
    )
    image_providers = _image_generation_provider_rows(config)
    selected_image_provider = next(
        (
            provider
            for provider in image_providers
            if provider["name"] == image_config.provider
        ),
        None,
    )
    model_presets = [
        {
            "name": "default",
            "label": "Default",
            "active": active_preset_name == "default",
            "is_default": True,
            "model": defaults.model,
            "provider": defaults.provider,
            "max_tokens": defaults.max_tokens,
            "context_window_tokens": defaults.context_window_tokens,
            "temperature": defaults.temperature,
            "reasoning_effort": defaults.reasoning_effort,
        }
    ]
    for name, preset in config.model_presets.items():
        model_presets.append(
            {
                "name": name,
                "label": preset.label or name,
                "active": active_preset_name == name,
                "is_default": False,
                "model": preset.model,
                "provider": preset.provider,
                "max_tokens": preset.max_tokens,
                "context_window_tokens": preset.context_window_tokens,
                "temperature": preset.temperature,
                "reasoning_effort": preset.reasoning_effort,
            }
        )

    exec_config = config.tools.exec
    sandbox_status = workspace_sandbox_status(
        restrict_to_workspace=config.tools.restrict_to_workspace,
        workspace=config.workspace_path,
    )
    payload = {
        "agent": {
            "model": effective_preset.model,
            "provider": selected_provider,
            "resolved_provider": provider_name,
            "has_api_key": bool(provider and provider.api_key),
            "model_preset": active_preset_name,
            "max_tokens": effective_preset.max_tokens,
            "context_window_tokens": effective_preset.context_window_tokens,
            "temperature": effective_preset.temperature,
            "reasoning_effort": effective_preset.reasoning_effort,
            "timezone": defaults.timezone,
            "bot_name": defaults.bot_name,
            "bot_icon": defaults.bot_icon,
            "tool_hint_max_length": defaults.tool_hint_max_length,
        },
        "model_presets": model_presets,
        "providers": providers,
        "web_search": {
            "provider": search_provider,
            "api_key_hint": _mask_secret_hint(search_config.api_key),
            "base_url": search_config.base_url or None,
            "max_results": search_config.max_results,
            "timeout": search_config.timeout,
            "providers": list(_WEB_SEARCH_PROVIDER_OPTIONS),
        },
        "web": {
            "enable": config.tools.web.enable,
            "proxy": config.tools.web.proxy,
            "user_agent": config.tools.web.user_agent,
            "search": {
                "max_results": search_config.max_results,
                "timeout": search_config.timeout,
            },
            "fetch": {
                "use_jina_reader": config.tools.web.fetch.use_jina_reader,
            },
        },
        "image_generation": {
            "enabled": image_config.enabled,
            "provider": image_config.provider,
            "provider_configured": bool(
                selected_image_provider and selected_image_provider["configured"]
            ),
            "model": image_config.model,
            "default_aspect_ratio": image_config.default_aspect_ratio,
            "default_image_size": image_config.default_image_size,
            "max_images_per_turn": image_config.max_images_per_turn,
            "save_dir": image_config.save_dir,
            "providers": image_providers,
        },
        "transcription": {
            "enabled": transcription.enabled,
            "provider": transcription.provider,
            "provider_configured": transcription.configured,
            "model": transcription.model,
            "language": transcription.language,
            "max_duration_sec": transcription.max_duration_sec,
            "max_upload_mb": transcription.max_upload_mb,
            "providers": _transcription_provider_rows(config),
        },
        "runtime": {
            "config_path": str(get_config_path().expanduser()),
            "workspace_path": str(config.workspace_path),
            "gateway_host": config.gateway.host,
            "gateway_port": config.gateway.port,
            "heartbeat": {
                "enabled": config.gateway.heartbeat.enabled,
                "interval_s": config.gateway.heartbeat.interval_s,
                "keep_recent_messages": config.gateway.heartbeat.keep_recent_messages,
            },
            "dream": {
                "schedule": defaults.dream.describe_schedule(),
            },
            "unified_session": defaults.unified_session,
        },
        "usage": token_usage_payload(timezone_name=defaults.timezone),
        "advanced": {
            "restrict_to_workspace": config.tools.restrict_to_workspace,
            "workspace_sandbox": sandbox_status.as_dict(),
            "webui_allow_local_service_access": config.tools.webui_allow_local_service_access,
            "allow_local_preview_access": config.tools.webui_allow_local_service_access,
            "webui_default_access_mode": read_webui_default_access_mode(),
            "private_service_protection_enabled": True,
            "ssrf_whitelist_count": len(config.tools.ssrf_whitelist),
            "mcp_server_count": len(config.tools.mcp_servers),
            "exec_enabled": exec_config.enable,
            "exec_sandbox": exec_config.sandbox or None,
            "exec_path_append_set": bool(exec_config.path_append),
        },
        "requires_restart": requires_restart,
    }
    return decorate_settings_payload(
        payload,
        surface=surface,
        runtime_capability_overrides=runtime_capability_overrides,
        restart_required_sections=restart_required_sections,
        apply_state=apply_state,
    )


def settings_usage_payload() -> dict[str, Any]:
    """Return the lightweight token usage slice for Overview refreshes."""
    config = load_config()
    return token_usage_payload(timezone_name=config.agents.defaults.timezone)


def update_agent_settings(query: QueryParams) -> dict[str, Any]:
    config = load_config()
    defaults = config.agents.defaults
    changed = False
    restart_required = False

    if "model_preset" in query or "modelPreset" in query:
        preset = (_query_first_alias(query, "model_preset", "modelPreset") or "").strip()
        preset_value = None if not preset or preset == "default" else preset
        if preset_value is not None and preset_value not in config.model_presets:
            raise WebUISettingsError("unknown model preset")
        if defaults.model_preset != preset_value:
            defaults.model_preset = preset_value
            changed = True

    model = _query_first(query, "model")
    if model is not None:
        model = model.strip()
        if not model:
            raise WebUISettingsError("model is required")
        if defaults.model != model:
            defaults.model = model
            changed = True

    provider = _query_first(query, "provider")
    if provider is not None:
        provider = provider.strip()
        if not provider:
            raise WebUISettingsError("provider is required")
        _validate_configured_provider(config, provider)
        if defaults.provider != provider:
            defaults.provider = provider
            changed = True

    context_window_tokens = _parse_context_window_tokens(
        _query_first_alias(query, "context_window_tokens", "contextWindowTokens")
    )
    if (
        context_window_tokens is not None
        and defaults.context_window_tokens != context_window_tokens
    ):
        defaults.context_window_tokens = context_window_tokens
        changed = True

    timezone = _query_first(query, "timezone")
    if timezone is not None:
        timezone = timezone.strip()
        if not timezone:
            raise WebUISettingsError("timezone is required")
        try:
            ZoneInfo(timezone)
        except Exception:
            raise WebUISettingsError("invalid timezone") from None
        if defaults.timezone != timezone:
            defaults.timezone = timezone
            changed = True
            restart_required = True

    bot_name = _query_first_alias(query, "bot_name", "botName")
    if bot_name is not None:
        bot_name = bot_name.strip()
        if not bot_name:
            raise WebUISettingsError("bot_name is required")
        if defaults.bot_name != bot_name:
            defaults.bot_name = bot_name
            changed = True
            restart_required = True

    bot_icon = _query_first_alias(query, "bot_icon", "botIcon")
    if bot_icon is not None:
        bot_icon = bot_icon.strip()
        if defaults.bot_icon != bot_icon:
            defaults.bot_icon = bot_icon
            changed = True
            restart_required = True

    tool_hint_max_length = _query_first_alias(
        query,
        "tool_hint_max_length",
        "toolHintMaxLength",
    )
    if tool_hint_max_length is not None:
        try:
            parsed = int(tool_hint_max_length)
        except ValueError:
            raise WebUISettingsError("tool_hint_max_length must be an integer") from None
        if parsed < 20 or parsed > 500:
            raise WebUISettingsError("tool_hint_max_length must be between 20 and 500")
        if defaults.tool_hint_max_length != parsed:
            defaults.tool_hint_max_length = parsed
            changed = True
            restart_required = True

    if changed:
        save_config(config)
    return settings_payload(requires_restart=restart_required)


def create_model_configuration(query: QueryParams) -> dict[str, Any]:
    label = (_query_first_alias(query, "label", "displayName") or "").strip()
    raw_name = (_query_first(query, "name") or label).strip()
    model = (_query_first(query, "model") or "").strip()
    provider = (_query_first(query, "provider") or "").strip()

    if not label:
        label = raw_name
    if not model:
        raise WebUISettingsError("model is required")
    if not provider:
        raise WebUISettingsError("provider is required")

    name = _model_configuration_slug(raw_name or label)
    config = load_config()
    if name in config.model_presets:
        raise WebUISettingsError("configuration already exists", status=409)
    _validate_configured_provider(config, provider)

    base = config.resolve_default_preset()
    config.model_presets[name] = ModelPresetConfig(
        label=label,
        model=model,
        provider=provider,
        max_tokens=base.max_tokens,
        context_window_tokens=base.context_window_tokens,
        temperature=base.temperature,
        reasoning_effort=base.reasoning_effort,
    )
    config.agents.defaults.model_preset = name
    save_config(config)
    return settings_payload()


def update_model_configuration(query: QueryParams) -> dict[str, Any]:
    name = (_query_first(query, "name") or "").strip()
    if not name or name == "default":
        raise WebUISettingsError("model configuration is required")

    config = load_config()
    preset = config.model_presets.get(name)
    if preset is None:
        raise WebUISettingsError("unknown model configuration")

    changed = False
    label = _query_first_alias(query, "label", "displayName")
    if label is not None:
        label = label.strip()
        if not label:
            raise WebUISettingsError("label is required")
        if preset.label != label:
            preset.label = label
            changed = True

    model = _query_first(query, "model")
    if model is not None:
        model = model.strip()
        if not model:
            raise WebUISettingsError("model is required")
        if preset.model != model:
            preset.model = model
            changed = True

    provider = _query_first(query, "provider")
    if provider is not None:
        provider = provider.strip()
        if not provider:
            raise WebUISettingsError("provider is required")
        _validate_configured_provider(config, provider)
        if preset.provider != provider:
            preset.provider = provider
            changed = True

    context_window_tokens = _parse_context_window_tokens(
        _query_first_alias(query, "context_window_tokens", "contextWindowTokens")
    )
    if (
        context_window_tokens is not None
        and preset.context_window_tokens != context_window_tokens
    ):
        preset.context_window_tokens = context_window_tokens
        changed = True

    if config.agents.defaults.model_preset != name:
        config.agents.defaults.model_preset = name
        changed = True

    if changed:
        save_config(config)
    return settings_payload()


def update_provider_settings(query: QueryParams) -> dict[str, Any]:
    provider_name = (_query_first(query, "provider") or "").strip()
    if not provider_name:
        raise WebUISettingsError("provider is required")
    spec = find_by_name(provider_name)
    if spec is None or spec.is_oauth:
        raise WebUISettingsError("unknown provider")

    config = load_config()
    provider_config = getattr(config.providers, spec.name, None)
    if provider_config is None:
        raise WebUISettingsError("unknown provider")

    changed = False
    if "api_key" in query or "apiKey" in query:
        api_key = _query_first_alias(query, "api_key", "apiKey")
        api_key = (api_key or "").strip() or None
        if provider_config.api_key != api_key:
            provider_config.api_key = api_key
            changed = True

    if "api_base" in query or "apiBase" in query:
        api_base = _query_first_alias(query, "api_base", "apiBase")
        api_base = (api_base or "").strip() or None
        if provider_config.api_base != api_base:
            provider_config.api_base = api_base
            changed = True

    if "api_type" in query:
        if spec.name == "openai":
            api_type = (_query_first(query, "api_type") or "").strip()
            try:
                parsed_api_type = type(provider_config)(api_type=api_type).api_type
            except Exception:
                raise WebUISettingsError("api_type must be auto, chat_completions, or responses") from None
            if provider_config.api_type != parsed_api_type:
                provider_config.api_type = parsed_api_type
                changed = True

    if changed:
        save_config(config)
    image_config = config.tools.image_generation
    restart_required = (
        changed
        and image_config.enabled
        and image_config.provider == spec.name
        and get_image_gen_provider(spec.name) is not None
    )
    return settings_payload(requires_restart=restart_required)


def login_oauth_provider(query: QueryParams) -> dict[str, Any]:
    provider_name = (_query_first(query, "provider") or "").strip()
    if not provider_name:
        raise WebUISettingsError("provider is required")
    spec = find_by_name(provider_name)
    if spec is None or not spec.is_oauth:
        raise WebUISettingsError("unknown OAuth provider")

    if spec.name == "openai_codex":
        try:
            from oauth_cli_kit import get_token, login_oauth_interactive
        except ImportError:
            raise WebUISettingsError("oauth_cli_kit is not installed", status=500) from None

        token = None
        with suppress(Exception):
            token = get_token()
        if not (token and token.access):
            messages: list[str] = []
            token = login_oauth_interactive(
                print_fn=lambda message: messages.append(str(message)),
                prompt_fn=lambda _prompt: "",
            )
        if not (token and token.access):
            raise WebUISettingsError("OAuth login failed", status=401)
        return settings_payload()

    if spec.name == "github_copilot":
        try:
            from blackcat.providers.github_copilot_provider import (
                get_github_copilot_login_status,
                login_github_copilot,
            )
        except ImportError:
            raise WebUISettingsError("GitHub Copilot OAuth support is unavailable", status=500) from None

        token = get_github_copilot_login_status()
        if not token:
            token = login_github_copilot(print_fn=lambda _message: None)
        if not (token and token.access):
            raise WebUISettingsError("OAuth login failed", status=401)
        return settings_payload()

    raise WebUISettingsError("OAuth login is not supported for this provider")


def logout_oauth_provider(query: QueryParams) -> dict[str, Any]:
    provider_name = (_query_first(query, "provider") or "").strip()
    if not provider_name:
        raise WebUISettingsError("provider is required")
    spec = find_by_name(provider_name)
    if spec is None or not spec.is_oauth:
        raise WebUISettingsError("unknown OAuth provider")

    if spec.name == "openai_codex":
        try:
            from oauth_cli_kit.providers import OPENAI_CODEX_PROVIDER
            from oauth_cli_kit.storage import FileTokenStorage
        except ImportError:
            raise WebUISettingsError("oauth_cli_kit is not installed", status=500) from None
        token_path = FileTokenStorage(token_filename=OPENAI_CODEX_PROVIDER.token_filename).get_token_path()
    elif spec.name == "github_copilot":
        try:
            from blackcat.providers.github_copilot_provider import get_storage
        except ImportError:
            raise WebUISettingsError("GitHub Copilot OAuth support is unavailable", status=500) from None
        token_path = get_storage().get_token_path()
    else:
        raise WebUISettingsError("OAuth logout is not supported for this provider")

    for path in (token_path, token_path.with_suffix(".lock")):
        with suppress(FileNotFoundError):
            path.unlink()
    return settings_payload()


def update_network_safety_settings(query: QueryParams) -> dict[str, Any]:
    raw_allow = (
        _query_first_alias(query, "webui_allow_local_service_access", "webuiAllowLocalServiceAccess")
        or _query_first_alias(query, "allow_local_preview_access", "allowLocalPreviewAccess")
    )
    raw_default_access_mode = _query_first_alias(query, "webui_default_access_mode", "webuiDefaultAccessMode")
    if raw_allow is None and raw_default_access_mode is None:
        raise WebUISettingsError("webui_allow_local_service_access or webui_default_access_mode is required")

    config = load_config()
    changed = False
    if raw_allow is not None:
        webui_allow_local_service_access = _parse_bool(raw_allow, "webui_allow_local_service_access")
        if config.tools.webui_allow_local_service_access != webui_allow_local_service_access:
            config.tools.webui_allow_local_service_access = webui_allow_local_service_access
            changed = True

    if changed:
        save_config(config)
    if raw_default_access_mode is not None:
        default_access_mode = raw_default_access_mode.strip().lower()
        if default_access_mode == "restricted":
            default_access_mode = "default"
        if default_access_mode not in {"default", "full"}:
            raise WebUISettingsError("webui_default_access_mode must be default or full")
        try:
            write_webui_default_access_mode(default_access_mode)
        except ValueError as exc:
            raise WebUISettingsError(str(exc)) from exc
    return settings_payload(requires_restart=changed)


def update_web_search_settings(query: QueryParams) -> dict[str, Any]:
    provider_name = (_query_first(query, "provider") or "").strip().lower()
    provider_option = _WEB_SEARCH_PROVIDER_BY_NAME.get(provider_name)
    if provider_option is None:
        raise WebUISettingsError("unknown web search provider")

    config = load_config()
    search_config = config.tools.web.search
    web_config = config.tools.web
    previous_provider = search_config.provider
    changed = False
    restart_required = False

    def set_search_value(attr: str, value: object) -> None:
        nonlocal changed
        if getattr(search_config, attr) != value:
            setattr(search_config, attr, value)
            changed = True

    def set_fetch_value(attr: str, value: object) -> None:
        nonlocal changed
        if getattr(web_config.fetch, attr) != value:
            setattr(web_config.fetch, attr, value)
            changed = True

    if search_config.provider != provider_name:
        search_config.provider = provider_name
        changed = True

    credential = provider_option["credential"]
    if credential == "none":
        set_search_value("api_key", "")
        set_search_value("base_url", "")
    elif credential == "base_url":
        base_url = _query_first_alias(query, "base_url", "baseUrl")
        base_url = base_url.strip() if base_url is not None else None
        if not base_url and previous_provider == provider_name and search_config.base_url:
            base_url = search_config.base_url
        if not base_url:
            raise WebUISettingsError("base_url is required")
        set_search_value("base_url", base_url)
        set_search_value("api_key", "")
    else:
        api_key = _query_first_alias(query, "api_key", "apiKey")
        api_key = api_key.strip() if api_key is not None else None
        if not api_key and previous_provider == provider_name and search_config.api_key:
            api_key = search_config.api_key
        if not api_key:
            raise WebUISettingsError("api_key is required")
        set_search_value("api_key", api_key)
        set_search_value("base_url", "")

    max_results = _query_first_alias(query, "max_results", "maxResults")
    if max_results is not None:
        try:
            parsed = int(max_results)
        except ValueError:
            raise WebUISettingsError("max_results must be an integer") from None
        if parsed < 1 or parsed > 10:
            raise WebUISettingsError("max_results must be between 1 and 10")
        set_search_value("max_results", parsed)

    timeout = _query_first(query, "timeout")
    if timeout is not None:
        try:
            parsed_timeout = int(timeout)
        except ValueError:
            raise WebUISettingsError("timeout must be an integer") from None
        if parsed_timeout < 1 or parsed_timeout > 120:
            raise WebUISettingsError("timeout must be between 1 and 120")
        set_search_value("timeout", parsed_timeout)

    use_jina_reader = _query_first_alias(query, "use_jina_reader", "useJinaReader")
    if use_jina_reader is not None:
        normalized = use_jina_reader.strip().lower()
        if normalized not in {"1", "0", "true", "false", "yes", "no"}:
            raise WebUISettingsError("use_jina_reader must be boolean")
        previous_jina_reader = web_config.fetch.use_jina_reader
        set_fetch_value("use_jina_reader", normalized in {"1", "true", "yes"})
        if web_config.fetch.use_jina_reader != previous_jina_reader:
            restart_required = True

    if changed:
        save_config(config)
    return settings_payload(requires_restart=restart_required)


def update_image_generation_settings(query: QueryParams) -> dict[str, Any]:
    config = load_config()
    image_config = config.tools.image_generation
    changed = False

    provider_name = _query_first(query, "provider")
    if provider_name is not None:
        provider_name = provider_name.strip().lower()
        if not provider_name:
            raise WebUISettingsError("image generation provider is required")
        if get_image_gen_provider(provider_name) is None:
            raise WebUISettingsError("unknown image generation provider")
        if image_config.provider != provider_name:
            image_config.provider = provider_name
            changed = True

    enabled = _query_first(query, "enabled")
    if enabled is not None:
        parsed_enabled = _parse_bool(enabled, "enabled")
        if image_config.enabled != parsed_enabled:
            image_config.enabled = parsed_enabled
            changed = True

    model = _query_first(query, "model")
    if model is not None:
        model = model.strip()
        if not model:
            raise WebUISettingsError("image generation model is required")
        if len(model) > 200:
            raise WebUISettingsError("image generation model is too long")
        if image_config.model != model:
            image_config.model = model
            changed = True

    default_aspect_ratio = _query_first_alias(
        query,
        "default_aspect_ratio",
        "defaultAspectRatio",
    )
    if default_aspect_ratio is not None:
        default_aspect_ratio = default_aspect_ratio.strip()
        if default_aspect_ratio not in _IMAGE_GENERATION_ASPECT_RATIOS:
            raise WebUISettingsError("unsupported image generation aspect ratio")
        if image_config.default_aspect_ratio != default_aspect_ratio:
            image_config.default_aspect_ratio = default_aspect_ratio
            changed = True

    default_image_size = _query_first_alias(
        query,
        "default_image_size",
        "defaultImageSize",
    )
    if default_image_size is not None:
        default_image_size = default_image_size.strip()
        if not default_image_size:
            raise WebUISettingsError("default image size is required")
        if len(default_image_size) > 32 or not all(
            char.isascii() and (char.isalnum() or char in {"x", "X", ":", "-", "_"})
            for char in default_image_size
        ):
            raise WebUISettingsError("unsupported image generation size")
        if image_config.default_image_size != default_image_size:
            image_config.default_image_size = default_image_size
            changed = True

    max_images_per_turn = _query_first_alias(
        query,
        "max_images_per_turn",
        "maxImagesPerTurn",
    )
    if max_images_per_turn is not None:
        try:
            parsed_max = int(max_images_per_turn)
        except ValueError:
            raise WebUISettingsError("max_images_per_turn must be an integer") from None
        if parsed_max < 1 or parsed_max > 8:
            raise WebUISettingsError("max_images_per_turn must be between 1 and 8")
        if image_config.max_images_per_turn != parsed_max:
            image_config.max_images_per_turn = parsed_max
            changed = True

    if image_config.enabled:
        selected_provider = next(
            (
                provider
                for provider in _image_generation_provider_rows(config)
                if provider["name"] == image_config.provider
            ),
            None,
        )
        if not selected_provider or not selected_provider["configured"]:
            raise WebUISettingsError("image generation provider is not configured")

    if changed:
        save_config(config)
    return settings_payload(requires_restart=changed)


def update_transcription_settings(query: QueryParams) -> dict[str, Any]:
    config = load_config()
    transcription = config.transcription
    changed = False

    enabled = _query_first(query, "enabled")
    if enabled is not None:
        parsed_enabled = _parse_bool(enabled, "enabled")
        if transcription.enabled != parsed_enabled:
            transcription.enabled = parsed_enabled
            changed = True

    provider = _query_first(query, "provider")
    if provider is not None:
        provider = provider.strip().lower()
        if provider not in _TRANSCRIPTION_PROVIDERS:
            raise WebUISettingsError("unknown transcription provider")
        if transcription.provider != provider:
            transcription.provider = provider  # type: ignore[assignment]
            changed = True

    model = _query_first(query, "model")
    if model is not None:
        model = model.strip() or None
        if model is not None and len(model) > 200:
            raise WebUISettingsError("transcription model is too long")
        if transcription.model != model:
            transcription.model = model
            changed = True

    language = _query_first(query, "language")
    if language is not None:
        language = language.strip().lower() or None
        if language is not None and not re.fullmatch(r"[a-z]{2,3}", language):
            raise WebUISettingsError("transcription language must be 2-3 lowercase letters")
        if transcription.language != language:
            transcription.language = language
            changed = True

    max_duration_sec = _query_first_alias(query, "max_duration_sec", "maxDurationSec")
    if max_duration_sec is not None:
        try:
            parsed_duration = int(max_duration_sec)
        except ValueError:
            raise WebUISettingsError("max_duration_sec must be an integer") from None
        if parsed_duration < 1 or parsed_duration > 600:
            raise WebUISettingsError("max_duration_sec must be between 1 and 600")
        if transcription.max_duration_sec != parsed_duration:
            transcription.max_duration_sec = parsed_duration
            changed = True

    max_upload_mb = _query_first_alias(query, "max_upload_mb", "maxUploadMb")
    if max_upload_mb is not None:
        try:
            parsed_upload = int(max_upload_mb)
        except ValueError:
            raise WebUISettingsError("max_upload_mb must be an integer") from None
        if parsed_upload < 1 or parsed_upload > 100:
            raise WebUISettingsError("max_upload_mb must be between 1 and 100")
        if transcription.max_upload_mb != parsed_upload:
            transcription.max_upload_mb = parsed_upload
            changed = True

    if changed:
        save_config(config)
    return settings_payload()
