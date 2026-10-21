from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock
from urllib.parse import parse_qs, urlsplit

import pytest
from websockets.datastructures import Headers

from nanobot.bus.queue import MessageBus
from nanobot.config.loader import get_config_path
from nanobot.config.network import NetworkConfig
from nanobot.config.schema import MCPServerConfig
from nanobot.runtime_admission import RuntimeBusyError
from nanobot.webui.http_utils import http_json_response
from nanobot.webui.mcp_presets_api import custom_mcp_action
from nanobot.webui.settings_routes import WebUISettingsRouter
from nanobot.webui.settings_services import WebUISettingsServices


def _router(
    *,
    authorized: bool = True,
    config_path: Path | None = None,
    mcp_runtime_status: Callable[[], Mapping[str, str]] | None = None,
    mcp_reload: Callable[[], Awaitable[dict[str, object]]] | None = None,
    image_generation_reload: Callable[[], Awaitable[dict[str, object]]] | None = None,
    rename_model_preset: Callable[[str, str], int] | None = None,
    refresh_runtime_config: Callable[[], None] | None = None,
) -> WebUISettingsRouter:
    return WebUISettingsRouter(
        settings=WebUISettingsServices.create(
            config_path or get_config_path(),
            rename_model_preset=rename_model_preset,
            refresh_runtime_config=refresh_runtime_config,
        ),
        bus=MessageBus(),
        logger=SimpleNamespace(exception=lambda *_args: None, warning=lambda *_args: None),
        check_api_token=lambda _request: authorized,
        parse_query=lambda path: parse_qs(urlsplit(path).query),
        json_response=http_json_response,
        error_response=lambda status, message: http_json_response(
            {"error": message},
            status=status,
        ),
        runtime_surface="browser",
        runtime_capabilities={},
        mcp_runtime_status=mcp_runtime_status,
        mcp_reload=mcp_reload,
        image_generation_reload=image_generation_reload,
        mcp_oauth_redirect_uri=lambda _request: "https://gateway.example/auth/mcp/callback",
    )


def _mutation_request(path: str, payload: dict[str, object]) -> SimpleNamespace:
    request = SimpleNamespace(path=path, headers=Headers())
    request._nanobot_webui_mutation_request = True
    request._nanobot_webui_mutation_payload = payload
    request._nanobot_trusted_proxy_authenticated = True
    return request


@pytest.mark.asyncio
async def test_nanobot_update_requires_auth_local_permission_and_websocket(tmp_path, monkeypatch):
    router = _router(config_path=tmp_path / "config.json")
    path = "/api/settings/nanobot-update/job/prepare"
    request = SimpleNamespace(path=path, headers=Headers())
    response = await router.dispatch(None, request, path)
    assert response.status_code == 405
    response = await router.dispatch(None, _mutation_request(path, {}), path)
    assert response.status_code == 403
    unauthorized = _router(authorized=False, config_path=tmp_path / "config.json")
    response = await unauthorized.dispatch(None, _mutation_request(path, {}), path)
    assert response.status_code == 401
    monkeypatch.setattr(router._system, "allow_feature_package_install", lambda _: True)
    response = await router.dispatch(None, _mutation_request(path, {"id": "invalid"}), path)
    assert response.status_code == 400
    router._runtime_surface = "native"
    response = await router.dispatch(None, _mutation_request(path, {}), path)
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_close_releases_channel_connectors() -> None:
    router = _router()
    closed = False

    class Connector:
        has_pending_work = False

        async def handle(self, action, query):
            return {}

        async def close(self) -> None:
            nonlocal closed
            closed = True

    router._system._channel_connectors["whatsapp"] = Connector()

    await router.close()

    assert closed is True
    assert router._system._channel_connectors == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("finish", ["cancel", "logout", "shutdown"])
async def test_provider_login_keeps_maintenance_busy_until_worker_exits(tmp_path, monkeypatch, finish):
    router = _router(config_path=tmp_path / "config.json")
    stopping, release = threading.Event(), threading.Event()
    saved = []

    def login(*, on_authorization, cancelled, persist, **_kwargs):
        assert persist is False
        on_authorization("https://github.com/login/device", "FIXTURE", 60)
        assert cancelled.wait(3)
        stopping.set()
        assert release.wait(3)
        return SimpleNamespace(access="late-fixture-token")

    monkeypatch.setattr("nanobot.providers.github_copilot_oauth.login_github_copilot", login)
    monkeypatch.setattr("nanobot.providers.github_copilot_provider.get_storage", lambda: SimpleNamespace(
        get_token_path=lambda: tmp_path / "copilot.json", save=saved.append,
    ))
    monkeypatch.setattr("nanobot.webui.settings_api.settings_payload", lambda **_: {})
    path = "/api/settings/provider/oauth-login"
    response = await router.dispatch(None, _mutation_request(path, {"provider": "github_copilot"}), path)
    assert response.status_code == 200
    payload = json.loads(response.body)
    with pytest.raises(RuntimeBusyError), router.bus.admission.pause_if_idle(lambda: False):
        pytest.fail("The authorization prompt still has a live worker")
    try:
        if finish == "shutdown":
            shutdown = asyncio.create_task(router.close())
            assert await asyncio.to_thread(stopping.wait, 1)
            shutdown.cancel()
            with pytest.raises(asyncio.CancelledError):
                await shutdown
        else:
            path = (
                "/api/settings/provider/oauth-logout" if finish == "logout"
                else "/api/settings/provider/oauth-login/complete"
            )
            response = await router.dispatch(None, _mutation_request(path, {
                "provider": "github_copilot", "flow_id": payload["flow_id"], "cancel": "true",
            }), path)
            assert response.status_code == 200
            assert await asyncio.to_thread(stopping.wait, 1)
        assert router.settings.oauth_flows.get("github_copilot", payload["flow_id"]) is None
        with pytest.raises(RuntimeBusyError), router.bus.admission.pause_if_idle(lambda: False):
            pytest.fail("Removing a login or cancelling its close awaiter cannot forget the thread")
    finally:
        release.set()
        await router.close()
    assert saved == []
    assert not router.settings.oauth_flows.has_pending_work
    with router.bus.admission.pause_if_idle(lambda: False):
        pass


