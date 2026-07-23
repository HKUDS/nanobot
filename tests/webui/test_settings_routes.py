from __future__ import annotations

import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from websockets.datastructures import Headers

from nanobot.webui.http_utils import http_json_response
from nanobot.webui.settings_routes import WebUISettingsRouter


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
    router = WebUISettingsRouter(
        bus=SimpleNamespace(),
        logger=SimpleNamespace(exception=lambda *_args: None),
        check_api_token=lambda _request: True,
        parse_query=lambda path: parse_qs(urlsplit(path).query),
        json_response=http_json_response,
        error_response=lambda status, message: http_json_response(
            {"error": message},
            status=status,
        ),
        runtime_surface="browser",
        runtime_capabilities={},
    )
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
