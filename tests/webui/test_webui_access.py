"""Exercise first-run access over the real HTTP and WebSocket listener."""

from __future__ import annotations

import asyncio
import base64
import json
import socket
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
import websockets
from pydantic import ValidationError
from websockets.exceptions import InvalidStatus

from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket.runtime import WebSocketChannel, WebSocketConfig
from nanobot.config.loader import load_config, resolve_config_env_vars, save_config
from nanobot.config.schema import Config
from nanobot.session.manager import SessionManager
from nanobot.webui.gateway_services import build_gateway_services


@pytest.fixture
def config_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr("nanobot.config.loader._current_config_path", tmp_path / "config.json")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    path = tmp_path / "config.json"
    save_config(Config(
        agents={"defaults": {"workspace": str(tmp_path / "workspace")}},
        channels={"websocket": {"port": port, "tokenIssuePath": "/auth/token"}},
    ), path)
    return path


@asynccontextmanager
async def running(config_path: Path):
    config = resolve_config_env_vars(load_config(config_path), config_path=config_path)
    active = WebSocketConfig.model_validate(config.channels.websocket)
    bus = MessageBus()
    workspace = config.workspace_path
    workspace.mkdir(exist_ok=True)
    static = config_path.parent / "dist"
    static.mkdir(exist_ok=True)
    (static / "index.html").write_text("<!doctype html><title>Access setup</title>")
    gateway = build_gateway_services(
        config=active, bus=bus, session_manager=SessionManager(workspace),
        static_dist_path=static, workspace_path=workspace, config_path=config_path,
        default_restrict_to_workspace=True, runtime_model_name=None,
        runtime_surface="browser", runtime_capabilities_overrides=None,
    )
    channel = WebSocketChannel(active, bus, gateway=gateway)
    task = asyncio.create_task(channel.start())
    try:
        async with asyncio.timeout(5):
            while not channel.is_running:
                if task.done():
                    await task
                await asyncio.sleep(0.01)
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{active.port}", trust_env=False,
        ) as client:
            yield channel, client
    finally:
        await channel.stop()
        await task


async def setup(client: httpx.AsyncClient, password: str, **headers: str) -> httpx.Response:
    return await client.post("/webui/setup", json={"password": password}, headers={
        "Origin": str(client.base_url).rstrip("/"), **headers,
    })


async def bootstrap(client: httpx.AsyncClient, password: str) -> dict:
    result = await client.get("/webui/bootstrap", headers={
        "X-Nanobot-Auth-Encoded": base64.b64encode(password.encode()).decode("ascii"),
    })
    assert result.status_code == 200, result.text
    return result.json()


async def mutation(client: httpx.AsyncClient, password: str, allow: bool) -> dict:
    boot = await bootstrap(client, password)
    async with websockets.connect(boot["ws_url"] + "?token=" + boot["token"]) as ws:
        await ws.send(json.dumps({
            "type": "webui_request", "request_id": uuid4().hex,
            "action": "settings.webui_access.update", "payload": {"allow_other_devices": allow},
        }))
        async with asyncio.timeout(5):
            while True:
                event = json.loads(await ws.recv())
                if event.get("event") == "webui_response":
                    assert event["ok"], event
                    return event["result"]


async def test_first_run_blocks_capabilities_then_persists_password(config_path: Path) -> None:
    password = "本机密码-😀"
    async with running(config_path) as (channel, client):
        assert (await client.get("/")).status_code == 200
        for path in ("/webui/bootstrap", "/webui/terminal", "/auth/token", "/api/settings", "/api/sessions"):
            result = await client.get(path)
            assert result.status_code == 428
            assert result.json() == {"error": "setup_required"}
        with pytest.raises(InvalidStatus) as rejected:
            async with websockets.connect(f"ws://127.0.0.1:{channel.config.port}/"):
                pass
        assert rejected.value.response.status_code == 428
        assert (await client.post("/api/attachments", content=b"uninitialized")).status_code == 401
        assert not channel.gateway.tokens.issued_tokens
        assert (await setup(client, password)).status_code == 200
        assert (await client.get("/webui/bootstrap")).status_code == 401
        boot = await bootstrap(client, password)
        assert "webui.access.v1" in boot["terminal"]["webui"]["capabilities"]
        async with websockets.connect(boot["ws_url"] + "?token=" + boot["token"]) as ws:
            assert json.loads(await ws.recv())["event"] == "ready"
        assert (await setup(client, "overwrite")).status_code == 409
    assert load_config(config_path).channels.websocket["tokenIssueSecret"] == password
    async with running(config_path) as (_, client):
        await bootstrap(client, password)
        assert (await setup(client, "overwrite-after-restart")).status_code == 409