@pytest.mark.asyncio
async def test_failed_codex_login_start_still_owns_late_worker(tmp_path, monkeypatch):
    import nanobot.providers.openai_codex_oauth as oauth

    router = _router(config_path=tmp_path / "config.json")
    entered, release = threading.Event(), threading.Event()
    target = tmp_path / "codex.json"
    monkeypatch.setenv("OAUTH_CLI_KIT_TOKEN_PATH", str(target))
    monkeypatch.setattr(oauth, "_AUTHORIZATION_URL_TIMEOUT_S", 0.02)

    def login(*, storage, **_kwargs):
        entered.set()
        assert release.wait(3)
        # The actual SDK can finish its token exchange after start() timed out.
        storage.save(SimpleNamespace(access="late-fixture-token"))

    monkeypatch.setattr(oauth, "login_oauth_interactive", login)
    path = "/api/settings/provider/oauth-login"
    try:
        response = await router.dispatch(None, _mutation_request(path, {
            "provider": "openai_codex", "remote_browser": "true",
        }), path)
        assert response.status_code == 502
        assert entered.is_set()
        with pytest.raises(RuntimeBusyError), router.bus.admission.pause_if_idle(lambda: False):
            pytest.fail("A failed start must retain its background worker")
    finally:
        release.set()
        await router.close()
    assert not target.exists()
    with router.bus.admission.pause_if_idle(lambda: False):
        pass


@pytest.mark.asyncio
@pytest.mark.parametrize("close_fails", [False, True])
async def test_channel_setup_blocks_maintenance_until_confirmed_cleanup(
    tmp_path, monkeypatch, close_fails,
) -> None:
    router = _router(config_path=tmp_path / "config.json")
    cleanup_started, allow_cleanup = asyncio.Event(), asyncio.Event()

    class Connector:
        has_pending_work = True

        async def handle(self, action, query):
            return {"status": "pending", "session_id": "test"}

        async def close(self):
            cleanup_started.set()
            await allow_cleanup.wait()
            if close_fails:
                raise RuntimeError("native writer has not stopped")
            self.has_pending_work = False

    connector = Connector()
    monkeypatch.setattr(
        "nanobot.webui.settings_routes.load_channel_plugin",
        lambda _: SimpleNamespace(load_connector=lambda: connector),
    )
    path = "/api/settings/channels/whatsapp/connect/start"
    response = await router.dispatch(None, _mutation_request(path, {}), path)
    assert response.status_code == 200
    assert json.loads(response.body)["status"] == "pending"
    with pytest.raises(RuntimeBusyError), router.bus.admission.pause_if_idle(lambda: False):
        pytest.fail("Returning a QR code does not finish its connection")
    shutdown = asyncio.create_task(router.close())
    try:
        await asyncio.wait_for(cleanup_started.wait(), timeout=0.5)
        with pytest.raises(RuntimeBusyError), router.bus.admission.pause_if_idle(lambda: False):
            pytest.fail("Cleanup still owns its pending connection")
    finally:
        allow_cleanup.set()
        await shutdown
    if close_fails:
        assert router._system._channel_connectors["whatsapp"] is connector
        with pytest.raises(RuntimeBusyError), router.bus.admission.pause_if_idle(lambda: False):
            pytest.fail("A failed close must not release ownership")
        close_fails = False
        await router.close()
    assert router._system._channel_connectors == {}
    with router.bus.admission.pause_if_idle(lambda: False):
        pass


@pytest.mark.asyncio
async def test_legacy_connector_can_connect_but_cannot_claim_maintenance_idle(tmp_path, monkeypatch):
    router = _router(config_path=tmp_path / "config.json")
    connector = SimpleNamespace(handle=AsyncMock(return_value={"status": "pending"}))
    monkeypatch.setattr(
        "nanobot.webui.settings_routes.load_channel_plugin",
        lambda _: SimpleNamespace(load_connector=lambda: connector),
    )
    path = "/api/settings/channels/custom/connect/start"
    response = await router.dispatch(None, _mutation_request(path, {}), path)
    assert response.status_code == 200
    await router.close()
    with pytest.raises(RuntimeBusyError), router.bus.admission.pause_if_idle(lambda: False):
        pytest.fail("An untracked extension must not be assumed idle")


