"""Settings REST helpers for the WebUI HTTP surface.

The WebSocket channel owns transport/authentication. This module owns the
settings payload shape and the allowlisted config mutations exposed to WebUI.
"""

from __future__ import annotations

import json
import math
import os
import re
import secrets
import threading
import time
from contextlib import suppress
from typing import Any, Literal
from zoneinfo import ZoneInfo

import httpx

from nanobot import __version__
from nanobot.agent.tools.web import SEARCH_PROVIDER_OPTIONS
from nanobot.audio.transcription import resolve_transcription_config
from nanobot.audio.transcription_registry import (
    resolve_transcription_provider,
    transcription_provider_names,
)
from nanobot.config.loader import get_config_path, load_config, resolve_config_env_vars, save_config
from nanobot.config.schema import ModelPresetConfig, ProviderConfig
from nanobot.providers.image_generation import (
    get_image_gen_provider,
    image_gen_provider_names,
)
from nanobot.providers.registry import PROVIDERS, create_dynamic_spec, find_by_name
from nanobot.security.network import is_loopback_host
from nanobot.security.workspace_access import workspace_sandbox_status
from nanobot.webui.token_usage import token_usage_payload
from nanobot.webui.workspaces import (
    read_webui_default_access_mode,
    write_webui_default_access_mode,
)

QueryParams = dict[str, list[str]]
RuntimeSurface = Literal["browser", "native"]


def _version_payload() -> dict[str, Any]:
    """Return version info for the settings payload."""
    return {
        "current": __version__,
    }


_DOCS_STABLE_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:\.post\d+)?$")
_DOCS_LATEST_URL = "https://nanobot.wiki/docs/latest"


def _docs_version(version: str) -> str:
    """Map package versions to the matching public docs path."""
    normalized = version.strip()
    if _DOCS_STABLE_VERSION_RE.fullmatch(normalized):
        return normalized
    return "latest"


def _docs_payload() -> dict[str, Any]:
    """Return version-aware documentation links for the WebUI."""
    docs_version = _docs_version(__version__)
    base_url = f"https://nanobot.wiki/docs/{docs_version}"
    return {
        "version": docs_version,
        "base_url": base_url,
        "chat_apps_url": f"{base_url}/getting-started/chat-apps",
        "latest_url": _DOCS_LATEST_URL,
    }


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

_WEB_SEARCH_PROVIDER_OPTIONS = SEARCH_PROVIDER_OPTIONS
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
_CONTEXT_WINDOW_TOKEN_OPTIONS = {65_536, 200_000, 262_144, 500_000, 1_048_576}
_OAUTH_PROXY_PROVIDERS = {"openai_codex", "xai_grok"}
_XAI_WEBUI_OAUTH_TIMEOUT_S = 600
_XAI_WEBUI_OAUTH_MAX_FLOWS = 8
_xai_webui_oauth_flows: dict[str, Any] = {}
_xai_webui_oauth_flows_lock = threading.Lock()
_MODEL_CONFIGURATION_SLUG_RE = re.compile(r"[^a-z0-9_-]+")
_ENV_REF_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

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


def _query_has_alias(query: QueryParams, snake: str, camel: str) -> bool:
    return snake in query or camel in query


def _provider_json_setting(
    query: QueryParams,
    snake: str,
    camel: str,
) -> dict[str, Any] | None:
    raw = (_query_first_alias(query, snake, camel) or "").strip()
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise WebUISettingsError(f"{snake} must be a JSON object") from exc
    if not isinstance(value, dict):
        raise WebUISettingsError(f"{snake} must be a JSON object")
    return value or None


_REDACTED_PROVIDER_SECRET = "••••••••"
_PROVIDER_STRUCTURED_FIELDS = ("extra_headers", "extra_body", "extra_query")
_PROVIDER_SECRET_KEYS = frozenset({
    "auth",
    "authentication",
    "authorization",
    "bearer",
    "cookie",
    "credential",
    "credentials",
    "hmac",
    "key",
    "passphrase",
    "passwd",
    "proxyauthorization",
    "setcookie",
    "sig",
    "signature",
})
_PROVIDER_SECRET_KEY_SUFFIXES = (
    "accesskey",
    "apikey",
    "encryptionkey",
    "password",
    "privatekey",
    "secret",
    "secretkey",
    "signingkey",
    "subscriptionkey",
    "token",
)


def _provider_setting_key_is_secret(key: str) -> bool:
    compact = re.sub(r"[^a-z0-9]", "", key.lower())
    return compact in _PROVIDER_SECRET_KEYS or compact.endswith(_PROVIDER_SECRET_KEY_SUFFIXES)


