"""Authenticated HTTP adapter for the extension management service."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from urllib.parse import unquote

from websockets.http11 import Request as WsRequest
from websockets.http11 import Response

from nanobot.extensions.service import ExtensionService
from nanobot.webui.http_utils import is_local_browser_request

_VALUES_HEADER = "X-Nanobot-Extension-Values"
_VALUES_MAX_BYTES = 32 * 1024
_ACTION_PATHS = {
    "/api/extensions/install": "install",
    "/api/extensions/enable": "enable",
    "/api/extensions/disable": "disable",
    "/api/extensions/trust": "trust",
    "/api/extensions/untrust": "untrust",
    "/api/extensions/permissions": "permissions",
    "/api/extensions/uninstall": "uninstall",
}


class WebUIExtensionsRouter:
    """Keep extension policy and installation outside WebSocket transport."""

    def __init__(
        self,
        *,
        service: ExtensionService | None,
        check_api_token: Callable[[WsRequest], bool],
        json_response: Callable[[dict[str, Any]], Response],
        error_response: Callable[[int, str | None], Response],
        allow_remote_package_install: bool = False,
        logger: Any,
    ) -> None:
        self._service = service
        self._check_api_token = check_api_token
        self._json_response = json_response
        self._error_response = error_response
        self._allow_remote_package_install = allow_remote_package_install
        self._logger = logger

    async def dispatch(
        self,
        connection: Any,
        request: WsRequest,
        path: str,
    ) -> Response | None:
        if not path.startswith("/api/extensions"):
            return None
        if not self._check_api_token(request):
            return self._error_response(401, "Unauthorized")
        if self._service is None:
            return self._error_response(503, "Extension service is not available")
        try:
            if path == "/api/extensions":
                if _method(request) != "GET":
                    return self._error_response(405, "Method not allowed")
                return self._json_response(await self._service.status())
            action = _ACTION_PATHS.get(path)
            if action is None:
                return None
            if _method(request) != "POST":
                return self._error_response(405, "Method not allowed")
            if not self._mutation_allowed(action, connection, request):
                return self._error_response(
                    403,
                    "Extension changes require a local WebUI connection",
                )
            values = self._values(request)
            if (
                action == "install"
                and str(values.get("kind") or "git") == "local"
                and not is_local_browser_request(connection, request.headers)
            ):
                return self._error_response(
                    403,
                    "Local extension paths require a local WebUI connection",
                )
            return self._json_response(await self._run_action(action, values))
        except KeyError as exc:
            return self._error_response(404, str(exc))
        except ValueError as exc:
            return self._error_response(400, str(exc))
        except RuntimeError as exc:
            return self._error_response(502, str(exc))
        except Exception:
            self._logger.exception("extension management request failed")
            return self._error_response(500, "Extension operation failed")

    async def _run_action(self, action: str, values: dict[str, Any]) -> dict[str, Any]:
        assert self._service is not None
        extension_id = str(values.get("id") or "").strip()
        if action == "install":
            source = str(values.get("source") or "").strip()
            if not source:
                raise ValueError("Missing extension source")
            return await self._service.install(
                source,
                kind=str(values.get("kind") or "git"),
                ref=str(values.get("ref") or ""),
                trusted=False,
            )
        if not extension_id:
            raise ValueError("Missing extension ID")
        if action == "enable":
            return await self._service.set_enabled(extension_id, True)
        if action == "disable":
            return await self._service.set_enabled(extension_id, False)
        if action == "trust":
            return await self._service.set_trusted(extension_id, True)
        if action == "untrust":
            return await self._service.set_trusted(extension_id, False)
        if action == "permissions":
            permissions = values.get("permissions", [])
            if not isinstance(permissions, list) or not all(
                isinstance(permission, str) for permission in permissions
            ):
                raise ValueError("Extension permissions must be an array of strings")
            return await self._service.set_permissions(extension_id, set(permissions))
        return await self._service.uninstall(extension_id)

    def _values(self, request: WsRequest) -> dict[str, Any]:
        raw = request.headers.get(_VALUES_HEADER)
        if not raw:
            return {}
        if len(raw.encode("utf-8")) > _VALUES_MAX_BYTES:
            raise ValueError("Extension request is too large")
        try:
            value = json.loads(unquote(raw))
        except json.JSONDecodeError as exc:
            raise ValueError("Invalid extension request") from exc
        if not isinstance(value, dict):
            raise ValueError("Extension request must be a JSON object")
        return value

    def _mutation_allowed(
        self,
        action: str,
        connection: Any,
        request: WsRequest,
    ) -> bool:
        return is_local_browser_request(connection, request.headers) or (
            action == "install" and self._allow_remote_package_install
        )


def _method(request: WsRequest) -> str:
    return str(getattr(request, "method", "GET")).upper()
