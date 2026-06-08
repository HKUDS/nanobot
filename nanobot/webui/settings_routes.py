"""HTTP route adapter for WebUI Settings APIs.

Keep WebUI Settings route handlers here, not in ``channels/websocket.py``.
The websocket channel owns transport concerns; this module owns WebUI Settings
request mapping and response shaping.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

from websockets.http11 import Request as WsRequest
from websockets.http11 import Response

from nanobot.agent.tools.mcp import request_mcp_reload
from nanobot.bus.queue import MessageBus
from nanobot.webui.cli_apps_api import cli_apps_action, cli_apps_payload
from nanobot.webui.mcp_presets_api import mcp_presets_settings_action
from nanobot.webui.settings_api import (
    WebUISettingsError,
    create_model_configuration,
    decorate_settings_payload,
    login_oauth_provider,
    logout_oauth_provider,
    provider_models_payload,
    settings_payload,
    settings_usage_payload,
    update_agent_settings,
    update_image_generation_settings,
    update_model_configuration,
    update_network_safety_settings,
    update_provider_settings,
    update_transcription_settings,
    update_web_search_settings,
)

QueryParams = dict[str, list[str]]

_MCP_VALUES_HEADER = "X-Nanobot-MCP-Values"
_MCP_VALUES_HEADER_MAX_BYTES = 64 * 1024

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
    ) -> None:
        self.bus = bus
        self.logger = logger
        self._check_api_token = check_api_token
        self._parse_query = parse_query
        self._json_response = json_response
        self._error_response = error_response
        self._runtime_surface = runtime_surface
        self._runtime_capabilities = runtime_capabilities
        self._restart_sections: set[str] = set()

    async def dispatch(self, request: WsRequest, path: str) -> Response | None:
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
        if path == "/api/settings/provider/update":
            return self._handle_settings_provider_update(request)
        if path == "/api/settings/provider-models":
            return await self._handle_settings_provider_models(request)
        if path == "/api/settings/provider/oauth-login":
            return await self._handle_settings_provider_oauth(request, "login")
        if path == "/api/settings/provider/oauth-logout":
            return await self._handle_settings_provider_oauth(request, "logout")
        if path == "/api/settings/web-search/update":
            return self._handle_settings_web_search_update(request)
        if path == "/api/settings/image-generation/update":
            return self._handle_settings_image_generation_update(request)
        if path == "/api/settings/transcription/update":
            return self._handle_settings_transcription_update(request)
        if path == "/api/settings/network-safety/update":
            return self._handle_settings_network_safety_update(request)
        if path == "/api/settings/cli-apps":
            return self._handle_settings_cli_apps(request)
        if path == "/api/settings/cli-apps/install":
            return await self._handle_settings_cli_apps_action(request, "install")
        if path == "/api/settings/cli-apps/update":
            return await self._handle_settings_cli_apps_action(request, "update")
        if path == "/api/settings/cli-apps/uninstall":
            return await self._handle_settings_cli_apps_action(request, "uninstall")
        if path == "/api/settings/cli-apps/test":
            return await self._handle_settings_cli_apps_action(request, "test")
        if path == "/api/settings/mcp-presets":
            return await self._handle_settings_mcp_presets(request)
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

    def _handle_settings_provider_update(self, request: WsRequest) -> Response:
        if not self._authorized(request):
            return self._unauthorized()
        try:
            payload = update_provider_settings(self._query(request))
        except WebUISettingsError as e:
            return self._error_response(e.status, e.message)
        return self._json_response(self._with_restart_state(payload, section="image"))

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
            else:
                payload = await asyncio.to_thread(logout_oauth_provider, query)
        except WebUISettingsError as e:
            return self._error_response(e.status, e.message)
        return self._json_response(self._with_restart_state(payload))

    def _handle_settings_web_search_update(self, request: WsRequest) -> Response:
        if not self._authorized(request):
            return self._unauthorized()
        try:
            payload = update_web_search_settings(self._query(request))
        except WebUISettingsError as e:
            return self._error_response(e.status, e.message)
        return self._json_response(self._with_restart_state(payload, section="browser"))

    def _handle_settings_image_generation_update(self, request: WsRequest) -> Response:
        if not self._authorized(request):
            return self._unauthorized()
        try:
            payload = update_image_generation_settings(self._query(request))
        except WebUISettingsError as e:
            return self._error_response(e.status, e.message)
        return self._json_response(self._with_restart_state(payload, section="image"))

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

    def _handle_settings_cli_apps(self, request: WsRequest) -> Response:
        if not self._authorized(request):
            return self._unauthorized()
        try:
            payload = cli_apps_payload()
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