def _redact_provider_secret_values(value: Any, *, secret: bool = False) -> Any:
    if secret and value not in (None, ""):
        return _REDACTED_PROVIDER_SECRET
    if isinstance(value, dict):
        return {
            key: _redact_provider_secret_values(
                item,
                secret=_provider_setting_key_is_secret(key),
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_provider_secret_values(item) for item in value]
    return value


def _restore_redacted_provider_secret_values(
    submitted: Any,
    current: Any,
    *,
    secret: bool = False,
) -> Any:
    if secret and submitted == _REDACTED_PROVIDER_SECRET:
        return current
    if isinstance(submitted, dict):
        current_mapping = current if isinstance(current, dict) else {}
        return {
            key: _restore_redacted_provider_secret_values(
                item,
                current_mapping.get(key),
                secret=_provider_setting_key_is_secret(key),
            )
            for key, item in submitted.items()
        }
    if isinstance(submitted, list):
        current_items = current if isinstance(current, list) else []
        return [
            _restore_redacted_provider_secret_values(
                item,
                current_items[index] if index < len(current_items) else None,
            )
            for index, item in enumerate(submitted)
        ]
    return submitted


def _provider_config_updates(query: QueryParams) -> dict[str, Any]:
    updates: dict[str, Any] = {}
    string_fields = (
        ("api_key", "apiKey"),
        ("api_base", "apiBase"),
        ("api_type", "apiType"),
        ("proxy", "proxy"),
        ("thinking_style", "thinkingStyle"),
        ("region", "region"),
        ("profile", "profile"),
        ("display_name", "displayName"),
    )
    for snake, camel in string_fields:
        if _query_has_alias(query, snake, camel):
            value = (_query_first_alias(query, snake, camel) or "").strip()
            updates[snake] = value or ("auto" if snake == "api_type" else None)

    for snake, camel in (
        ("extra_headers", "extraHeaders"),
        ("extra_body", "extraBody"),
        ("extra_query", "extraQuery"),
    ):
        if _query_has_alias(query, snake, camel):
            updates[snake] = _provider_json_setting(query, snake, camel)
    return updates


def _validated_provider_config(
    provider_config: ProviderConfig | None,
    updates: dict[str, Any],
) -> ProviderConfig:
    config_type = type(provider_config) if provider_config is not None else ProviderConfig
    values = provider_config.model_dump(mode="python") if provider_config is not None else {}
    if provider_config is not None:
        for field in _PROVIDER_STRUCTURED_FIELDS:
            if field in updates:
                updates[field] = _restore_redacted_provider_secret_values(
                    updates[field],
                    getattr(provider_config, field),
                )
    values.update(updates)
    try:
        return config_type.model_validate(values)
    except ValueError as exc:
        errors = getattr(exc, "errors", lambda: [])()
        if errors:
            error = errors[0]
            field = ".".join(str(part) for part in error.get("loc", ()))
            message = str(error.get("msg", "invalid value"))
            raise WebUISettingsError(f"{field}: {message}" if field else message) from exc
        raise WebUISettingsError(str(exc)) from exc


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


def _provider_requires_api_base(spec: Any) -> bool:
    if spec.name == "azure_openai":
        return True
    return bool(spec.backend == "openai_compat" and spec.is_direct and not spec.default_api_base)


def _oauth_provider_status(spec: Any) -> dict[str, Any]:
    if not getattr(spec, "is_oauth", False):
        return {"configured": False, "account": None, "expires_at": None, "login_supported": False}

    if spec.name == "openai_codex":
        try:
            from oauth_cli_kit.providers import OPENAI_CODEX_PROVIDER
            from oauth_cli_kit.storage import FileTokenStorage
        except Exception:
            return {
                "configured": False,
                "account": None,
                "expires_at": None,
                "login_supported": False,
            }
        token = None
        with suppress(Exception):
            token = FileTokenStorage(
                token_filename=OPENAI_CODEX_PROVIDER.token_filename,
            ).load()
        expires_at = getattr(token, "expires", None) if token else None
        now_ms = int(time.time() * 1000)
        return {
            "configured": bool(
                token
                and token.access
                and (getattr(token, "refresh", None) or (expires_at and expires_at > now_ms))
            ),
            "account": getattr(token, "account_id", None) if token else None,
            "expires_at": expires_at,
            "login_supported": True,
        }

    if spec.name == "github_copilot":
        try:
            from nanobot.providers.github_copilot_provider import get_github_copilot_login_status
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

    if spec.name == "xai_grok":
        try:
            from nanobot.providers.xai_oauth import get_xai_oauth_login_status
        except Exception:
            return {
                "configured": False,
                "account": None,
                "expires_at": None,
                "login_supported": False,
            }
        token = None
        with suppress(Exception):
            token = get_xai_oauth_login_status()
        expires_at = getattr(token, "expires", None) if token else None
        now_ms = int(time.time() * 1000)
        return {
            "configured": bool(
                token
                and token.access
                and (getattr(token, "refresh", None) or (expires_at and expires_at > now_ms))
            ),
            "account": getattr(token, "account_id", None) if token else None,
            "expires_at": expires_at,
            "login_supported": True,
        }

    return {"configured": False, "account": None, "expires_at": None, "login_supported": False}


def _provider_configured_for_settings(spec: Any, provider_config: Any) -> bool:
    if spec.is_oauth:
        return bool(_oauth_provider_status(spec)["configured"])
    if _provider_requires_api_base(spec):
        return bool(provider_config.api_base)
    if _provider_requires_api_key(spec):
        return bool(provider_config.api_key)
    return bool(
        provider_config.api_key
        or provider_config.api_base
        or getattr(provider_config, "region", None)
        or getattr(provider_config, "profile", None)
    )


def _dynamic_provider_items(config: Any) -> list[tuple[str, ProviderConfig]]:
    return [
        (name, provider_config)
        for name, provider_config in (config.providers.model_extra or {}).items()
        if isinstance(provider_config, ProviderConfig)
    ]


def _resolve_settings_provider(
    config: Any,
    provider_name: str,
) -> tuple[Any, str, ProviderConfig] | None:
    spec = find_by_name(provider_name)
    if spec is not None:
        provider_config = getattr(config.providers, spec.name, None)
        if isinstance(provider_config, ProviderConfig):
            return spec, spec.name, provider_config
        return None

    normalized = provider_name.replace("-", "_")
    for extra_name, provider_config in _dynamic_provider_items(config):
        if provider_name == extra_name or normalized == extra_name.replace("-", "_"):
            return (
                create_dynamic_spec(
                    extra_name,
                    display_name=provider_config.display_name or "",
                    thinking_style=provider_config.thinking_style or "",
                ),
                extra_name,
                provider_config,
            )
    return None


def _provider_advanced_field_names(name: str, spec: Any) -> list[str]:
    fields: list[str] = []
    if spec.backend in {"openai_compat", "anthropic"}:
        fields.append("extra_headers")
    if spec.backend in {"openai_compat", "bedrock", "openai_codex", "xai_grok"}:
        fields.append("extra_body")
    if spec.backend == "openai_compat":
        fields.extend(("extra_query", "proxy"))
    if spec.name in _OAUTH_PROXY_PROVIDERS and "proxy" not in fields:
        fields.append("proxy")
    if spec.name == "openai":
        fields.append("api_type")
    if spec.backend == "bedrock":
        fields.extend(("region", "profile"))
    if find_by_name(name) is None:
        fields.append("thinking_style")
    return fields


def _provider_settings_row(
    name: str,
    spec: Any,
    provider_config: ProviderConfig,
) -> dict[str, Any]:
    oauth_status = _oauth_provider_status(spec) if spec.is_oauth else None
    is_custom = find_by_name(name) is None

    row = {
        "name": name,
        "label": spec.label,
        "is_custom": is_custom,
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
        "model_selectable": not spec.is_transcription_only,
        "model_catalog": _model_catalog_kind(spec),
        "advanced_fields": _provider_advanced_field_names(name, spec),
        "extra_headers": _redact_provider_secret_values(provider_config.extra_headers),
        "extra_body": _redact_provider_secret_values(provider_config.extra_body),
        "extra_query": _redact_provider_secret_values(provider_config.extra_query),
        "thinking_style": provider_config.thinking_style,
        "region": getattr(provider_config, "region", None),
        "profile": getattr(provider_config, "profile", None),
        "proxy": provider_config.proxy,
    }
    if oauth_status is not None:
        row["oauth_account"] = oauth_status["account"]
        row["oauth_expires_at"] = oauth_status["expires_at"]
        row["oauth_login_supported"] = oauth_status["login_supported"]
    if spec.name == "openai":
        row["api_type"] = provider_config.api_type
    return row


def _provider_settings_rows(config: Any, selected_provider: str | None) -> list[dict[str, Any]]:
    """Return one Settings row per provider family while preserving legacy configs."""
    aliases: dict[str, list[Any]] = {}
    for spec in PROVIDERS:
        if spec.settings_alias_for:
            aliases.setdefault(spec.settings_alias_for, []).append(spec)

    rows: list[dict[str, Any]] = []
    for canonical in PROVIDERS:
        if canonical.settings_alias_for:
            continue
        candidates = [canonical, *aliases.get(canonical.name, [])]
        chosen = next((spec for spec in candidates if spec.name == selected_provider), None)
        if chosen is None:
            chosen = next(
                (
                    spec
                    for spec in candidates
                    if (provider_config := getattr(config.providers, spec.name, None)) is not None
                    and _provider_configured_for_settings(spec, provider_config)
                ),
                canonical,
            )
        provider_config = getattr(config.providers, chosen.name, None)
        if provider_config is None:
            continue
        row = _provider_settings_row(chosen.name, chosen, provider_config)
        row["label"] = canonical.label
        rows.append(row)
    return rows


def _model_catalog_kind(spec: Any) -> str:
    catalog = getattr(spec, "model_catalog", "auto")
    if catalog != "auto":
        return catalog
    if spec.is_transcription_only or spec.is_oauth:
        return "unsupported"
    if spec.backend != "openai_compat" and spec.name != "minimax_anthropic":
        return "unsupported"
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
    description: str | None = None
    owned_by: str | None = None
    if isinstance(row, dict):
        raw_label = row.get("display_name") or row.get("label") or row.get("name")
        if isinstance(raw_label, str) and raw_label.strip() and raw_label.strip() != model_id:
            label = raw_label.strip()
        raw_description = row.get("description")
        if isinstance(raw_description, str) and raw_description.strip():
            description = raw_description.strip()
        raw_owner = row.get("owned_by") or row.get("owner") or row.get("organization")
        if isinstance(raw_owner, str) and raw_owner.strip():
            owned_by = raw_owner.strip()
    payload = {
        "id": model_id,
        "label": label,
        "owned_by": owned_by,
        "context_window": _model_context_window(row),
    }
    if description:
        payload["description"] = description
    return payload


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

    config = load_config()
    resolved_provider = _resolve_settings_provider(config, provider_name)
    if resolved_provider is None:
        raise WebUISettingsError("unknown provider")
    spec, provider_key, provider_config = resolved_provider

    catalog_kind = _model_catalog_kind(spec)
    base_payload: dict[str, Any] = {
        "provider": provider_key,
        "label": spec.label,
        "catalog_kind": catalog_kind,
        "models": [],
        "model_count": 0,
        "message": None,
        "fetched_at": time.time(),
    }
    if catalog_kind == "unsupported":
        return {
            **base_payload,
            "status": "unsupported",
            "message": "Model list is not available for this provider. Type a model ID manually.",
        }

    if catalog_kind == "builtin":
        rows = [
            {
                "id": model.id,
                "label": model.label or None,
                "description": model.description or None,
                "owned_by": spec.label,
                "context_window": model.context_window,
            }
            for model in spec.builtin_models
        ]
        return {
            **base_payload,
            "status": "available",
            "models": rows,
            "model_count": len(rows),
        }

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
        raise WebUISettingsError(
            "context_window_tokens must be 65536, 200000, 262144, 500000, or 1048576"
        )
    return parsed


def _parse_positive_int(value: str | None, field: str) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except ValueError:
        raise WebUISettingsError(f"{field} must be an integer") from None
    if parsed <= 0:
        raise WebUISettingsError(f"{field} must be greater than zero")
    return parsed


def _parse_temperature(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except ValueError:
        raise WebUISettingsError("temperature must be a number") from None
    if not math.isfinite(parsed) or parsed < 0 or parsed > 2:
        raise WebUISettingsError("temperature must be between 0 and 2")
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


def _custom_provider_key(config: Any, display_name: str) -> str:
    slug = _MODEL_CONFIGURATION_SLUG_RE.sub("-", display_name.strip().lower()).strip("-_")
    base = f"custom-{slug or 'provider'}"
    if len(base) > 56:
        base = base[:56].rstrip("-_")
    existing = {
        name.replace("_", "-").lower()
        for name, _provider_config in _dynamic_provider_items(config)
    }
    candidate = base
    suffix = 2
    while candidate.replace("_", "-").lower() in existing or find_by_name(candidate):
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def _provider_display_name_exists(
    config: Any,
    display_name: str,
    *,
    exclude_key: str | None = None,
) -> bool:
    normalized = display_name.strip().casefold()
    if any(spec.label.strip().casefold() == normalized for spec in PROVIDERS):
        return True
    for provider_key, provider_config in _dynamic_provider_items(config):
        if provider_key == exclude_key:
            continue
        label = (
            provider_config.display_name
            or provider_key.replace("-", " ").replace("_", " ").title()
        )
        if label.strip().casefold() == normalized:
            return True
    return False


def _unique_model_configuration_name(config: Any, label: str) -> str:
    """Return a stable, unused preset name for a migrated model configuration."""
    try:
        base = _model_configuration_slug(label)
    except WebUISettingsError:
        base = "model"
    candidate = base
    suffix = 2
    while candidate in config.model_presets:
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def _model_configuration_label(model: str) -> str:
    return model.rsplit("/", 1)[-1] or model


def _model_call_order_state(config: Any) -> tuple[list[str], bool]:
    defaults = config.agents.defaults
    primary = defaults.model_preset
    if not primary or primary == "default" or primary not in config.model_presets:
        return [], False
    order = [primary]
    for fallback in defaults.fallback_models:
        if not isinstance(fallback, str):
            return [], False
        order.append(fallback)
    return order, True


def _validate_configured_provider(config: Any, provider: str) -> None:
    if provider == "auto":
        return
    resolved_provider = _resolve_settings_provider(config, provider)
    if resolved_provider is None:
        raise WebUISettingsError("unknown provider")
    spec, _, provider_config = resolved_provider
    if spec.is_transcription_only:
        raise WebUISettingsError("provider does not support chat models")
    if not _provider_configured_for_settings(spec, provider_config):
        raise WebUISettingsError("provider is not configured")


def _image_generation_provider_rows(config: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name in image_gen_provider_names():
        image_provider = get_image_gen_provider(name)
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
                "models": list(image_provider.model_options) if image_provider else [],
                "default_model": (
                    image_provider.model_options[0]
                    if image_provider and image_provider.model_options
                    else None
                ),
            }
        )
    return rows


_DEFAULT_REASONING_EFFORT_VALUES: tuple[str, ...] = ("", "low", "medium", "high")


def _reasoning_effort_values_for(provider_name: str, model: str) -> list[str]:
    """Return user-facing reasoning_effort options for this provider+model.

    Mistral chat models accept only "high"/"none"; Magistral rejects the
    kwarg entirely (reasoning is implicit). For everyone else, return the
    full OpenAI vocab.
    """
    spec = find_by_name(provider_name) if provider_name else None
    if spec is None:
        return list(_DEFAULT_REASONING_EFFORT_VALUES)

    model_lower = (model or "").lower()
    if model_lower.rsplit("/", 1)[-1] == "kimi-k3":
        # K3 always reasons and currently exposes only its default/max effort.
        return ["", "max"]

    implicit = getattr(spec, "implicit_reasoning_models", ())
    if implicit and any(pat in model_lower for pat in implicit):
        # Reasoning is always on; only "Default" makes sense.
        return [""]

    remap = getattr(spec, "reasoning_effort_remap", ())
    if remap:
        # Reverse the remap: surface the distinct wire-vocab outputs as the
        # user's options. Mistral collapses to "high"/"none" → UI shows
        # "Default" + "High".
        wire_values: list[str] = []
        for _user_val, wire_val in remap:
            if wire_val and wire_val != "none" and wire_val not in wire_values:
                wire_values.append(wire_val)
        return ["", *wire_values]

    return list(_DEFAULT_REASONING_EFFORT_VALUES)


def _transcription_provider_rows(config: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name in transcription_provider_names():
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
    effective_preset = config.resolve_preset()

    provider_name = (
        config.get_provider_name(effective_preset.model, preset=effective_preset)
        or effective_preset.provider
    )
    provider = config.get_provider(effective_preset.model, preset=effective_preset)
    selected_provider = provider_name
    if effective_preset.provider != "auto":
        spec = find_by_name(effective_preset.provider)
        selected_provider = spec.name if spec else provider_name

    providers = _provider_settings_rows(config, selected_provider)
    for provider_key, provider_config in _dynamic_provider_items(config):
        providers.append(
            _provider_settings_row(
                provider_key,
                create_dynamic_spec(
                    provider_key,
                    display_name=provider_config.display_name or "",
                    thinking_style=provider_config.thinking_style or "",
                ),
                provider_config,
            )
        )

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
            "resolved_provider": config.get_provider_name(
                defaults.model,
                preset=config.resolve_default_preset(),
            ),
            "max_tokens": defaults.max_tokens,
            "context_window_tokens": defaults.context_window_tokens,
            "temperature": defaults.temperature,
            "reasoning_effort": defaults.reasoning_effort,
            "reasoning_effort_values": _reasoning_effort_values_for(
                config.get_provider_name(
                    defaults.model,
                    preset=config.resolve_default_preset(),
                )
                or defaults.provider,
                defaults.model,
            ),
        }
    ]
    for name, preset in config.model_presets.items():
        resolved_preset_provider = (
            config.get_provider_name(
                preset.model,
                preset=preset,
            )
            or preset.provider
        )
        model_presets.append(
            {
                "name": name,
                "label": preset.label or name,
                "active": active_preset_name == name,
                "is_default": False,
                "model": preset.model,
                "provider": preset.provider,
                "resolved_provider": resolved_preset_provider,
                "max_tokens": preset.max_tokens,
                "context_window_tokens": preset.context_window_tokens,
                "temperature": preset.temperature,
                "reasoning_effort": preset.reasoning_effort,
                "reasoning_effort_values": _reasoning_effort_values_for(
                    resolved_preset_provider, preset.model
                ),
            }
        )

    model_call_order, model_call_order_editable = _model_call_order_state(config)
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
        "model_call_order": model_call_order,
        "model_call_order_editable": model_call_order_editable,
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
        "api": {
            "host": config.api.host,
            "port": config.api.port,
            "timeout": config.api.timeout,
            "api_key_hint": _mask_secret_hint(config.api.api_key),
        },
        "observability": {
            "provider": "langfuse",
            "configured": bool(
                os.environ.get("LANGFUSE_SECRET_KEY")
                and os.environ.get("LANGFUSE_PUBLIC_KEY")
            ),
            "base_url": os.environ.get("LANGFUSE_BASE_URL") or "https://cloud.langfuse.com",
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
            "exec_path_prepend_set": bool(exec_config.path_prepend),
            "exec_path_append_set": bool(exec_config.path_append),
        },
        "requires_restart": requires_restart,
        "version": _version_payload(),
        "docs": _docs_payload(),
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

    base = config.resolve_preset()
    max_tokens = _parse_positive_int(
        _query_first_alias(query, "max_tokens", "maxTokens"),
        "max_tokens",
    )
    context_window_tokens = _parse_positive_int(
        _query_first_alias(query, "context_window_tokens", "contextWindowTokens"),
        "context_window_tokens",
    )
    temperature = _parse_temperature(_query_first(query, "temperature"))
    reasoning_effort = base.reasoning_effort
    if "reasoning_effort" in query or "reasoningEffort" in query:
        reasoning_effort = (
            _query_first_alias(query, "reasoning_effort", "reasoningEffort") or ""
        ).strip() or None
    config.model_presets[name] = ModelPresetConfig(
        label=label,
        model=model,
        provider=provider,
        max_tokens=max_tokens if max_tokens is not None else base.max_tokens,
        context_window_tokens=(
            context_window_tokens
            if context_window_tokens is not None
            else base.context_window_tokens
        ),
        temperature=temperature if temperature is not None else base.temperature,
        reasoning_effort=reasoning_effort,
    )
    save_config(config)
    payload = settings_payload()
    payload["created_model_preset"] = name
    return payload


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

    context_window_tokens = _parse_positive_int(
        _query_first_alias(query, "context_window_tokens", "contextWindowTokens"),
        "context_window_tokens",
    )
    if (
        context_window_tokens is not None
        and preset.context_window_tokens != context_window_tokens
    ):
        preset.context_window_tokens = context_window_tokens
        changed = True

    max_tokens = _parse_positive_int(
        _query_first_alias(query, "max_tokens", "maxTokens"),
        "max_tokens",
    )
    if max_tokens is not None and preset.max_tokens != max_tokens:
        preset.max_tokens = max_tokens
        changed = True

    temperature = _parse_temperature(_query_first(query, "temperature"))
    if temperature is not None and preset.temperature != temperature:
        preset.temperature = temperature
        changed = True

    if "reasoning_effort" in query or "reasoningEffort" in query:
        reasoning_effort = (
            _query_first_alias(query, "reasoning_effort", "reasoningEffort") or ""
        ).strip() or None
        if preset.reasoning_effort != reasoning_effort:
            preset.reasoning_effort = reasoning_effort
            changed = True

    if changed:
        save_config(config)
    return settings_payload()