@pytest.mark.asyncio
async def test_mcp_list_serializes_local_runtime_failure_snapshot(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    custom_mcp_action(
        "custom",
        {
            "name": ["team-docs"],
            "transport": ["streamableHttp"],
            "url": ["https://mcp.example.com/mcp"],
        },
        config_path=config_path,
    )
    snapshot_calls = 0

    def runtime_snapshot() -> Mapping[str, str]:
        nonlocal snapshot_calls
        snapshot_calls += 1
        return {"team-docs": "failed"}

    router = _router(
        config_path=config_path,
        mcp_runtime_status=runtime_snapshot,
    )
    request = SimpleNamespace(
        path="/api/settings/mcp-presets",
        headers=Headers(),
    )

    response = await router.dispatch(None, request, "/api/settings/mcp-presets")

    assert response is not None
    assert response.status_code == 200
    payload = json.loads(response.body)
    row = next(item for item in payload["presets"] if item["name"] == "team-docs")
    assert row["status"] == "configured"
    assert row["runtime_status"] == "failed"
    assert b'"runtime_status": "failed"' in response.body
    assert snapshot_calls == 1


@pytest.mark.asyncio
async def test_usage_query_runs_off_the_event_loop(monkeypatch) -> None:
    calling_thread = threading.get_ident()
    worker_threads: list[int] = []

    def usage_payload(**_kwargs):
        worker_threads.append(threading.get_ident())
        return {"days": []}

    monkeypatch.setattr("nanobot.webui.settings_routes.settings_usage_payload", usage_payload)
    request = SimpleNamespace(path="/api/settings/usage", headers=Headers())

    response = await _router().dispatch(None, request, request.path)

    assert response is not None
    assert response.status_code == 200
    assert worker_threads and worker_threads[0] != calling_thread


@pytest.mark.asyncio
async def test_full_settings_query_runs_off_the_event_loop(monkeypatch) -> None:
    calling_thread = threading.get_ident()
    worker_threads: list[int] = []
    router = _router()

    def settings_response():
        worker_threads.append(threading.get_ident())
        return http_json_response({"ok": True})

    monkeypatch.setattr(router, "_handle_settings", settings_response)
    request = SimpleNamespace(path="/api/settings", headers=Headers())

    response = await router.dispatch(None, request, request.path)

    assert response is not None
    assert response.status_code == 200
    assert worker_threads and worker_threads[0] != calling_thread


@pytest.mark.asyncio
@pytest.mark.parametrize(("provider", "model", "effort", "expected"), [
    ("openai", "gpt-4o", "", "chat_completions"),
    ("openai", "gpt-4o", "high", "responses"),
    ("tenant", "gpt-6-luna", "high", "chat_completions"),
    ("openai_codex", "gpt-6-astra", "", "responses"),
])
async def test_automatic_model_api_read_resolves_drafts_without_saving_or_probing(
    tmp_path, monkeypatch, provider, model, effort, expected,
) -> None:
    from nanobot.config.loader import save_config
    from nanobot.config.schema import Config

    config_path = tmp_path / "config.json"
    save_config(Config.model_validate({"providers": {
        "openai": {"apiKey": "fixture"},
        "tenant": {"apiBase": "https://tenant.test/v1"},
    }}), config_path)
    before = config_path.read_bytes()

    def unexpected_client(*_args, **_kwargs):
        pytest.fail("API resolution must not construct an HTTP client")

    monkeypatch.setattr("httpx.Client", unexpected_client)
    monkeypatch.setattr("httpx.AsyncClient", unexpected_client)
    path = f"/api/settings/model-api?provider={provider}&model={model}&reasoning_effort={effort}"
    request = SimpleNamespace(path=path, headers=Headers())
    route = "/api/settings/model-api"
    denied = await _router(authorized=False, config_path=config_path).dispatch(None, request, route)
    assert denied is not None and denied.status_code == 401
    response = await _router(config_path=config_path).dispatch(None, request, route)
    assert response is not None and response.status_code == 200
    assert json.loads(response.body) == {"provider": provider, "api": expected}
    assert config_path.read_bytes() == before
    assert WebUISettingsRouter.is_mutation_path(route) is False


@pytest.mark.asyncio
async def test_mcp_reload_callback_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = asyncio.Event()

    async def reload_mcp() -> dict[str, object]:
        started.set()
        await asyncio.Event().wait()
        return {"ok": True}

    monkeypatch.setattr(
        "nanobot.webui.settings_routes._MCP_RELOAD_TIMEOUT_SECONDS",
        0.01,
    )
    router = _router(mcp_reload=reload_mcp)

    result = await router._reload_mcp_runtime()

    assert started.is_set()
    assert result == {
        "ok": False,
        "message": "MCP hot reload timed out. Restart nanobot to pick up changes.",
        "requires_restart": True,
    }


@pytest.mark.asyncio
async def test_settings_shutdown_joins_browser_authorization_and_releases_admission(
    tmp_path, monkeypatch,
) -> None:
    config = MCPServerConfig(type="streamableHttp", auth="oauth", url="https://mcp.example/mcp")
    monkeypatch.setattr(
        "nanobot.webui.settings_routes.ensure_mcp_oauth_server",
        lambda _query, *, config_path=None: ("linear", config, NetworkConfig()),
    )
    monkeypatch.setattr("nanobot.webui.mcp_oauth_api.validate_url_target", lambda _: (True, ""))
    cleanup_started, allow_cleanup = asyncio.Event(), asyncio.Event()

    async def connect(_servers, _registry, *, oauth_handlers, network):
        handlers = oauth_handlers["linear"]
        await handlers.redirect_handler("https://accounts.example/authorize?state=settings")
        try:
            await handlers.callback_handler()
        finally:
            cleanup_started.set()
            await allow_cleanup.wait()
        return {}

    monkeypatch.setattr("nanobot.webui.mcp_oauth_api.connect_mcp_servers", connect)
    router = _router(config_path=tmp_path / "config.json")
    path = "/api/settings/mcp-oauth/start"
    response = await router.dispatch(None, _mutation_request(path, {"name": "linear"}), path)
    assert response.status_code == 200
    assert json.loads(response.body)["status"] == "authorization_required"
    with pytest.raises(RuntimeBusyError), router.bus.admission.pause_if_idle(lambda: False):
        pytest.fail("Settings returned, but authorization has not finished")

    shutdown = asyncio.create_task(router.close())
    try:
        await asyncio.wait_for(cleanup_started.wait(), timeout=0.5)
        assert not shutdown.done()
        with pytest.raises(RuntimeBusyError), router.bus.admission.pause_if_idle(lambda: False):
            pytest.fail("Settings shutdown must retain ownership through cleanup")
    finally:
        allow_cleanup.set()
        await shutdown
    with router.bus.admission.pause_if_idle(lambda: False):
        pass


@pytest.mark.asyncio
async def test_mcp_oauth_start_uses_gateway_callback_and_requires_api_auth(monkeypatch) -> None:
    config = SimpleNamespace(
        type="streamableHttp",
        auth="oauth",
        url="https://app.xmind.com/api/mcp",
    )
    network = SimpleNamespace(proxy="http://shared.example:8080")
    monkeypatch.setattr(
        "nanobot.webui.settings_routes.ensure_mcp_oauth_server",
        lambda _query, *, config_path=None: ("xmind", config, network),
    )
    router = _router()
    start = AsyncMock(return_value={
        "status": "authorization_required",
        "flow_id": "flow-123",
        "name": "xmind",
        "authorization_url": "https://xmind.example/authorize?state=state-123",
    })
    router._mcp_oauth = SimpleNamespace(start=start)
    request = _mutation_request(
        "/api/settings/mcp-oauth/start",
        {"name": "xmind"},
    )

    response = await router.dispatch(None, request, "/api/settings/mcp-oauth/start")

    assert response is not None
    assert response.status_code == 200
    assert json.loads(response.body)["flow_id"] == "flow-123"
    start.assert_awaited_once_with(
        "xmind",
        config,
        "https://gateway.example/auth/mcp/callback",
        reload_mcp=ANY,
        network=network,
        reset_credentials=False,
    )

    denied = _router(authorized=False)
    denied_response = await denied.dispatch(None, request, "/api/settings/mcp-oauth/start")
    assert denied_response is not None
    assert denied_response.status_code == 401

    failed = _router()
    failed._mcp_oauth = SimpleNamespace(
        start=AsyncMock(side_effect=RuntimeError("upstream secret response"))
    )
    failed_response = await failed.dispatch(None, request, "/api/settings/mcp-oauth/start")
    assert failed_response is not None
    assert failed_response.status_code == 500
    assert json.loads(failed_response.body) == {"error": "MCP OAuth start failed"}
    assert b"upstream secret response" not in failed_response.body


@pytest.mark.asyncio
async def test_mcp_oauth_callback_is_state_authenticated_and_returns_close_page() -> None:
    router = _router(authorized=False)
    submit = MagicMock(return_value="xmind")
    router._mcp_oauth = SimpleNamespace(submit_callback=submit)
    request = SimpleNamespace(
        path="/auth/mcp/callback?code=oauth-code&state=state-123",
        headers=Headers(),
    )

    response = await router.dispatch(None, request, "/auth/mcp/callback")

    assert response is not None
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "text/html; charset=utf-8"
    assert response.headers["Cache-Control"] == "no-store"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert b"window.close" in response.body
    assert b"Authorization received" in response.body
    assert b"oauth-code" not in response.body
    submit.assert_called_once_with(state="state-123", code="oauth-code", error=None)


@pytest.mark.asyncio
async def test_mcp_oauth_manual_completion_reads_websocket_payload() -> None:
    callback_url = (
        "http://127.0.0.1:8765/auth/mcp/callback?code=oauth-code&state=state-123"
    )
    router = _router()
    submit = MagicMock(
        return_value={
            "flow_id": "flow-123",
            "name": "linear",
            "status": "connecting",
            "expires_in": 299,
            "completion_input": "callback_url",
        }
    )
    router._mcp_oauth = SimpleNamespace(submit_callback_url=submit)
    request = _mutation_request(
        "/api/settings/mcp-oauth/complete",
        {"flow_id": "flow-123", "callback_url": callback_url},
    )

    response = await router.dispatch(None, request, "/api/settings/mcp-oauth/complete")

    assert response is not None
    assert response.status_code == 200
    assert json.loads(response.body)["status"] == "connecting"
    assert b"oauth-code" not in response.body
    submit.assert_called_once_with(flow_id="flow-123", callback_url=callback_url)

    denied = _router(authorized=False)
    denied_response = await denied.dispatch(
        None,
        request,
        "/api/settings/mcp-oauth/complete",
    )
    assert denied_response is not None
    assert denied_response.status_code == 401


@pytest.mark.parametrize(
    ("provider", "authorization_response"),
    [
        ("xai_grok", "secret"),
        (
            "openai_codex",
            "http://localhost:1455/auth/callback?code=secret&state=test",
        ),
    ],
)
@pytest.mark.asyncio
async def test_oauth_completion_reads_websocket_payload(
    monkeypatch,
    provider: str,
    authorization_response: str,
) -> None:
    captured: dict[str, object] = {}

    def complete(
        query,
        authorization_response=None,
        *,
        oauth_flows=None,
        config_path=None,
    ):
        captured.update(query=query, authorization_response=authorization_response)
        return {
            "status": "pending",
            "provider": provider,
            "flow_id": "flow-123",
        }

    monkeypatch.setattr("nanobot.webui.settings_routes.complete_oauth_provider", complete)
    router = _router()
    request = _mutation_request(
        "/api/settings/provider/oauth-login/complete",
        {
            "provider": provider,
            "flow_id": "flow-123",
            "authorization_response": authorization_response,
        },
    )

    response = await router.dispatch(
        None,
        request,
        "/api/settings/provider/oauth-login/complete",
    )

    assert response is not None
    assert response.status_code == 200
    assert json.loads(response.body) == {
        "status": "pending",
        "provider": provider,
        "flow_id": "flow-123",
    }
    assert captured == {
        "query": {"provider": [provider], "flow_id": ["flow-123"]},
        "authorization_response": authorization_response,
    }
    assert request.path == "/api/settings/provider/oauth-login/complete"
    assert not request.headers


@pytest.mark.parametrize(
    ("route_path", "function_name", "payload", "expected_query"),
    [
        (
            "/api/settings/update",
            "update_agent_settings",
            {"model_preset": "Codex"},
            {"model_preset": ["Codex"]},
        ),
        (
            "/api/settings/model-configurations/create",
            "create_model_configuration",
            {"name": "Codex", "model": "openai-codex/gpt-5.6"},
            {"name": ["Codex"], "model": ["openai-codex/gpt-5.6"]},
        ),
        (
            "/api/settings/model-configurations/delete",
            "delete_model_configuration",
            {"name": "spare"},
            {"name": ["spare"]},
        ),
        (
            "/api/settings/model-configurations/migrate",
            "migrate_model_configurations",
            {},
            {},
        ),
        (
            "/api/settings/model-call-order/update",
            "update_model_call_order",
            {"order": ["backup"]},
            {"order": ['["backup"]']},
        ),
        (
            "/api/settings/provider/create",
            "create_provider_settings",
            {"name": "team", "api_base": "https://llm.example/v1"},
            {"name": ["team"], "api_base": ["https://llm.example/v1"]},
        ),
        (
            "/api/settings/provider/update",
            "update_provider_settings",
            {"provider": "team", "api_base": "https://llm.example/v2"},
            {"provider": ["team"], "api_base": ["https://llm.example/v2"]},
        ),
    ],
)
@pytest.mark.asyncio
async def test_runtime_config_mutation_routes_refresh_live_runtime(
    monkeypatch,
    route_path: str,
    function_name: str,
    payload: dict[str, object],
    expected_query: dict[str, list[str]],
) -> None:
    captured: dict[str, object] = {}
    refresh_runtime_config = MagicMock()

    def mutate(query, *, config_path=None):
        captured["query"] = query
        return {"routed": function_name}

    monkeypatch.setattr(f"nanobot.webui.settings_routes.{function_name}", mutate)
    request = _mutation_request(route_path, payload)

    response = await _router(
        refresh_runtime_config=refresh_runtime_config,
    ).dispatch(None, request, route_path)

    assert response is not None
    assert response.status_code == 200
    assert json.loads(response.body)["routed"] == function_name
    assert captured["query"] == expected_query
    refresh_runtime_config.assert_called_once_with()


@pytest.mark.asyncio
async def test_model_update_route_forwards_session_rename_dependency(monkeypatch) -> None:
    rename_model_preset = MagicMock(return_value=2)
    refresh_runtime_config = MagicMock()
    captured: dict[str, object] = {}

    def update(query, *, config_path=None, rename_model_preset=None):
        captured.update(query=query, rename_model_preset=rename_model_preset)
        return {"updated": True}

    monkeypatch.setattr("nanobot.webui.settings_routes.update_model_configuration", update)
    path = "/api/settings/model-configurations/update"
    request = _mutation_request(path, {"name": "openai", "new_name": "Codex"})

    response = await _router(
        rename_model_preset=rename_model_preset,
        refresh_runtime_config=refresh_runtime_config,
    ).dispatch(
        None,
        request,
        path,
    )

    assert response is not None
    assert response.status_code == 200
    assert captured == {
        "query": {"name": ["openai"], "new_name": ["Codex"]},
        "rename_model_preset": rename_model_preset,
    }
    refresh_runtime_config.assert_called_once_with()


@pytest.mark.asyncio
async def test_settings_get_mutation_route_is_method_not_allowed() -> None:
    path = "/api/settings/provider/update"
    request = SimpleNamespace(
        path=f"{path}?provider=openrouter&api_key=must-not-run",
        headers=Headers(),
    )

    response = await _router().dispatch(None, request, path)

    assert response is not None
    assert response.status_code == 405
    assert json.loads(response.body) == {
        "error": "WebUI mutations require an authenticated WebSocket"
    }


@pytest.mark.parametrize(
    ("update_info", "expected"),
    [
        (None, {"updateAvailable": None}),
        (
            {
                "currentVersion": "1.2.0",
                "latestVersion": "1.3.0",
                "pypiUrl": "https://pypi.org/project/nanobot-ai/",
            },
            {
                "updateAvailable": {
                    "currentVersion": "1.2.0",
                    "latestVersion": "1.3.0",
                    "pypiUrl": "https://pypi.org/project/nanobot-ai/",
                }
            },
        ),
    ],
)
@pytest.mark.asyncio
async def test_version_check_route_returns_stable_payload(
    monkeypatch: pytest.MonkeyPatch,
    update_info: dict[str, str] | None,
    expected: dict[str, object],
) -> None:
    monkeypatch.setattr(
        "nanobot.webui.settings_routes.check_for_update",
        AsyncMock(return_value={"updateAvailable": update_info, "releaseStatus": {"state": "available" if update_info else "current"}}),
    )
    request = SimpleNamespace(path="/api/settings/version-check", headers=Headers())

    response = await _router().dispatch(None, request, request.path)

    assert response is not None
    assert response.status_code == 200
    assert json.loads(response.body) == expected


async def test_version_check_and_mcp_requests_share_the_gateway_loop(monkeypatch, tmp_path):
    import httpx
    from packaging.tags import Tag

    import nanobot
    from nanobot.release_feed import PYPI_URL, ReleaseFeed
    from nanobot.releases import release_filenames
    from nanobot.security import network
    from nanobot.update_channel import UpdateChannel
    from nanobot.webui import version_check

    gateway_loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    finish = asyncio.Event()
    requests = []

    def resolve(url, **_kwargs):
        if url == f"{PYPI_URL}/json":
            # Settle the gateway requests on the next tick of the checking loop,
            # after discovery has tried to acquire the already-contended lock.
            asyncio.get_running_loop().call_soon(gateway_loop.call_soon_threadsafe, finish.set)
        return True, "", ("93.184.216.34",)

    async def respond(request):
        requests.append(str(request.url))
        if request.url.host == "mcp.example":
            entered.set()
            await finish.wait()
            return httpx.Response(200, json={})
        assert str(request.url) == f"{PYPI_URL}/json"
        return httpx.Response(200, json={
            "info": {"name": "nanobot-ai", "version": "0.3.5", "requires_python": ">=3.11"},
            "urls": [{"filename": name, "size": 123, "yanked": False,
                      "digests": {"sha256": "c" * 64},
                      "url": f"https://files.pythonhosted.org/packages/{name}"}
                     for name in sorted(release_filenames("0.3.5"))
                     if name.endswith((".whl", ".tar.gz"))],
        })

    def transport():
        return network.PinnedDNSAsyncTransport(inner=httpx.MockTransport(respond))

    monkeypatch.setattr(network.PinnedDNSAsyncTransport, "_resolver_lock", asyncio.Lock())
    monkeypatch.setattr(network, "resolve_url_target", resolve)
    monkeypatch.setattr(nanobot, "__version__", "0.3.5")
    monkeypatch.setattr(version_check, "read_update_channel", UpdateChannel)
    monkeypatch.setattr(version_check, "installation_state_dir", lambda: tmp_path)
    monkeypatch.setattr(version_check, "ReleaseFeed", lambda directory: ReleaseFeed(
        directory, transport=transport(), supported_tags=[Tag("py3", "none", "win_amd64")],
    ))
    request = SimpleNamespace(path="/api/settings/version-check", headers=Headers())

    async with httpx.AsyncClient(transport=transport(), trust_env=False) as client:
        first = asyncio.create_task(client.get("https://mcp.example/first"))
        await asyncio.wait_for(entered.wait(), timeout=5)
        second = asyncio.create_task(client.get("https://mcp.example/second"))
        await asyncio.sleep(0)  # Let the second gateway request wait on the shared lock.
        try:
            response = await asyncio.wait_for(_router().dispatch(None, request, request.path), timeout=5)
        finally:
            finish.set()
            await asyncio.gather(first, second)
        subsequent = await client.get("https://mcp.example/subsequent")

    assert response.status_code == 200
    assert json.loads(response.body) == {"updateAvailable": None}
    assert subsequent.status_code == 200
    assert requests == ["https://mcp.example/first", "https://mcp.example/second",
                        f"{PYPI_URL}/json", "https://mcp.example/subsequent"]


@pytest.mark.asyncio
async def test_version_check_route_enforces_auth_and_bounds_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    check = AsyncMock(side_effect=RuntimeError("upstream secret body"))
    monkeypatch.setattr("nanobot.webui.settings_routes.check_for_update", check)
    request = SimpleNamespace(path="/api/settings/version-check", headers=Headers())

    unauthorized = await _router(authorized=False).dispatch(None, request, request.path)
    assert unauthorized is not None
    assert unauthorized.status_code == 401
    check.assert_not_called()

    failed = await _router().dispatch(None, request, request.path)
    assert failed is not None
    assert failed.status_code == 500
    assert json.loads(failed.body) == {"error": "version check failed"}
    assert "upstream secret body" not in failed.body.decode()
    check.assert_awaited_once_with()


@pytest.mark.parametrize("state", ["waiting_stable", "withdrawn", "unavailable", "publishing", "unsupported"])
async def test_channel_status_is_explicit_and_old_clients_never_report_false_success(monkeypatch, state):
    result = {"updateAvailable": None, "releaseStatus": {
        "channel": "stable", "revision": 2, "currentVersion": "0.3.7.dev42", "state": state,
    }}
    monkeypatch.setattr("nanobot.webui.settings_routes.check_for_update", AsyncMock(return_value=result))
    request = SimpleNamespace(path="/api/settings/version-check", headers=Headers())
    router = _router()
    response = await router.dispatch(None, request, request.path)
    assert response.status_code == 409
    request.path += "?channel_status=1"
    response = await router.dispatch(None, request, "/api/settings/version-check")
    assert response.status_code == 200
    assert json.loads(response.body)["releaseStatus"] == result["releaseStatus"]
    assert response.headers["Cache-Control"] == "no-store"


async def test_version_check_owner_is_additive_read_only_and_failure_is_not_a_release_failure(monkeypatch):
    from nanobot.webui import settings_system

    result = {"updateAvailable": None, "releaseStatus": {"state": "current"}}
    monkeypatch.setattr("nanobot.webui.settings_routes.check_for_update", AsyncMock(return_value=result))
    inspect_owner = MagicMock(return_value=SimpleNamespace(owner="pipx", records={}))
    monkeypatch.setattr(settings_system, "inspect_update_installation", inspect_owner)
    request = SimpleNamespace(path="/api/settings/version-check", headers=Headers())
    router = _router()
    legacy = await router.dispatch(None, request, "/api/settings/version-check")
    assert json.loads(legacy.body) == {"updateAvailable": None}
    inspect_owner.assert_not_called()
    request.path += "?channel_status=1"
    modern = await router.dispatch(None, request, "/api/settings/version-check")
    assert json.loads(modern.body)["installation_method"] == "pipx"
    inspect_owner.side_effect = ValueError("private receipt secret")
    unavailable = await router.dispatch(None, request, "/api/settings/version-check")
    body = json.loads(unavailable.body)
    assert body["installation_method"] is None and body["releaseStatus"] == result["releaseStatus"]
    assert "secret" not in unavailable.body.decode()


async def test_runtime_config_route_authentication_validation_and_restart(tmp_path):
    from nanobot.config.loader import load_config

    path = "/api/settings/runtime-config/update"
    config_path = tmp_path / "config.json"
    request = _mutation_request(path, {"values": {"tools.exec.timeout": 19}})
    unauthorized = await _router(authorized=False, config_path=config_path).dispatch(None, request, path)
    assert unauthorized.status_code == 401
    assert not config_path.exists()
    router = _router(config_path=config_path)
    http_request = SimpleNamespace(path=path, headers=Headers())
    assert (await router.dispatch(None, http_request, path)).status_code == 405
    invalid = _mutation_request(path, {"values": {"channels.send_progress": False}})
    assert (await router.dispatch(None, invalid, path)).status_code == 400
    assert not config_path.exists()
    result = await router.dispatch(None, request, path)
    assert result.status_code == 200
    assert load_config(config_path).tools.exec.timeout == 19
    body = json.loads(result.body)
    assert body["runtime_config"]["tools.exec.timeout"] == 19
    assert body["restart_required_sections"] == ["runtime"]
    refreshed = await router.dispatch(None, SimpleNamespace(path="/api/settings", headers=Headers()), "/api/settings")
    assert json.loads(refreshed.body)["restart_required_sections"] == ["runtime"]


async def test_runtime_settings_only_save_without_refreshing_or_rebinding(tmp_path, monkeypatch):
    refresh = MagicMock()
    runtime = MagicMock()
    monkeypatch.setattr(WebUISettingsRouter, "_api_runtime", lambda _self: runtime)
    router = _router(config_path=tmp_path / "config.json", refresh_runtime_config=refresh)
    path = "/api/settings/runtime-config/update"
    response = await router.dispatch(None, _mutation_request(path, {
        "values": {"agents.defaults.dream.enabled": False, "api.timeout": 45},
    }), path)
    assert response.status_code == 200
    assert json.loads(response.body)["requires_restart"]
    refresh.assert_not_called()
    runtime.restart.assert_not_called()


async def test_reverting_runtime_switch_clears_restart_but_preserves_other_changes(tmp_path):
    router = _router(config_path=tmp_path / "config.json")
    config = router.settings.config.load()
    original_memory = config.agents.defaults.dream.enabled
    original_web = config.tools.web.enable
    path = "/api/settings/runtime-config/update"

    async def update(values):
        response = await router.dispatch(None, _mutation_request(path, {"values": values}), path)
        assert response.status_code == 200
        return json.loads(response.body)

    assert (await update({"agents.defaults.dream.enabled": not original_memory}))["requires_restart"]
    await update({"tools.web.enable": not original_web})
    assert (await update({"agents.defaults.dream.enabled": original_memory}))["requires_restart"]
    reverted = await update({"tools.web.enable": original_web})
    assert reverted["requires_restart"] is False
    assert reverted["restart_required_sections"] == []
    refreshed = await router.dispatch(None, SimpleNamespace(path="/api/settings", headers=Headers()), "/api/settings")
    assert json.loads(refreshed.body)["requires_restart"] is False


async def test_reverting_web_reader_preserves_unrelated_restart_reason(tmp_path):
    router = _router(config_path=tmp_path / "config.json")
    config = router.settings.config.load()
    original_reader = config.tools.web.fetch.use_jina_reader
    original_timeout = config.api.timeout
    path = "/api/settings/web-search/update"
    first = await router.dispatch(None, _mutation_request(path, {
        "provider": "duckduckgo", "use_jina_reader": not original_reader,
    }), path)
    assert first.status_code == 200
    assert json.loads(first.body)["restart_required_sections"] == ["browser"]

    runtime_path = "/api/settings/runtime-config/update"
    changed = await router.dispatch(None, _mutation_request(runtime_path, {
        "values": {"api.timeout": original_timeout + 1},
    }), runtime_path)
    assert changed.status_code == 200
    assert set(json.loads(changed.body)["restart_required_sections"]) == {"browser", "runtime"}

    restored = await router.dispatch(None, _mutation_request(path, {
        "provider": "duckduckgo", "use_jina_reader": original_reader,
    }), path)
    assert restored.status_code == 200
    assert json.loads(restored.body)["restart_required_sections"] == ["runtime"]
    refreshed = await router.dispatch(None, SimpleNamespace(path="/api/settings", headers=Headers()), "/api/settings")
    assert json.loads(refreshed.body)["restart_required_sections"] == ["runtime"]
    reverted = await router.dispatch(None, _mutation_request(runtime_path, {
        "values": {"api.timeout": original_timeout},
    }), runtime_path)
    assert reverted.status_code == 200
    assert json.loads(reverted.body)["restart_required_sections"] == []


@pytest.mark.parametrize("enabled", [False, True])
async def test_image_switch_round_trip_clears_restart(tmp_path, enabled):
    from nanobot.config.loader import save_config
    from nanobot.config.schema import Config

    config = Config()
    config.providers.openrouter.api_key = "sk-test"
    config.tools.image_generation.enabled = enabled
    config_path = tmp_path / "config.json"
    save_config(config, config_path)
    router = _router(
        config_path=config_path,
        image_generation_reload=AsyncMock(return_value={"ok": False, "requires_restart": True}),
    )
    router.logger.warning = MagicMock()
    path = "/api/settings/image-generation/update"
    changed = await router.dispatch(None, _mutation_request(path, {"enabled": not enabled}), path)
    assert json.loads(changed.body)["requires_restart"] is True
    reverted = await router.dispatch(None, _mutation_request(path, {"enabled": enabled}), path)
    assert json.loads(reverted.body)["requires_restart"] is False
    assert json.loads(reverted.body)["restart_required_sections"] == []


@pytest.mark.asyncio
async def test_first_mcp_oauth_request_saves_proxy_flag_before_starting_flow(tmp_path) -> None:
    from nanobot.config.loader import load_config

    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "network": {"proxy": "http://shared.example:8080"},
        "agents": {"defaults": {"workspace": str(tmp_path / "workspace")}},
    }), encoding="utf-8")
    router = _router(config_path=config_path)
    captured = {}

    async def start(name, cfg, redirect_uri, *, reload_mcp, network, reset_credentials):
        saved = load_config(config_path)
        assert name == "xmind"
        assert cfg.auth == "oauth"
        assert cfg.use_proxy is True
        assert saved.tools.mcp_servers[name].use_proxy is True
        assert network == saved.network
        captured["network"] = network.proxy
        return {"status": "authorization_required", "name": name, "flow_id": "first-flow"}

    router._mcp_oauth = SimpleNamespace(start=start)
    request = _mutation_request(
        "/api/settings/mcp-oauth/start",
        {"name": "xmind", "use_proxy": True},
    )
    response = await router.dispatch(None, request, "/api/settings/mcp-oauth/start")

    assert response is not None
    assert response.status_code == 200
    assert json.loads(response.body)["flow_id"] == "first-flow"
    assert captured == {"network": "http://shared.example:8080"}


