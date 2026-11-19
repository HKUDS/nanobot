from __future__ import annotations

import asyncio
import html
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from functools import partial
from typing import Any, cast

from websockets.http11 import Request as WsRequest
from websockets.http11 import Response

from nanobot.agent.tools.mcp_oauth import MCP_OAUTH_CALLBACK_PATH
from nanobot.bus.queue import MessageBus
from nanobot.channels.registry import load_channel_plugin
from nanobot.channels.validation import validate_channel_config
from nanobot.pairing import approve_code, deny_code, list_pending
from nanobot.pairing.events import PairingChanged
from nanobot.webui import settings_capabilities as capability_domain
from nanobot.webui import settings_contracts as contracts
from nanobot.webui import settings_models as model_domain
from nanobot.webui import settings_system as system_domain
from nanobot.webui.cli_apps_api import cli_apps_action, cli_apps_payload
from nanobot.webui.http_utils import (
    case_insensitive_header,
    etag_matches,
    http_json_response,
)
from nanobot.webui.http_utils import http_response as _http_response
from nanobot.webui.http_utils import is_local_browser_request as _is_local_browser_request
from nanobot.webui.mcp_oauth_api import McpOAuthManager
from nanobot.webui.mcp_presets_api import (
    ensure_mcp_oauth_server,
    mcp_presets_settings_action,
)
from nanobot.webui.mutation import MutationResult
from nanobot.webui.nanobot_features_api import (
    nanobot_feature_instance_target,
    nanobot_features_action,
    nanobot_features_payload,
)
from nanobot.webui.settings_api import (
    complete_oauth_provider,
    create_model_configuration,
    create_provider_settings,
    decorate_settings_payload,
    delete_model_configuration,
    login_oauth_provider,
    logout_oauth_provider,
    migrate_model_configurations,
    model_api_resolution_payload,
    provider_models_payload,
    settings_payload,
    settings_usage_payload,
    update_agent_settings,
    update_image_generation_settings,
    update_model_call_order,
    update_model_configuration,
    update_network_safety_settings,
    update_provider_settings,
    update_runtime_config_settings,
    update_transcription_settings,
    update_web_search_settings,
)
from nanobot.webui.settings_contracts import (
    HttpQuery,
    MutationParams,
    SettingsRequest,
    SettingsRouteResult,
)
from nanobot.webui.settings_runtime import runtime_config_payload
from nanobot.webui.settings_services import WebUISettingsServices
from nanobot.webui.version_check import check_for_update

_CHANNEL_CONNECT_ACTIONS = frozenset({"start", "poll", "cancel"})
_MCP_OAUTH_CALLBACK_URL_MAX_BYTES = 8 * 1024
_MCP_RELOAD_TIMEOUT_SECONDS = 15.0
_IMAGE_GENERATION_RELOAD_TIMEOUT_SECONDS = 5.0
_query_first = contracts.query_first


def _channel_connect_route(path: str) -> tuple[str, str] | None:
    prefix = "/api/settings/channels/"
    if not path.startswith(prefix):
        return None
    parts = path.removeprefix(prefix).split("/")
    if (
        len(parts) != 3
        or parts[1] != "connect"
        or parts[2] not in _CHANNEL_CONNECT_ACTIONS
    ):
        return None
    channel_name = parts[0].strip()
    return (channel_name, parts[2]) if channel_name else None


@dataclass(frozen=True, slots=True)
class _SettingsRoute:
    domain: str
    action: str
    mutation: str | None = None