def update_model_call_order(query: QueryParams) -> dict[str, Any]:
    raw_order = _query_first_alias(query, "order", "presetNames")
    if raw_order is None:
        raise WebUISettingsError("model call order is required")
    try:
        order = json.loads(raw_order)
    except json.JSONDecodeError:
        raise WebUISettingsError("model call order must be a JSON array") from None
    if (
        not isinstance(order, list)
        or not order
        or any(not isinstance(name, str) or not name.strip() for name in order)
    ):
        raise WebUISettingsError("model call order must contain at least one preset")

    normalized_order = [name.strip() for name in order]
    config = load_config()
    _, editable = _model_call_order_state(config)
    if not editable:
        raise WebUISettingsError(
            "convert the existing model configuration to presets first",
            status=409,
        )
    unknown = [name for name in normalized_order if name not in config.model_presets]
    if unknown:
        raise WebUISettingsError(f"unknown model preset: {unknown[0]}")

    defaults = config.agents.defaults
    fallback_models = normalized_order[1:]
    if (
        defaults.model_preset != normalized_order[0]
        or defaults.fallback_models != fallback_models
    ):
        defaults.model_preset = normalized_order[0]
        defaults.fallback_models = fallback_models
        save_config(config)
    return settings_payload()


def migrate_model_configurations(_query: QueryParams | None = None) -> dict[str, Any]:
    """Materialize legacy primary/inline model settings as named presets."""
    config = load_config()
    defaults = config.agents.defaults
    primary = config.resolve_preset()
    created: list[str] = []

    if not defaults.model_preset or defaults.model_preset == "default":
        label = _model_configuration_label(primary.model)
        name = _unique_model_configuration_name(config, label)
        config.model_presets[name] = ModelPresetConfig(
            label=label,
            model=primary.model,
            provider=primary.provider,
            max_tokens=primary.max_tokens,
            context_window_tokens=primary.context_window_tokens,
            temperature=primary.temperature,
            reasoning_effort=primary.reasoning_effort,
        )
        defaults.model_preset = name
        created.append(name)

    fallback_models: list[str] = []
    for fallback in defaults.fallback_models:
        if isinstance(fallback, str):
            fallback_models.append(fallback)
            continue
        label = _model_configuration_label(fallback.model)
        name = _unique_model_configuration_name(config, label)
        config.model_presets[name] = ModelPresetConfig(
            label=label,
            model=fallback.model,
            provider=fallback.provider,
            max_tokens=(
                fallback.max_tokens
                if fallback.max_tokens is not None
                else primary.max_tokens
            ),
            context_window_tokens=(
                fallback.context_window_tokens
                if fallback.context_window_tokens is not None
                else primary.context_window_tokens
            ),
            temperature=(
                fallback.temperature
                if fallback.temperature is not None
                else primary.temperature
            ),
            reasoning_effort=fallback.reasoning_effort,
        )
        fallback_models.append(name)
        created.append(name)

    if created:
        defaults.fallback_models = fallback_models
        save_config(config)
    return settings_payload()


