from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlsplit

import pytest
from websockets.datastructures import Headers

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
        lambda: update_info,
    )
    request = SimpleNamespace(path="/api/settings/version-check", headers=Headers())

    response = await _router().dispatch(None, request, request.path)

    assert response is not None
    assert response.status_code == 200
    assert json.loads(response.body) == expected


@pytest.mark.asyncio
async def test_version_check_route_enforces_auth_and_bounds_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    check = MagicMock(side_effect=RuntimeError("upstream secret body"))
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
