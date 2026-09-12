from __future__ import annotations

import json
from pathlib import Path


async def test_development_http_requires_auth_and_mutations_require_socket(tmp_path: Path, monkeypatch):
    from types import SimpleNamespace

    from websockets.datastructures import Headers
    from websockets.http11 import Request

    from nanobot.bus.queue import MessageBus
    from nanobot.channels.websocket.runtime import WebSocketConfig
    from nanobot.config.schema import Config
    from nanobot.development.models import Requirement
    from nanobot.development.service import DevelopmentService
    from nanobot.session.manager import SessionManager
    from nanobot.webui.gateway_services import build_gateway_services

    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "workspace")
    config.tools.development.enable = True
    config.tools.development.owner_session_key = "telegram:owner"
    config.tools.development.repository = str(tmp_path)
    services = build_gateway_services(config=WebSocketConfig(), bus=MessageBus(),
                                     session_manager=SessionManager(config.workspace_path),
                                     static_dist_path=None, workspace_path=config.workspace_path,
                                     default_restrict_to_workspace=False, runtime_model_name=None,
                                     runtime_surface="browser", runtime_capabilities_overrides=None)
    monkeypatch.setattr(services.http.settings.config, "load", lambda: config)
    monkeypatch.setattr(services.http.settings.config, "path", tmp_path / "config.json")
    project = DevelopmentService(config.tools.development, config.workspace_path, tmp_path / "config.json")
    project.store.initialize("Required full scope", [Requirement(id="one", description="Acceptance")])
    assert services.http._handle_development(Request("/api/webui/development", Headers()), mutate=False).status_code == 401
    assert (await services.http._handle_codex_limits(Request("/api/webui/codex-limits", Headers()))).status_code == 401
    connection = SimpleNamespace(request=Request("/", Headers()))
    response = await services.http.dispatch_webui_mutation(connection, "development.control", {"action": "pause"})
    assert response.status_code == 200
    assert json.loads(response.body)["project"]["paused"] is True
    assert services.http._is_webui_mutation_path("/api/webui/development/control")