def delete_model_configuration(query: QueryParams) -> dict[str, Any]:
    name = (_query_first(query, "name") or "").strip()
    if not name or name == "default":
        raise WebUISettingsError("model configuration is required")

    config = load_config()
    if name not in config.model_presets:
        raise WebUISettingsError("unknown model configuration")
    defaults = config.agents.defaults
    referenced = defaults.model_preset == name or any(
        fallback == name for fallback in defaults.fallback_models
    )
    if referenced:
        raise WebUISettingsError(
            "remove the model preset from the call order first",
            status=409,
        )

    del config.model_presets[name]
    save_config(config)
    return settings_payload()


def create_provider_settings(query: QueryParams) -> dict[str, Any]:
    display_name = (_query_first_alias(query, "name", "displayName") or "").strip()
    if not display_name:
        raise WebUISettingsError("provider name is required")
    if len(display_name) > 80:
        raise WebUISettingsError("provider name must be 80 characters or fewer")
    updates = _provider_config_updates(query)
    allowed = {
        "api_key",
        "api_base",
        "proxy",
        "extra_headers",
        "extra_body",
        "extra_query",
        "thinking_style",
        "display_name",
    }
    unsupported = set(updates) - allowed
    if unsupported:
        field = sorted(unsupported)[0]
        raise WebUISettingsError(f"{field} is not supported for a custom provider")
    api_base = str(updates.get("api_base") or "")
    if not api_base:
        raise WebUISettingsError("API base is required")

    config = load_config()
    if _provider_display_name_exists(config, display_name):
        raise WebUISettingsError("provider already exists", status=409)

    provider_key = _custom_provider_key(config, display_name)
    updates["display_name"] = display_name
    updates["api_type"] = "auto"
    provider_config = _validated_provider_config(None, updates)
    setattr(config.providers, provider_key, provider_config)
    save_config(config)
    payload = settings_payload()
    payload["created_provider"] = provider_key
    return payload


