from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Awaitable, Callable, TypedDict

from nanobot.agent.tools.web import SEARCH_PROVIDER_OPTIONS
from nanobot.audio.transcription import resolve_transcription_config
from nanobot.audio.transcription_registry import (
    resolve_transcription_provider,
    transcription_provider_names,
)
from nanobot.config.schema import Config
from nanobot.providers.image_generation import (
    get_image_gen_provider,
    image_gen_provider_names,
)
from nanobot.providers.registry import find_by_name
from nanobot.webui.request_settings import (
    parse_request_object,
    redact_request_secrets,
    restore_request_secrets,
    validate_request_config,
)
from nanobot.webui.settings_contracts import (
    QueryParams,
    SettingsRequest,
    SettingsRouteResult,
    WebUISettingsError,
    parse_bool,
    query_first,
    query_first_alias,
    query_has_alias,
)
from nanobot.webui.settings_models import (
    OAuthStatusReader,
    mask_secret_hint,
    provider_configured_for_settings,
)
from nanobot.webui.workspaces import (
    read_webui_default_access_mode,
)

if TYPE_CHECKING:
    from nanobot.webui.settings_services import WebUISettingsServices

SettingsOperation = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class CapabilitySettingsOperations:
    update_web_search: SettingsOperation
    update_image: SettingsOperation
    update_transcription: SettingsOperation
    update_network: SettingsOperation
    reload_image: Callable[[], Awaitable[dict[str, Any]]]


class CapabilitySettingsPayload(TypedDict):
    web_search: dict[str, Any]
    web: dict[str, Any]
    observability: dict[str, Any]
    image_generation: dict[str, Any]
    transcription: dict[str, Any]


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