_SETTINGS_ROUTES = {
    "/api/settings/update": _SettingsRoute("models", "agent-update", "settings.agent.update"),
    "/api/settings/model-configurations/create": _SettingsRoute("models", "model-create", "settings.model_configuration.create"),
    "/api/settings/model-configurations/update": _SettingsRoute("models", "model-update", "settings.model_configuration.update"),
    "/api/settings/model-configurations/delete": _SettingsRoute("models", "model-delete", "settings.model_configuration.delete"),
    "/api/settings/model-configurations/migrate": _SettingsRoute("models", "models-migrate", "settings.model_configuration.migrate"),
    "/api/settings/model-call-order/update": _SettingsRoute("models", "call-order-update", "settings.model_call_order.update"),
    "/api/settings/provider/update": _SettingsRoute("models", "provider-update", "settings.provider.update"),
    "/api/settings/provider/create": _SettingsRoute("models", "provider-create", "settings.provider.create"),
    "/api/settings/provider-models": _SettingsRoute("models", "provider-models"),
    "/api/settings/model-api": _SettingsRoute("models", "model-api"),
    "/api/settings/provider/oauth-login": _SettingsRoute("models", "oauth-login", "settings.provider.oauth_login"),
    "/api/settings/provider/oauth-login/complete": _SettingsRoute("models", "oauth-complete", "settings.provider.oauth_complete"),
    "/api/settings/provider/oauth-logout": _SettingsRoute("models", "oauth-logout", "settings.provider.oauth_logout"),
    "/api/settings/web-search/update": _SettingsRoute("capabilities", "web-search-update", "settings.web_search.update"),
    "/api/settings/image-generation/update": _SettingsRoute("capabilities", "image-update", "settings.image_generation.update"),
    "/api/settings/transcription/update": _SettingsRoute("capabilities", "transcription-update", "settings.transcription.update"),
    "/api/settings/network-safety/update": _SettingsRoute("capabilities", "network-update", "settings.network_safety.update"),
    "/api/settings/sandbox/check": _SettingsRoute("system", "sandbox-check", "settings.sandbox.check"),
    "/api/settings/runtime-config/update": _SettingsRoute("system", "runtime-config-update", "settings.runtime_config.update"),
    "/api/settings/cli-apps": _SettingsRoute("system", "cli-list"),
    "/api/settings/cli-apps/install": _SettingsRoute("system", "cli-install", "settings.cli_app.install"),
    "/api/settings/cli-apps/update": _SettingsRoute("system", "cli-update", "settings.cli_app.update"),
    "/api/settings/cli-apps/uninstall": _SettingsRoute("system", "cli-uninstall", "settings.cli_app.uninstall"),
    "/api/settings/cli-apps/test": _SettingsRoute("system", "cli-test", "settings.cli_app.test"),
    "/api/settings/nanobot-features": _SettingsRoute("system", "features-list"),
    "/api/settings/nanobot-features/enable": _SettingsRoute("system", "features-enable", "settings.feature.enable"),
    "/api/settings/nanobot-features/disable": _SettingsRoute("system", "features-disable", "settings.feature.disable"),
    "/api/settings/channels/validate": _SettingsRoute("system", "channel-validate", "settings.channel.validate"),
    "/api/settings/channels/configure": _SettingsRoute("system", "channel-configure", "settings.channel.configure"),
    "/api/settings/pairing": _SettingsRoute("system", "pairing-list"),
    "/api/settings/pairing/approve": _SettingsRoute("system", "pairing-approve", "settings.pairing.approve"),
    "/api/settings/pairing/deny": _SettingsRoute("system", "pairing-deny", "settings.pairing.deny"),
    "/api/settings/mcp-presets": _SettingsRoute("system", "mcp-list"),
    "/api/settings/version-check": _SettingsRoute("system", "version-check"),
    "/api/settings/nanobot-update/channel": _SettingsRoute("system", "update-channel", "settings.nanobot.update.channel"),
    "/api/settings/nanobot-update/plan": _SettingsRoute("system", "update-plan-read"),
    "/api/settings/nanobot-update/plan/create": _SettingsRoute("system", "update-plan-create", "settings.nanobot.update.plan"),
    "/api/settings/nanobot-update/job": _SettingsRoute("system", "update-job-read"),
    "/api/settings/nanobot-update/job/prepare": _SettingsRoute("system", "update-job-prepare", "settings.nanobot.update.prepare"),
    "/api/settings/nanobot-update/job/settle": _SettingsRoute("system", "update-job-settle", "settings.nanobot.update.settle"),
    "/api/settings/nanobot-update/job/execute": _SettingsRoute("system", "update-job-execute", "settings.nanobot.update.execute"),
    "/api/settings/nanobot-update/job/retry": _SettingsRoute("system", "update-job-retry", "settings.nanobot.update.retry"),
    "/api/settings/mcp-presets/enable": _SettingsRoute("system", "mcp-enable", "settings.mcp.enable"),
    "/api/settings/mcp-presets/disable": _SettingsRoute("system", "mcp-disable", "settings.mcp.disable"),
    "/api/settings/mcp-presets/remove": _SettingsRoute("system", "mcp-remove", "settings.mcp.remove"),
    "/api/settings/mcp-presets/test": _SettingsRoute("system", "mcp-test", "settings.mcp.test"),
    "/api/settings/mcp-presets/reconnect": _SettingsRoute("system", "mcp-reconnect", "settings.mcp.reconnect"),
    "/api/settings/mcp-presets/proxy": _SettingsRoute("system", "mcp-proxy", "settings.mcp.proxy"),
    "/api/settings/mcp-presets/custom": _SettingsRoute("system", "mcp-custom", "settings.mcp.custom"),
    "/api/settings/mcp-presets/import": _SettingsRoute("system", "mcp-import", "settings.mcp.import"),
    "/api/settings/mcp-presets/import-cursor": _SettingsRoute("system", "mcp-import-cursor", "settings.mcp.import_cursor"),
    "/api/settings/mcp-presets/tools": _SettingsRoute("system", "mcp-tools", "settings.mcp.tools"),
    "/api/settings/mcp-oauth/start": _SettingsRoute("oauth", "start", "settings.mcp.oauth_start"),
    "/api/settings/mcp-oauth/complete": _SettingsRoute("oauth", "complete", "settings.mcp.oauth_complete"),
    "/api/settings/mcp-oauth/cancel": _SettingsRoute("oauth", "cancel", "settings.mcp.oauth_cancel"),
}
_SETTINGS_WS_ROUTES = {route.mutation: route for route in _SETTINGS_ROUTES.values() if route.mutation}
_CHANNEL_CONNECT_WS = {f"settings.channel.connect.{action}": action for action in _CHANNEL_CONNECT_ACTIONS}
_CHANNEL_NAME_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")
_LOCAL_BROWSER_ACTIONS = frozenset({
    "runtime-config-update", "features-enable", "channel-configure", "channel-connect",
    "update-channel", "version-check", "update-plan-create", "update-plan-read",
    "update-job-prepare", "update-job-settle", "update-job-execute", "update-job-retry",
})