def update_provider_settings(query: QueryParams) -> dict[str, Any]:
    provider_name = (_query_first(query, "provider") or "").strip()
    if not provider_name:
        raise WebUISettingsError("provider is required")

    config = load_config()
    resolved_provider = _resolve_settings_provider(config, provider_name)
    if resolved_provider is None:
        raise WebUISettingsError("unknown provider")
    spec, provider_key, provider_config = resolved_provider
    updates = _provider_config_updates(query)
    if not spec.is_oauth and spec.name != "openai":
        # Preserve the legacy settings API contract: api_type only applies to
        # OpenAI, and is ignored when older clients send it for another provider.
        updates.pop("api_type", None)
    if spec.is_oauth:
        if spec.name not in _OAUTH_PROXY_PROVIDERS:
            raise WebUISettingsError("unknown provider")
        unsupported = set(updates) - {"proxy", "extra_body"}
        if unsupported:
            raise WebUISettingsError("OAuth provider only supports proxy and extra_body settings")
    else:
        allowed = {
            "api_key",
            "api_base",
            *_provider_advanced_field_names(provider_key, spec),
        }
        if find_by_name(provider_key) is None:
            allowed.add("display_name")
        unsupported = set(updates) - allowed
        if unsupported:
            field = sorted(unsupported)[0]
            raise WebUISettingsError(f"{field} is not supported for this provider")

    if "display_name" in updates:
        display_name = str(updates["display_name"] or "")
        if not display_name:
            raise WebUISettingsError("provider name is required")
        if len(display_name) > 80:
            raise WebUISettingsError("provider name must be 80 characters or fewer")
        if _provider_display_name_exists(config, display_name, exclude_key=provider_key):
            raise WebUISettingsError("provider already exists", status=409)

    updated_provider_config = _validated_provider_config(provider_config, updates)
    changed = updated_provider_config != provider_config
    if changed:
        setattr(config.providers, provider_key, updated_provider_config)
        save_config(config)
    image_config = config.tools.image_generation
    restart_required = (
        changed
        and image_config.enabled
        and image_config.provider == provider_key
        and get_image_gen_provider(provider_key) is not None
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
            raise WebUISettingsError(
                "oauth_cli_kit not installed. Run: pip install oauth-cli-kit", status=500
            ) from None

        try:
            proxy = resolve_config_env_vars(load_config()).providers.openai_codex.proxy or None
        except ValueError as e:
            raise WebUISettingsError(str(e), status=400) from e
        token = None
        with suppress(Exception):
            token = get_token(proxy=proxy)
        if not (token and token.access):
            messages: list[str] = []
            token = login_oauth_interactive(
                print_fn=lambda message: messages.append(str(message)),
                prompt_fn=lambda _prompt: "",
                proxy=proxy,
            )
        if not (token and token.access):
            raise WebUISettingsError("OAuth login failed", status=401)
        return settings_payload()

    if spec.name == "github_copilot":
        try:
            from nanobot.providers.github_copilot_provider import (
                get_github_copilot_login_status,
                login_github_copilot,
            )
        except ImportError:
            raise WebUISettingsError(
                "oauth_cli_kit not installed. Run: pip install oauth-cli-kit", status=500
            ) from None

        token = get_github_copilot_login_status()
        if not token:
            token = login_github_copilot(print_fn=lambda _message: None)
        if not (token and token.access):
            raise WebUISettingsError("OAuth login failed", status=401)
        return settings_payload()

    if spec.name == "xai_grok":
        from nanobot.providers.xai_oauth import start_xai_oauth_login

        try:
            proxy = resolve_config_env_vars(load_config()).providers.xai_grok.proxy or None
        except ValueError as e:
            raise WebUISettingsError(str(e), status=400) from e
        try:
            flow = start_xai_oauth_login(
                proxy=proxy,
                timeout_s=_XAI_WEBUI_OAUTH_TIMEOUT_S,
            )
        except Exception as e:
            raise WebUISettingsError(f"xAI OAuth login failed: {e}", status=502) from e
        flow_id = secrets.token_urlsafe(24)
        _register_xai_webui_oauth_flow(flow_id, flow)
        return {
            "status": "authorization_required",
            "provider": spec.name,
            "flow_id": flow_id,
            "authorization_url": flow.authorization_url,
            "expires_in": flow.remaining_seconds,
        }

    raise WebUISettingsError("OAuth login is not supported for this provider")


def complete_oauth_provider(
    query: QueryParams,
    authorization_code: str | None = None,
) -> dict[str, Any]:
    provider_name = (_query_first(query, "provider") or "").strip()
    flow_id = (_query_first(query, "flow_id") or "").strip()
    spec = find_by_name(provider_name)
    if spec is None or spec.name != "xai_grok":
        raise WebUISettingsError("OAuth completion is not supported for this provider")
    if not flow_id:
        raise WebUISettingsError("flow_id is required")

    flow = _get_xai_webui_oauth_flow(flow_id)
    if flow is None:
        raise WebUISettingsError("xAI sign-in expired. Start again.", status=410)

    from nanobot.providers.xai_oauth import complete_xai_oauth_login

    try:
        token = complete_xai_oauth_login(flow, authorization_code)
    except Exception as e:
        _remove_xai_webui_oauth_flow(flow_id, flow)
        raise WebUISettingsError(f"xAI OAuth login failed: {e}", status=502) from e
    if token is None:
        return {
            "status": "pending",
            "provider": spec.name,
            "flow_id": flow_id,
        }
    _remove_xai_webui_oauth_flow(flow_id, flow, cancel=False)
    if not token.access:
        raise WebUISettingsError("OAuth login failed", status=401)
    return settings_payload()


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
            raise WebUISettingsError(
                "oauth_cli_kit not installed. Run: pip install oauth-cli-kit", status=500
            ) from None
        token_path = FileTokenStorage(token_filename=OPENAI_CODEX_PROVIDER.token_filename).get_token_path()
    elif spec.name == "github_copilot":
        try:
            from nanobot.providers.github_copilot_provider import get_storage
        except ImportError:
            raise WebUISettingsError(
                "oauth_cli_kit not installed. Run: pip install oauth-cli-kit", status=500
            ) from None
        token_path = get_storage().get_token_path()
    elif spec.name == "xai_grok":
        from nanobot.providers.xai_oauth import logout_xai_oauth

        _clear_xai_webui_oauth_flows()
        logout_xai_oauth()
        return settings_payload()
    else:
        raise WebUISettingsError("OAuth logout is not supported for this provider")

    for path in (token_path, token_path.with_suffix(".lock")):
        with suppress(FileNotFoundError):
            path.unlink()
    return settings_payload()


def _register_xai_webui_oauth_flow(flow_id: str, flow: Any) -> None:
    discarded: list[Any] = []
    with _xai_webui_oauth_flows_lock:
        for existing_id, existing in list(_xai_webui_oauth_flows.items()):
            if existing.expired:
                discarded.append(_xai_webui_oauth_flows.pop(existing_id))
        while len(_xai_webui_oauth_flows) >= _XAI_WEBUI_OAUTH_MAX_FLOWS:
            oldest_id = next(iter(_xai_webui_oauth_flows))
            discarded.append(_xai_webui_oauth_flows.pop(oldest_id))
        _xai_webui_oauth_flows[flow_id] = flow
    for existing in discarded:
        existing.cancel()


def _get_xai_webui_oauth_flow(flow_id: str) -> Any | None:
    with _xai_webui_oauth_flows_lock:
        flow = _xai_webui_oauth_flows.get(flow_id)
        if flow is None or not flow.expired:
            return flow
        _xai_webui_oauth_flows.pop(flow_id, None)
    flow.cancel()
    return None


def _remove_xai_webui_oauth_flow(
    flow_id: str,
    flow: Any,
    *,
    cancel: bool = True,
) -> None:
    with _xai_webui_oauth_flows_lock:
        if _xai_webui_oauth_flows.get(flow_id) is flow:
            _xai_webui_oauth_flows.pop(flow_id)
    if cancel:
        flow.cancel()


def _clear_xai_webui_oauth_flows() -> None:
    with _xai_webui_oauth_flows_lock:
        flows = list(_xai_webui_oauth_flows.values())
        _xai_webui_oauth_flows.clear()
    for flow in flows:
        flow.cancel()


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
    elif credential in {"api_key", "optional_api_key"}:
        raw_api_key = _query_first_alias(query, "api_key", "apiKey")
        api_key = raw_api_key.strip() if raw_api_key is not None else None
        if api_key is None and previous_provider == provider_name and search_config.api_key:
            api_key = search_config.api_key
        if credential == "api_key" and not api_key:
            raise WebUISettingsError("api_key is required")
        set_search_value("api_key", api_key or "")
        set_search_value("base_url", "")
    else:
        raise WebUISettingsError("unknown web search credential type")

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


def update_api_settings(query: QueryParams) -> dict[str, Any]:
    """Update the managed OpenAI-compatible API configuration."""
    config = load_config()
    api = config.api

    host = _query_first(query, "host")
    if host is not None:
        host = host.strip()
        if not host:
            raise WebUISettingsError("host is required")
        api.host = host

    port = _query_first(query, "port")
    if port is not None:
        try:
            parsed_port = int(port)
        except ValueError:
            raise WebUISettingsError("port must be an integer") from None
        if parsed_port < 1 or parsed_port > 65535:
            raise WebUISettingsError("port must be between 1 and 65535")
        api.port = parsed_port

    timeout = _query_first(query, "timeout")
    if timeout is not None:
        try:
            parsed_timeout = float(timeout)
        except ValueError:
            raise WebUISettingsError("timeout must be a number") from None
        if parsed_timeout < 1 or parsed_timeout > 3600:
            raise WebUISettingsError("timeout must be between 1 and 3600")
        api.timeout = parsed_timeout

    api_key = _query_first_alias(query, "api_key", "apiKey")
    if api_key is not None:
        api.api_key = api_key.strip()

    if not is_loopback_host(api.host) and not api.api_key.strip():
        raise WebUISettingsError("an API key is required when the API is available on the network")

    save_config(config)
    return settings_payload()


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
        provider_spec = resolve_transcription_provider(provider)
        if provider_spec is None:
            raise WebUISettingsError("unknown transcription provider")
        provider = provider_spec.name
        if transcription.provider != provider:
            transcription.provider = provider
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
