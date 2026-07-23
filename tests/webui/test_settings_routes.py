from __future__ import annotations

import json
from types import SimpleNamespace
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


@pytest.mark.asyncio
async def test_xai_oauth_completion_reads_code_from_private_header(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def complete(query, authorization_code=None):
        captured.update(query=query, authorization_code=authorization_code)
        return {
            "status": "pending",
            "provider": "xai_grok",
            "flow_id": "flow-123",
        }

    monkeypatch.setattr("nanobot.webui.settings_routes.complete_oauth_provider", complete)
    router = _router()
    request = SimpleNamespace(
        path=(
            "/api/settings/provider/oauth-login/complete"
            "?provider=xai_grok&flow_id=flow-123"
        ),
        headers=Headers(
            [
                (
                    "X-Nanobot-OAuth-Code",
                    "secret",
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
        "provider": "xai_grok",
        "flow_id": "flow-123",
    }
    assert captured == {
        "query": {"provider": ["xai_grok"], "flow_id": ["flow-123"]},
        "authorization_code": "secret",
    }
    assert "secret" not in request.path


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
