"""Two real authenticated clients share durable read progress, including offline results."""

import asyncio
import json
from pathlib import Path
from urllib.parse import urlencode

import httpx
import websockets

from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket.runtime import WebSocketChannel, WebSocketConfig
from nanobot.session.display_history import (
    HISTORY_GENERATION_METADATA_KEY,
    HistoryFact,
    HistoryKind,
)
from nanobot.session.manager import SessionManager
from nanobot.webui.gateway_services import build_gateway_services


async def _receive(socket, event, request_id=None):
    async with asyncio.timeout(5):
        while True:
            frame = json.loads(await socket.recv())
            if frame["event"] == event and (request_id is None or frame.get("request_id") == request_id):
                return frame


async def test_two_devices_reconcile_offline_completion_and_late_read_receipts(tmp_path: Path):
    sessions = SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "sessions")
    session = await sessions.state.get("websocket:two-devices")
    await sessions.state.append_history(session.key, [
        HistoryFact(HistoryKind.INPUT, {"text": "offline request"}, "offline-turn"),
        HistoryFact(HistoryKind.ANSWER_SEGMENT, {"text": "offline result"}, "offline-turn"),
        HistoryFact(HistoryKind.COMPLETION, {"outcome": "completed"}, "offline-turn"),
    ], expected_generation=session.generation)
    bus = MessageBus()
    config = WebSocketConfig.model_validate({
        "enabled": True, "allowFrom": ["*"], "host": "127.0.0.1", "port": 0,
        "path": "/ws", "token": "isolated-read-sync-test",
    })
    gateway = build_gateway_services(
        config=config, bus=bus, session_manager=sessions, static_dist_path=None,
        workspace_path=tmp_path / "workspace", default_restrict_to_workspace=True,
        runtime_model_name=None, runtime_surface="browser", runtime_capabilities_overrides=None,
    )
    channel = WebSocketChannel(config.model_dump(), bus, gateway=gateway)
    task = asyncio.create_task(channel.start())
    try:
        async with asyncio.timeout(5):
            while channel._server is None:
                await asyncio.sleep(0.01)
        port = channel._server.sockets[0].getsockname()[1]
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", trust_env=False) as http:
            async def bootstrap():
                response = await http.get("/webui/bootstrap", headers={"Authorization": "Bearer isolated-read-sync-test"})
                assert response.status_code == 200
                return response.json()

            boot_a, boot_b = await bootstrap(), await bootstrap()
            api_headers = {"Authorization": f"Bearer {boot_a['api_token']}"}
            initial = await http.get("/api/sessions", headers=api_headers)
            assert initial.status_code == 200
            assert initial.json()["sessions"][0]["read_state"] == {
                "generation": session.generation, "latest": 1, "read": 0,
            }
            urls = [f"ws://127.0.0.1:{port}/ws?" + urlencode({"token": boot["token"], "client_id": name})
                    for boot, name in ((boot_a, "device-a"), (boot_b, "device-b"))]
            async with websockets.connect(urls[0], proxy=None) as a, websockets.connect(urls[1], proxy=None) as b:
                await _receive(a, "ready")
                await _receive(b, "ready")

                async def read(socket, request_id, cursor, generation=session.generation):
                    await socket.send(json.dumps({
                        "type": "webui_request", "request_id": request_id, "action": "session.mark_read",
                        "payload": {"session_key": session.key, "generation": generation, "cursor": cursor},
                    }))
                    return await _receive(socket, "webui_response", request_id)

                response = await read(a, "read-offline-result", 1)
                assert response["ok"] and response["result"]["state"]["read"] == 1
                assert (await _receive(b, "session_read_state"))["state"]["read"] == 1
                await channel.send_payload(
                    "two-devices", {"event": "turn_end", "chat_id": "two-devices", "outcome": "completed"},
                    persistence="turn_complete", metadata={
                        HISTORY_GENERATION_METADATA_KEY: session.generation, "webui_turn_id": "new-result",
                    },
                )
                next_state = (await _receive(b, "session_read_state"))["state"]
                assert next_state == {"generation": session.generation, "latest": 2, "read": 1}
                late = await read(b, "late-old-read", 1)
                assert late["ok"] and late["result"] == {"state": next_state, "changed": False}
                current = await http.get("/api/sessions", headers=api_headers)
                assert current.json()["sessions"][0]["read_state"] == next_state
                forbidden = await http.get("/api/webui/sessions/mark-read", headers=api_headers)
                assert forbidden.status_code == 405
                await sessions.state.reset(session.key)
                stale = await read(a, "old-generation", 2)
                assert stale["ok"] is False and stale["error"]["status"] == 409
    finally:
        await channel.stop()
        await task
        await sessions.state.aclose()