def _image_generation_provider_rows(
    config: Config,
    *,
    oauth_status: OAuthStatusReader,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name in image_gen_provider_names(config.providers):
        spec = find_by_name(name)
        provider_config = getattr(config.providers, name, None)
        image_provider = get_image_gen_provider(name, provider_config)
        configured = (
            provider_configured_for_settings(spec, provider_config, oauth_status)
            if spec is not None and provider_config is not None
            else bool(provider_config and provider_config.api_base)
        )
        rows.append(
            {
                "name": name,
                "label": spec.label if spec is not None else getattr(provider_config, "display_name", None) or name,
                "uses_images_api": spec is None or name == "custom",
                "configured": configured,
                "auth_type": "oauth" if spec is not None and spec.is_oauth else "api_key",
                "api_key_hint": mask_secret_hint(getattr(provider_config, "api_key", None)),
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


def _transcription_provider_rows(config: Config) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name in transcription_provider_names():
        spec = find_by_name(name)
        provider_config = getattr(config.providers, name, None)
        rows.append(
            {
                "name": name,
                "label": spec.label if spec is not None else name,
                "configured": bool(getattr(provider_config, "api_key", None)),
                "api_key_hint": mask_secret_hint(getattr(provider_config, "api_key", None)),
                "api_base": getattr(provider_config, "api_base", None),
                "default_api_base": (
                    spec.default_api_base if spec and spec.default_api_base else None
                ),
            }
        )
    return rows


def capability_settings_payload(
    config: Config,
    *,
    oauth_status: OAuthStatusReader,
) -> CapabilitySettingsPayload:
    search_config = config.tools.web.search
    image_config = config.tools.image_generation
    transcription = resolve_transcription_config(config)
    search_provider = (
        search_config.provider
        if search_config.provider in _WEB_SEARCH_PROVIDER_BY_NAME
        else "duckduckgo"
    )
    image_providers = _image_generation_provider_rows(config, oauth_status=oauth_status)
    selected_image_provider = next(
        (
            provider
            for provider in image_providers
            if provider["name"] == image_config.provider
        ),
        None,
    )
    return {
        "web_search": {
            "provider": search_provider,
            "api_key_hint": mask_secret_hint(search_config.api_key),
            "base_url": search_config.base_url or None,
            "max_results": search_config.max_results,
            "timeout": search_config.timeout,
            "providers": list(_WEB_SEARCH_PROVIDER_OPTIONS),
        },
        "web": {
            "enable": config.tools.web.enable,
            "use_proxy": config.tools.web.use_proxy,
            "user_agent": config.tools.web.user_agent,
            "search": {
                "max_results": search_config.max_results,
                "timeout": search_config.timeout,
            },
            "fetch": {
                "use_jina_reader": config.tools.web.fetch.use_jina_reader,
            },
        },
        "observability": {
            "provider": "langfuse",
            "configured": bool(
                os.environ.get("LANGFUSE_SECRET_KEY")
                and os.environ.get("LANGFUSE_PUBLIC_KEY")
            ),
            "base_url": os.environ.get("LANGFUSE_BASE_URL")
            or "https://cloud.langfuse.com",
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
            "request_overrides_supported": True,
            "extra_headers": redact_request_secrets(image_config.extra_headers),
            "extra_body": redact_request_secrets(image_config.extra_body),
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
    }


def update_network_safety_settings(
    config: Config,
    query: QueryParams,
) -> tuple[bool, str | None]:
    raw_allow = (
        query_first_alias(
            query,
            "webui_allow_local_service_access",
            "webuiAllowLocalServiceAccess",
        )
        or query_first_alias(
            query,
            "allow_local_preview_access",
            "allowLocalPreviewAccess",
        )
    )
    raw_default_access_mode = query_first_alias(
        query,
        "webui_default_access_mode",
        "webuiDefaultAccessMode",
    )
    if raw_allow is None and raw_default_access_mode is None:
        raise WebUISettingsError(
            "webui_allow_local_service_access or webui_default_access_mode is required"
        )

    changed = False
    if raw_allow is not None:
        allow_local = parse_bool(raw_allow, "webui_allow_local_service_access")
        if config.tools.webui_allow_local_service_access != allow_local:
            config.tools.webui_allow_local_service_access = allow_local
            changed = True

    default_access_mode: str | None = None
    if raw_default_access_mode is not None:
        default_access_mode = raw_default_access_mode.strip().lower()
        if default_access_mode == "restricted":
            default_access_mode = "default"
        if default_access_mode not in {"default", "full"}:
            raise WebUISettingsError(
                "webui_default_access_mode must be default or full"
            )
    return changed, default_access_mode


def update_web_search_settings(config: Config, query: QueryParams) -> tuple[bool, bool]:
    provider_name = (query_first(query, "provider") or "").strip().lower()
    provider_option = _WEB_SEARCH_PROVIDER_BY_NAME.get(provider_name)
    if provider_option is None:
        raise WebUISettingsError("unknown web search provider")

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
        base_url = query_first_alias(query, "base_url", "baseUrl")
        base_url = base_url.strip() if base_url is not None else None
        if not base_url and previous_provider == provider_name and search_config.base_url:
            base_url = search_config.base_url
        if not base_url:
            raise WebUISettingsError("base_url is required")
        set_search_value("base_url", base_url)
        set_search_value("api_key", "")
    elif credential in {"api_key", "optional_api_key"}:
        raw_api_key = query_first_alias(query, "api_key", "apiKey")
        api_key = raw_api_key.strip() if raw_api_key is not None else None
        if api_key is None and previous_provider == provider_name and search_config.api_key:
            api_key = search_config.api_key
        if credential == "api_key" and not api_key:
            raise WebUISettingsError("api_key is required")
        set_search_value("api_key", api_key or "")
        set_search_value("base_url", "")
    else:
        raise WebUISettingsError("unknown web search credential type")

    max_results = query_first_alias(query, "max_results", "maxResults")
    if max_results is not None:
        try:
            parsed = int(max_results)
        except ValueError:
            raise WebUISettingsError("max_results must be an integer") from None
        if parsed < 1 or parsed > 10:
            raise WebUISettingsError("max_results must be between 1 and 10")
        set_search_value("max_results", parsed)

    timeout = query_first(query, "timeout")
    if timeout is not None:
        try:
            parsed_timeout = int(timeout)
        except ValueError:
            raise WebUISettingsError("timeout must be an integer") from None
        if parsed_timeout < 1 or parsed_timeout > 120:
            raise WebUISettingsError("timeout must be between 1 and 120")
        set_search_value("timeout", parsed_timeout)

    use_jina_reader = query_first_alias(query, "use_jina_reader", "useJinaReader")
    if use_jina_reader is not None:
        previous_jina_reader = web_config.fetch.use_jina_reader
        set_fetch_value("use_jina_reader", parse_bool(use_jina_reader, "use_jina_reader"))
        if web_config.fetch.use_jina_reader != previous_jina_reader:
            restart_required = True
    return changed, restart_required


def update_image_generation_settings(
    config: Config,
    query: QueryParams,
    *,
    oauth_status: OAuthStatusReader,
) -> bool:
    image_config = config.tools.image_generation
    changed = False

    provider_name = query_first(query, "provider")
    if provider_name is not None:
        provider_name = provider_name.strip()
        if provider_name.lower() in image_gen_provider_names():
            provider_name = provider_name.lower()
        if not provider_name:
            raise WebUISettingsError("image generation provider is required")
        if get_image_gen_provider(provider_name, getattr(config.providers, provider_name, None)) is None:
            raise WebUISettingsError("unknown image generation provider")
        if image_config.provider != provider_name:
            image_config.provider = provider_name
            image_config.extra_headers = None
            image_config.extra_body = None
            changed = True

    overrides = {
        snake: restore_request_secrets(
            parse_request_object(query, snake, camel), getattr(image_config, snake),
        )
        for snake, camel in (("extra_headers", "extraHeaders"), ("extra_body", "extraBody"))
        if query_has_alias(query, snake, camel)
    }
    validated = validate_request_config(None, overrides)
    for field in overrides:
        value = getattr(validated, field)
        if getattr(image_config, field) != value:
            setattr(image_config, field, value)
            changed = True

    enabled = query_first(query, "enabled")
    if enabled is not None:
        parsed_enabled = parse_bool(enabled, "enabled")
        if image_config.enabled != parsed_enabled:
            image_config.enabled = parsed_enabled
            changed = True

    model = query_first(query, "model")
    if model is not None:
        model = model.strip()
        if not model:
            raise WebUISettingsError("image generation model is required")
        if len(model) > 200:
            raise WebUISettingsError("image generation model is too long")
        if image_config.model != model:
            image_config.model = model
            changed = True

    default_aspect_ratio = query_first_alias(
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

    default_image_size = query_first_alias(
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

    max_images_per_turn = query_first_alias(
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
                for provider in _image_generation_provider_rows(
                    config,
                    oauth_status=oauth_status,
                )
                if provider["name"] == image_config.provider
            ),
            None,
        )
        if not selected_provider or not selected_provider["configured"]:
            raise WebUISettingsError("image generation provider is not configured")
    return changed


def update_transcription_settings(config: Config, query: QueryParams) -> bool:
    transcription = config.transcription
    changed = False

    enabled = query_first(query, "enabled")
    if enabled is not None:
        parsed_enabled = parse_bool(enabled, "enabled")
        if transcription.enabled != parsed_enabled:
            transcription.enabled = parsed_enabled
            changed = True

    provider = query_first(query, "provider")
    if provider is not None:
        provider = provider.strip().lower()
        provider_spec = resolve_transcription_provider(provider)
        if provider_spec is None:
            raise WebUISettingsError("unknown transcription provider")
        provider = provider_spec.name
        if transcription.provider != provider:
            transcription.provider = provider
            changed = True

    model = query_first(query, "model")
    if model is not None:
        model = model.strip() or None
        if model is not None and len(model) > 200:
            raise WebUISettingsError("transcription model is too long")
        if transcription.model != model:
            transcription.model = model
            changed = True

    language = query_first(query, "language")
    if language is not None:
        language = language.strip().lower() or None
        if language is not None and not re.fullmatch(r"[a-z]{2,3}", language):
            raise WebUISettingsError(
                "transcription language must be 2-3 lowercase letters"
            )
        if transcription.language != language:
            transcription.language = language
            changed = True

    max_duration_sec = query_first_alias(query, "max_duration_sec", "maxDurationSec")
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

    max_upload_mb = query_first_alias(query, "max_upload_mb", "maxUploadMb")
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
    return changed


def network_safety_payload(config: Config) -> dict[str, Any]:
    """Return the network-related fields embedded in the advanced DTO."""
    return {
        "webui_allow_local_service_access": config.tools.webui_allow_local_service_access,
        "allow_local_preview_access": config.tools.webui_allow_local_service_access,
        "webui_default_access_mode": read_webui_default_access_mode(),
        "private_service_protection_enabled": True,
        "ssrf_whitelist_count": len(config.tools.ssrf_whitelist),
    }


class CapabilitySettingsHandler:
    """Handle capability commands after transport authentication and decoding."""

    def __init__(self, settings: WebUISettingsServices, logger: Any) -> None:
        self.settings = settings
        self.logger = logger

    async def handle(
        self,
        action: str,
        request: SettingsRequest,
        operations: CapabilitySettingsOperations,
    ) -> SettingsRouteResult:
        mutation = {
            "web-search-update": (
                operations.update_web_search,
                "browser",
                False,
            ),
            "transcription-update": (
                operations.update_transcription,
                None,
                False,
            ),
            "network-update": (
                operations.update_network,
                "runtime",
                False,
            ),
            "image-update": (
                operations.update_image,
                "image",
                True,
            ),
        }.get(action)
        if mutation is None:
            return SettingsRouteResult.failure(404, "unknown settings action")

        operation, section, apply_image_reload = mutation
        try:
            payload = self.settings.mutate(operation, request.query)
        except WebUISettingsError as exc:
            return SettingsRouteResult.failure(exc.status, exc.message)
        if apply_image_reload:
            payload, image_restart_cleared = await self.apply_image_runtime_change(
                payload,
                operations.reload_image,
            )
        else:
            image_restart_cleared = False
        return SettingsRouteResult.success(
            payload,
            decorate_restart=True,
            restart_section=section,
            clear_restart_section=("image" if image_restart_cleared else None),
        )

    async def apply_image_runtime_change(
        self,
        payload: dict[str, Any],
        reload_image: Callable[[], Awaitable[dict[str, Any]]],
    ) -> tuple[dict[str, Any], bool]:
        """Hot-apply image settings, preserving restart fallback on failure."""
        if not payload.get("requires_restart"):
            return payload, False
        try:
            result = await reload_image()
        except Exception:
            self.logger.exception("failed to hot-reload image generation settings")
            return payload, False

        applied = bool(result.get("ok")) and not result.get("requires_restart")
        updated = dict(payload)
        updated["requires_restart"] = not applied
        if not applied:
            self.logger.warning(
                "image generation settings were saved but require restart: {}",
                result.get("message") or "hot reload failed",
            )
        return updated, applied
