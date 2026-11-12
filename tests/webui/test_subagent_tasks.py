"""The WebUI reads and cancels tasks through the session-owned lifecycle."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock
from urllib.parse import quote

import pytest
from websockets.datastructures import Headers
from websockets.http11 import Request

from nanobot.agent.memory import Consolidator
from nanobot.agent.subagent import SubagentManager
from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket.runtime import WebSocketConfig
from nanobot.providers.base import GenerationSettings, LLMProvider
from nanobot.session.manager import SessionManager
from nanobot.utils.llm_runtime import LLMRuntime
from nanobot.webui.gateway_services import build_gateway_services


@pytest.mark.asyncio
async def test_webui_task_access_and_targeted_idempotent_cancel(tmp_path):
    bus = MessageBus()
    manager = SubagentManager(
        workspace=tmp_path, bus=bus, max_tool_result_chars=16000,
        consolidator=MagicMock(spec=Consolidator),
    )
    provider = MagicMock(spec=LLMProvider)
    provider.generation = GenerationSettings()
    runtime = LLMRuntime.capture(provider, "test", context_window_tokens=128000)
    gateway = build_gateway_services(
        config=WebSocketConfig(), bus=bus, session_manager=SessionManager(tmp_path),
        static_dist_path=None, workspace_path=tmp_path, default_restrict_to_workspace=True,
        config_path=tmp_path / "config.json", runtime_model_name=None,
        runtime_surface="gateway", runtime_capabilities_overrides=None,
        subagent_manager=manager,
    )
    connection = SimpleNamespace(remote_address=("127.0.0.1", 12345))
    token = gateway.tokens.issue_api_token(60)
    headers = Headers({"Authorization": f"Bearer {token}"})
    entered = asyncio.Queue()

    async def blocked(spec):
        await entered.put(True)
        await asyncio.Event().wait()

    manager.runner.run = blocked
    try:
        for owner in ("websocket:a", "websocket:a", "websocket:b"):
            await manager.spawn("work", session_key=owner, runtime=runtime)
            await asyncio.wait_for(entered.get(), timeout=2)
        first, sibling = manager.statuses_for_session("websocket:a")
        foreign, = manager.statuses_for_session("websocket:b")
        path = f"/api/sessions/{quote('websocket:a', safe='')}/subagents"
        denied = await gateway.http.dispatch(connection, Request(path, Headers()))
        assert denied.status_code == 401
        response = await gateway.http.dispatch(connection, Request(path, headers))
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store"
        tasks = json.loads(response.body)["tasks"]
        assert {task["task_id"] for task in tasks} == {first, sibling}
        assert all(task["state"] == "running" and "owner" not in task for task in tasks)

        http_stop = await gateway.http.dispatch(
            connection, Request("/api/webui/subagents/cancel", headers),
        )
        assert http_stop.status_code == 405
        errors = []
        for task_id in (foreign, "missing"):
            result = await gateway.http.dispatch_webui_mutation(
                connection, "subagent.cancel", {"session_key": "websocket:a", "task_id": task_id},
            )
            assert result.status_code == 404
            errors.append(result.body)
        assert errors[0] == errors[1]
        assert manager.check(foreign, "websocket:b").state == "running"

        for _ in range(2):
            result = await gateway.http.dispatch_webui_mutation(
                connection, "subagent.cancel", {"session_key": "websocket:a", "task_id": first},
            )
            assert result.status_code == 200
            assert json.loads(result.body)["state"] == "cancelled"
        assert manager.check(sibling, "websocket:a").state == "running"
        assert manager.check(foreign, "websocket:b").state == "running"
        assert bus.inbound_size == 1
        refreshed = await gateway.http.dispatch(connection, Request(path, headers))
        assert {t["task_id"]: t["state"] for t in json.loads(refreshed.body)["tasks"]} == {
            first: "cancelled", sibling: "running",
        }
    finally:
        await manager.close()
