"""HTTP route adapter for WebUI Settings APIs.

Keep WebUI Settings route handlers here, not in ``channels/websocket.py``.
The websocket channel owns transport concerns; this module owns WebUI Settings
request mapping and response shaping.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import unquote

from websockets.http11 import Request as WsRequest
from websockets.http11 import Response

from nanobot.agent.tools.image_generation import request_image_generation_reload
from nanobot.agent.tools.mcp import request_mcp_reload
from nanobot.api.runtime import ApiRuntime, ApiStartOptions, api_runtime_paths
from nanobot.bus.queue import MessageBus
from nanobot.channels._setup import channel_setup_spec
from nanobot.channels.connect import ChannelConnectError
from nanobot.channels.contracts import (
    channel_instance_config,
    channel_update_instance_config,
)
from nanobot.channels.registry import load_channel_plugin
from nanobot.channels.validation import validate_channel_config
from nanobot.config.loader import get_config_path, load_config, save_config
from nanobot.optional_features import (
    OptionalFeatureError,
    extra_installed,
    optional_dependency_groups,
    with_channel_runtime_status,
)
from nanobot.pairing import approve_code, deny_code, list_pending
from nanobot.webui.cli_apps_api import cli_apps_action, cli_apps_payload
from nanobot.webui.http_utils import case_insensitive_header
from nanobot.webui.http_utils import is_local_browser_request as _is_local_browser_request
from nanobot.webui.http_utils import query_first as _query_first
from nanobot.webui.mcp_presets_api import mcp_presets_settings_action
from nanobot.webui.nanobot_features_api import (
    nanobot_feature_instance_target,
    nanobot_features_action,
    nanobot_features_payload,
)
from nanobot.webui.settings_api import (
    WebUISettingsError,
    complete_oauth_provider,
    create_model_configuration,
    create_provider_settings,
    decorate_settings_payload,
    delete_model_configuration,
    login_oauth_provider,
    logout_oauth_provider,
    migrate_model_configurations,
    provider_models_payload,
    settings_payload,
    settings_usage_payload,
    update_agent_settings,
    update_api_settings,
    update_image_generation_settings,
    update_model_call_order,
    update_model_configuration,
    update_network_safety_settings,
    update_provider_settings,
    update_transcription_settings,
    update_web_search_settings,
)
from nanobot.webui.version_check import check_for_update

QueryParams = dict[str, list[str]]

_MCP_VALUES_HEADER = "X-Nanobot-MCP-Values"
_MCP_VALUES_HEADER_MAX_BYTES = 64 * 1024
_PROVIDER_VALUES_HEADER = "X-Nanobot-Provider-Values"
_PROVIDER_VALUES_HEADER_MAX_BYTES = 64 * 1024
_CHANNEL_VALUES_HEADER = "X-Nanobot-Channel-Values"
_CHANNEL_VALUES_HEADER_MAX_BYTES = 64 * 1024
_API_SERVICE_VALUES_HEADER = "X-Nanobot-API-Service-Values"
_API_SERVICE_VALUES_HEADER_MAX_BYTES = 8 * 1024
_OAUTH_CODE_HEADER = "X-Nanobot-OAuth-Code"
_OAUTH_CODE_HEADER_MAX_BYTES = 8 * 1024

_SKIP_FIELD = object()
_CHANNEL_CONNECT_ACTIONS = frozenset({"start", "poll", "cancel"})


def _channel_connect_route(path: str) -> tuple[str, str] | None:
    prefix = "/api/settings/channels/"
    if not path.startswith(prefix):
        return None
    parts = path.removeprefix(prefix).split("/")
    if len(parts) != 3 or parts[1] != "connect" or parts[2] not in _CHANNEL_CONNECT_ACTIONS:
        return None
    channel_name = parts[0].strip()
    return (channel_name, parts[2]) if channel_name else None

_MCP_PRESET_ACTIONS_BY_PATH = {
    "/api/settings/mcp-presets/enable": "enable",
    "/api/settings/mcp-presets/remove": "remove",
    "/api/settings/mcp-presets/test": "test",
    "/api/settings/mcp-presets/custom": "custom",
    "/api/settings/mcp-presets/import": "import",
    "/api/settings/mcp-presets/import-cursor": "import-cursor",
    "/api/settings/mcp-presets/tools": "tools",
}


class WebUISettingsRouter:
    """Route WebUI Settings HTTP requests behind a transport-neutral boundary."""

    def __init__(
        self,
        *,
        bus: MessageBus,
        logger: Any,
        check_api_token: Callable[[WsRequest], bool],
        parse_query: Callable[[str], QueryParams],
        json_response: Callable[[dict[str, Any]], Response],
        error_response: Callable[[int, str | None], Response],
        runtime_surface: str,
        runtime_capabilities: dict[str, Any],
        channel_feature_action: Callable[..., Any] | None = None,
        channel_runtime_status: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self.bus = bus
        self.logger = logger
        self._check_api_token = check_api_token
        self._parse_query = parse_query
        self._json_response = json_response
        self._error_response = error_response
        self._runtime_surface = runtime_surface
        self._runtime_capabilities = runtime_capabilities
        self._channel_feature_action = channel_feature_action
        self._channel_runtime_status = channel_runtime_status
        self._restart_sections: set[str] = set()
        self._channel_connectors: dict[str, Any] = {}

    async def dispatch(self, connection: Any, request: WsRequest, path: str) -> Response | None:
        if path == "/api/settings":
            return self._handle_settings(request)
        if path == "/api/settings/usage":
            return self._handle_settings_usage(request)
        if path == "/api/settings/update":
            return self._handle_settings_update(request)
        if path == "/api/settings/model-configurations/create":
            return self._handle_settings_model_configuration_create(request)
        if path == "/api/settings/model-configurations/update":
            return self._handle_settings_model_configuration_update(request)
        if path == "/api/settings/model-configurations/delete":
            return self._handle_settings_model_configuration_delete(request)
        if path == "/api/settings/model-configurations/migrate":
            return self._handle_settings_model_configurations_migrate(request)
        if path == "/api/settings/model-call-order/update":
            return self._handle_settings_model_call_order_update(request)
        if path == "/api/settings/provider/update":
            return await self._handle_settings_provider_update(request)
        if path == "/api/settings/provider/create":
            return self._handle_settings_provider_create(request)
        if path == "/api/settings/provider-models":
            return await self._handle_settings_provider_models(request)
        if path == "/api/settings/provider/oauth-login":
            return await self._handle_settings_provider_oauth(request, "login")
        if path == "/api/settings/provider/oauth-login/complete":
            return await self._handle_settings_provider_oauth(request, "complete")
        if path == "/api/settings/provider/oauth-logout":
            return await self._handle_settings_provider_oauth(request, "logout")
        if path == "/api/settings/web-search/update":
            return self._handle_settings_web_search_update(request)
        if path == "/api/settings/api-service":
            return self._handle_settings_api_service(request)
        if path == "/api/settings/api-service/start":
            return await self._handle_settings_api_service_start(connection, request)
        if path == "/api/settings/api-service/stop":
            return await self._handle_settings_api_service_stop(request)
        if path == "/api/settings/image-generation/update":
            return await self._handle_settings_image_generation_update(request)
        if path == "/api/settings/transcription/update":
            return self._handle_settings_transcription_update(request)
        if path == "/api/settings/network-safety/update":
            return self._handle_settings_network_safety_update(request)
        if path == "/api/settings/cli-apps":
            return await self._handle_settings_cli_apps(request)
        if path == "/api/settings/cli-apps/install":
            return await self._handle_settings_cli_apps_action(request, "install")
        if path == "/api/settings/cli-apps/update":
            return await self._handle_settings_cli_apps_action(request, "update")
        if path == "/api/settings/cli-apps/uninstall":
            return await self._handle_settings_cli_apps_action(request, "uninstall")
        if path == "/api/settings/cli-apps/test":
            return await self._handle_settings_cli_apps_action(request, "test")
        if path == "/api/settings/nanobot-features":
            return await self._handle_settings_nanobot_features(request)
        if path == "/api/settings/nanobot-features/enable":
            return await self._handle_settings_nanobot_features_action(connection, request, "enable")
        if path == "/api/settings/nanobot-features/disable":
            return await self._handle_settings_nanobot_features_action(connection, request, "disable")
        channel_connect = _channel_connect_route(path)
        if channel_connect is not None:
            channel_name, action = channel_connect
            return await self._handle_settings_channel_connect(
                connection,
                request,
                channel_name,
                action,
            )
        if path == "/api/settings/channels/validate":
            return await self._handle_settings_channel_validate(request)
        if path == "/api/settings/channels/configure":
            return await self._handle_settings_channel_configure(connection, request)
        if path == "/api/settings/pairing":
            return self._handle_settings_pairing(request)
        if path == "/api/settings/pairing/approve":
            return self._handle_settings_pairing_action(request, "approve")
        if path == "/api/settings/pairing/deny":
            return self._handle_settings_pairing_action(request, "deny")
        if path == "/api/settings/mcp-presets":
            return await self._handle_settings_mcp_presets(request)
        if path == "/api/settings/version-check":
            return await self._handle_settings_version_check(request)
        mcp_action = _MCP_PRESET_ACTIONS_BY_PATH.get(path)
        if mcp_action is not None:
            return await self._handle_settings_mcp_presets(request, mcp_action)
        return None

    def _query(self, request: WsRequest) -> QueryParams:
        return self._parse_query(request.path)

    def _authorized(self, request: WsRequest) -> bool:
        return self._check_api_token(request)

    def _unauthorized(self) -> Response:
        return self._error_response(401, "Unauthorized")

    def _with_restart_state(
        self,
        payload: dict[str, Any],
        *,
        section: str | None = None,
    ) -> dict[str, Any]:
        """Keep restart-required state alive for this gateway process."""
        if section and payload.get("requires_restart"):
            self._restart_sections.add(section)
        sections = sorted(self._restart_sections)
        payload = dict(payload)
        if sections:
            payload["requires_restart"] = True
        return decorate_settings_payload(
            payload,
            surface=self._runtime_surface,
            runtime_capability_overrides=self._runtime_capabilities,
            restart_required_sections=sections,
        )

    def _parse_mcp_settings_query(self, request: WsRequest) -> QueryParams:
        query = self._query(request)
        raw = request.headers.get(_MCP_VALUES_HEADER)
        if not raw:
            return query
        if len(raw.encode("utf-8")) > _MCP_VALUES_HEADER_MAX_BYTES:
            raise WebUISettingsError("MCP settings payload is too large")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise WebUISettingsError("invalid MCP settings payload") from exc
        if not isinstance(payload, dict):
            raise WebUISettingsError("MCP settings payload must be a JSON object")
        merged = {key: list(values) for key, values in query.items()}
        for key, value in payload.items():
            if not isinstance(key, str) or not key:
                raise WebUISettingsError("MCP settings payload contains an invalid key")
            if value is None:
                continue
            if isinstance(value, str):
                text = value.strip()
            else:
                text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            if text:
                merged[key] = [text]
        return merged

    def _parse_provider_settings_query(self, request: WsRequest) -> QueryParams:
        query = self._query(request)
        raw = request.headers.get(_PROVIDER_VALUES_HEADER)
        if not raw:
            return query
        if len(raw.encode("utf-8")) > _PROVIDER_VALUES_HEADER_MAX_BYTES:
            raise WebUISettingsError("provider settings payload is too large")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            try:
                payload = json.loads(unquote(raw))
            except json.JSONDecodeError:
                raise WebUISettingsError("invalid provider settings payload") from exc
        if not isinstance(payload, dict):
            raise WebUISettingsError("provider settings payload must be a JSON object")

        merged = {key: list(values) for key, values in query.items()}
        for key, value in payload.items():
            if not isinstance(key, str) or not key:
                raise WebUISettingsError("provider settings payload contains an invalid key")
            if isinstance(value, str):
                text = value
            elif value is None:
                text = ""
            else:
                text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            merged[key] = [text]
        return merged

    def _handle_settings(self, request: WsRequest) -> Response:
        if not self._authorized(request):
            return self._unauthorized()
        return self._json_response(
            self._with_restart_state(
                settings_payload(
                    surface=self._runtime_surface,
                    runtime_capability_overrides=self._runtime_capabilities,
                )
            )
        )

    def _handle_settings_usage(self, request: WsRequest) -> Response:
        if not self._authorized(request):
            return self._unauthorized()
        return self._json_response(settings_usage_payload())

    def _handle_settings_pairing(self, request: WsRequest) -> Response:
        if not self._authorized(request):
            return self._unauthorized()
        return self._json_response(_pairing_payload())

    def _handle_settings_pairing_action(self, request: WsRequest, action: str) -> Response:
        if not self._authorized(request):
            return self._unauthorized()
        query = self._query(request)
        code = (_query_first(query, "code") or "").strip()
        if not code:
            return self._error_response(400, "Missing pairing code")

        if action == "approve":
            result = approve_code(code)
            if result is None:
                return self._error_response(404, "Pairing code not found or expired")
            channel, sender_id = result
            return self._json_response(
                _pairing_payload({
                    "ok": True,
                    "action": "approve",
                    "message": f"Approved {sender_id} for {channel}",
                    "channel": channel,
                    "sender_id": sender_id,
                    "code": code,
                })
            )

        if not deny_code(code):
            return self._error_response(404, "Pairing code not found or expired")
        return self._json_response(
            _pairing_payload({
                "ok": True,
                "action": "deny",
                "message": f"Denied pairing code {code}",
                "code": code,
            })
        )

    def _handle_settings_update(self, request: WsRequest) -> Response:
        if not self._authorized(request):
            return self._unauthorized()
        try:
            payload = update_agent_settings(self._query(request))
        except WebUISettingsError as e:
            return self._error_response(e.status, e.message)
        return self._json_response(self._with_restart_state(payload, section="runtime"))

    def _handle_settings_model_configuration_create(self, request: WsRequest) -> Response:
        if not self._authorized(request):
            return self._unauthorized()
        try:
            payload = create_model_configuration(self._query(request))
        except WebUISettingsError as e:
            return self._error_response(e.status, e.message)
        return self._json_response(self._with_restart_state(payload))

    def _handle_settings_model_configuration_update(self, request: WsRequest) -> Response:
        if not self._authorized(request):
            return self._unauthorized()
        try:
            payload = update_model_configuration(self._query(request))
        except WebUISettingsError as e:
            return self._error_response(e.status, e.message)
        return self._json_response(self._with_restart_state(payload))

    def _handle_settings_model_configuration_delete(self, request: WsRequest) -> Response:
        if not self._authorized(request):
            return self._unauthorized()
        try:
            payload = delete_model_configuration(self._query(request))
        except WebUISettingsError as e:
            return self._error_response(e.status, e.message)
        return self._json_response(self._with_restart_state(payload))

    def _handle_settings_model_configurations_migrate(self, request: WsRequest) -> Response:
        if not self._authorized(request):
            return self._unauthorized()
        try:
            payload = migrate_model_configurations(self._query(request))
        except WebUISettingsError as e:
            return self._error_response(e.status, e.message)
        return self._json_response(self._with_restart_state(payload))

    def _handle_settings_model_call_order_update(self, request: WsRequest) -> Response:
        if not self._authorized(request):
            return self._unauthorized()
        try:
            payload = update_model_call_order(self._query(request))
        except WebUISettingsError as e:
            return self._error_response(e.status, e.message)
        return self._json_response(self._with_restart_state(payload))

    async def _handle_settings_provider_update(self, request: WsRequest) -> Response:
        if not self._authorized(request):
            return self._unauthorized()
        try:
            payload = update_provider_settings(self._parse_provider_settings_query(request))
        except WebUISettingsError as e:
            return self._error_response(e.status, e.message)
        payload = await self._apply_image_generation_runtime_change(payload)
        return self._json_response(self._with_restart_state(payload, section="image"))

    def _handle_settings_provider_create(self, request: WsRequest) -> Response:
        if not self._authorized(request):
            return self._unauthorized()
        try:
            payload = create_provider_settings(self._parse_provider_settings_query(request))
        except WebUISettingsError as e:
            return self._error_response(e.status, e.message)
        return self._json_response(self._with_restart_state(payload))

    async def _handle_settings_provider_models(self, request: WsRequest) -> Response:
        if not self._authorized(request):
            return self._unauthorized()
        try:
            payload = await asyncio.to_thread(provider_models_payload, self._query(request))
        except WebUISettingsError as e:
            return self._error_response(e.status, e.message)
        except Exception:
            self.logger.exception("failed to load provider model list")
            return self._error_response(500, "failed to load provider model list")
        return self._json_response(payload)

    async def _handle_settings_provider_oauth(
        self,
        request: WsRequest,
        action: str,
    ) -> Response:
        if not self._authorized(request):
            return self._unauthorized()
        query = self._query(request)
        try:
            if action == "login":
                payload = await asyncio.to_thread(login_oauth_provider, query)
            elif action == "complete":
                authorization_code = case_insensitive_header(
                    request.headers,
                    _OAUTH_CODE_HEADER,
                )
                if len(authorization_code.encode("utf-8")) > _OAUTH_CODE_HEADER_MAX_BYTES:
                    raise WebUISettingsError("OAuth authorization code is too large")
                payload = await asyncio.to_thread(
                    complete_oauth_provider,
                    query,
                    authorization_code or None,
                )
            else:
                payload = await asyncio.to_thread(logout_oauth_provider, query)
        except WebUISettingsError as e:
            return self._error_response(e.status, e.message)
        if payload.get("status") in {"authorization_required", "pending"}:
            return self._json_response(payload)
        return self._json_response(self._with_restart_state(payload))

    def _handle_settings_web_search_update(self, request: WsRequest) -> Response:
        if not self._authorized(request):
            return self._unauthorized()
        try:
            payload = update_web_search_settings(self._query(request))
        except WebUISettingsError as e:
            return self._error_response(e.status, e.message)
        return self._json_response(self._with_restart_state(payload, section="browser"))

    def _handle_settings_api_service(self, request: WsRequest) -> Response:
        if not self._authorized(request):
            return self._unauthorized()
        return self._json_response(self._api_service_payload())

    async def _handle_settings_api_service_start(
        self,
        connection: Any,
        request: WsRequest,
    ) -> Response:
        if not self._authorized(request):
            return self._unauthorized()
        try:
            await asyncio.to_thread(
                nanobot_features_action,
                "enable",
                {"name": ["api"]},
                allow_install=self._allow_feature_package_install(connection, request),
            )
            update_api_settings(self._parse_api_service_settings_query(request))
            config = load_config()
            runtime = self._api_runtime()
            options = ApiStartOptions(
                host=config.api.host,
                port=config.api.port,
                workspace=str(config.workspace_path),
                config_path=str(get_config_path().expanduser().resolve(strict=False)),
            )
            current = runtime.status()
            result = await asyncio.to_thread(
                runtime.restart if current.running else runtime.start_background,
                options,
            )
            if not result.ok:
                return self._error_response(500, self._api_runtime_message(result.message))
        except (WebUISettingsError, OptionalFeatureError) as e:
            return self._error_response(getattr(e, "status", 400), getattr(e, "message", str(e)))
        except Exception as e:
            self.logger.exception("failed to start managed API service")
            return self._error_response(500, str(e))
        return self._json_response(self._api_service_payload(last_action="started"))

    def _parse_api_service_settings_query(self, request: WsRequest) -> QueryParams:
        query = self._query(request)
        if "api_key" in query or "apiKey" in query:
            raise WebUISettingsError("API service API key must be provided in the private header")
        raw = request.headers.get(_API_SERVICE_VALUES_HEADER)
        if not raw:
            return query
        if len(raw.encode("utf-8")) > _API_SERVICE_VALUES_HEADER_MAX_BYTES:
            raise WebUISettingsError("API service settings payload is too large")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise WebUISettingsError("invalid API service settings payload") from exc
        if not isinstance(payload, dict):
            raise WebUISettingsError("API service settings payload must be a JSON object")

        unknown = set(payload) - {"api_key"}
        if unknown:
            raise WebUISettingsError("API service settings payload contains an invalid key")
        api_key = payload.get("api_key")
        if api_key is not None and not isinstance(api_key, str):
            raise WebUISettingsError("API service API key must be a string")

        merged = {key: list(values) for key, values in query.items() if key != "api_key"}
        if api_key is not None:
            merged["api_key"] = [api_key]
        return merged

    async def _handle_settings_api_service_stop(self, request: WsRequest) -> Response:
        if not self._authorized(request):
            return self._unauthorized()
        try:
            result = await asyncio.to_thread(self._api_runtime().stop)
        except Exception as e:
            self.logger.exception("failed to stop managed API service")
            return self._error_response(500, str(e))
        if not result.ok and result.message != "api_not_running":
            return self._error_response(500, self._api_runtime_message(result.message))
        return self._json_response(self._api_service_payload(last_action="stopped"))

    @staticmethod
    def _api_runtime() -> ApiRuntime:
        config_path = get_config_path().expanduser().resolve(strict=False)
        return ApiRuntime(paths=api_runtime_paths(config_path))

    def _api_service_payload(self, *, last_action: str | None = None) -> dict[str, Any]:
        config = load_config()
        status = self._api_runtime().status()
        extras = optional_dependency_groups()
        connect_host = "127.0.0.1" if config.api.host in {"0.0.0.0", "::"} else config.api.host
        payload = {
            "installed": extra_installed("api", extras.get("api")),
            "running": status.running,
            "managed": status.running,
            "host": config.api.host,
            "port": config.api.port,
            "timeout": config.api.timeout,
            "api_key_hint": self._masked_secret(config.api.api_key),
            "endpoint": f"http://{connect_host}:{config.api.port}/v1",
            "command": "nanobot serve",
            "log_path": str(status.log_path),
        }
        if last_action:
            payload["last_action"] = last_action
        return payload

    @staticmethod
    def _masked_secret(value: str) -> str | None:
        value = value.strip()
        if not value:
            return None
        return f"{value[:3]}...{value[-4:]}" if len(value) > 8 else "configured"

    @staticmethod
    def _api_runtime_message(message: str) -> str:
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

    async def _handle_settings_image_generation_update(self, request: WsRequest) -> Response:
        if not self._authorized(request):
            return self._unauthorized()
        try:
            payload = update_image_generation_settings(self._query(request))
        except WebUISettingsError as e:
            return self._error_response(e.status, e.message)
        payload = await self._apply_image_generation_runtime_change(payload)
        return self._json_response(self._with_restart_state(payload, section="image"))

    async def _apply_image_generation_runtime_change(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Hot-apply image settings, preserving restart fallback on failure."""
        if not payload.get("requires_restart"):
            return payload
        try:
            result = await request_image_generation_reload(self.bus)
        except Exception:
            self.logger.exception("failed to hot-reload image generation settings")
            return payload

        applied = bool(result.get("ok")) and not result.get("requires_restart")
        payload = dict(payload)
        payload["requires_restart"] = not applied
        if applied:
            self._restart_sections.discard("image")
        else:
            self.logger.warning(
                "image generation settings were saved but require restart: {}",
                result.get("message") or "hot reload failed",
            )
        return payload

    def _handle_settings_transcription_update(self, request: WsRequest) -> Response:
        if not self._authorized(request):
            return self._unauthorized()
        try:
            payload = update_transcription_settings(self._query(request))
        except WebUISettingsError as e:
            return self._error_response(e.status, e.message)
        return self._json_response(self._with_restart_state(payload))

    def _handle_settings_network_safety_update(self, request: WsRequest) -> Response:
        if not self._authorized(request):
            return self._unauthorized()
        try:
            payload = update_network_safety_settings(self._query(request))
        except WebUISettingsError as e:
            return self._error_response(e.status, e.message)
        return self._json_response(self._with_restart_state(payload, section="runtime"))

    async def _handle_settings_cli_apps(self, request: WsRequest) -> Response:
        if not self._authorized(request):
            return self._unauthorized()
        installed_only = (_query_first(self._query(request), "installed_only") or "").lower() in {
            "1",
            "true",
            "yes",
        }
        try:
            payload = await cli_apps_payload(installed_only=installed_only)
        except Exception:
            self.logger.exception("failed to load CLI Apps payload")
            return self._error_response(500, "failed to load CLI Apps")
        return self._json_response(payload)

    async def _handle_settings_cli_apps_action(
        self,
        request: WsRequest,
        action: str,
    ) -> Response:
        if not self._authorized(request):
            return self._unauthorized()
        try:
            payload = await asyncio.to_thread(cli_apps_action, action, self._query(request))
        except WebUISettingsError as e:
            return self._error_response(e.status, e.message)
        except Exception as e:
            status = getattr(e, "status", 500)
            message = getattr(e, "message", str(e))
            if status >= 500:
                self.logger.exception("CLI Apps action '{}' failed", action)
            return self._error_response(status, message)
        return self._json_response(payload)

    async def _handle_settings_nanobot_features(self, request: WsRequest) -> Response:
        if not self._authorized(request):
            return self._unauthorized()
        try:
            payload = await asyncio.to_thread(nanobot_features_payload)
        except Exception:
            self.logger.exception("failed to load nanobot features")
            return self._error_response(500, "failed to load nanobot features")
        return self._json_response(self._with_channel_runtime_status(payload))

    async def _handle_settings_nanobot_features_action(
        self,
        connection: Any,
        request: WsRequest,
        action: str,
    ) -> Response:
        if not self._authorized(request):
            return self._unauthorized()
        try:
            payload = await asyncio.to_thread(
                nanobot_features_action,
                action,
                self._query(request),
                allow_install=action != "enable"
                or self._allow_feature_package_install(connection, request),
            )
        except OptionalFeatureError as e:
            return self._error_response(e.status, e.message)
        except Exception as e:
            status = getattr(e, "status", 500)
            message = getattr(e, "message", str(e))
            if status >= 500:
                self.logger.exception("nanobot feature action '{}' failed", action)
            return self._error_response(status, message)
        payload = await self._apply_nanobot_feature_runtime_change(
            action,
            self._query(request),
            payload,
        )
        payload = self._with_channel_runtime_status(payload)
        return self._json_response(self._with_restart_state(payload, section="runtime"))

    def _with_channel_runtime_status(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._channel_runtime_status is None:
            return payload
        try:
            return with_channel_runtime_status(payload, self._channel_runtime_status())
        except Exception:
            self.logger.exception("failed to load channel runtime status")
            return payload

    async def _apply_nanobot_feature_runtime_change(
        self,
        action: str,
        query: QueryParams,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if self._channel_feature_action is None:
            return payload

        name = (_query_first(query, "name") or "").strip()
        if not name:
            return payload

        try:
            instance_id = nanobot_feature_instance_target(query)
            result = self._channel_feature_action(action, name, instance_id)
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:
            self.logger.exception("failed to apply channel '{}' without restart", name)
            return self._feature_runtime_fallback(
                payload,
                message=f"{name} channel config was saved, but hot reload failed: {exc}",
            )

        if not isinstance(result, dict) or not result.get("handled"):
            return payload

        payload = dict(payload)
        if result.get("requires_restart"):
            payload["requires_restart"] = True
        else:
            payload["requires_restart"] = False

        message = result.get("message")
        if isinstance(message, str) and message:
            last_action = dict(payload.get("last_action") or {})
            previous = last_action.get("message")
            if isinstance(previous, str) and previous:
                last_action["message"] = f"{previous}. {message}"
            else:
                last_action["message"] = message
            last_action["hot_reload"] = not payload["requires_restart"]
            if "ok" in result:
                last_action["ok"] = bool(result["ok"])
            payload["last_action"] = last_action
        return payload

    @staticmethod
    def _feature_runtime_fallback(payload: dict[str, Any], *, message: str) -> dict[str, Any]:
        payload = dict(payload)
        payload["requires_restart"] = True
        last_action = dict(payload.get("last_action") or {})
        previous = last_action.get("message")
        last_action["message"] = f"{previous}. {message}" if isinstance(previous, str) and previous else message
        last_action["hot_reload"] = False
        payload["last_action"] = last_action
        return payload

    async def _handle_settings_channel_configure(
        self,
        connection: Any,
        request: WsRequest,
    ) -> Response:
        if not self._authorized(request):
            return self._unauthorized()
        query = self._query(request)
        name = (_query_first(query, "name") or "").strip()
        instance_id = (_query_first(query, "instance_id") or "default").strip()
        enable = (_query_first(query, "enable") or "").strip().lower() in {"1", "true", "yes"}
        try:
            saved = await asyncio.to_thread(
                self._save_channel_config_values,
                name,
                self._parse_channel_values_header(request),
                instance_id,
            )
        except WebUISettingsError as e:
            return self._error_response(e.status, e.message)
        except Exception:
            self.logger.exception("failed to save channel '{}' settings", name)
            return self._error_response(500, "failed to save channel settings")

        payload: dict[str, Any] = {
            "name": name,
            "saved": True,
            "saved_keys": saved,
        }
        if not enable:
            features = await asyncio.to_thread(nanobot_features_payload)
            features = self._with_channel_runtime_status(features)
            payload["nanobot_features"] = self._with_restart_state(features, section="runtime")
            return self._json_response(payload)

        feature_query = {"name": [name]}
        if instance_id:
            feature_query["instance_id"] = [instance_id]

        try:
            features = await asyncio.to_thread(
                nanobot_features_action,
                "enable",
                feature_query,
                allow_install=self._allow_feature_package_install(connection, request),
            )
        except OptionalFeatureError as e:
            return self._error_response(e.status, f"Settings saved, but {e.message}")
        except Exception as e:
            self.logger.exception("failed to enable channel '{}' after settings save", name)
            return self._error_response(500, f"Settings saved, but enabling {name} failed: {e}")

        features = await self._apply_nanobot_feature_runtime_change(
            "enable",
            feature_query,
            features,
        )
        features = self._with_channel_runtime_status(features)
        payload["nanobot_features"] = self._with_restart_state(features, section="runtime")
        return self._json_response(payload)

    async def _handle_settings_channel_validate(self, request: WsRequest) -> Response:
        if not self._authorized(request):
            return self._unauthorized()
        query = self._query(request)
        name = (_query_first(query, "name") or "").strip()
        instance_id = (_query_first(query, "instance_id") or "default").strip()
        try:
            payload = await asyncio.to_thread(
                validate_channel_config,
                name,
                self._parse_channel_values_header(request),
                instance_id=instance_id,
            )
        except WebUISettingsError as e:
            return self._error_response(e.status, e.message)
        except Exception:
            self.logger.exception("failed to validate channel '{}' settings", name)
            return self._error_response(500, "failed to validate channel settings")
        return self._json_response(payload)

    def _parse_channel_values_header(self, request: WsRequest) -> dict[str, Any]:
        raw = request.headers.get(_CHANNEL_VALUES_HEADER)
        if not raw:
            return {}
        if len(raw.encode("utf-8")) > _CHANNEL_VALUES_HEADER_MAX_BYTES:
            raise WebUISettingsError("channel settings payload is too large")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise WebUISettingsError("invalid channel settings payload") from exc
        if not isinstance(payload, dict):
            raise WebUISettingsError("channel settings payload must be a JSON object")
        return payload

    def _save_channel_config_values(
        self,
        name: str,
        raw_values: dict[str, Any],
        instance_id: str = "default",
    ) -> list[str]:
        if not name:
            raise WebUISettingsError("missing channel name")
        try:
            plugin = load_channel_plugin(name)
        except ImportError:
            raise WebUISettingsError(f"unknown channel '{name}'", status=404) from None
        setup_spec = channel_setup_spec(name, plugin=plugin)
        if setup_spec is None:
            raise WebUISettingsError(f"channel '{name}' cannot be configured from WebUI", status=404)
        field_types = setup_spec.route_field_types
        if not raw_values:
            return []

        config = load_config()
        section = getattr(config.channels, name, None)
        channel_config = channel_instance_config(
            plugin,
            section,
            instance_id=instance_id,
        )

        saved: list[str] = []
        prefix = f"channels.{name}."
        for raw_key, raw_value in raw_values.items():
            if not isinstance(raw_key, str) or not raw_key:
                raise WebUISettingsError("channel settings payload contains an invalid key")
            field = raw_key[len(prefix):] if raw_key.startswith(prefix) else raw_key
            value_type = field_types.get(field)
            if value_type is None:
                raise WebUISettingsError(f"'{raw_key}' cannot be configured from WebUI")
            value = self._coerce_channel_value(raw_key, raw_value, value_type)
            if value is _SKIP_FIELD:
                continue
            self._assign_channel_config_value(channel_config, field, value)
            saved.append(raw_key)

        try:
            updated_section = channel_update_instance_config(
                plugin,
                section,
                channel_config,
                instance_id=instance_id,
            )
        except ValueError as exc:
            raise WebUISettingsError(
                f"Invalid {name} configuration: {exc}",
                status=400,
            ) from exc
        setattr(config.channels, name, updated_section)
        save_config(config)
        return saved

    @staticmethod
    def _coerce_channel_value(raw_key: str, raw_value: Any, value_type: Any) -> Any:
        if isinstance(value_type, tuple):
            kind = value_type[0]
            allowed = value_type[1]
        else:
            kind = value_type
            allowed = None

        if kind in {"string", "secret"}:
            value = raw_value.strip() if isinstance(raw_value, str) else str(raw_value)
            if kind == "secret" and not value:
                return _SKIP_FIELD
            return value

        if kind == "list":
            if raw_value is None:
                return []
            if isinstance(raw_value, str):
                return [item.strip() for item in raw_value.split(",") if item.strip()]
            if isinstance(raw_value, list):
                return [str(item).strip() for item in raw_value if str(item).strip()]
            raise WebUISettingsError(f"'{raw_key}' must be a comma-separated list")

        if kind == "int":
            if raw_value in (None, ""):
                return _SKIP_FIELD
            try:
                return int(raw_value)
            except (TypeError, ValueError) as exc:
                raise WebUISettingsError(f"'{raw_key}' must be a number") from exc

        if kind == "bool":
            if isinstance(raw_value, bool):
                return raw_value
            value = str(raw_value).strip().lower()
            if value in {"true", "1", "yes", "on"}:
                return True
            if value in {"false", "0", "no", "off"}:
                return False
            raise WebUISettingsError(f"'{raw_key}' must be true or false")

        if kind == "enum":
            value = raw_value.strip() if isinstance(raw_value, str) else str(raw_value)
            if not value:
                return _SKIP_FIELD
            if value not in allowed:
                options = ", ".join(sorted(allowed))
                raise WebUISettingsError(f"'{raw_key}' must be one of: {options}")
            return value

        raise WebUISettingsError(f"'{raw_key}' has an unsupported field type")

    @staticmethod
    def _assign_channel_config_value(channel_config: dict[str, Any], field: str, value: Any) -> None:
        target = channel_config
        parts = field.split(".")
        for part in parts[:-1]:
            current = target.get(part)
            if not isinstance(current, dict):
                current = {}
                target[part] = current
            target = current
        target[parts[-1]] = value

    async def _handle_settings_channel_connect(
        self,
        connection: Any,
        request: WsRequest,
        channel_name: str,
        action: str,
    ) -> Response:
        if not self._authorized(request):
            return self._unauthorized()

        try:
            connector = self._channel_connectors.get(channel_name)
            if connector is None:
                plugin = load_channel_plugin(channel_name)
                connector = plugin.load_connector()
                self._channel_connectors[channel_name] = connector
        except ImportError:
            return self._error_response(404, f"channel '{channel_name}' does not support connect")

        try:
            payload = await connector.handle(action, self._query(request))
        except ChannelConnectError as exc:
            return self._error_response(exc.status, exc.message)
        except Exception:
            self.logger.exception(
                "failed to run {} WebUI connect action for {}",
                action,
                channel_name,
            )
            return self._error_response(500, f"failed to {action} {channel_name} connection")

        if payload.get("status") == "succeeded":
            payload = await self._with_channel_connect_success(
                connection,
                request,
                channel_name,
                payload,
            )
        return self._json_response(payload)

    async def _with_channel_connect_success(
        self,
        connection: Any,
        request: WsRequest,
        channel_name: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        target = {"name": [channel_name]}
        if payload.get("instance_id"):
            target["instance_id"] = [str(payload["instance_id"])]
        try:
            features = await asyncio.to_thread(
                nanobot_features_action,
                "enable",
                target,
                allow_install=self._allow_feature_package_install(connection, request),
            )
        except OptionalFeatureError as exc:
            features = self._feature_runtime_fallback(
                nanobot_features_payload(),
                message=(
                    f"{channel_name} connected, but enabling channel support failed: "
                    f"{exc.message}"
                ),
            )
        else:
            features = await self._apply_nanobot_feature_runtime_change(
                "enable",
                target,
                features,
            )
        features = self._with_channel_runtime_status(features)
        payload = dict(payload)
        payload["nanobot_features"] = self._with_restart_state(features, section="runtime")
        return payload

    def _allow_feature_package_install(self, connection: Any, request: WsRequest) -> bool:
        if _is_local_browser_request(connection, request.headers):
            return True
        try:
            return bool(load_config().tools.webui_allow_remote_package_install)
        except Exception:
            self.logger.exception("failed to load remote package install policy")
            return False

    async def _handle_settings_mcp_presets(
        self,
        request: WsRequest,
        action: str | None = None,
    ) -> Response:
        if not self._authorized(request):
            return self._unauthorized()
        try:
            payload = await mcp_presets_settings_action(
                action,
                self._parse_mcp_settings_query(request),
                reload_mcp=lambda: request_mcp_reload(self.bus),
            )
        except Exception as e:
            status = getattr(e, "status", 500)
            message = getattr(e, "message", str(e))
            if status >= 500:
                self.logger.exception("MCP preset action '{}' failed", action or "list")
            return self._error_response(status, message)
        if action is None:
            return self._json_response(payload)
        return self._json_response(self._with_restart_state(payload, section="runtime"))

    async def _handle_settings_version_check(self, request: WsRequest) -> Response:
        if not self._authorized(request):
            return self._unauthorized()
        try:
            update_info = await asyncio.to_thread(check_for_update)
        except Exception:
            self.logger.exception("version check failed")
            return self._error_response(500, "version check failed")
        return self._json_response({
            "updateAvailable": update_info,
        })


def _pairing_payload(last_action: dict[str, Any] | None = None) -> dict[str, Any]:
    now = time.time()
    requests = []
    for item in list_pending():
        expires_at = float(item.get("expires_at", 0) or 0)
        created_at = float(item.get("created_at", 0) or 0)
        requests.append({
            "code": str(item.get("code", "")),
            "channel": str(item.get("channel", "")),
            "sender_id": str(item.get("sender_id", "")),
            "created_at_ms": int(created_at * 1000) if created_at else None,
            "expires_at_ms": int(expires_at * 1000) if expires_at else None,
            "expires_in_seconds": max(0, int(expires_at - now)) if expires_at else None,
        })
    payload: dict[str, Any] = {"requests": requests}
    if last_action is not None:
        payload["last_action"] = last_action
    return payload
