"""Capability settings domain logic for Web, media, network, and API features."""

from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Awaitable, Callable, TypedDict

from nanobot.agent.tools.web import SEARCH_PROVIDER_OPTIONS
from nanobot.api.runtime import ApiRuntime, ApiStartOptions
from nanobot.audio.transcription import resolve_transcription_config
from nanobot.audio.transcription_registry import (
    resolve_transcription_provider,
    transcription_provider_names,
)
from nanobot.config.schema import Config
from nanobot.optional_features import (
    OptionalFeatureError,
    extra_installed,
    optional_dependency_groups,
)
from nanobot.providers.image_generation import (
    get_image_gen_provider,
    image_gen_provider_names,
)
from nanobot.providers.registry import find_by_name
from nanobot.security.network import is_loopback_host
from nanobot.webui.settings_contracts import (
    QueryParams,
    SettingsRequest,
    SettingsRouteResult,
    WebUISettingsError,
    parse_bool,
    query_first,
    query_first_alias,
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
    update_api: SettingsOperation
    update_image: SettingsOperation
    update_transcription: SettingsOperation
    update_network: SettingsOperation
    nanobot_features_action: SettingsOperation
    api_runtime: Callable[[], ApiRuntime]
    reload_image: Callable[[], Awaitable[dict[str, Any]]]


class CapabilitySettingsPayload(TypedDict):
    web_search: dict[str, Any]
    web: dict[str, Any]
    api: dict[str, Any]
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
    for name in image_gen_provider_names():
        image_provider = get_image_gen_provider(name)
        spec = find_by_name(name)
        provider_config = getattr(config.providers, name, None)
        configured = (
            provider_configured_for_settings(spec, provider_config, oauth_status)
            if spec is not None and provider_config is not None
            else bool(getattr(provider_config, "api_key", None))
        )
        rows.append(
            {
                "name": name,
                "label": spec.label if spec is not None else name,
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
            "api_key_hint": mask_secret_hint(config.api.api_key),
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


def update_api_settings(config: Config, query: QueryParams) -> None:
    """Update the managed OpenAI-compatible API configuration."""
    api = config.api
    host = query_first(query, "host")
    if host is not None:
        host = host.strip()
        if not host:
            raise WebUISettingsError("host is required")
        api.host = host

    port = query_first(query, "port")
    if port is not None:
        try:
            parsed_port = int(port)
        except ValueError:
            raise WebUISettingsError("port must be an integer") from None
        if parsed_port < 1 or parsed_port > 65535:
            raise WebUISettingsError("port must be between 1 and 65535")
        api.port = parsed_port

    timeout = query_first(query, "timeout")
    if timeout is not None:
        try:
            parsed_timeout = float(timeout)
        except ValueError:
            raise WebUISettingsError("timeout must be a number") from None
        if parsed_timeout < 1 or parsed_timeout > 3600:
            raise WebUISettingsError("timeout must be between 1 and 3600")
        api.timeout = parsed_timeout

    api_key = query_first_alias(query, "api_key", "apiKey")
    if api_key is not None:
        api.api_key = api_key.strip()
    if not is_loopback_host(api.host) and not api.api_key.strip():
        raise WebUISettingsError(
            "an API key is required when the API is available on the network"
        )


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
        provider_name = provider_name.strip().lower()
        if not provider_name:
            raise WebUISettingsError("image generation provider is required")
        if get_image_gen_provider(provider_name) is None:
            raise WebUISettingsError("unknown image generation provider")
        if image_config.provider != provider_name:
            image_config.provider = provider_name
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


def masked_api_secret(value: str) -> str | None:
    value = value.strip()
    if not value:
        return None
    return f"{value[:3]}...{value[-4:]}" if len(value) > 8 else "configured"


def api_runtime_message(message: str) -> str:
    known = {
        "api_exited_during_startup": "API server exited during startup. Check its log for details.",
        "api_stop_timeout": "API server did not stop in time.",
        "api_state_stale": "API server state was stale; try starting it again.",
    }
    if message in known:
        return known[message]
    if message.startswith("api_"):
        return f"API server {message.removeprefix('api_').replace('_', ' ')}"
    return message.replace("_", " ")


def api_service_payload(
    settings: WebUISettingsServices,
    runtime: ApiRuntime,
    *,
    last_action: str | None = None,
) -> dict[str, Any]:
    config = settings.config.load()
    status = runtime.status()
    extras = optional_dependency_groups()
    connect_host = (
        "127.0.0.1" if config.api.host in {"0.0.0.0", "::"} else config.api.host
    )
    payload = {
        "installed": extra_installed("api", extras.get("api")),
        "running": status.running,
        "managed": status.running,
        "host": config.api.host,
        "port": config.api.port,
        "timeout": config.api.timeout,
        "api_key_hint": masked_api_secret(config.api.api_key),
        "endpoint": f"http://{connect_host}:{config.api.port}/v1",
        "command": "nanobot serve",
        "log_path": str(status.log_path),
    }
    if last_action:
        payload["last_action"] = last_action
    return payload


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
        if action == "api-status":
            return SettingsRouteResult.success(
                api_service_payload(self.settings, operations.api_runtime())
            )
        if action == "api-start":
            return await self._start_api(request, operations)
        if action == "api-stop":
            return await self._stop_api(operations)

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

    async def _start_api(
        self,
        request: SettingsRequest,
        operations: CapabilitySettingsOperations,
    ) -> SettingsRouteResult:
        api_key = (request.payload or {}).get("api_key")
        if api_key is not None and not isinstance(api_key, str):
            return SettingsRouteResult.failure(
                400,
                "API service API key must be a string",
            )
        try:
            await asyncio.to_thread(
                self.settings.mutate,
                operations.nanobot_features_action,
                "enable",
                {"name": ["api"]},
                allow_install=self._allow_feature_package_install(request),
            )
            self.settings.mutate(operations.update_api, request.query)
            config = self.settings.config.load()
            runtime = operations.api_runtime()
            options = ApiStartOptions(
                host=config.api.host,
                port=config.api.port,
                workspace=str(config.workspace_path),
                config_path=str(self.settings.config.path),
            )
            current = runtime.status()
            result = await asyncio.to_thread(
                runtime.restart if current.running else runtime.start_background,
                options,
            )
            if not result.ok:
                return SettingsRouteResult.failure(
                    500,
                    api_runtime_message(result.message),
                )
        except (WebUISettingsError, OptionalFeatureError) as exc:
            return SettingsRouteResult.failure(
                getattr(exc, "status", 400),
                getattr(exc, "message", str(exc)),
            )
        except Exception as exc:
            self.logger.exception("failed to start managed API service")
            return SettingsRouteResult.failure(500, str(exc))
        return SettingsRouteResult.success(
            api_service_payload(
                self.settings,
                operations.api_runtime(),
                last_action="started",
            )
        )

    async def _stop_api(
        self,
        operations: CapabilitySettingsOperations,
    ) -> SettingsRouteResult:
        runtime = operations.api_runtime()
        try:
            result = await asyncio.to_thread(runtime.stop)
        except Exception as exc:
            self.logger.exception("failed to stop managed API service")
            return SettingsRouteResult.failure(500, str(exc))
        if not result.ok and result.message != "api_not_running":
            return SettingsRouteResult.failure(
                500,
                api_runtime_message(result.message),
            )
        return SettingsRouteResult.success(
            api_service_payload(
                self.settings,
                operations.api_runtime(),
                last_action="stopped",
            )
        )

    def _allow_feature_package_install(self, request: SettingsRequest) -> bool:
        if request.local_browser:
            return True
        try:
            return bool(
                self.settings.config.load().tools.webui_allow_remote_package_install
            )
        except Exception:
            self.logger.exception("failed to load remote package install policy")
            return False
