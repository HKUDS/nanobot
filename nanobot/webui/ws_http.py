"""HTTP API handler extracted from WebSocketChannel.

Handles all non-WebSocket HTTP routes: bootstrap, sessions, settings,
media, commands, sidebar state, static file serving, and token management.

Also houses shared HTTP utility functions used by both this module and
``websocket.py`` to avoid circular imports.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import mimetypes
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol, TypeVar, cast
from urllib.parse import parse_qs, unquote, urlsplit, urlunsplit

from loguru import logger
from websockets.datastructures import Headers, MultipleValuesError
from websockets.http11 import Request as WsRequest
from websockets.http11 import Response

from nanobot.agent.subagent import SubagentControlError
from nanobot.agent.subagent_status import SubagentSessionError
from nanobot.command.application import builtin_command_palette
from nanobot.context_graph import ContextGraph
from nanobot.runtime_admission import RuntimeMaintenanceError
from nanobot.security.workspace_access import WorkspaceScope, WorkspaceScopeError
from nanobot.session.display_history import HistoryReader
from nanobot.session.manager import SessionManager
from nanobot.session.session_handles import (
    SessionHandle,
    SessionHandleResolver,
)
from nanobot.webui.automation_routes import WebUIAutomationRoutes
from nanobot.webui.file_preview import (
    WebUIFilePreviewError,
    file_preview_availability_payload,
    file_preview_payload,
    file_reference_payload,
)
from nanobot.webui.gateway_tokens import GatewayTokenStore, token_response_payload
from nanobot.webui.http_utils import JSONResponseMetrics
from nanobot.webui.http_utils import accepts_gzip as _accepts_gzip
from nanobot.webui.http_utils import (
    case_insensitive_header as _case_insensitive_header,
)
from nanobot.webui.http_utils import (
    combined_list_header as _combined_list_header,
)
from nanobot.webui.http_utils import etag_matches as _etag_matches
from nanobot.webui.http_utils import (
    host_for_url as _host_for_url,
)
from nanobot.webui.http_utils import (
    http_error as _http_error,
)
from nanobot.webui.http_utils import (
    http_json_response as _http_json_response,
)
from nanobot.webui.http_utils import (
    http_response as _http_response,
)
from nanobot.webui.http_utils import (
    is_local_browser_request as _is_local_browser_request,
)
from nanobot.webui.http_utils import is_loopback_host as _is_loopback_host
from nanobot.webui.http_utils import (
    is_trusted_proxy_authenticated_request as _is_trusted_proxy_authenticated_request,
)
from nanobot.webui.http_utils import (
    issue_route_secret_matches as _issue_route_secret_matches,
)
from nanobot.webui.http_utils import (
    normalize_config_path as _normalize_config_path,
)
from nanobot.webui.http_utils import (
    parse_query as _parse_query,
)
from nanobot.webui.http_utils import (
    parse_request_path as _parse_request_path,
)
from nanobot.webui.http_utils import (
    query_first as _query_first,
)
from nanobot.webui.http_utils import (
    safe_host_header as _safe_host_header,
)
from nanobot.webui.ingress_policy import WebUIIngressPolicy
from nanobot.webui.media_gateway import WebUIMediaGateway
from nanobot.webui.mutation import MutationResult
from nanobot.webui.recovery import RecoveryActionError
from nanobot.webui.session_automations import serialize_automation_jobs
from nanobot.webui.session_context import session_context_payload
from nanobot.webui.session_identity import is_webui_session_key
from nanobot.webui.session_list_index import (
    WEBUI_SESSION_INDEX_INTERNAL_FIELDS,
    indexed_workspace_scope,
    list_webui_sessions,
)
from nanobot.webui.settings_contracts import MutationParams
from nanobot.webui.settings_contracts import query_first as _mutation_text
from nanobot.webui.sidebar_state import (
    WebUISidebarState,
    ensure_webui_archives_imported,
)
from nanobot.webui.skills_api import (
    SkillManagementError,
    delete_webui_skill,
    set_webui_skill_enabled,
    webui_skill_detail_payload,
    webui_skills_payload,
)
from nanobot.webui.skills_marketplace import (
    SkillsMarketplaceError,
    install_marketplace_skill,
    marketplace_skill_trends,
    search_marketplace_skills,
    trending_marketplace_skills,
)
from nanobot.webui.star_prompt import update_star_prompt
from nanobot.webui.transcript import (
    TranscriptReplayStats,
    build_session_thread_response,
    build_webui_thread_response,
    build_webui_trace_detail_response,
    webui_transcript_revision,
)
from nanobot.webui.workspace_browser import browse_workspace_directories
from nanobot.webui.workspaces import WebUIWorkspaceController

_SLOW_WEBUI_HTTP_LOG_MS = 1_000
_NO_STORE_HEADERS = [("Cache-Control", "no-store")]


def _quoted_etag(revision: str) -> str:
    return f'"{revision}"'


@dataclass(slots=True)
class _WebUIThreadDiagnostics:
    transcript: TranscriptReplayStats = field(default_factory=TranscriptReplayStats)
    response: JSONResponseMetrics = field(default_factory=JSONResponseMetrics)
    session_hash: str = ""
    build_ms: float = 0.0
    total_ms: float = 0.0
    event_loop_lag_ms: float = 0.0

_WEBUI_MUTATION_PATHS = {
    "remote.discover": "/api/remote-instances/discover",
    "remote.pair_start": "/api/remote-instances/pair_start",
    "remote.pair_preview": "/api/remote-instances/pair_preview",
    "remote.pair_finish": "/api/remote-instances/pair_finish",
    "remote.pair_cancel": "/api/remote-instances/pair_cancel",
    "remote.pair_route": "/api/remote-instances/pair_route",
    "remote.inspect": "/api/remote-instances/inspect",
    "remote.pick_file": "/api/remote-instances/pick_file",
    "remote.save": "/api/remote-instances/save",
    "remote.rename": "/api/remote-instances/rename",
    "remote.connect": "/api/remote-instances/connect",
    "remote.disconnect": "/api/remote-instances/disconnect",
    "remote.remove": "/api/remote-instances/remove",
    "remote.fingerprint": "/api/remote-instances/fingerprint",
    "remote.trust": "/api/remote-instances/trust",
    "automation.enable": "/api/webui/automations/enable",
    "automation.disable": "/api/webui/automations/disable",
    "automation.delete": "/api/webui/automations/delete",
    "automation.run": "/api/webui/automations/run",
    "automation.update": "/api/webui/automations/update",
    "automation.change_chat": "/api/webui/automations/change-chat",
    "skill.install": "/api/webui/skills/install",
    "skill.update": "/api/webui/skills/update",
    "skill.delete": "/api/webui/skills/delete",
    "star_prompt.claim": "/api/webui/star-prompt/claim",
    "star_prompt.dismiss": "/api/webui/star-prompt/dismiss",
    "sidebar.update": "/api/webui/sidebar-state/update",
    "workspace.favorite": "/api/workspaces/favorite",
    "workspace.resolve_project": "/api/workspaces/resolve-project",
    "recovery.continue": "/api/webui/recovery/continue",
    "recovery.dismiss": "/api/webui/recovery/dismiss",
    "subagent.cancel": "/api/webui/subagents/cancel",
}
_WEBUI_STATIC_MUTATION_PATHS = frozenset(_WEBUI_MUTATION_PATHS.values())

# Fix for #5190: On Windows, mimetypes.guess_type() reads the registry key
# HKEY_CLASSES_ROOT\.js\Content Type, which is commonly set to 'text/plain'
# because .js is associated with Windows Script Host rather than web JavaScript.
# That registry value overrides Python's built-in mapping and causes browsers to
# reject ES module scripts with:
#   Failed to load module script: Expected a JavaScript-or-Wasm module script
#   but the server responded with a MIME type of "text/plain".
# We explicitly register correct MIME types for common web static assets here
# (module-import time) so all callers of mimetypes.guess_type() in this process
# benefit, regardless of host registry configuration.
_MIME_FIXES: dict[str, str] = {
    ".js":    "application/javascript",
    ".mjs":   "application/javascript",
    ".css":   "text/css",
    ".html":  "text/html",
    ".json":  "application/json",
    ".svg":   "image/svg+xml",
    ".wasm":  "application/wasm",
}

for _ext, _ctype in _MIME_FIXES.items():
    mimetypes.add_type(_ctype, _ext, strict=True)


if TYPE_CHECKING:
    from nanobot.agent.subagent import SubagentManager
    from nanobot.bus.queue import MessageBus
    from nanobot.channels.websocket.runtime import WebSocketConfig
    from nanobot.webui.settings_services import WebUISettingsServices

_API_KEY_RE = re.compile(r"^[A-Za-z0-9_:.-]{1,128}$")
_UUID_RE = re.compile(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}")
_SESSION_PROMPTS_RE = re.compile(r"/api/sessions/([^/]+)/webui-thread/prompts")
_SESSION_TRACE_DETAIL_RE = re.compile(r"^/api/sessions/([^/]+)/webui-thread/trace-detail$")
_SESSION_WEBUI_THREAD_RE = re.compile(r"^/api/sessions/([^/]+)/webui-thread$")
_SESSION_CONTEXT_RE = re.compile(r"^/api/sessions/([^/]+)/context$")
_SESSION_FILE_PREVIEW_RE = re.compile(r"^/api/sessions/([^/]+)/file-preview$")
_SESSION_AUTOMATIONS_RE = re.compile(r"^/api/sessions/([^/]+)/automations$")
_SESSION_SUBAGENT_THREAD_RE = re.compile(r"/api/sessions/([^/]+)/subagents/([^/]+)/webui-thread")
_SESSION_SUBAGENTS_RE = re.compile(r"/api/sessions/([^/]+)/subagents")
_SESSION_DELETE_RE = re.compile(r"^/api/sessions/([^/]+)/delete$")
_MEDIA_ROUTE_RE = re.compile(r"^/api/media/([A-Za-z0-9_-]+)/([A-Za-z0-9_-]+)$")
_SKILL_DETAIL_RE = re.compile(r"^/api/webui/skills/([^/]+)$")


def _decode_api_key(raw_key: str) -> str | None:
    key = unquote(raw_key)
    if _API_KEY_RE.match(key) is None:
        return None
    return key


def _default_model_name_from_config(config_path: Path | None = None) -> str | None:
    try:
        from nanobot.config.loader import load_config
        model = load_config(config_path).resolve_preset().model.strip()
        return model or None
    except Exception as e:
        logger.debug("bootstrap model_name could not load from config: {}", e)
        return None


def _resolve_bootstrap_model_name(
    runtime_name: Callable[[], str | None] | None,
    config_path: Path | None = None,
) -> str:
    if runtime_name is not None:
        try:
            raw = runtime_name()
        except Exception as e:
            logger.debug("bootstrap runtime model resolver failed: {}", e)
        else:
            if isinstance(raw, str):
                stripped = raw.strip()
                if stripped:
                    return stripped
    return _default_model_name_from_config(config_path) or ""


_ProjectionResult = TypeVar("_ProjectionResult", covariant=True)


class _HistoryProjection(Protocol[_ProjectionResult]):
    def __call__(self, request: WsRequest, key: str, /, *, history: HistoryReader) -> _ProjectionResult: ...


@dataclass
class _PreparedThreadResponse:
    data: dict[str, Any]
    headers: list[tuple[str, str]]


def _encode_thread_response(data: dict[str, Any], *, graph_references: bool, **kwargs: Any) -> Response:
    if graph_references:
        graphs: dict[str, object] = {}
        references: dict[int, tuple[str, ContextGraph]] = {}
        nodes: list[object] = []
        edges: list[object] = []
        node_ids: dict[int, int] = {}
        edge_ids: dict[int, int] = {}

        def index(value: object, values: list[object], ids: dict[int, int]) -> int:
            identity = id(value)
            if identity not in ids:
                ids[identity] = len(values)
                values.append(value)
            return ids[identity]

        def reference(graph: ContextGraph) -> str:
            identity = id(graph)
            if identity not in references:
                key = str(len(graphs))
                references[identity] = (key, graph)
                graphs[key] = {
                    "nodes": [index(node, nodes, node_ids) for node in graph["nodes"]],
                    "edges": [index(edge, edges, edge_ids) for edge in graph["edges"]],
                }
            return references[identity][0]

        for event in data.get("events", []):
            if "context_graph" in event:
                event["context_graph_ref"] = reference(event.pop("context_graph"))
            snapshot = event.get("context_snapshot")
            if isinstance(snapshot, dict) and "graph" in snapshot:
                snapshot = cast(dict[str, Any], snapshot)
                event["context_snapshot"] = {**snapshot, "graph_ref": reference(snapshot["graph"])}
                event["context_snapshot"].pop("graph")
        data["context_graphs"] = graphs
        data["context_graph_nodes"] = nodes
        data["context_graph_edges"] = edges
    return _http_json_response(data, **kwargs)


class GatewayHTTPHandler:
    """Handles all HTTP routes served alongside the WebSocket endpoint.

    Routes HTTP requests and delegates stateful work to explicit gateway
    services owned by the composition layer.
    """

    def __init__(
        self,
        *,
        config: WebSocketConfig,
        session_manager: SessionManager | None,
        static_dist_path: Path | None,
        runtime_model_name: Callable[[], str | None] | None,
        runtime_surface: str,
        runtime_capabilities_overrides: dict[str, Any] | None,
        bus: MessageBus,
        tokens: GatewayTokenStore,
        media: WebUIMediaGateway,
        ingress: WebUIIngressPolicy,
        workspaces: WebUIWorkspaceController,
        settings: WebUISettingsServices,
        skills_workspace_path: Path,
        disabled_skills: set[str] | None = None,
        automation_routes: WebUIAutomationRoutes,
        channel_feature_action: Callable[..., Any] | None = None,
        channel_runtime_status: Callable[[], dict[str, Any]] | None = None,
        mcp_runtime_status: Callable[[], Mapping[str, str]] | None = None,
        mcp_reload: Callable[[], Awaitable[dict[str, Any]]] | None = None,
        image_generation_reload: Callable[[], Awaitable[dict[str, Any]]] | None = None,
        skill_state_action: Callable[[set[str]], None] | None = None,
        recovery_action: (
            Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]] | None
        ) = None,
        subagent_manager: SubagentManager | None = None,
        discard_session: Callable[[str], Awaitable[None]] | None = None,
        log: Any = logger,
    ) -> None:
        self.config = config
        self.session_manager = session_manager
        self.sidebar_state = WebUISidebarState(session_manager.state if session_manager is not None else None)
        self.static_dist_path = static_dist_path
        self.runtime_model_name = runtime_model_name
        self.bus = bus
        self.tokens = tokens
        self.media = media
        self.ingress = ingress
        self.workspaces = workspaces
        self.settings = settings
        from nanobot.webui.remote_instances import RemoteInstances

        self.remote_instances = RemoteInstances(
            settings.config.path.parent / "webui", local_gateway_id=tokens.instance_id,
        )
        self.skills_workspace_path = skills_workspace_path
        self.disabled_skills: set[str] = (
            disabled_skills if disabled_skills is not None else set()
        )
        self.skill_state_action = skill_state_action
        self.recovery_action = recovery_action
        self.subagent_manager = subagent_manager
        self.discard_session = discard_session
        self._skill_install_lock = asyncio.Lock()
        self.automation_routes = automation_routes
        self._log = log
        self._runtime_surface = runtime_surface

        from nanobot.webui.settings_api import runtime_capabilities as _rc
        from nanobot.webui.settings_routes import WebUISettingsRouter

        self._capabilities = _rc(runtime_surface, runtime_capabilities_overrides or {})
        self.settings_routes = WebUISettingsRouter(
            settings=settings,
            bus=bus,
            logger=self._log,
            check_api_token=self.check_api_token,
            parse_query=_parse_query,
            json_response=_http_json_response,
            error_response=_http_error,
            runtime_surface=runtime_surface,
            runtime_capabilities=self._capabilities,
            channel_feature_action=channel_feature_action,
            channel_runtime_status=channel_runtime_status,
            mcp_runtime_status=mcp_runtime_status,
            mcp_reload=mcp_reload,
            image_generation_reload=image_generation_reload,
            mcp_oauth_redirect_uri=self._mcp_oauth_redirect_uri,
        )


    def check_api_token(self, request: WsRequest) -> bool:
        if getattr(request, "_nanobot_trusted_proxy_authenticated", False):
            return True
        return self.tokens.check_api_token(request)


    async def dispatch(self, connection: Any, request: WsRequest) -> Any | None:
        """Route an HTTP request. Returns Response or None."""
        got, _ = _parse_request_path(request.path)
        started = time.perf_counter()
        response: Any | None = None
        setattr(
            request,
            "_nanobot_trusted_proxy_authenticated",
            _is_trusted_proxy_authenticated_request(connection, request.headers, self.config),
        )

        try:
            if self._is_webui_mutation_path(got):
                return _http_error(
                    405,
                    "WebUI mutations require an authenticated WebSocket",
                )
            with self.bus.admission.activity():
                response = await self._dispatch_resolved(connection, request, got)
            return response
        except RuntimeMaintenanceError:
            return _http_error(503, "Gateway update is being verified. Retry shortly.")
        finally:
            self._log_slow_http(got, response, started)

    async def dispatch_webui_mutation(
        self,
        connection: Any,
        action: str,
        payload: dict[str, Any],
    ) -> MutationResult:
        """Run an allowlisted action from the authenticated WebUI command router."""
        headers = getattr(getattr(connection, "request", None), "headers", None) or Headers()
        params = MutationParams(payload)
        try:
            # The operation outlives its socket; hold admission until the write ends.
            with self.bus.admission.activity():
                if action.startswith("settings."):
                    return await self.settings_routes.dispatch_mutation(connection, headers, action, params)
                if action == "session.delete":
                    key = payload.get("key")
                    if not isinstance(key, str) or not key.strip():
                        return MutationResult.failure(400, "missing session key")
                    return await self._handle_session_delete(key, params)
                if action in _WEBUI_MUTATION_PATHS:
                    kind, _, operation = action.partition(".")
                    if kind == "remote":
                        return await self._mutate_remote_instances(connection, headers, operation, payload)
                    if kind == "automation":
                        return await self.automation_routes.mutate(params, operation.replace("_", "-"))
                    if kind == "recovery":
                        return await self._mutate_recovery(operation, payload)
                    if action == "subagent.cancel":
                        return await self._handle_subagent_cancel(payload)
                    if action == "sidebar.update":
                        return await self._handle_webui_sidebar_state_update(payload)
                    if action == "workspace.favorite":
                        return await asyncio.to_thread(self._handle_workspace_favorite, payload)
                    if action == "workspace.resolve_project":
                        return await asyncio.to_thread(self._handle_workspace_resolve_project, payload)
                    if action == "skill.install":
                        return await self._handle_webui_skill_install(connection, headers, params)
                    if action == "skill.update":
                        return await self._handle_webui_skill_update(params)
                    if action == "skill.delete":
                        return await self._handle_webui_skill_delete(connection, headers, params)
                    if kind == "star_prompt" and (operation == "claim" or operation == "dismiss"):
                        return await self._mutate_star_prompt(operation)
        except RuntimeMaintenanceError:
            return MutationResult.failure(503, "Gateway update is being verified. Retry shortly.")
        return MutationResult.failure(404, "unknown WebUI mutation action")

    def _is_webui_mutation_path(self, path: str) -> bool:
        if path.startswith("/api/remote-instances/"):
            return True
        if self.settings_routes.is_mutation_path(path):
            return True
        if _SESSION_DELETE_RE.match(path):
            return True
        return path in _WEBUI_STATIC_MUTATION_PATHS

    async def _dispatch_resolved(
        self,
        connection: Any,
        request: WsRequest,
        got: str,
    ) -> Any | None:
        if got == "/api/settings/background-style":
            if not self.check_api_token(request):
                return _http_error(401, "Unauthorized")
            from nanobot.webui.background import load_background_style

            directory = self.settings.config.path.parent / "webui"
            style = await asyncio.to_thread(load_background_style, directory)
            return _http_json_response(
                style, extra_headers=_NO_STORE_HEADERS,
            )
        if got == "/api/settings/background":
            if not self.check_api_token(request):
                return _http_error(401, "Unauthorized")
            path = self.settings.config.path.parent / "webui" / "background.png"
            try:
                body = await asyncio.to_thread(path.read_bytes)
            except FileNotFoundError:
                return _http_error(404, "Background not found")
            return _http_response(body, content_type="image/png", extra_headers=[
                ("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff"),
            ])
        if got == "/api/remote-instances":
            return await self._read_remote_instances(connection, request)
        if self.config.token_issue_path:
            issue_expected = _normalize_config_path(self.config.token_issue_path)
            if got == issue_expected:
                return self._handle_token_issue(connection, request)

        if got == "/webui/bootstrap":
            return await self._handle_bootstrap(connection, request)
        if got == "/webui/terminal":
            return await self._handle_bootstrap(connection, request, terminal_probe=True)

        response = await self.settings_routes.dispatch(connection, request, got)
        if response is not None:
            return response

        response = await self._dispatch_session_routes(request, got)
        if response is not None:
            return response

        response = await self._dispatch_media_routes(request, got)
        if response is not None:
            return response

        response = await self.automation_routes.dispatch_read(request, got, self.check_api_token)
        if response is not None:
            return response

        response = await self._dispatch_misc_routes(connection, request, got)
        if response is not None:
            return response

        # API 404 (never serve SPA for /api/ routes)
        if got.startswith("/api/"):
            return _http_error(404, "API route not found")

        if self.static_dist_path is not None:
            response = await asyncio.to_thread(
                self._serve_static,
                got,
                accept_encoding=_combined_list_header(request.headers, "Accept-Encoding"),
            )
            if response is not None:
                return response

        return connection.respond(404, "Not Found")

    def _allow_remote_instances(self, connection: Any, headers: Any) -> bool:
        # A public/reverse-proxied WebUI must not gain access to host SSH credentials.
        if not (_is_loopback_host(self.config.host)
                and _is_local_browser_request(connection, headers)):
            return False
        try:
            origin = headers.get("Origin", "")
            return isinstance(origin, str) and (
                not origin or _is_loopback_host(urlsplit(origin).hostname or "")
            )
        except (MultipleValuesError, ValueError):
            return False

    async def _read_remote_instances(self, connection: Any, request: WsRequest) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        if not self._allow_remote_instances(connection, request.headers):
            return _http_error(403, "remote_connections_local_only")
        parsed = urlsplit(request.path)
        try:
            if parsed.fragment or len(parsed.query) > 4096:
                raise ValueError
            query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True, max_num_fields=20)
            if query.keys() - {"check"} or any(
                _UUID_RE.fullmatch(key) is None for key in query.get("check", [])
            ):
                raise ValueError
        except ValueError:
            return _http_error(400, "invalid_health_check")
        check = {key.lower() for key in query.get("check", [])}
        try:
            result = await self.remote_instances.health(check) if check else self.remote_instances.snapshot()
        except OSError:
            return _http_error(500, "local_io_error")
        return _http_json_response(result, extra_headers=_NO_STORE_HEADERS)

    async def _mutate_remote_instances(
        self, connection: Any, headers: Any, action: str, payload: dict[str, Any],
    ) -> MutationResult:
        from pydantic import ValidationError

        from nanobot.webui.remote_ssh import RemoteError

        if not self._allow_remote_instances(connection, headers):
            return MutationResult.failure(403, "remote_connections_local_only")
        try:
            return MutationResult.success(await self.remote_instances.action(action, payload))
        except RemoteError as exc:
            return MutationResult.failure(400, str(exc))
        except ValidationError:
            return MutationResult.failure(400, "invalid_profile")
        except OSError:
            return MutationResult.failure(500, "local_io_error")

    def _log_slow_http(self, path: str, response: Any | None, started: float) -> None:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        if elapsed_ms < _SLOW_WEBUI_HTTP_LOG_MS:
            return
        if not (path.startswith("/api/") or path == "/webui/bootstrap"):
            return
        if path.endswith("/webui-thread"):
            return
        status = getattr(response, "status_code", None)
        self._log.warning(
            "slow webui http route path={} status={} duration_ms={}",
            path,
            status if status is not None else "none",
            elapsed_ms,
        )


    def _handle_token_issue(self, connection: Any, request: Any) -> Any:
        secret = self.config.token_issue_secret.strip() or self.config.token.strip()
        if secret:
            if not _issue_route_secret_matches(request.headers, secret):
                return connection.respond(401, "Unauthorized")
        else:
            self._log.warning(
                "token_issue_path is set but token_issue_secret is empty; "
                "any client can obtain connection tokens — set token_issue_secret for production."
            )
        if not self.tokens.can_issue():
            self._log.error(
                "too many outstanding issued tokens ({}), rejecting issuance",
                len(self.tokens.issued_tokens),
            )
            return _http_json_response(
                {"error": "too many outstanding tokens"},
                status=429,
                extra_headers=_NO_STORE_HEADERS,
            )
        token_value = self.tokens.issue_token(self.config.token_ttl_s)
        return _http_json_response(
            token_response_payload(token_value, self.config.token_ttl_s),
            extra_headers=_NO_STORE_HEADERS,
        )


    async def _handle_bootstrap(
        self, connection: Any, request: Any, *, terminal_probe: bool = False,
    ) -> Response:
        secret = self.config.token_issue_secret.strip() or self.config.token.strip()
        is_local_browser = _is_local_browser_request(connection, request.headers)
        is_proxy_authenticated = _is_trusted_proxy_authenticated_request(
            connection,
            request.headers,
            self.config,
        )
        if not is_proxy_authenticated:
            if secret:
                if not _issue_route_secret_matches(request.headers, secret):
                    return _http_error(401, "Unauthorized")
            elif not is_local_browser:
                return _http_error(403, "bootstrap is localhost-only")

        from nanobot.webui.client_contract import gateway_identity

        terminal = gateway_identity(self.tokens.instance_id)
        if terminal_probe:
            # Capability probing does not allocate credentials or acquire client leases.
            return _http_json_response(terminal, extra_headers=_NO_STORE_HEADERS)

        if is_proxy_authenticated:
            model_name = await asyncio.to_thread(
                _resolve_bootstrap_model_name,
                self.runtime_model_name,
                self.settings.config.path,
            )
            payload = {
                "ws_path": _normalize_config_path(self.config.path),
                "ws_url": self._bootstrap_ws_url(request.headers),
                "limits": self.ingress.bootstrap_limits(
                    max_frame_bytes=self.config.max_message_bytes,
                ),
                "model_name": model_name,
                "runtime_surface": self._runtime_surface,
                "runtime_capabilities": self._capabilities,
                "terminal": terminal,
            }
            return _http_json_response(payload, extra_headers=_NO_STORE_HEADERS)

        api_token_allowed = bool(secret) or is_local_browser
        if not self.tokens.can_issue(include_api_token=api_token_allowed):
            return _http_response(
                json.dumps({"error": "too many outstanding tokens"}).encode("utf-8"),
                status=429,
                content_type="application/json; charset=utf-8",
                extra_headers=_NO_STORE_HEADERS,
            )
        token = self.tokens.issue_token(self.config.token_ttl_s, audience="webui")
        api_token = (
            self.tokens.issue_api_token(self.config.token_ttl_s)
            if api_token_allowed
            else None
        )

        ws_url = self._bootstrap_ws_url(request.headers)
        expected_path = _normalize_config_path(self.config.path)
        model_name = await asyncio.to_thread(
            _resolve_bootstrap_model_name,
            self.runtime_model_name,
            self.settings.config.path,
        )
        payload = {
            "token": token,
            "terminal": terminal,
            "ws_path": expected_path,
            "ws_url": ws_url,
            "expires_in": self.config.token_ttl_s,
            "limits": self.ingress.bootstrap_limits(
                max_frame_bytes=self.config.max_message_bytes,
            ),
            "model_name": model_name,
            "runtime_surface": self._runtime_surface,
            "runtime_capabilities": self._capabilities,
        }
        if api_token is not None:
            payload["api_token"] = api_token
        return _http_json_response(payload, extra_headers=_NO_STORE_HEADERS)

    def _bootstrap_ws_url(self, headers: Any) -> str:
        if self.config.public_ws_url:
            return self.config.public_ws_url
        host = _safe_host_header(_case_insensitive_header(headers, "Host"))
        if not host:
            host = _host_for_url(self.config.host, self.config.port)
        proto = _case_insensitive_header(headers, "X-Forwarded-Proto")
        proto = proto.split(",", 1)[0].strip().lower()
        secure = proto in {"https", "wss"} or bool(self.config.ssl_certfile.strip())
        scheme = "wss" if secure else "ws"
        expected_path = _normalize_config_path(self.config.path)
        return f"{scheme}://{host}{expected_path}"

    def _mcp_oauth_redirect_uri(self, headers: Any) -> str:
        from nanobot.agent.tools.mcp_oauth import MCP_OAUTH_CALLBACK_PATH

        public_ws_url = urlsplit(self._bootstrap_ws_url(headers))
        scheme = "https" if public_ws_url.scheme == "wss" else "http"
        return urlunsplit((scheme, public_ws_url.netloc, MCP_OAUTH_CALLBACK_PATH, "", ""))


    def _authorize_websocket_session(self, request: WsRequest, raw_key: str) -> str | Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        decoded_key = _decode_api_key(raw_key)
        if decoded_key is None:
            return _http_error(400, "invalid session key")
        if not _is_websocket_channel_session_key(decoded_key):
            return _http_error(404, "session not found")
        return decoded_key

    async def _dispatch_session_routes(self, request: WsRequest, got: str) -> Response | None:
        m = _SESSION_PROMPTS_RE.fullmatch(got)
        if m:
            return await self._project_session_history(request, m.group(1), self._handle_prompt_index_get)

        m = _SESSION_TRACE_DETAIL_RE.match(got)
        if m:
            return await self._project_session_history(request, m.group(1), self._handle_webui_trace_detail_get)

        m = _SESSION_WEBUI_THREAD_RE.match(got)
        if m:
            return await self._handle_webui_thread_get_async(request, m.group(1))

        m = _SESSION_CONTEXT_RE.match(got)
        if m:
            return await self._handle_session_context_get(request, m.group(1))

        m = _SESSION_FILE_PREVIEW_RE.match(got)
        if m:
            return await asyncio.to_thread(self._handle_file_preview, request, m.group(1))

        m = _SESSION_AUTOMATIONS_RE.match(got)
        if m:
            return self._handle_session_automations(request, m.group(1))

        m = _SESSION_SUBAGENT_THREAD_RE.fullmatch(got)
        if m:
            return await asyncio.to_thread(self._handle_subagent_thread_get, request, m.group(1), m.group(2))

        m = _SESSION_SUBAGENTS_RE.fullmatch(got)
        if m:
            return await self._handle_subagents_get(request, m.group(1))

        return None

    async def _mutate_recovery(self, action: str, payload: dict[str, Any]) -> MutationResult:
        if self.recovery_action is None:
            return MutationResult.failure(503, "WebUI recovery is unavailable")
        try:
            result = await self.recovery_action(action, payload)
        except RecoveryActionError as exc:
            return MutationResult.failure(exc.status, str(exc))
        return MutationResult.success(result)

    async def _handle_subagents_get(self, request: WsRequest, key: str) -> Response:
        session_key = self._authorize_websocket_session(request, key)
        if isinstance(session_key, Response):
            return session_key
        if self.subagent_manager is None:
            return _http_error(503, "subagent manager unavailable")
        query = _parse_query(request.path)
        scope = query.get("scope")
        if scope is not None and scope != ["window"]:
            return _http_error(400, "invalid task scope")
        turns = query.get("turn_id", [])
        tracked = query.get("track", [])
        if scope == ["window"] and (len(turns) + len(tracked) > 512
                or any(not value or len(value) > 512 for value in (*turns, *tracked))):
            return _http_error(400, "invalid task window")
        try:
            if scope == ["window"]:
                statuses = await self.subagent_manager.read_statuses_for_session(
                    session_key, turns=turns, tracked=tracked,
                )
            else:
                statuses = await self.subagent_manager.read_statuses_for_session(session_key)
        except (OSError, SubagentSessionError):
            return _http_error(503, "task history unavailable")
        return _http_json_response({
            "tasks": [status.as_dict() for status in statuses.values()],
        }, extra_headers=_NO_STORE_HEADERS)

    async def _handle_subagent_cancel(self, payload: dict[str, Any]) -> MutationResult:
        if self.subagent_manager is None:
            return MutationResult.failure(503, "subagent manager unavailable")
        session_key, task_id = payload.get("session_key"), payload.get("task_id")
        if not isinstance(session_key, str) or not is_webui_session_key(session_key):
            return MutationResult.failure(400, "invalid session key")
        if not isinstance(task_id, str) or not task_id.strip():
            return MutationResult.failure(400, "missing task id")
        try:
            status = await self.subagent_manager.cancel(task_id, session_key)
        except SubagentControlError:
            return MutationResult.failure(404, "task unavailable")
        except (OSError, SubagentSessionError):
            return MutationResult.failure(503, "task history unavailable")
        return MutationResult.success(status.as_dict())

    def _handle_subagent_thread_get(self, request: WsRequest, key: str, task_id: str) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        session_key, decoded_task_id = _decode_api_key(key), _decode_api_key(task_id)
        if session_key is None or decoded_task_id is None:
            return _http_error(400, "invalid task key")
        if not is_webui_session_key(session_key):
            return _http_error(404, "task unavailable")
        if self.subagent_manager is None:
            return _http_error(503, "task history unavailable")
        try:
            status, child = self.subagent_manager.read_session(decoded_task_id, session_key)
        except SubagentControlError:
            return _http_error(404, "task unavailable")
        except (OSError, SubagentSessionError):
            return _http_error(503, "task history unavailable")
        scope = self.workspaces.scope_for_session_key(session_key)
        data = build_session_thread_response(
            child,
            active=status.state in {"queued", "running", "stopping"},
            latency_ms=(int(max(0.0, status.finished_at - status.started_at) * 1000)
                        if status.finished_at is not None else None),
            augment_user_media=lambda paths, local: self.media.augment_transcript_user_media(paths, local, session_key=session_key),
            augment_assistant_media=self.media.augment_transcript_media,
            augment_assistant_text=lambda text: self.media.rewrite_local_markdown_images(
                text, workspace_path=scope.project_path,
            ),
        )
        return _http_json_response(data, extra_headers=_NO_STORE_HEADERS)

    async def _handle_session_context_get(self, request: WsRequest, key: str) -> Response:
        decoded_key = self._authorize_websocket_session(request, key)
        if isinstance(decoded_key, Response):
            return decoded_key
        if self.session_manager is None:
            return _http_error(503, "session manager unavailable")
        session = await asyncio.to_thread(
            self.session_manager.read_session_snapshot,
            decoded_key,
        )
        if session is None:
            return _http_error(404, "session not found")
        return _http_json_response(session_context_payload(session))

    async def _handle_sessions_list(self, request: WsRequest) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        if self.session_manager is None:
            return _http_error(503, "session manager unavailable")
        accept_encoding = _combined_list_header(request.headers, "Accept-Encoding")

        def render(stored: list[dict[str, Any]]) -> Response | None:
            payload = self._sessions_list_from_snapshot(stored)
            if payload is None:
                return None
            return _http_json_response(payload, accept_encoding=accept_encoding)

        response = await self.session_manager.state.query_metadata(render)
        if response is None:
            handles = await SessionHandleResolver(self.session_manager).alist_all_by_key()

            def render_allocated(stored: list[dict[str, Any]]) -> Response:
                return _http_json_response(
                    self._sessions_list_payload(handles, stored), accept_encoding=accept_encoding,
                )

            response = await self.session_manager.state.query_metadata(render_allocated)
        return response

    def _sessions_list_from_snapshot(
        self, stored_sessions: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        assert self.session_manager is not None
        handles = SessionHandleResolver(self.session_manager).handles_from_metadata(stored_sessions)
        if handles is None:
            return None
        return self._sessions_list_payload(handles, stored_sessions)

    def _sessions_list_payload(
        self,
        handles: dict[str, SessionHandle],
        stored_sessions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        assert self.session_manager is not None
        from nanobot.session.webui_turns import latest_live_websocket_turn

        sessions = list_webui_sessions(self.session_manager, stored_sessions)
        cleaned: list[dict[str, Any]] = []
        default_scope: WorkspaceScope | None = None
        scopes: dict[str, WorkspaceScope] = {}
        for s in sessions:
            key = s.get("key")
            if not (isinstance(key, str) and is_webui_session_key(key)):
                continue
            row = {
                k: v
                for k, v in s.items()
                if k != "path" and k not in WEBUI_SESSION_INDEX_INTERNAL_FIELDS
            }
            # Keep the additive recovery field absent for ordinary sessions so
            # older clients and compact list responses stay unchanged.
            if row.get("recovery_state") is None:
                row.pop("recovery_state", None)
            chat_id = key.split(":", 1)[1]
            turn = latest_live_websocket_turn(chat_id)
            if turn is not None:
                row["run_started_at"] = turn[0]
            if default_scope is None:
                default_scope = self.workspaces.default_scope()
            scope_present, raw_scope = indexed_workspace_scope(s)
            if scope_present:
                scope_key = json.dumps(raw_scope, ensure_ascii=False, sort_keys=True)
                scope = scopes.get(scope_key)
                if scope is None:
                    scope = self.workspaces.scope_for_indexed_metadata(
                        raw_scope, scope_present=True, default_scope=default_scope,
                    )
                    scopes[scope_key] = scope
            else:
                scope = default_scope
            row["workspace_scope"] = scope.payload()
            row["project_locked"] = True
            handle = handles.get(key)
            if handle is not None:
                row["handle"] = handle.public_payload()
            cleaned.append(row)
        return {"sessions": cleaned}

    def _read_session_messages(self, key: str) -> list[dict[str, Any]] | None:
        if self.session_manager is None:
            return None
        session_data = self.session_manager.read_session_file(key)
        raw_messages = session_data.get("messages") if isinstance(session_data, dict) else None
        if not isinstance(raw_messages, list):
            return None
        return [
            cast(dict[str, Any], message)
            for message in cast(list[Any], raw_messages)
            if isinstance(message, dict)
        ]

    def _read_session_version(self, key: str) -> tuple[str, int] | None:
        return self.session_manager.read_session_version(key) if self.session_manager is not None else None

    async def _project_session_history(
        self, request: WsRequest, key: str, project: _HistoryProjection[_ProjectionResult],
    ) -> _ProjectionResult | Response:
        decoded = self._authorize_websocket_session(request, key)
        if isinstance(decoded, Response):
            return decoded
        if self.session_manager is None:
            return _http_error(503, "session manager unavailable")
        return await self.session_manager.state.project_history(
            decoded, lambda history: project(request, decoded, history=history),
        )

    def _handle_prompt_index_get(self, request: WsRequest, decoded_key: str, *, history: HistoryReader) -> Response:
        from nanobot.webui.transcript import prompt_index_response, prompt_index_revision

        revision = prompt_index_revision(decoded_key, self._read_session_version(decoded_key), history=history)
        etag = _quoted_etag(revision) if revision else None
        if etag and _etag_matches(_case_insensitive_header(request.headers, "If-None-Match"), etag):
            return _http_response(b"", status=304, extra_headers=[*_NO_STORE_HEADERS, ("ETag", etag)])
        query = _parse_query(request.path)
        data = prompt_index_response(
            decoded_key, _query_first(query, "since"), history=history,
            session_messages_loader=lambda: self._read_session_messages(decoded_key),
            session_version_loader=lambda: self._read_session_version(decoded_key),
        )
        headers = list(_NO_STORE_HEADERS)
        response_revision = data.get("revision")
        if response_revision:
            headers.append(("ETag", _quoted_etag(response_revision)))
        return _http_json_response(
            dict(data),
            accept_encoding=_combined_list_header(request.headers, "Accept-Encoding"),
            extra_headers=headers,
        )

    async def _handle_webui_thread_get_async(self, request: WsRequest, key: str) -> Response:
        diagnostics = _WebUIThreadDiagnostics()
        loop = asyncio.get_running_loop()
        expected_sample_at = loop.time() + 0.05
        max_lag_s = 0.0
        active = True
        timer: asyncio.TimerHandle

        def sample_event_loop_lag() -> None:
            nonlocal expected_sample_at, max_lag_s, timer
            now = loop.time()
            max_lag_s = max(max_lag_s, now - expected_sample_at)
            expected_sample_at = now + 0.05
            if active:
                timer = loop.call_later(0.05, sample_event_loop_lag)

        timer = loop.call_later(0.05, sample_event_loop_lag)
        started = time.perf_counter()
        def project(request: WsRequest, key: str, *, history: HistoryReader) -> Response | _PreparedThreadResponse:
            return self._handle_webui_thread_get(request, key, history=history, diagnostics=diagnostics)

        try:
            prepared = await self._project_session_history(request, key, project)
            if isinstance(prepared, _PreparedThreadResponse):
                response = await asyncio.to_thread(
                    _encode_thread_response, prepared.data,
                    graph_references=_query_first(_parse_query(request.path), "context_graph_encoding") == "references-v1",
                    accept_encoding=_combined_list_header(request.headers, "Accept-Encoding"),
                    extra_headers=prepared.headers, metrics=diagnostics.response,
                )
            else:
                response = prepared
        finally:
            active = False
            timer.cancel()
        diagnostics.total_ms = (time.perf_counter() - started) * 1000
        diagnostics.event_loop_lag_ms = max_lag_s * 1000
        self._log_webui_thread_diagnostics(response, diagnostics)
        return response

    def _log_webui_thread_diagnostics(
        self,
        response: Response,
        diagnostics: _WebUIThreadDiagnostics,
    ) -> None:
        stats = diagnostics.transcript
        if not (
            diagnostics.total_ms >= _SLOW_WEBUI_HTTP_LOG_MS
            or stats.capped_by_bytes
            or stats.capped_by_records
        ):
            return
        self._log.warning(
            "webui thread replay session_hash={} status={} limit={} source_bytes={} "
            "parsed_records={} selected_bytes={} selected_records={} compacted_deltas={} "
            "capped_bytes={} capped_records={} "
            "truncated_turn={} replay_ms={} build_ms={} json_ms={} gzip_ms={} gzip={} "
            "response_bytes={} event_loop_lag_ms={} total_ms={}",
            diagnostics.session_hash or "unknown",
            response.status_code,
            stats.effective_limit,
            stats.source_bytes,
            stats.parsed_records,
            stats.selected_bytes,
            stats.selected_records,
            stats.compacted_delta_records,
            stats.capped_by_bytes,
            stats.capped_by_records,
            stats.truncated_oversized_turn,
            stats.replay_ms,
            round(diagnostics.build_ms, 1),
            round(diagnostics.response.json_encode_ms, 1),
            round(diagnostics.response.gzip_ms, 1),
            diagnostics.response.gzip_enabled,
            diagnostics.response.response_bytes,
            round(diagnostics.event_loop_lag_ms, 1),
            round(diagnostics.total_ms, 1),
        )

    def _handle_webui_thread_get(
        self,
        request: WsRequest,
        decoded_key: str,
        *,
        history: HistoryReader,
        diagnostics: _WebUIThreadDiagnostics | None = None,
    ) -> Response | _PreparedThreadResponse:
        if diagnostics is not None:
            diagnostics.session_hash = hashlib.sha256(decoded_key.encode("utf-8")).hexdigest()[:12]
        scope = self.workspaces.scope_for_session_key(decoded_key)

        query = _parse_query(request.path)
        raw_limit = _query_first(query, "limit")
        limit: int | None = None
        if raw_limit is not None and raw_limit.strip():
            try:
                limit = int(raw_limit)
            except ValueError:
                return _http_error(400, "invalid limit")
        direction = _query_first(query, "direction")
        if direction is not None and direction not in {"latest"}:
            return _http_error(400, "invalid direction")
        before = _query_first(query, "before")
        after = _query_first(query, "after")
        if after is not None:
            from nanobot.webui.transcript import decode_transcript_cursor

            if before is not None or direction is not None or decode_transcript_cursor(after) is None:
                return _http_error(400, "invalid navigation cursor")
        from nanobot.session.webui_turns import (
            websocket_turn_id,
            websocket_turn_transcript_persistence_failed,
            websocket_turn_wall_started_at,
        )

        chat_id = decoded_key.split(":", 1)[1]
        active_turn_started_at = websocket_turn_wall_started_at(chat_id)
        active_turn_id = websocket_turn_id(chat_id)
        active_turn_transcript_persistence_failed = (
            websocket_turn_transcript_persistence_failed(chat_id)
        )
        include_model_requests = _query_first(query, "include_model_requests") == "1"
        revision_variant = {
            "include_model_requests": include_model_requests,
            "context_graph_encoding": _query_first(query, "context_graph_encoding"),
            "active_turn_id": active_turn_id,
            "active_turn_started_at": active_turn_started_at,
            "active_turn_transcript_persistence_failed": (
                active_turn_transcript_persistence_failed
            ),
            "before": before,
            "after": after,
            "direction": direction,
            "gateway_instance": self.tokens.instance_id,
            "limit": limit,
            "session_version": self._read_session_version(decoded_key),
            "workspace_scope": scope.payload(),
        }
        initial_revision = webui_transcript_revision(decoded_key, history=history, variant=revision_variant)
        if initial_revision is not None:
            etag = _quoted_etag(initial_revision)
            if _etag_matches(_case_insensitive_header(request.headers, "If-None-Match"), etag):
                return _http_response(b"", status=304, extra_headers=[*_NO_STORE_HEADERS, ("ETag", etag)])
        build_started = time.perf_counter()
        replay_stats = diagnostics.transcript if diagnostics is not None else TranscriptReplayStats()
        data = build_webui_thread_response(
            decoded_key, history=history, include_model_requests=include_model_requests,
            augment_user_media=lambda paths, local: self.media.augment_transcript_user_media(paths, local, session_key=decoded_key),
            augment_assistant_media=self.media.augment_transcript_media,
            augment_assistant_text=lambda text: self.media.rewrite_local_markdown_images(
                text,
                workspace_path=scope.project_path,
            ),
            session_messages_loader=lambda: self._read_session_messages(decoded_key),
            session_version_loader=lambda: self._read_session_version(decoded_key),
            active_turn_started_at=active_turn_started_at,
            active_turn_id=active_turn_id,
            active_turn_transcript_persistence_failed=(
                active_turn_transcript_persistence_failed
            ),
            limit=limit,
            direction=direction,
            before=before,
            after=after,
            stats=replay_stats,
        )
        if diagnostics is not None:
            diagnostics.build_ms = (time.perf_counter() - build_started) * 1000
        if data is None:
            return _http_error(404, "webui thread not found")
        data["workspace_scope"] = scope.payload()
        revision_variant["session_version"] = self._read_session_version(decoded_key)
        final_revision = webui_transcript_revision(decoded_key, history=history, variant=revision_variant)
        response_headers = list(_NO_STORE_HEADERS)
        if final_revision is not None and final_revision == initial_revision:
            response_headers.append(("ETag", _quoted_etag(final_revision)))
            data["revision"] = final_revision
        return _PreparedThreadResponse(
            data=data, headers=response_headers,
        )

    def _handle_webui_trace_detail_get(self, request: WsRequest, decoded_key: str, *, history: HistoryReader) -> Response:
        detail_ref = _query_first(_parse_query(request.path), "ref")
        if not detail_ref:
            return _http_error(400, "missing trace detail ref")
        data = build_webui_trace_detail_response(decoded_key, detail_ref, history=history)
        if data is None:
            return _http_error(404, "trace detail not found")
        return _http_json_response(
            data,
            accept_encoding=_combined_list_header(request.headers, "Accept-Encoding"),
            extra_headers=_NO_STORE_HEADERS,
        )

    def _handle_file_preview(self, request: WsRequest, key: str) -> Response:
        decoded_key = self._authorize_websocket_session(request, key)
        if isinstance(decoded_key, Response):
            return decoded_key
        query = _parse_query(request.path)
        path = _query_first(query, "path")
        is_probe = _query_first(query, "probe") == "1"
        metadata_only = _query_first(query, "metadata") == "1"
        try:
            scope = self.workspaces.scope_for_session_key(decoded_key)
            if metadata_only:
                payload = file_reference_payload(path, scope=scope)
            elif is_probe:
                payload = file_preview_availability_payload(path, scope=scope)
            else:
                payload = file_preview_payload(path, scope=scope)
        except WebUIFilePreviewError as e:
            if is_probe and not metadata_only and e.status in {400, 403, 404, 413, 415}:
                return _http_json_response({"available": False}, extra_headers=_NO_STORE_HEADERS)
            return _http_error(e.status, e.message)
        return _http_json_response(payload, extra_headers=_NO_STORE_HEADERS)

    def _handle_session_automations(self, request: WsRequest, key: str) -> Response:
        decoded_key = self._authorize_websocket_session(request, key)
        if isinstance(decoded_key, Response):
            return decoded_key
        return _http_json_response(self.automation_routes.session_payload(decoded_key))

    async def _handle_session_delete(self, key: str, params: MutationParams) -> MutationResult:
        if self.session_manager is None:
            return MutationResult.failure(503, "session manager unavailable")
        decoded_key = key
        if _API_KEY_RE.fullmatch(decoded_key) is None:
            return MutationResult.failure(400, "invalid session key")
        if not _is_websocket_channel_session_key(decoded_key):
            return MutationResult.failure(404, "session not found")
        delete_automations = (_mutation_text(params, "delete_automations") or "").lower()
        automation_jobs = self.automation_routes.session_jobs(decoded_key)
        if automation_jobs and delete_automations not in {"1", "true", "yes"}:
            return MutationResult.success(
                {
                    "deleted": False,
                    "blocked_by_automations": True,
                    "automations": serialize_automation_jobs(automation_jobs),
                }
            )
        await ensure_webui_archives_imported(self.session_manager.state)
        await self.automation_routes.remove_session_jobs(automation_jobs)
        draft_deleted = self.workspaces.discard_draft_scope(decoded_key)
        if self.discard_session is not None:
            await self.discard_session(decoded_key)
        elif self.subagent_manager is not None:
            await self.subagent_manager.cancel_by_session(decoded_key)
        session_deleted = await self.session_manager.state.delete(decoded_key)
        return MutationResult.success({"deleted": bool(draft_deleted or session_deleted)})


    async def _dispatch_media_routes(self, request: WsRequest, got: str) -> Response | None:
        m = _MEDIA_ROUTE_RE.match(got)
        if m:
            return await asyncio.to_thread(self._handle_media_fetch, m.group(1), m.group(2), request)
        return None

    def _handle_media_fetch(
        self, sig: str, payload: str, request: WsRequest | None = None
    ) -> Response:
        return self.media.serve_signed_media(
            sig,
            payload,
            request=request,
            scope_for_session=self.workspaces.existing_scope_for_session_key,
        )


    async def _dispatch_misc_routes(
        self, connection: Any, request: WsRequest, got: str
    ) -> Response | None:
        if got == "/api/sessions":
            return await self._handle_sessions_list(request)
        if got == "/api/commands":
            return self._handle_commands(request)
        if got == "/api/workspaces/directories":
            return await self._handle_workspace_directories(connection, request)
        if got == "/api/workspaces":
            return await asyncio.to_thread(self._handle_workspaces, connection, request)
        if got == "/api/webui/skills/search":
            return await self._handle_webui_skills_search(request)
        if got == "/api/webui/skills/trending":
            return await self._handle_webui_skills_trending(request)
        if got == "/api/webui/skills/trends":
            return await self._handle_webui_skill_trends(request)
        if got == "/api/webui/skills":
            return await self._handle_webui_skills(request)
        m = _SKILL_DETAIL_RE.match(got)
        if m:
            return await self._handle_webui_skill_detail(request, m.group(1))
        if got == "/api/webui/sidebar-state":
            return await self._handle_webui_sidebar_state(request)
        return None

    def _handle_commands(self, request: WsRequest) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        return _http_json_response({"commands": builtin_command_palette()})

    def _handle_workspaces(self, connection: Any, request: WsRequest) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        return _http_json_response(
            self.workspaces.payload(
                can_change_project=True,  # This HTTP route requires owner API authentication.
            )
        )

    def _handle_workspace_favorite(self, payload: dict[str, Any]) -> MutationResult:
        try:
            favorites = self.workspaces.set_favorite_project(payload.get("path"), payload.get("pinned"))
        except WorkspaceScopeError as exc:
            return MutationResult.failure(exc.status, exc.message)
        except OSError:
            return MutationResult.failure(500, "could not save favorite folders")
        return MutationResult.success({"favorite_projects": favorites})

    def _handle_workspace_resolve_project(self, payload: dict[str, Any]) -> MutationResult:
        try:
            project = self.workspaces.resolve_project(payload.get("path"))
        except WorkspaceScopeError as exc:
            return MutationResult.failure(exc.status, exc.message)
        return MutationResult.success(project)

    async def _handle_workspace_directories(self, connection: Any, request: WsRequest) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        query = _parse_query(request.path)
        try:
            payload = await asyncio.to_thread(
                browse_workspace_directories,
                _query_first(query, "path") or "",
                default_workspace=self.workspaces.default_scope().project_path,
                query=_query_first(query, "q") or "",
                show_hidden=_query_first(query, "hidden") == "1",
                allow_partial=_query_first(query, "partial") == "1",
            )
        except WorkspaceScopeError as exc:
            return _http_error(exc.status, exc.message)
        return _http_json_response(dict(payload))

    async def _load_webui_skills(self) -> dict[str, Any]:
        return await asyncio.to_thread(
            webui_skills_payload,
            self.skills_workspace_path,
            disabled_skills=set(self.disabled_skills),
        )

    async def _handle_webui_skills(self, request: WsRequest) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        return _http_json_response(await self._load_webui_skills())

    async def _handle_webui_skills_search(self, request: WsRequest) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        params = _parse_query(request.path)
        query = _query_first(params, "q") or ""
        provider = _query_first(params, "provider") or "all"
        try:
            payload = await search_marketplace_skills(
                query,
                self.skills_workspace_path,
                provider=provider,
            )
        except SkillsMarketplaceError as exc:
            return _http_error(exc.status, exc.message)
        except Exception:
            self._log.exception("skills marketplace search failed")
            return _http_error(500, "skills marketplace search failed")
        return _http_json_response(payload)

    async def _handle_webui_skills_trending(self, request: WsRequest) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        provider = _query_first(_parse_query(request.path), "provider") or "all"
        try:
            payload = await trending_marketplace_skills(
                self.skills_workspace_path,
                provider=provider,
            )
        except SkillsMarketplaceError as exc:
            return _http_error(exc.status, exc.message)
        except Exception:
            self._log.exception("skills marketplace trending lookup failed")
            return _http_error(500, "skills marketplace trending lookup failed")
        return _http_json_response(payload)

    async def _handle_webui_skill_trends(self, request: WsRequest) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        skill_ids = _parse_query(request.path).get("id", [])
        try:
            payload = await marketplace_skill_trends(skill_ids)
        except Exception:
            self._log.exception("skills.sh trend history lookup failed")
            return _http_error(500, "skills.sh trend history lookup failed")
        return _http_json_response(payload)

    async def _handle_webui_skill_install(
        self,
        connection: Any,
        headers: Any,
        params: MutationParams,
    ) -> MutationResult:
        if not await asyncio.to_thread(self._allow_webui_package_install, connection, headers):
            return MutationResult.failure(403, "remote skill installation is disabled")
        if self._skill_install_lock.locked():
            return MutationResult.failure(409, "another skill installation is already in progress")

        provider = _mutation_text(params, "provider") or "skills_sh"
        source = _mutation_text(params, "source") or ""
        skill_id = _mutation_text(params, "skill") or ""
        version = _mutation_text(params, "version") or ""
        async with self._skill_install_lock:
            try:
                action = await install_marketplace_skill(
                    source,
                    skill_id,
                    self.skills_workspace_path,
                    provider=provider,
                    version=version,
                )
            except SkillsMarketplaceError as exc:
                return MutationResult.failure(exc.status, exc.message)
            except Exception:
                self._log.exception("skill installation failed")
                return MutationResult.failure(500, "skill installation failed")
        return MutationResult.success({
            **(await self._load_webui_skills()),
            "last_action": action,
        })

    def _allow_webui_package_install(self, connection: Any, headers: Any) -> bool:
        if _is_local_browser_request(connection, headers):
            return True
        try:
            return bool(
                self.settings.config.load().tools.webui_allow_remote_package_install
            )
        except Exception:
            self._log.exception("failed to load remote package install policy")
            return False

    async def _handle_webui_skill_update(self, params: MutationParams) -> MutationResult:
        name = _mutation_text(params, "name") or ""
        raw_enabled = (_mutation_text(params, "enabled") or "").lower()
        if raw_enabled not in {"true", "false"}:
            return MutationResult.failure(400, "enabled must be true or false")
        try:
            action = await asyncio.to_thread(
                self.settings.config.run_serialized,
                lambda config_path: set_webui_skill_enabled(
                    self.skills_workspace_path,
                    name,
                    enabled=raw_enabled == "true",
                    disabled_skills=self.disabled_skills,
                    config_path=config_path,
                ),
            )
        except SkillManagementError as exc:
            return MutationResult.failure(exc.status, exc.message)
        self._apply_skill_state()
        return MutationResult.success({
            **(await self._load_webui_skills()),
            "last_action": action,
        })

    async def _handle_webui_skill_delete(
        self,
        connection: Any,
        headers: Any,
        params: MutationParams,
    ) -> MutationResult:
        if not _is_local_browser_request(connection, headers):
            return MutationResult.failure(403, "remote skill deletion is disabled")
        name = _mutation_text(params, "name") or ""
        try:
            action = await asyncio.to_thread(
                self.settings.config.run_serialized,
                lambda config_path: delete_webui_skill(
                    self.skills_workspace_path,
                    name,
                    disabled_skills=self.disabled_skills,
                    config_path=config_path,
                ),
            )
        except SkillManagementError as exc:
            return MutationResult.failure(exc.status, exc.message)
        self._apply_skill_state()
        return MutationResult.success({
            **(await self._load_webui_skills()),
            "last_action": action,
        })

    def _apply_skill_state(self) -> None:
        if self.skill_state_action is not None:
            self.skill_state_action(set(self.disabled_skills))

    async def _handle_webui_skill_detail(self, request: WsRequest, raw_name: str) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        from urllib.parse import unquote

        name = unquote(raw_name)
        if not name or "/" in name or "\\" in name:
            return _http_error(400, "invalid skill name")
        payload = await asyncio.to_thread(
            webui_skill_detail_payload,
            self.skills_workspace_path,
            name,
            disabled_skills=set(self.disabled_skills),
        )
        if payload is None:
            return _http_error(404, "skill not found")
        return _http_json_response(payload)

    async def _handle_webui_sidebar_state(self, request: WsRequest) -> Response:
        if not self.check_api_token(request):
            return _http_error(401, "Unauthorized")
        try:
            state = await self.sidebar_state.read()
        except (OSError, ValueError):
            self._log.exception("failed to read webui sidebar state")
            return _http_error(500, "failed to read sidebar state")
        return _http_json_response(state)

    async def _handle_webui_sidebar_state_update(self, payload: dict[str, Any]) -> MutationResult:
        state_value = payload.get("state")
        if state_value is None:
            return MutationResult.failure(400, "missing state")
        if not isinstance(state_value, dict):
            return MutationResult.failure(400, "state must be an object")
        try:
            state = await self.sidebar_state.write(cast(dict[str, Any], state_value))
        except ValueError as e:
            return MutationResult.failure(400, str(e))
        except OSError:
            self._log.exception("failed to write webui sidebar state")
            return MutationResult.failure(500, "failed to write sidebar state")
        return MutationResult.success(state)


    async def _mutate_star_prompt(self, action: Literal["claim", "dismiss"]) -> MutationResult:
        try:
            show = await asyncio.to_thread(update_star_prompt, action)
        except (OSError, ValueError, TimeoutError):
            self._log.exception("failed to persist star invitation state")
            return MutationResult.failure(500, "failed to save reminder preference")
        return MutationResult.success({"show": show})

    def _serve_static(
        self,
        request_path: str,
        *,
        accept_encoding: str = "",
    ) -> Response | None:
        assert self.static_dist_path is not None
        rel = request_path.lstrip("/")
        if not rel:
            rel = "index.html"
        if ".." in rel.split("/") or rel.startswith("/"):
            return _http_error(403, "Forbidden")
        candidate = (self.static_dist_path / rel).resolve()
        try:
            candidate.relative_to(self.static_dist_path)
        except ValueError:
            return _http_error(403, "Forbidden")
        if not candidate.is_file():
            index = self.static_dist_path / "index.html"
            if index.is_file():
                candidate = index
            else:
                return None
        ctype, _ = mimetypes.guess_type(candidate.name)
        if ctype is None:
            ctype = "application/octet-stream"
        utf8_text = ctype.startswith("text/") or ctype in {
            "application/javascript",
            "application/json",
        }
        compressible = utf8_text or ctype == "image/svg+xml"
        response_path = candidate
        extra_headers: list[tuple[str, str]] = []
        if compressible:
            extra_headers.append(("Vary", "Accept-Encoding"))
            gzip_candidate = candidate.with_name(f"{candidate.name}.gz")
            if _accepts_gzip(accept_encoding) and gzip_candidate.is_file():
                response_path = gzip_candidate
                extra_headers.append(("Content-Encoding", "gzip"))
        try:
            body = response_path.read_bytes()
        except OSError as e:
            self._log.warning("static: failed to read {}: {}", response_path, e)
            return _http_error(500, "Internal Server Error")
        if utf8_text:
            ctype = f"{ctype}; charset=utf-8"
        if candidate.name == "index.html":
            cache = "no-cache"
        else:
            cache = "public, max-age=31536000, immutable"
        return _http_response(
            body,
            status=200,
            content_type=ctype,
            extra_headers=[("Cache-Control", cache), *extra_headers],
        )


def _is_websocket_channel_session_key(key: str) -> bool:
    return is_webui_session_key(key)