class WebUISettingsRouter:
    """Authenticate and dispatch settings requests to transport-neutral domains."""

    def __init__(
        self,
        *,
        settings: WebUISettingsServices,
        bus: MessageBus,
        logger: Any,
        check_api_token: Callable[[WsRequest], bool],
        parse_query: Callable[[str], HttpQuery],
        json_response: Callable[[dict[str, Any]], Response],
        error_response: Callable[[int, str | None], Response],
        runtime_surface: str,
        runtime_capabilities: dict[str, Any],
        channel_feature_action: Callable[..., Any] | None = None,
        channel_runtime_status: Callable[[], dict[str, Any]] | None = None,
        mcp_runtime_status: Callable[[], Mapping[str, str]] | None = None,
        mcp_reload: Callable[[], Awaitable[dict[str, Any]]] | None = None,
        image_generation_reload: Callable[[], Awaitable[dict[str, Any]]] | None = None,
        mcp_oauth_redirect_uri: Callable[[Any], str] | None = None,
    ) -> None:
        self.settings = settings
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
        self._mcp_runtime_status = mcp_runtime_status
        self._mcp_reload = mcp_reload
        self._image_generation_reload = image_generation_reload
        self._mcp_oauth_redirect_uri = mcp_oauth_redirect_uri
        self._mcp_oauth = McpOAuthManager(bus.admission)
        self._restart_sections: set[str] = set()
        self._restart_baselines: dict[str, dict[str, Any]] = {}
        self._restart_changes: dict[str, str] = {}
        self._models = model_domain.ModelSettingsHandler(settings, logger, bus.admission)
        self._capabilities = capability_domain.CapabilitySettingsHandler(
            settings,
            logger,
        )
        self._system = system_domain.SystemSettingsHandler(settings, logger, bus.admission)
        self._model_ops = self._model_operations()
        self._capability_ops = self._capability_operations()
        self._system_ops = self._system_operations()

    async def close(self) -> None:
        """Release state owned by settings domains."""
        await self._mcp_oauth.close()
        await self._models.close()
        await self._system.close()

    async def dispatch(
        self,
        connection: Any,
        request: WsRequest,
        path: str,
    ) -> Response | None:
        if self.is_mutation_path(path):
            return self._error_response(405, "WebUI mutations require an authenticated WebSocket")
        if path == MCP_OAUTH_CALLBACK_PATH:
            return self._handle_mcp_oauth_callback(request)
        if path not in {"/api/settings", "/api/settings/usage", "/api/settings/mcp-oauth/status"} and path not in _SETTINGS_ROUTES:
            return None
        if not self._authorized(request):
            return self._unauthorized()
        if path == "/api/settings/mcp-oauth/status":
            return await self._handle_mcp_oauth_status(request)
        if path == "/api/settings":
            return await asyncio.to_thread(self._handle_settings)
        if path == "/api/settings/usage":
            return await asyncio.to_thread(self._handle_settings_usage, request)

        route = _SETTINGS_ROUTES[path]
        domain_request = SettingsRequest(
            query=self._parse_query(request.path),
            local_browser=self._local_browser_for(route.action, connection, request.headers),
        )
        result = await self._dispatch_domain(route, domain_request)
        response = self._render_result(result)
        if route.action.startswith("update-") or route.action == "version-check":
            # A saved review is immutable, but its local validity and permission are not.
            response.headers["Cache-Control"] = "no-store"
        return response

    async def dispatch_mutation(
        self, connection: Any, headers: Any, action: str, params: MutationParams,
    ) -> MutationResult:
        """Dispatch a settings mutation after the WebSocket ingress has authenticated it."""
        route = _SETTINGS_WS_ROUTES.get(action)
        channel_name: str | None = None
        connect_action = _CHANNEL_CONNECT_WS.get(action)
        if connect_action is not None:
            channel_name = params.values.get("channel")
            if not isinstance(channel_name, str) or _CHANNEL_NAME_RE.fullmatch(channel_name) is None:
                return MutationResult.failure(400, "invalid channel name")
            route = _SettingsRoute("system", "channel-connect")
        if route is None:
            return MutationResult.failure(404, "unknown WebUI mutation action")
        if route.domain == "oauth":
            if route.action == "start":
                return await self._handle_mcp_oauth_start(headers, params)
            if route.action == "complete":
                return self._handle_mcp_oauth_complete(params)
            return await self._handle_mcp_oauth_cancel(params)

        domain_request = SettingsRequest(
            query=params,
            payload=params.values,
            local_browser=self._local_browser_for(route.action, connection, headers),
        )
        result = await self._dispatch_domain(
            route, domain_request, channel_name=channel_name, connect_action=connect_action,
        )
        if result.error is not None:
            return MutationResult.failure(result.status, result.error)
        return MutationResult.success(self._result_payload(result), status=result.status)

    @staticmethod
    def _local_browser_for(action: str, connection: Any, headers: Any) -> bool:
        return action in _LOCAL_BROWSER_ACTIONS and _is_local_browser_request(connection, headers)

    async def _dispatch_domain(
        self,
        route: _SettingsRoute,
        domain_request: SettingsRequest,
        *,
        channel_name: str | None = None,
        connect_action: str | None = None,
    ) -> SettingsRouteResult:
        domain, action = route.domain, route.action
        if action.startswith("update-") and self._runtime_surface == "native":
            return SettingsRouteResult.failure(409, "Update this installation through Nanobot Desktop.")
        restart_before = (
            await asyncio.to_thread(self._restart_values, action)
            if action in {"runtime-config-update", "image-update", "web-search-update"}
            else None
        )
        if domain == "models":
            result = await self._models.handle(action, domain_request, self._model_ops)
        elif domain == "capabilities":
            result = await self._capabilities.handle(action, domain_request, self._capability_ops)
        else:
            result = await self._system.handle(
                action, domain_request, self._system_ops,
                channel_name=channel_name, connect_action=connect_action,
            )
        if restart_before is not None and result.error is None and result.payload is not None:
            restart_after = await asyncio.to_thread(self._restart_values, action)
            if result.clear_restart_section:
                self._restart_baselines.pop(action, None)
                self._restart_changes.pop(action, None)
            elif result.payload.get("requires_restart") or action in self._restart_changes:
                baseline = self._restart_baselines.setdefault(action, {})
                for key, value in restart_before.items():
                    if restart_after.get(key) != value:
                        baseline.setdefault(key, value)
                for key in list(baseline):
                    if restart_after.get(key) == baseline[key]:
                        del baseline[key]
                if not baseline:
                    self._restart_baselines.pop(action, None)
                    self._restart_changes.pop(action, None)
                elif result.restart_section:
                    self._restart_changes[action] = result.restart_section
                # Reversible changes are tracked separately from installation and reload failures.
                result.payload["requires_restart"] = False
        return result

    def _restart_values(self, action: str) -> dict[str, Any]:
        config = self.settings.config.load()
        if action == "runtime-config-update":
            return runtime_config_payload(config)
        if action == "image-update":
            return config.tools.image_generation.model_dump(mode="json")
        return {"use_jina_reader": config.tools.web.fetch.use_jina_reader}

    @staticmethod
    def is_mutation_path(path: str) -> bool:
        route = _SETTINGS_ROUTES.get(path)
        return (route is not None and route.mutation is not None) or _channel_connect_route(path) is not None

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
        if section and payload.get("requires_restart"):
            self._restart_sections.add(section)
        sections = sorted(self._restart_sections | set(self._restart_changes.values()))
        updated = dict(payload)
        if sections:
            updated["requires_restart"] = True
        return decorate_settings_payload(
            updated,
            surface=self._runtime_surface,
            runtime_capability_overrides=self._runtime_capabilities,
            restart_required_sections=sections,
        )

    def _render_result(self, result: SettingsRouteResult) -> Response:
        if result.error is not None:
            return self._error_response(result.status, result.error)
        return self._json_response(self._result_payload(result))

    def _result_payload(self, result: SettingsRouteResult) -> dict[str, Any]:
        assert result.payload is not None
        payload = result.payload
        if result.clear_restart_section:
            self._restart_sections.discard(result.clear_restart_section)
        if result.decorate_restart:
            if result.restart_payload_key:
                nested = payload.get(result.restart_payload_key)
                if isinstance(nested, dict):
                    payload = dict(payload)
                    payload[result.restart_payload_key] = self._with_restart_state(
                        cast(dict[str, Any], nested),
                        section=result.restart_section,
                    )
            else:
                payload = self._with_restart_state(
                    payload,
                    section=result.restart_section,
                )
        return payload

    def _handle_settings(self) -> Response:
        return self._json_response(
            self._with_restart_state(
                self.settings.read(
                    settings_payload,
                    surface=self._runtime_surface,
                    runtime_capability_overrides=self._runtime_capabilities,
                )
            )
        )

    def _handle_settings_usage(self, request: WsRequest) -> Response:
        details = contracts.query_first(self._parse_query(request.path), "details")
        if details not in (None, "true", "false"):
            return self._error_response(400, "details must be true or false")
        payload = self.settings.read(settings_usage_payload, details=details == "true")
        revision = payload.get("revision")
        headers = [("Cache-Control", "private, no-cache")]
        if revision:
            etag = f'W/"{revision}"'
            headers.append(("ETag", etag))
            if etag_matches(case_insensitive_header(request.headers, "If-None-Match"), etag):
                return _http_response(
                    b"", status=304, extra_headers=[*headers, ("Vary", "Accept-Encoding")],
                )
        return http_json_response(
            payload,
            accept_encoding=request.headers.get("Accept-Encoding", ""),
            extra_headers=headers,
        )

    def _model_operations(self) -> model_domain.ModelSettingsOperations:
        return model_domain.ModelSettingsOperations(
            update_agent=update_agent_settings,
            create_model=create_model_configuration,
            update_model=update_model_configuration,
            delete_model=delete_model_configuration,
            migrate_models=migrate_model_configurations,
            update_call_order=update_model_call_order,
            update_provider=update_provider_settings,
            create_provider=create_provider_settings,
            provider_models=provider_models_payload,
            model_api=model_api_resolution_payload,
            oauth_login=login_oauth_provider,
            oauth_complete=complete_oauth_provider,
            oauth_logout=logout_oauth_provider,
            apply_image_runtime_change=self._apply_image_generation_runtime_change_result,
        )

    def _capability_operations(
        self,
    ) -> capability_domain.CapabilitySettingsOperations:
        return capability_domain.CapabilitySettingsOperations(
            update_web_search=update_web_search_settings,
            update_image=update_image_generation_settings,
            update_transcription=update_transcription_settings,
            update_network=update_network_safety_settings,
            reload_image=self._reload_image_generation_runtime,
        )

    def _pairing_changed(self) -> None:
        self.bus.publish_nowait(PairingChanged())

    def _system_operations(self) -> system_domain.SystemSettingsOperations:
        return system_domain.SystemSettingsOperations(
            update_runtime_config=update_runtime_config_settings,
            cli_apps_payload=cli_apps_payload,
            cli_apps_action=cli_apps_action,
            nanobot_features_payload=nanobot_features_payload,
            nanobot_features_action=nanobot_features_action,
            nanobot_feature_instance_target=nanobot_feature_instance_target,
            validate_channel_config=validate_channel_config,
            load_channel_plugin=load_channel_plugin,
            list_pending=list_pending,
            approve_code=partial(approve_code, on_change=self._pairing_changed),
            deny_code=partial(deny_code, on_change=self._pairing_changed),
            mcp_presets_action=mcp_presets_settings_action,
            reload_mcp=self._reload_mcp_runtime,
            mcp_runtime_status=self._mcp_runtime_status,
            check_for_update=check_for_update,
            channel_feature_action=self._channel_feature_action,
            channel_runtime_status=self._channel_runtime_status,
        )

    async def _apply_image_generation_runtime_change_result(
        self,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        return await self._capabilities.apply_image_runtime_change(
            payload,
            self._reload_image_generation_runtime,
        )

    async def _reload_image_generation_runtime(self) -> dict[str, Any]:
        if self._image_generation_reload is None:
            return {
                "ok": False,
                "message": "Image generation runtime reload is unavailable. Restart nanobot to apply changes.",
                "requires_restart": True,
            }
        try:
            return await asyncio.wait_for(
                self._image_generation_reload(),
                timeout=_IMAGE_GENERATION_RELOAD_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            return {
                "ok": False,
                "message": "Image generation hot reload timed out.",
                "requires_restart": True,
            }
        except Exception as exc:
            self.logger.exception("Image generation hot reload failed")
            return {
                "ok": False,
                "message": "Image generation hot reload failed.",
                "requires_restart": True,
                "error": str(exc),
            }

    async def _reload_mcp_runtime(self) -> dict[str, Any]:
        if self._mcp_reload is None:
            return {
                "ok": False,
                "message": "MCP runtime reload is unavailable. Restart nanobot to apply changes.",
                "requires_restart": True,
            }
        try:
            return await asyncio.wait_for(
                self._mcp_reload(),
                timeout=_MCP_RELOAD_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            return {
                "ok": False,
                "message": "MCP hot reload timed out. Restart nanobot to pick up changes.",
                "requires_restart": True,
            }
        except Exception as exc:
            self.logger.exception("MCP hot reload failed")
            return {
                "ok": False,
                "message": "MCP hot reload failed. Restart nanobot to pick up changes.",
                "requires_restart": True,
                "error": str(exc),
            }

    def _save_channel_config_values(
        self,
        name: str,
        raw_values: dict[str, Any],
        instance_id: str = "default",
    ) -> list[str]:
        return self.settings.config.update(
            lambda config: system_domain.save_channel_config_values(
                config,
                name,
                raw_values,
                instance_id,
                load_channel_plugin=load_channel_plugin,
            )
        )

    async def _handle_mcp_oauth_start(self, headers: Any, query: MutationParams) -> MutationResult:
        if self._mcp_oauth_redirect_uri is None:
            return MutationResult.failure(500, "MCP OAuth callback is not configured")
        try:
            name, cfg, network = await asyncio.to_thread(
                self.settings.mutate,
                ensure_mcp_oauth_server,
                query,
            )
            redirect_uri = self._mcp_oauth_redirect_uri(headers)
            reset = (_query_first(query, "reset") or "").lower() in {"1", "true", "yes"}
            payload = await self._mcp_oauth.start(
                name,
                cfg,
                redirect_uri,
                reload_mcp=self._reload_mcp_runtime,
                network=network,
                reset_credentials=reset,
            )
        except Exception as exc:
            return self._mcp_oauth_failure(exc, action="start")
        return MutationResult.success(payload)

    async def _handle_mcp_oauth_status(self, request: WsRequest) -> Response:
        flow_id = (_query_first(self._parse_query(request.path), "flow_id") or "").strip()
        if not flow_id:
            return self._error_response(400, "missing MCP OAuth flow ID")
        try:
            payload = await self._mcp_oauth.status(flow_id)
        except Exception as exc:
            failure = self._mcp_oauth_failure(exc, action="status")
            return self._error_response(failure.status_code, failure.message)
        return self._json_response(payload)

    def _handle_mcp_oauth_complete(self, query: MutationParams) -> MutationResult:
        flow_id = (_query_first(query, "flow_id") or "").strip()
        if not flow_id:
            return MutationResult.failure(400, "missing MCP OAuth flow ID")
        callback_url = (_query_first(query, "callback_url") or "").strip()
        if not callback_url:
            return MutationResult.failure(400, "Paste the complete callback URL to continue")
        if len(callback_url.encode("utf-8")) > _MCP_OAUTH_CALLBACK_URL_MAX_BYTES:
            return MutationResult.failure(400, "The MCP OAuth callback URL is too long")
        try:
            payload = self._mcp_oauth.submit_callback_url(
                flow_id=flow_id,
                callback_url=callback_url,
            )
        except Exception as exc:
            return self._mcp_oauth_failure(exc, action="complete")
        return MutationResult.success(payload)

    async def _handle_mcp_oauth_cancel(self, query: MutationParams) -> MutationResult:
        flow_id = (_query_first(query, "flow_id") or "").strip()
        if not flow_id:
            return MutationResult.failure(400, "missing MCP OAuth flow ID")
        try:
            payload = await self._mcp_oauth.cancel(flow_id)
        except Exception as exc:
            return self._mcp_oauth_failure(exc, action="cancel")
        return MutationResult.success(payload)

    def _handle_mcp_oauth_callback(self, request: WsRequest) -> Response:
        query = self._parse_query(request.path)
        state = (_query_first(query, "state") or "").strip()
        if not state:
            return self._mcp_oauth_callback_page(
                ok=False,
                message="This authorization request is missing its security state.",
                status=400,
            )
        try:
            name = self._mcp_oauth.submit_callback(
                state=state,
                code=_query_first(query, "code"),
                error=_query_first(query, "error"),
            )
        except Exception as exc:
            status = int(getattr(exc, "status", 400))
            message = str(getattr(exc, "message", "Could not complete MCP authorization"))
            return self._mcp_oauth_callback_page(ok=False, message=message, status=status)
        return self._mcp_oauth_callback_page(
            ok=True,
            message=f"Authorization received for {name}. Return to nanobot to finish connecting.",
        )

    def _mcp_oauth_failure(self, exc: Exception, *, action: str) -> MutationResult:
        raw_status = getattr(exc, "status", 500)
        status = raw_status if isinstance(raw_status, int) and 400 <= raw_status <= 599 else 500
        if status >= 500:
            self.logger.exception("MCP OAuth '{}' failed", action)
            message = f"MCP OAuth {action} failed"
        else:
            raw_message = getattr(exc, "message", None)
            message = raw_message if isinstance(raw_message, str) else "MCP OAuth request failed"
        return MutationResult.failure(status, message)

    @staticmethod
    def _mcp_oauth_callback_page(
        *,
        ok: bool,
        message: str,
        status: int = 200,
    ) -> Response:
        title = "Authorization received" if ok else "Connection failed"
        safe_title = html.escape(title)
        safe_message = html.escape(message)
        close_script = "<script>setTimeout(() => window.close(), 700)</script>" if ok else ""
        body = (
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{safe_title}</title><style>"
            "body{font:16px system-ui;margin:0;min-height:100vh;display:grid;place-items:center;"
            "background:#f7f7f6;color:#171717}.card{max-width:34rem;margin:2rem;padding:2rem;"
            "border:1px solid #ddd;border-radius:16px;background:white}h1{font-size:1.35rem}"
            "p{line-height:1.55;color:#555}</style></head><body><main class='card'>"
            f"<h1>{safe_title}</h1><p>{safe_message}</p></main>{close_script}</body></html>"
        ).encode("utf-8")
        return _http_response(
            body,
            status=status,
            content_type="text/html; charset=utf-8",
            extra_headers=[
                ("Cache-Control", "no-store"),
                ("Referrer-Policy", "no-referrer"),
                (
                    "Content-Security-Policy",
                    "default-src 'none'; base-uri 'none'; form-action 'none'; "
                    "frame-ancestors 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'",
                ),
            ],
        )
