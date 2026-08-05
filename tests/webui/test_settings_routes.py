from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from websockets.datastructures import Headers

from nanobot.process_runtime import ProcessStatus
from nanobot.webui.http_utils import http_json_response
from nanobot.webui.settings_routes import WebUISettingsRouter


def _router(*, authorized: bool = True) -> WebUISettingsRouter:
    return WebUISettingsRouter(
        bus=SimpleNamespace(),
        logger=SimpleNamespace(exception=lambda *_args: None),
        check_api_token=lambda _request: authorized,
        parse_query=lambda path: parse_qs(urlsplit(path).query),
        json_response=http_json_response,
        error_response=lambda status, message: http_json_response(
            {"error": message},
            status=status,
        ),
        runtime_surface="browser",
        runtime_capabilities={},
    )


@pytest.mark.parametrize(
    ("provider", "header_name", "authorization_response"),
    [
        ("xai_grok", "X-Nanobot-OAuth-Code", "secret"),
        (
            "openai_codex",
            "X-Nanobot-OAuth-Callback",
            "http://localhost:1455/auth/callback?code=secret&state=test",
        ),
    ],
)
@pytest.mark.asyncio
async def test_oauth_completion_reads_private_response_header(
    monkeypatch,
    provider: str,
    header_name: str,
    authorization_response: str,
) -> None:
    captured: dict[str, object] = {}

    def complete(query, authorization_response=None):
        captured.update(query=query, authorization_response=authorization_response)
        return {
            "status": "pending",
            "provider": provider,
            "flow_id": "flow-123",
        }

    monkeypatch.setattr("nanobot.webui.settings_routes.complete_oauth_provider", complete)
    router = _router()
    request = SimpleNamespace(
        path=(
            "/api/settings/provider/oauth-login/complete"
            f"?provider={provider}&flow_id=flow-123"
        ),
        headers=Headers(
            [
                (
                    header_name,
                    authorization_response,
                )
            ]
        ),
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
    assert authorization_response not in request.path


@pytest.mark.parametrize(
    ("request_path", "route_path", "function_name", "expected_query"),
    [
        (
            "/api/settings/model-configurations/delete?name=spare",
            "/api/settings/model-configurations/delete",
            "delete_model_configuration",
            {"name": ["spare"]},
        ),
        (
            "/api/settings/model-configurations/migrate",
            "/api/settings/model-configurations/migrate",
            "migrate_model_configurations",
            {},
        ),
        (
            "/api/settings/model-call-order/update?order=%5B%22backup%22%5D",
            "/api/settings/model-call-order/update",
            "update_model_call_order",
            {"order": ['["backup"]']},
        ),
    ],
)
@pytest.mark.asyncio
async def test_model_preset_mutation_routes(
    monkeypatch,
    request_path: str,
    route_path: str,
    function_name: str,
    expected_query: dict[str, list[str]],
) -> None:
    captured: dict[str, object] = {}

    def mutate(query):
        captured["query"] = query
        return {"routed": function_name}

    monkeypatch.setattr(f"nanobot.webui.settings_routes.{function_name}", mutate)
    request = SimpleNamespace(path=request_path, headers=Headers())

    response = await _router().dispatch(None, request, route_path)

    assert response is not None
    assert response.status_code == 200
    assert json.loads(response.body)["routed"] == function_name
    assert captured["query"] == expected_query
    monkeypatch.setattr(f"nanobot.webui.settings_routes.{function_name}", mutate)
    request = SimpleNamespace(path=request_path, headers=Headers())

    response = await _router().dispatch(None, request, route_path)

    assert response is not None
    assert response.status_code == 200
    assert json.loads(response.body)["routed"] == function_name
    assert captured["query"] == expected_query


def _api_config(**overrides) -> SimpleNamespace:
    values = {"host": "0.0.0.0", "port": 8900, "timeout": 120.0, "api_key": ""}
    values.update(overrides)
    return SimpleNamespace(**values)


def _status(*, running: bool, managed: bool, reason: str) -> ProcessStatus:
    return ProcessStatus(
        running=running,
        pid=1234 if running and managed else None,
        state_path=Path("/tmp/api-state.json"),
        log_path=Path("/tmp/api.log"),
        port=8900 if running else None,
        reason=reason,
        managed=managed,
    )


def _patch_api_service_deps(monkeypatch, status: ProcessStatus) -> None:
    monkeypatch.setattr(
        "nanobot.webui.settings_routes.load_config",
        lambda: SimpleNamespace(api=_api_config(), workspace_path=Path("/tmp/workspace")),
    )
    monkeypatch.setattr(
        "nanobot.webui.settings_routes.ApiRuntime.effective_status",
        lambda _self, **_kwargs: status,
    )
    monkeypatch.setattr(
        "nanobot.webui.settings_routes.optional_dependency_groups", lambda: {"api": ["aiohttp"]}
    )
    monkeypatch.setattr(
        "nanobot.webui.settings_routes.extra_installed", lambda *_args, **_kwargs: True
    )


@pytest.mark.asyncio
async def test_api_service_payload_reports_externally_managed(monkeypatch) -> None:
    _patch_api_service_deps(monkeypatch, _status(running=True, managed=False, reason="external"))
    request = SimpleNamespace(path="/api/settings/api-service", headers=Headers())

    response = await _router().dispatch(None, request, "/api/settings/api-service")

    assert response is not None
    assert response.status_code == 200
    body = json.loads(response.body)
    assert body["running"] is True
    assert body["managed"] is False
    assert body["endpoint"] == "http://127.0.0.1:8900/v1"


@pytest.mark.asyncio
async def test_api_service_payload_reports_managed_running(monkeypatch) -> None:
    _patch_api_service_deps(monkeypatch, _status(running=True, managed=True, reason="running"))
    request = SimpleNamespace(path="/api/settings/api-service", headers=Headers())

    response = await _router().dispatch(None, request, "/api/settings/api-service")

    assert response is not None
    body = json.loads(response.body)
    assert body["running"] is True
    assert body["managed"] is True


@pytest.mark.asyncio
async def test_api_service_payload_reports_off(monkeypatch) -> None:
    _patch_api_service_deps(monkeypatch, _status(running=False, managed=False, reason="not_started"))
    request = SimpleNamespace(path="/api/settings/api-service", headers=Headers())

    response = await _router().dispatch(None, request, "/api/settings/api-service")

    assert response is not None
    body = json.loads(response.body)
    assert body["running"] is False
    assert body["managed"] is False


@pytest.mark.asyncio
async def test_api_service_start_refuses_external(monkeypatch) -> None:
    _patch_api_service_deps(monkeypatch, _status(running=True, managed=False, reason="external"))
    request = SimpleNamespace(path="/api/settings/api-service/start", headers=Headers())

    response = await _router().dispatch(None, request, "/api/settings/api-service/start")

    assert response is not None
    assert response.status_code == 409
    assert "outside this app" in json.loads(response.body)["error"]


@pytest.mark.asyncio
async def test_api_service_stop_refuses_external(monkeypatch) -> None:
    _patch_api_service_deps(monkeypatch, _status(running=True, managed=False, reason="external"))
    request = SimpleNamespace(path="/api/settings/api-service/stop", headers=Headers())

    response = await _router().dispatch(None, request, "/api/settings/api-service/stop")

    assert response is not None
    assert response.status_code == 409
    assert "outside this app" in json.loads(response.body)["error"]