@pytest.mark.asyncio
@pytest.mark.parametrize("use_proxy", [True, False])
async def test_mcp_proxy_mutation_persists_reloads_and_keeps_oauth_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, use_proxy: bool,
) -> None:
    from mcp.shared.auth import OAuthToken
    from websockets.http11 import Request

    from nanobot.agent.tools.mcp_oauth import MCPOAuthStorage
    from nanobot.bus.queue import MessageBus
    from nanobot.channels.websocket.runtime import WebSocketConfig
    from nanobot.config.loader import load_config, save_config
    from nanobot.config.schema import Config
    from nanobot.webui.gateway_services import build_gateway_services

    monkeypatch.setattr("nanobot.agent.tools.mcp_oauth.get_data_dir", lambda: tmp_path)
    config_path = tmp_path / "config.json"
    config = Config.model_validate({
        "network": {"proxy": "http://proxy.example:8080"},
        "tools": {"mcpServers": {"team-docs": {
            "type": "streamableHttp", "auth": "oauth",
            "url": "https://mcp.example.com/mcp", "useProxy": not use_proxy,
            "headers": {"X-Organization": "team"}, "enabledTools": ["read"],
        }}},
    })
    save_config(config, config_path)
    original = config.tools.mcp_servers["team-docs"].model_copy(deep=True)
    storage = MCPOAuthStorage("team-docs", original.url)
    await storage.set_tokens(OAuthToken(access_token="synthetic-access", token_type="Bearer"))

    async def reload_mcp() -> dict[str, object]:
        assert load_config(config_path).tools.mcp_servers["team-docs"].use_proxy is use_proxy
        return {"ok": True, "connected": ["team-docs"], "requires_restart": False}

    reload = AsyncMock(side_effect=reload_mcp)
    gateway = build_gateway_services(
        config=WebSocketConfig(), bus=MessageBus(), session_manager=None,
        static_dist_path=None, workspace_path=tmp_path, config_path=config_path,
        default_restrict_to_workspace=True, runtime_model_name=None,
        runtime_surface="browser", runtime_capabilities_overrides=None, mcp_reload=reload,
    )
    connection = SimpleNamespace(
        remote_address=("127.0.0.1", 12345),
        request=Request("/", Headers({"Host": "127.0.0.1:8765"})),
    )
    path = "/api/settings/mcp-presets/proxy"
    try:
        http_response = await gateway.http.dispatch(connection, Request(path, Headers()))
        assert http_response.status_code == 405
        response = await gateway.http.dispatch_webui_mutation(
            connection, "settings.mcp.proxy", {"name": "team-docs", "use_proxy": str(use_proxy).lower()},
        )
        assert response.status_code == 200
        payload = json.loads(response.body)
        assert payload["hot_reload"]["ok"] is True
        assert payload["requires_restart"] is False
        row = next(row for row in payload["presets"] if row["name"] == "team-docs")
        assert row["use_proxy"] is use_proxy
        assert load_config(config_path).tools.mcp_servers["team-docs"] == original.model_copy(update={"use_proxy": use_proxy})
        assert storage.has_credentials() is True
        reload.assert_awaited_once()
    finally:
        await gateway.http.settings_routes.close()
