"""Exercise authenticated network access settings over real gateway listeners."""

from __future__ import annotations

import asyncio
import json
import socket
import string
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

LOCAL_SECRET = "generated-local-secret"


@pytest.fixture
def config_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr("nanobot.config.loader._current_config_path", tmp_path / "config.json")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    path = tmp_path / "config.json"
    save_config(Config(
        agents={"defaults": {"workspace": str(tmp_path / "workspace")}},
        channels={"websocket": {
            "host": "127.0.0.1", "port": port, "tokenIssuePath": "/auth/token",
            "tokenIssueSecret": LOCAL_SECRET, "tokenIssueSecretGenerated": True,
        }},
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
    (static / "index.html").write_text("<!doctype html><title>WebUI</title>")
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


async def bootstrap(client: httpx.AsyncClient, password: str = LOCAL_SECRET) -> dict:
    result = await client.get("/webui/bootstrap", headers={
        "X-Nanobot-Auth": password,
    })
    assert result.status_code == 200, result.text
    return result.json()


@asynccontextmanager
async def signed_in(client: httpx.AsyncClient, password: str = LOCAL_SECRET, **kwargs):
    boot = await bootstrap(client, password)
    async with websockets.connect(
        boot["ws_url"] + "?token=" + boot["token"],
        origin=str(client.base_url).rstrip("/"), **kwargs,
    ) as ws:
        yield ws


async def mutation(ws, allow: bool, password: object = None) -> dict:
    request_id = uuid4().hex
    payload = {"allow_other_devices": allow}
    if password is not None:
        payload["password"] = password
    await ws.send(json.dumps({
        "type": "webui_request", "request_id": request_id,
        "action": "settings.webui_access.update", "payload": payload,
    }))
    async with asyncio.timeout(5):
        while True:
            event = json.loads(await ws.recv())
            if event.get("event") == "webui_response" and event.get("request_id") == request_id:
                return event


async def settings(client: httpx.AsyncClient, password: str = LOCAL_SECRET) -> dict:
    boot = await bootstrap(client, password)
    response = await client.get("/api/settings", headers={"Authorization": "Bearer " + boot["api_token"]})
    assert response.status_code == 200
    return response.json()


async def test_generated_credential_authenticates_locally_but_cannot_enable_network_without_password(
    config_path: Path,
) -> None:
    async with running(config_path) as (_, client):
        assert (await client.get("/webui/bootstrap")).status_code == 401
        assert (await client.get("/api/settings")).status_code == 401
        payload = await settings(client)
        assert payload["webui_access"]["password_required"]
        assert not payload["webui_access"]["allow_other_devices"]
        assert (await client.get("/api/settings/webui-access/update")).status_code == 405
        async with signed_in(client) as ws:
            result = await mutation(ws, True)
            assert result["error"] == {"status": 400, "message": "password_required"}
        assert load_config(config_path).channels.websocket["host"] == "127.0.0.1"


async def test_bootstrap_rejects_non_ascii_auth_headers(config_path: Path) -> None:
    async with running(config_path) as (_, client):
        for headers in (
            [(b"X-Nanobot-Auth", b"bad-\xff")],
            [(b"Authorization", b"Bearer bad-\xff")],
        ):
            for path in ("/webui/bootstrap", "/auth/token"):
                response = await client.get(path, headers=headers)
                assert response.status_code == 401
        await bootstrap(client)


async def test_password_and_scope_save_together_and_restart_with_new_credentials(config_path: Path) -> None:
    password = "Network-Access42!@#"
    async with running(config_path) as (channel, client):
        old_boot = await bootstrap(client)
        async with signed_in(client) as ws:
            changed = await mutation(ws, True, password)
            assert changed["ok"], changed
        assert changed["result"]["webui_access"] == {
            "allow_other_devices": True, "active_allow_other_devices": False,
            "host": "0.0.0.0", "active_host": "127.0.0.1", "requires_restart": True,
            "can_change": True, "password_required": False,
        }
        assert "runtime" in changed["result"]["restart_required_sections"]
        assert channel._server.sockets[0].getsockname()[0] == "127.0.0.1"
        assert (await client.get("/webui/bootstrap", headers={"X-Nanobot-Auth": LOCAL_SECRET})).status_code == 401
        await settings(client, password)
    saved = load_config(config_path).channels.websocket
    assert saved["tokenIssueSecret"] == password
    assert saved["tokenIssueSecretGenerated"] is False
    async with running(config_path) as (channel, client):
        assert channel._server.sockets[0].getsockname()[0] == "0.0.0.0"
        assert (await client.get("/api/settings", headers={"Authorization": "Bearer " + old_boot["api_token"]})).status_code == 401
        with pytest.raises(InvalidStatus) as rejected:
            async with websockets.connect(old_boot["ws_url"] + "?token=" + old_boot["token"]):
                pass
        assert rejected.value.response.status_code == 401
        access = (await settings(client, password))["webui_access"]
        assert access["active_allow_other_devices"] and not access["requires_restart"]
        async with signed_in(client, password) as ws:
            disabled = await mutation(ws, False)
            assert disabled["ok"]
    async with running(config_path) as (channel, client):
        assert channel._server.sockets[0].getsockname()[0] == "127.0.0.1"
        assert not (await settings(client, password))["webui_access"]["password_required"]
        async with signed_in(client, password) as ws:
            enabled = await mutation(ws, True)
            assert enabled["ok"]
            reverted = await mutation(ws, False)
            assert not reverted["result"]["requires_restart"]
        assert load_config(config_path).channels.websocket["tokenIssueSecret"] == password


async def test_cross_site_and_forwarded_requests_cannot_set_network_password(config_path: Path) -> None:
    async with running(config_path) as (_, client):
        boot = await bootstrap(client)
        with pytest.raises(InvalidStatus) as rejected:
            async with websockets.connect(
                boot["ws_url"] + "?token=" + boot["token"], origin="https://attacker.example",
            ):
                pass
        assert rejected.value.response.status_code == 403
        for kwargs in (
            {"additional_headers": {"X-Forwarded-For": "203.0.113.20"}},
            {"local_addr": ("127.0.0.2", 0)},
        ):
            async with signed_in(client, **kwargs) as ws:
                result = await mutation(ws, True, "Network-Password42!")
                assert result["error"] == {"status": 403, "message": "access_local_only"}
        assert load_config(config_path).channels.websocket["tokenIssueSecret"] == LOCAL_SECRET


async def test_two_authenticated_tabs_cannot_overwrite_password(config_path: Path) -> None:
    async with running(config_path) as (_, client):
        async with signed_in(client) as first, signed_in(client) as second:
            results = await asyncio.gather(
                mutation(first, True, "Tab-One-Password42!"), mutation(second, True, "Tab-Two-Password42!"),
            )
        assert sum(result["ok"] for result in results) == 1
        winner = "Tab-One-Password42!" if results[0]["ok"] else "Tab-Two-Password42!"
        loser = results[1] if results[0]["ok"] else results[0]
        assert loser["error"] == {"status": 409, "message": "password_already_set"}
        assert load_config(config_path).channels.websocket["tokenIssueSecret"] == winner
        await bootstrap(client, winner)


async def test_failed_save_keeps_local_credentials_and_can_retry(
    config_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with running(config_path) as (channel, client), signed_in(client) as ws:
        with monkeypatch.context() as patch:
            def fail_save(*_args) -> None:
                raise PermissionError("read-only configuration")
            patch.setattr("nanobot.webui.settings_services.save_config", fail_save)
            result = await mutation(ws, True, "Retry-Password42!")
            assert result["error"] == {"status": 500, "message": "save_failed"}
        await bootstrap(client)
        saved = load_config(config_path).channels.websocket
        assert saved["tokenIssueSecret"] == LOCAL_SECRET and saved["host"] == "127.0.0.1"
        assert channel._server.sockets[0].getsockname()[0] == "127.0.0.1"
        assert (await mutation(ws, True, "Retry-Password42!"))["ok"]
        await bootstrap(client, "Retry-Password42!")


@pytest.mark.parametrize("password", [
    "abcdefgh", "ABCDEFGH", "12345678", string.punctuation.replace("$", ""), "a" * 1024,
    "Aa1!'OR'1'='1';--", 'Aa1!"},"token":"injected"',
])
async def test_network_password_rules_and_symbol_round_trip(config_path: Path, password: str) -> None:
    async with running(config_path) as (_, client), signed_in(client) as ws:
        for invalid in (
            "Aa1!bcd", "Aa1!" * 256 + "x", "Valid42!中文", "Valid42!😀", "Valid42!$",
            " Valid42!", "Valid42! ", "Valid 42!", "Valid42!\n", "Valid42!\r\nX-Test: injected",
            "Valid42!\x00", "Valid42!${PASSWORD}", {"password": "Valid42!"}, 42,
        ):
            result = await mutation(ws, True, invalid)
            assert result["error"] == {"status": 400, "message": "invalid_password"}
        saved = load_config(config_path).channels.websocket
        assert saved["tokenIssueSecret"] == LOCAL_SECRET and saved["host"] == "127.0.0.1"
        await bootstrap(client)
        assert (await mutation(ws, True, password))["ok"]
        assert load_config(config_path).channels.websocket["tokenIssueSecret"] == password
        assert not load_config(config_path).channels.websocket.get("token")
        await bootstrap(client, password)
    async with running(config_path) as (_, client):
        await bootstrap(client, password)


@pytest.mark.parametrize("authentication", [
    {"token": "existing-static"}, {"tokenIssueSecret": "legacy-random-secret"},
    {"tokenIssueSecret": "${NAN238_SECRET}"},
    {"trustedProxyAuth": {"trustedPeerCidrs": ["127.0.0.1/32"], "assertionHeader": "X-Identity"}},
])
async def test_existing_authentication_can_enable_network_without_replacing_credentials(
    config_path: Path, monkeypatch: pytest.MonkeyPatch, authentication: dict,
) -> None:
    monkeypatch.setenv("NAN238_HOST", "127.0.0.1")
    monkeypatch.setenv("NAN238_SECRET", "from-environment")
    config = load_config(config_path)
    config.channels.websocket.pop("tokenIssueSecret")
    config.channels.websocket.pop("tokenIssueSecretGenerated")
    config.channels.websocket.update(host="${NAN238_HOST}", **authentication)
    save_config(config, config_path)
    async with running(config_path) as (_, client):
        if "trustedProxyAuth" in authentication:
            result = await client.get("/webui/bootstrap", headers={"X-Identity": "signed-in-user"})
            boot = result.json()
            connection = websockets.connect(boot["ws_url"], additional_headers={"X-Identity": "signed-in-user"})
        else:
            password = authentication.get("token") or authentication["tokenIssueSecret"]
            connection = signed_in(client, "from-environment" if password.startswith("${") else password)
        async with connection as ws:
            result = await mutation(ws, True)
            assert result["ok"], result
            assert not result["result"]["webui_access"]["password_required"]
        saved = load_config(config_path).channels.websocket
        assert saved["host"] == "0.0.0.0"
        for key, value in authentication.items():
            assert saved[key] == value


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.42", "nanobot.example"])
def test_external_bind_requires_authentication(host: str) -> None:
    with pytest.raises(ValidationError, match="outside localhost"):
        WebSocketConfig(host=host)