async def test_setup_rejects_cross_site_forwarded_and_nonlocal_requests(config_path: Path) -> None:
    async with running(config_path) as (_, client):
        for headers in (
            {"Origin": "https://attacker.example"}, {"Origin": "null"}, {"Origin": ""},
            {"Host": "attacker.example", "Origin": "http://attacker.example"},
            {"X-Forwarded-For": "203.0.113.20"}, {"X-Forwarded-Host": "remote.example"},
        ):
            assert (await setup(client, "secret", **headers)).status_code == 403
        # A direct TCP peer outside the accepted local addresses cannot initialize.
        async with httpx.AsyncClient(
            base_url=client.base_url, trust_env=False,
            transport=httpx.AsyncHTTPTransport(local_address="127.0.0.2"),
        ) as other_peer:
            assert (await setup(other_peer, "remote")).status_code == 403
        assert (await setup(client, "secret", Origin="http://127.0.0.1:5173")).status_code == 200
        boot = await bootstrap(client, "secret")
        with pytest.raises(InvalidStatus) as rejected:
            async with websockets.connect(
                boot["ws_url"] + "?token=" + boot["token"], origin="https://attacker.example",
            ):
                pass
        assert rejected.value.response.status_code == 403


async def test_two_tabs_only_one_password_wins(config_path: Path) -> None:
    async with running(config_path) as (_, client):
        results = await asyncio.gather(setup(client, "tab-one"), setup(client, "tab-two"))
        assert sorted(result.status_code for result in results) == [200, 409]
        winner = "tab-one" if results[0].status_code == 200 else "tab-two"
        assert load_config(config_path).channels.websocket["tokenIssueSecret"] == winner
        await bootstrap(client, winner)


async def test_failed_save_can_retry_without_unlocking_gateway(
    config_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with running(config_path) as (_, client):
        with monkeypatch.context() as patch:
            def fail_save(*_args) -> None:
                raise PermissionError("read-only configuration")
            patch.setattr("nanobot.webui.settings_services.save_config", fail_save)
            result = await setup(client, "retry-secret")
            assert result.status_code == 500
            assert result.json() == {"error": "save_failed"}
        assert (await client.get("/webui/bootstrap")).status_code == 428
        assert not load_config(config_path).channels.websocket.get("tokenIssueSecret")
        assert (await setup(client, "retry-secret")).status_code == 200
        await bootstrap(client, "retry-secret")


async def test_unicode_password_limit_can_authenticate(config_path: Path) -> None:
    async with running(config_path) as (_, client):
        assert (await setup(client, "prefix-${PASSWORD}")).status_code == 400
        assert (await setup(client, "😀" * 1025)).status_code == 400
        password = "😀" * 1024
        assert (await setup(client, password)).status_code == 200
        await bootstrap(client, password)


async def test_scope_resolves_env_without_rewriting_credentials(
    config_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NAN238_HOST", "127.0.0.1")
    monkeypatch.setenv("NAN238_SECRET", "from-environment")
    config = load_config(config_path)
    config.channels.websocket.update(host="${NAN238_HOST}", tokenIssueSecret="${NAN238_SECRET}")
    save_config(config, config_path)
    async with running(config_path) as (_, client):
        boot = await bootstrap(client, "from-environment")
        response = await client.get("/api/settings", headers={"Authorization": "Bearer " + boot["api_token"]})
        access = response.json()["webui_access"]
        assert not access["allow_other_devices"]
        assert not access["requires_restart"]
        assert access["host"] == "127.0.0.1"
        changed = await mutation(client, "from-environment", True)
        assert changed["webui_access"]["requires_restart"]
        saved = load_config(config_path).channels.websocket
        assert saved["host"] == "0.0.0.0"
        assert saved["tokenIssueSecret"] == "${NAN238_SECRET}"


async def test_scope_saves_restarts_and_can_be_reverted(config_path: Path) -> None:
    async with running(config_path) as (channel, client):
        assert (await setup(client, "scope-secret")).status_code == 200
        response = await mutation(client, "scope-secret", True)
        assert response["webui_access"] == {
            "allow_other_devices": True, "active_allow_other_devices": False,
            "host": "0.0.0.0", "active_host": "127.0.0.1", "requires_restart": True,
            "can_change": True,
        }
        assert "runtime" in response["restart_required_sections"]
        assert channel._server.sockets[0].getsockname()[0] == "127.0.0.1"
        reverted = await mutation(client, "scope-secret", False)
        assert not reverted["requires_restart"]
        await mutation(client, "scope-secret", True)
    async with running(config_path) as (channel, client):
        assert channel._server.sockets[0].getsockname()[0] == "0.0.0.0"
        boot = await bootstrap(client, "scope-secret")
        response = await client.get("/api/settings", headers={"Authorization": "Bearer " + boot["api_token"]})
        assert response.json()["webui_access"]["active_allow_other_devices"]
        assert not response.json()["requires_restart"]
        await mutation(client, "scope-secret", False)
    async with running(config_path) as (channel, client):
        assert channel._server.sockets[0].getsockname()[0] == "127.0.0.1"
        await bootstrap(client, "scope-secret")


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.42", "nanobot.example"])
def test_uninitialized_external_bind_rejected(host: str) -> None:
    with pytest.raises(ValidationError, match="outside localhost"):
        WebSocketConfig(host=host)
