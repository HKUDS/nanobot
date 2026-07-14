"""End-to-end tests for the embedded webui's HTTP routes on the WebSocket channel."""

import asyncio
import functools
import json
import random
import socket
import time
from contextlib import suppress
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import quote, urlencode

import httpx
import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.channels.base import BaseChannel
from nanobot.channels.websocket import WebSocketChannel, WebSocketConfig
from nanobot.cron.service import CronService
from nanobot.cron.types import CronJob, CronPayload, CronSchedule
from nanobot.optional_features import InstallResult
from nanobot.runtime_context import (
    RUNTIME_CONTEXT_HISTORY_META,
    RuntimeContextBlock,
    append_runtime_context,
)
from nanobot.session.keys import UNIFIED_SESSION_KEY
from nanobot.session.manager import Session, SessionManager
from nanobot.triggers.local_store import LocalTriggerStore
from nanobot.webui.gateway_services import GatewayServices, build_gateway_services

_PORT = 29900


class _MatrixChannel(BaseChannel):
    name = "matrix"
    display_name = "Matrix"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return {"enabled": False, "allowFrom": []}

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def send(self, msg: OutboundMessage) -> None:
        pass


def _free_port() -> int:
    for _ in range(100):
        port = random.randint(30_000, 60_000)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError("could not find a free localhost port")


def _make_handler(
    cfg: dict[str, Any] | WebSocketConfig,
    bus: Any,
    *,
    session_manager: SessionManager | None = None,
    static_dist_path: Path | None = None,
    workspace_path: Path | None = None,
    runtime_model_name: Any | None = None,
    cron_service: CronService | None = None,
    local_trigger_store: LocalTriggerStore | None = None,
    cron_pending_job_ids: Any | None = None,
    local_trigger_pending_ids: Any | None = None,
    channel_feature_action: Any | None = None,
) -> GatewayServices:
    config = WebSocketConfig.model_validate(cfg) if isinstance(cfg, dict) else cfg
    workspace = workspace_path or Path.cwd()
    return build_gateway_services(
        config=config,
        bus=bus,
        session_manager=session_manager,
        static_dist_path=static_dist_path,
        workspace_path=workspace,
        default_restrict_to_workspace=False,
        runtime_model_name=runtime_model_name,
        runtime_surface="browser",
        runtime_capabilities_overrides=None,
        cron_service=cron_service,
        local_trigger_store=local_trigger_store,
        cron_pending_job_ids=cron_pending_job_ids,
        local_trigger_pending_ids=local_trigger_pending_ids,
        channel_feature_action=channel_feature_action,
    )


def _ch(
    bus: Any,
    *,
    session_manager: SessionManager | None = None,
    static_dist_path: Path | None = None,
    workspace_path: Path | None = None,
    port: int = _PORT,
    runtime_model_name: Any | None = None,
    cron_service: CronService | None = None,
    local_trigger_store: LocalTriggerStore | None = None,
    cron_pending_job_ids: Any | None = None,
    local_trigger_pending_ids: Any | None = None,
    channel_feature_action: Any | None = None,
    **extra: Any,
) -> WebSocketChannel:
    cfg: dict[str, Any] = {
        "enabled": True,
        "allowFrom": ["*"],
        "host": "127.0.0.1",
        "port": port,
        "path": "/",
        "websocketRequiresToken": False,
    }
    cfg.update(extra)
    gateway = _make_handler(
        cfg, bus,
        session_manager=session_manager,
        static_dist_path=static_dist_path,
        workspace_path=workspace_path,
        runtime_model_name=runtime_model_name,
        cron_service=cron_service,
        local_trigger_store=local_trigger_store,
        cron_pending_job_ids=cron_pending_job_ids,
        local_trigger_pending_ids=local_trigger_pending_ids,
        channel_feature_action=channel_feature_action,
    )
    return WebSocketChannel(cfg, bus, gateway=gateway)


@pytest.fixture()
def bus() -> MagicMock:
    b = MagicMock()
    b.publish_inbound = AsyncMock()
    return b


async def _http_get(
    url: str, headers: dict[str, str] | None = None
) -> httpx.Response:
    return await asyncio.to_thread(
        functools.partial(httpx.get, url, headers=headers or {}, timeout=5.0, trust_env=False)
    )


def _seed_session(workspace: Path, key: str = "websocket:test") -> SessionManager:
    sm = SessionManager(workspace)
    s = Session(key=key)
    s.add_message("user", "hi")
    s.add_message("assistant", "hello back")
    sm.save(s)
    return sm


def _seed_many(workspace: Path, keys: list[str]) -> SessionManager:
    sm = SessionManager(workspace)
    for k in keys:
        s = Session(key=k)
        s.add_message("user", f"hi from {k}")
        sm.save(s)
    return sm


def _stub_matrix_feature(
    monkeypatch: pytest.MonkeyPatch,
    config_path: Path,
    *,
    deps: list[str] | None = None,
    installed: bool = True,
    install_calls: list[str] | None = None,
    channels: list[str] | None = None,
) -> None:
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)
    monkeypatch.setattr(
        "nanobot.channels.registry.discover_channel_names",
        lambda: channels or ["matrix"],
    )
    monkeypatch.setattr("nanobot.channels.registry.discover_plugins", lambda: {})
    monkeypatch.setattr("nanobot.channels.registry.load_channel_class", lambda _name: _MatrixChannel)
    monkeypatch.setattr(
        "nanobot.optional_features.optional_dependency_groups",
        lambda: {"matrix": deps if deps is not None else []},
    )
    monkeypatch.setattr("nanobot.optional_features.extra_installed", lambda _name, _deps: installed)
    if install_calls is not None:
        monkeypatch.setattr(
            "nanobot.optional_features.install_extra",
            lambda name, _deps, *, runner: install_calls.append(name)
            or InstallResult(True, f"{name} support", ["python", "-m", "pip", "install", name]),
        )


@pytest.mark.asyncio
async def test_bootstrap_returns_token_for_localhost(
    bus: MagicMock, tmp_path: Path
) -> None:
    sm = _seed_session(tmp_path)
    channel = _ch(bus, session_manager=sm, port=29901)
    server_task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)
    try:
        resp = await _http_get("http://127.0.0.1:29901/webui/bootstrap")
        assert resp.status_code == 200
        body = resp.json()
        assert body["token"].startswith("nbwt_")
        assert body["api_token"].startswith("nbwt_")
        assert body["api_token"] != body["token"]
        assert body["ws_path"] == "/"
        assert body["ws_url"] == "ws://127.0.0.1:29901/"
        assert body["expires_in"] > 0
        assert isinstance(body.get("model_name"), str)
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_sessions_routes_require_bearer_token(
    bus: MagicMock, tmp_path: Path
) -> None:
    sm = _seed_session(tmp_path, key="websocket:abc")
    channel = _ch(bus, session_manager=sm, port=29902)
    server_task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)
    try:
        # Unauthenticated → 401.
        deny = await _http_get("http://127.0.0.1:29902/api/sessions")
        assert deny.status_code == 401

        # Directly mint an API token for route-level auth checks.
        token = channel.gateway.tokens.issue_api_token(300)
        auth = {"Authorization": f"Bearer {token}"}

        listing = await _http_get("http://127.0.0.1:29902/api/sessions", headers=auth)
        assert listing.status_code == 200
        keys = [s["key"] for s in listing.json()["sessions"]]
        assert "websocket:abc" in keys
        # Server stays an opaque source: filesystem paths must not leak to the wire.
        assert all("path" not in s for s in listing.json()["sessions"])

        msgs = await _http_get(
            "http://127.0.0.1:29902/api/sessions/websocket:abc/messages",
            headers=auth,
        )
        assert msgs.status_code == 200
        body = msgs.json()
        assert body["key"] == "websocket:abc"
        assert [m["role"] for m in body["messages"]] == ["user", "assistant"]
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_session_automations_route_filters_by_webui_session(
    bus: MagicMock, tmp_path: Path
) -> None:
    cron = CronService(tmp_path / "cron" / "jobs.json")
    hourly = CronSchedule(kind="every", every_ms=3_600_000)
    pending_job_id = ""
    for name, message, to in (
        ("Morning check", "Check the project status", "abc"),
        ("Other session", "Do not show", "other"),
    ):
        job = cron.add_job(
            name=name,
            schedule=hourly,
            message=message,
            session_key=f"websocket:{to}",
            origin_channel="websocket",
            origin_chat_id=to,
        )
        if name == "Morning check":
            pending_job_id = job.id
    cron.add_job(
        name="Legacy same target",
        schedule=hourly,
        message="Legacy job should be migrated",
        deliver=True,
        channel="websocket",
        to="abc",
        session_key="websocket:abc",
    )
    cron.register_system_job(
        CronJob(
            id="heartbeat",
            name="heartbeat",
            schedule=CronSchedule(kind="every", every_ms=60_000),
            payload=CronPayload(kind="system_event"),
        )
    )
    channel = _ch(
        bus,
        session_manager=_seed_session(tmp_path, key="websocket:abc"),
        cron_service=cron,
        cron_pending_job_ids=lambda key: {pending_job_id} if key == "websocket:abc" else set(),
        port=29914,
    )
    server_task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)
    try:
        deny = await _http_get(
            "http://127.0.0.1:29914/api/sessions/websocket:abc/automations"
        )
        assert deny.status_code == 401

        token = channel.gateway.tokens.issue_api_token(300)
        auth = {"Authorization": f"Bearer {token}"}
        resp = await _http_get(
            "http://127.0.0.1:29914/api/sessions/websocket%3Aabc/automations",
            headers=auth,
        )

        assert resp.status_code == 200
        body = resp.json()
        assert [job["name"] for job in body["jobs"]] == ["Morning check", "Legacy same target"]
        job = body["jobs"][0]
        assert job["schedule"]["kind"] == "every"
        assert job["schedule"]["every_ms"] == 3_600_000
        assert job["payload"]["message"] == "Check the project status"
        assert job["state"]["pending"] is True
        assert body["jobs"][1]["state"]["pending"] is False
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_session_automations_route_ignores_unified_owner(
    bus: MagicMock, tmp_path: Path
) -> None:
    cron = CronService(tmp_path / "cron" / "jobs.json")
    hourly = CronSchedule(kind="every", every_ms=3_600_000)
    cron.add_job(
        name="Unified check",
        schedule=hourly,
        message="Check the shared session",
        session_key=UNIFIED_SESSION_KEY,
        origin_channel="websocket",
        origin_chat_id="abc",
    )
    cron.add_job(
        name="Visible chat job",
        schedule=hourly,
        message="Show for this chat",
        session_key="websocket:abc",
        origin_channel="websocket",
        origin_chat_id="abc",
    )
    channel = _ch(
        bus,
        session_manager=_seed_session(tmp_path, key="websocket:abc"),
        cron_service=cron,
        port=29917,
    )
    server_task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)
    try:
        token = channel.gateway.tokens.issue_api_token(300)
        auth = {"Authorization": f"Bearer {token}"}

        resp = await _http_get(
            "http://127.0.0.1:29917/api/sessions/websocket%3Aabc/automations",
            headers=auth,
        )
        assert resp.status_code == 200
        assert [job["name"] for job in resp.json()["jobs"]] == ["Visible chat job"]

        resp = await _http_get(
            "http://127.0.0.1:29917/api/sessions/websocket%3Aother/automations",
            headers=auth,
        )
        assert resp.status_code == 200
        assert resp.json()["jobs"] == []
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_session_automations_route_lists_local_triggers(
    bus: MagicMock, tmp_path: Path
) -> None:
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    trigger_store = LocalTriggerStore(tmp_path)
    trigger = trigger_store.create(
        name="PR review",
        channel="websocket",
        chat_id="abc",
        session_key="websocket:abc",
    )
    channel = _ch(
        bus,
        session_manager=_seed_session(tmp_path, key="websocket:abc"),
        local_trigger_store=trigger_store,
        local_trigger_pending_ids=lambda key: (
            {trigger.id} if key == "websocket:abc" else set()
        ),
        port=port,
    )
    server_task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)
    try:
        token = channel.gateway.tokens.issue_api_token(300)
        auth = {"Authorization": f"Bearer {token}"}

        resp = await _http_get(
            f"{base_url}/api/sessions/websocket%3Aabc/automations",
            headers=auth,
        )

        assert resp.status_code == 200
        body = resp.json()
        assert [job["id"] for job in body["jobs"]] == [trigger.id]
        job = body["jobs"][0]
        assert job["kind"] == "local_trigger"
        assert job["schedule"]["kind"] == "local"
        assert job["payload"]["kind"] == "local_trigger"
        assert job["payload"]["command"] == f'nanobot trigger {trigger.id} "message"'
        assert job["state"]["pending"] is True
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_webui_skills_route_requires_token_and_hides_paths(
    bus: MagicMock, tmp_path: Path
) -> None:
    workspace_skill = tmp_path / "skills" / "workspace-skill"
    workspace_skill.mkdir(parents=True)
    (workspace_skill / "SKILL.md").write_text(
        "---\nname: workspace-skill\ndescription: Workspace skill.\n---\n",
        encoding="utf-8",
    )
    unavailable_skill = tmp_path / "skills" / "zz-unavailable-skill"
    unavailable_skill.mkdir(parents=True)
    (unavailable_skill / "SKILL.md").write_text(
        "\n".join([
            "---",
            "name: zz-unavailable-skill",
            "description: Missing CLI skill.",
            "metadata:",
            "  nanobot:",
            "    requires:",
            "      bins:",
            "        - definitely-missing-nanobot-skill-cli",
            "      env:",
            "        - DEFINITELY_MISSING_NANOBOT_SKILL_ENV",
            "---",
            "Use the missing CLI and env var.",
        ]),
        encoding="utf-8",
    )
    channel = _ch(
        bus,
        session_manager=_seed_session(tmp_path),
        workspace_path=tmp_path,
        port=29920,
    )
    server_task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)
    try:
        deny = await _http_get("http://127.0.0.1:29920/api/webui/skills")
        assert deny.status_code == 401
        deny_detail = await _http_get("http://127.0.0.1:29920/api/webui/skills/workspace-skill")
        assert deny_detail.status_code == 401

        token = channel.gateway.tokens.issue_api_token(300)
        resp = await _http_get(
            "http://127.0.0.1:29920/api/webui/skills",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 200
        body = resp.json()
        names = [skill["name"] for skill in body["skills"]]
        assert names[0] == "workspace-skill"
        assert "cron" in names
        assert all("path" not in skill for skill in body["skills"])
        workspace = body["skills"][0]
        assert workspace == {
            "name": "workspace-skill",
            "description": "Workspace skill.",
            "source": "workspace",
            "available": True,
            "unavailable_reason": "",
        }
        unavailable = next(skill for skill in body["skills"] if skill["name"] == "zz-unavailable-skill")
        assert unavailable["available"] is False
        assert unavailable["unavailable_reason"] == (
            "CLI: definitely-missing-nanobot-skill-cli, "
            "ENV: DEFINITELY_MISSING_NANOBOT_SKILL_ENV"
        )

        detail = await _http_get(
            "http://127.0.0.1:29920/api/webui/skills/zz-unavailable-skill",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert detail.status_code == 200
        detail_body = detail.json()
        assert "path" not in detail_body
        assert detail_body["requirements"] == {
            "bins": ["definitely-missing-nanobot-skill-cli"],
            "env": ["DEFINITELY_MISSING_NANOBOT_SKILL_ENV"],
            "missing_bins": ["definitely-missing-nanobot-skill-cli"],
            "missing_env": ["DEFINITELY_MISSING_NANOBOT_SKILL_ENV"],
        }
        assert "Use the missing CLI and env var." in detail_body["raw_markdown"]
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_cli_apps_routes_require_token_and_return_payload(
    bus: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def payload(*, installed_only: bool = False) -> dict[str, Any]:
        return {
            "apps": [
                {
                    "name": "gimp",
                    "display_name": "GIMP",
                    "category": "image",
                    "description": "Image editing",
                    "requires": "Python",
                    "source": "harness",
                    "entry_point": "cli-anything-gimp",
                    "install_supported": True,
                    "installed": False,
                    "available": False,
                    "status": "not_installed",
                    "logo_url": None,
                    "brand_color": None,
                    "skill_installed": False,
                }
            ],
            "installed_count": 0,
            "catalog_updated_at": "2026-04-18",
        }

    monkeypatch.setattr(
        "nanobot.webui.settings_routes.cli_apps_payload",
        payload,
    )
    monkeypatch.setattr(
        "nanobot.webui.settings_routes.cli_apps_action",
        lambda action, query: {
            "apps": [],
            "installed_count": 1,
            "catalog_updated_at": "2026-04-18",
            "last_action": {"ok": True, "message": f"{action}:{query['name'][0]}"},
        },
    )
    channel = _ch(bus, session_manager=_seed_session(tmp_path), port=29912)
    server_task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)
    try:
        deny = await _http_get("http://127.0.0.1:29912/api/settings/cli-apps")
        assert deny.status_code == 401

        token = channel.gateway.tokens.issue_api_token(300)
        auth = {"Authorization": f"Bearer {token}"}

        catalog = await _http_get(
            "http://127.0.0.1:29912/api/settings/cli-apps",
            headers=auth,
        )
        assert catalog.status_code == 200
        assert catalog.json()["apps"][0]["name"] == "gimp"

        installed = await _http_get(
            "http://127.0.0.1:29912/api/settings/cli-apps/install?name=gimp",
            headers=auth,
        )
        assert installed.status_code == 200
        assert installed.json()["last_action"]["message"] == "install:gimp"
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_nanobot_feature_routes_require_token_and_enable(
    bus: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    _stub_matrix_feature(monkeypatch, config_path, channels=["matrix", "websocket"])
    channel = _ch(bus, session_manager=_seed_session(tmp_path), port=29916)
    server_task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)
    try:
        deny = await _http_get("http://127.0.0.1:29916/api/settings/nanobot-features")
        assert deny.status_code == 401

        token = channel.gateway.tokens.issue_api_token(300)
        auth = {"Authorization": f"Bearer {token}"}

        catalog = await _http_get(
            "http://127.0.0.1:29916/api/settings/nanobot-features",
            headers=auth,
        )
        assert catalog.status_code == 200
        features = {feature["name"]: feature for feature in catalog.json()["features"]}
        assert features["matrix"]["status"] == "not_enabled"
        assert features["websocket"]["enabled"] is True
        assert features["websocket"]["ready"] is True

        enabled = await _http_get(
            "http://127.0.0.1:29916/api/settings/nanobot-features/enable?name=matrix",
            headers=auth,
        )
        assert enabled.status_code == 200
        body = enabled.json()
        assert body["last_action"]["message"] == "Enabled channel 'matrix'"
        assert body["restart_required_sections"] == ["runtime"]

        disabled_websocket = await _http_get(
            "http://127.0.0.1:29916/api/settings/nanobot-features/disable?name=websocket",
            headers=auth,
        )
        assert disabled_websocket.status_code == 400
        assert "cannot be disabled from WebUI" in disabled_websocket.text
        assert "websocket" not in json.loads(config_path.read_text(encoding="utf-8"))["channels"]

        disabled = await _http_get(
            "http://127.0.0.1:29916/api/settings/nanobot-features/disable?name=matrix",
            headers=auth,
        )
        assert disabled.status_code == 200
        body = disabled.json()
        assert body["last_action"]["message"] == "Disabled channel 'matrix'"
        assert body["restart_required_sections"] == ["runtime"]
        assert json.loads(config_path.read_text(encoding="utf-8"))["channels"]["matrix"][
            "enabled"
        ] is False
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_pairing_routes_require_token_and_approve_or_deny(
    bus: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pending = [
        {
            "code": "ABCD-EFGH",
            "channel": "feishu",
            "sender_id": "ou_123",
            "created_at": 1_000.0,
            "expires_at": 1_600.0,
        }
    ]
    approved: list[str] = []
    denied: list[str] = []

    monkeypatch.setattr("nanobot.webui.settings_routes.list_pending", lambda: list(pending))
    monkeypatch.setattr(
        "nanobot.webui.settings_routes.approve_code",
        lambda code: approved.append(code) or ("feishu", "ou_123") if code == "ABCD-EFGH" else None,
    )
    monkeypatch.setattr(
        "nanobot.webui.settings_routes.deny_code",
        lambda code: denied.append(code) or code == "ABCD-EFGH",
    )

    channel = _ch(bus, session_manager=_seed_session(tmp_path), port=_free_port())
    token = channel.gateway.tokens.issue_api_token(300)

    denied_response = await channel.gateway.http.settings_routes.dispatch(
        _LOCAL,
        _FakeReq(path="/api/settings/pairing"),
        "/api/settings/pairing",
    )
    assert denied_response is not None
    assert denied_response.status_code == 401

    auth = {"Authorization": f"Bearer {token}"}
    listed = await channel.gateway.http.settings_routes.dispatch(
        _LOCAL,
        _FakeReq(auth, path="/api/settings/pairing"),
        "/api/settings/pairing",
    )
    assert listed is not None
    assert listed.status_code == 200
    body = json.loads(listed.body.decode())
    assert body["requests"][0]["code"] == "ABCD-EFGH"
    assert body["requests"][0]["channel"] == "feishu"
    assert body["requests"][0]["sender_id"] == "ou_123"
    assert body["requests"][0]["created_at_ms"] == 1_000_000
    assert body["requests"][0]["expires_at_ms"] == 1_600_000

    approved_response = await channel.gateway.http.settings_routes.dispatch(
        _LOCAL,
        _FakeReq(auth, path="/api/settings/pairing/approve?code=ABCD-EFGH"),
        "/api/settings/pairing/approve",
    )
    assert approved_response is not None
    assert approved_response.status_code == 200
    body = json.loads(approved_response.body.decode())
    assert body["last_action"]["action"] == "approve"
    assert body["last_action"]["sender_id"] == "ou_123"
    assert approved == ["ABCD-EFGH"]

    denied_action = await channel.gateway.http.settings_routes.dispatch(
        _LOCAL,
        _FakeReq(auth, path="/api/settings/pairing/deny?code=ABCD-EFGH"),
        "/api/settings/pairing/deny",
    )
    assert denied_action is not None
    assert denied_action.status_code == 200
    assert json.loads(denied_action.body.decode())["last_action"]["action"] == "deny"
    assert denied == ["ABCD-EFGH"]

    missing_code = await channel.gateway.http.settings_routes.dispatch(
        _LOCAL,
        _FakeReq(auth, path="/api/settings/pairing/approve"),
        "/api/settings/pairing/approve",
    )
    assert missing_code is not None
    assert missing_code.status_code == 400
    assert "Missing pairing code" in missing_code.body.decode()


def test_api_service_settings_read_api_key_from_private_header(bus: MagicMock) -> None:
    channel = _ch(bus)
    request = _FakeReq(
        {"X-Nanobot-API-Service-Values": json.dumps({"api_key": "secret-token"})},
        path="/api/settings/api-service/start?host=0.0.0.0&port=8900&timeout=120",
    )

    query = channel.gateway.http.settings_routes._parse_api_service_settings_query(request)

    assert query == {
        "host": ["0.0.0.0"],
        "port": ["8900"],
        "timeout": ["120"],
        "api_key": ["secret-token"],
    }


def test_api_service_settings_reject_invalid_private_header(bus: MagicMock) -> None:
    from nanobot.webui.settings_api import WebUISettingsError

    channel = _ch(bus)
    request = _FakeReq(
        {"X-Nanobot-API-Service-Values": json.dumps({"api_key": 123})},
        path="/api/settings/api-service/start?host=127.0.0.1",
    )

    with pytest.raises(WebUISettingsError, match="API key must be a string"):
        channel.gateway.http.settings_routes._parse_api_service_settings_query(request)

    query_secret = _FakeReq(
        path="/api/settings/api-service/start?host=127.0.0.1&api_key=secret-token",
    )
    with pytest.raises(WebUISettingsError, match="private header"):
        channel.gateway.http.settings_routes._parse_api_service_settings_query(query_secret)


@pytest.mark.asyncio
async def test_nanobot_feature_remote_install_requires_opt_in(
    bus: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    install_calls: list[str] = []
    _stub_matrix_feature(
        monkeypatch,
        config_path,
        deps=["matrix-nio>=0.25.2"],
        installed=False,
        install_calls=install_calls,
    )
    channel = _ch(bus, session_manager=_seed_session(tmp_path), port=_free_port())
    token = channel.gateway.tokens.issue_api_token(300)
    path = "/api/settings/nanobot-features/enable?name=matrix"
    request = _FakeReq({"Authorization": f"Bearer {token}"}, path=path)

    blocked = await channel.gateway.http.settings_routes.dispatch(
        _REMOTE,
        request,
        "/api/settings/nanobot-features/enable",
    )

    assert blocked is not None
    assert blocked.status_code == 403
    assert "remote WebUI is disabled" in blocked.body.decode()
    assert install_calls == []

    config_path.write_text(
        json.dumps({"tools": {"webuiAllowRemotePackageInstall": True}}),
        encoding="utf-8",
    )

    allowed = await channel.gateway.http.settings_routes.dispatch(
        _REMOTE,
        request,
        "/api/settings/nanobot-features/enable",
    )

    assert allowed is not None
    assert allowed.status_code == 200
    assert install_calls == ["matrix"]


@pytest.mark.asyncio
async def test_nanobot_feature_local_install_allowed_by_default(
    bus: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    install_calls: list[str] = []
    _stub_matrix_feature(
        monkeypatch,
        config_path,
        deps=["matrix-nio>=0.25.2"],
        installed=False,
        install_calls=install_calls,
    )
    channel = _ch(bus, session_manager=_seed_session(tmp_path), port=_free_port())
    token = channel.gateway.tokens.issue_api_token(300)
    request = _FakeReq(
        {"Authorization": f"Bearer {token}", "Host": "127.0.0.1:8765"},
        path="/api/settings/nanobot-features/enable?name=matrix",
    )

    response = await channel.gateway.http.settings_routes.dispatch(
        _LOCAL,
        request,
        "/api/settings/nanobot-features/enable",
    )

    assert response is not None
    assert response.status_code == 200
    assert install_calls == ["matrix"]
    assert json.loads(config_path.read_text(encoding="utf-8"))["channels"]["matrix"][
        "enabled"
    ] is True


@pytest.mark.asyncio
async def test_nanobot_feature_channel_action_can_apply_without_restart(
    bus: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    _stub_matrix_feature(monkeypatch, config_path, deps=["matrix-nio>=0.25.2"])
    calls: list[tuple[str, str]] = []

    async def channel_feature_action(action: str, name: str) -> dict[str, Any]:
        calls.append((action, name))
        return {
            "handled": True,
            "ok": True,
            "requires_restart": False,
            "message": "Matrix channel applied without restart.",
        }

    channel = _ch(
        bus,
        session_manager=_seed_session(tmp_path),
        port=_free_port(),
        channel_feature_action=channel_feature_action,
    )
    token = channel.gateway.tokens.issue_api_token(300)
    request = _FakeReq(
        {"Authorization": f"Bearer {token}", "Host": "127.0.0.1:8765"},
        path="/api/settings/nanobot-features/enable?name=matrix",
    )

    response = await channel.gateway.http.settings_routes.dispatch(
        _LOCAL,
        request,
        "/api/settings/nanobot-features/enable",
    )

    assert response is not None
    assert response.status_code == 200
    body = json.loads(response.body.decode())
    assert calls == [("enable", "matrix")]
    assert body["requires_restart"] is False
    assert body["restart_required_sections"] == []
    assert body["last_action"]["hot_reload"] is True
    assert body["last_action"]["message"].endswith("Matrix channel applied without restart.")


@pytest.mark.asyncio
async def test_feishu_connect_routes_write_config_and_hot_reload(
    bus: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nanobot.channels import feishu as feishu_module
    from nanobot.config import loader
    from nanobot.config.schema import Config

    config_path = tmp_path / "config.json"
    loader.save_config(Config(), config_path)
    monkeypatch.setattr(loader, "_current_config_path", config_path)
    monkeypatch.setattr(feishu_module, "_init_registration", lambda _domain: None)
    monkeypatch.setattr(
        feishu_module,
        "_begin_registration",
        lambda _domain: {
            "device_code": "device",
            "qr_url": "https://accounts.feishu.cn/login?device_code=device",
            "interval": 2,
            "expire_in": 600,
        },
    )
    monkeypatch.setattr(
        feishu_module,
        "poll_registration_once",
        lambda *, device_code, domain: {
            "status": "succeeded",
            "app_id": "cli_app",
            "app_secret": "secret",
            "domain": "feishu",
        },
    )
    monkeypatch.setattr(
        feishu_module,
        "fetch_feishu_app_identity",
        lambda app_id, app_secret, domain: {
            "displayName": "Voraflare Bot",
            "avatarUrl": "https://example.com/feishu.png",
            "identityFetchedAt": "2026-07-06T00:00:00Z",
        },
    )
    monkeypatch.setattr(
        "nanobot.webui.settings_routes.nanobot_features_action",
        lambda _action, _query, *, allow_install=True: {
            "features": [{
                "name": "feishu",
                "display_name": "Feishu",
                "type": "channel",
                "enabled": True,
                "installed": True,
                "ready": True,
                "status": "enabled",
                "install_supported": True,
                "requires_restart": True,
            }],
            "enabled_count": 1,
            "requires_restart": True,
            "last_action": {"ok": True, "message": "Enabled channel 'feishu'", "enabled": True},
        },
    )
    calls: list[tuple[str, str]] = []

    async def channel_feature_action(action: str, name: str) -> dict[str, Any]:
        calls.append((action, name))
        return {
            "handled": True,
            "ok": True,
            "requires_restart": False,
            "message": "Feishu channel applied without restart.",
        }

    channel = _ch(
        bus,
        session_manager=_seed_session(tmp_path),
        port=_free_port(),
        channel_feature_action=channel_feature_action,
    )
    token = channel.gateway.tokens.issue_api_token(300)
    auth = {"Authorization": f"Bearer {token}", "Host": "127.0.0.1:8765"}

    started = await channel.gateway.http.settings_routes.dispatch(
        _LOCAL,
        _FakeReq(
            auth,
            path="/api/settings/channels/feishu/connect/start?domain=feishu&instance_id=default",
        ),
        "/api/settings/channels/feishu/connect/start",
    )

    assert started is not None
    assert started.status_code == 200
    start_body = json.loads(started.body.decode())
    assert start_body["status"] == "pending"
    assert start_body["instance_id"] == "default"
    assert start_body["qr_url"].startswith("https://accounts.feishu.cn/")

    polled = await channel.gateway.http.settings_routes.dispatch(
        _LOCAL,
        _FakeReq(
            auth,
            path=f"/api/settings/channels/feishu/connect/poll?session_id={start_body['session_id']}",
        ),
        "/api/settings/channels/feishu/connect/poll",
    )

    assert polled is not None
    assert polled.status_code == 200
    body = json.loads(polled.body.decode())
    assert body["status"] == "succeeded"
    assert body["instance_id"] == "default"
    assert "app_secret" not in body
    assert calls == [("enable", "feishu")]
    assert body["nanobot_features"]["requires_restart"] is False
    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert data["channels"]["feishu"]["instances"][0]["id"] == "default"
    assert data["channels"]["feishu"]["instances"][0]["appId"] == "cli_app"
    assert data["channels"]["feishu"]["instances"][0]["appSecret"] == "secret"
    assert data["channels"]["feishu"]["instances"][0]["enabled"] is True
    assert data["channels"]["feishu"]["instances"][0]["displayName"] == "Voraflare Bot"
    assert data["channels"]["feishu"]["instances"][0]["avatarUrl"] == "https://example.com/feishu.png"


def test_feishu_connect_create_appends_instance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nanobot.channels import feishu as feishu_module
    from nanobot.config import loader
    from nanobot.webui.channel_connect import FeishuConnectStore

    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({
            "channels": {
                "feishu": {
                    "instances": [{
                        "id": "default",
                        "name": "nanobot",
                        "enabled": True,
                        "appId": "cli_default",
                        "appSecret": "default-secret",
                    }]
                }
            }
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(loader, "_current_config_path", config_path)
    monkeypatch.setattr(feishu_module, "_init_registration", lambda _domain: None)
    monkeypatch.setattr(
        feishu_module,
        "_begin_registration",
        lambda _domain: {
            "device_code": "device",
            "qr_url": "https://accounts.feishu.cn/login?device_code=device",
            "interval": 2,
            "expire_in": 600,
        },
    )
    monkeypatch.setattr(
        feishu_module,
        "poll_registration_once",
        lambda *, device_code, domain: {
            "status": "succeeded",
            "app_id": "cli_new",
            "app_secret": "new-secret",
            "domain": "feishu",
        },
    )
    monkeypatch.setattr(
        feishu_module,
        "fetch_feishu_app_identity",
        lambda app_id, app_secret, domain: {
            "displayName": f"Assistant {app_id}",
            "avatarUrl": f"https://example.com/{app_id}.png",
            "identityFetchedAt": "2026-07-06T00:00:00Z",
        },
    )

    store = FeishuConnectStore()
    started = store.start(mode="create")
    polled = store.poll(started["session_id"])

    assert polled["status"] == "succeeded"
    assert polled["instance_id"] != "default"
    data = json.loads(config_path.read_text(encoding="utf-8"))
    instances = data["channels"]["feishu"]["instances"]
    assert [item["id"] for item in instances] == ["default", polled["instance_id"]]
    assert instances[0]["appId"] == "cli_default"
    assert instances[1]["appId"] == "cli_new"
    assert instances[0].get("displayName") is None
    assert instances[1]["displayName"] == "Assistant cli_new"
    assert instances[1]["avatarUrl"] == "https://example.com/cli_new.png"


@pytest.mark.asyncio
async def test_channel_configure_route_saves_discord_config_and_hot_reloads(
    bus: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nanobot.config import loader
    from nanobot.config.schema import Config

    config_path = tmp_path / "config.json"
    loader.save_config(Config(), config_path)
    monkeypatch.setattr(loader, "_current_config_path", config_path)

    def fake_feature_action(
        action: str,
        query: dict[str, list[str]],
        *,
        allow_install: bool = True,
    ) -> dict[str, Any]:
        assert action == "enable"
        assert query == {"name": ["discord"]}
        cfg = loader.load_raw_config()
        section = dict(getattr(cfg.channels, "discord", {}) or {})
        section["enabled"] = True
        setattr(cfg.channels, "discord", section)
        loader.save_config(cfg)
        return {
            "features": [{
                "name": "discord",
                "display_name": "Discord",
                "type": "channel",
                "enabled": True,
                "installed": True,
                "ready": True,
                "status": "enabled",
                "install_supported": True,
                "requires_restart": True,
            }],
            "enabled_count": 1,
            "requires_restart": True,
            "last_action": {"ok": True, "message": "Enabled channel 'discord'", "enabled": True},
        }

    monkeypatch.setattr("nanobot.webui.settings_routes.nanobot_features_action", fake_feature_action)
    calls: list[tuple[str, str]] = []

    async def channel_feature_action(action: str, name: str) -> dict[str, Any]:
        calls.append((action, name))
        cfg = loader.load_raw_config()
        assert getattr(cfg.channels, "discord")["token"] == "discord-token"
        return {
            "handled": True,
            "ok": True,
            "requires_restart": False,
            "message": "Discord channel applied without restart.",
        }

    channel = _ch(
        bus,
        session_manager=_seed_session(tmp_path),
        port=_free_port(),
        channel_feature_action=channel_feature_action,
    )
    token = channel.gateway.tokens.issue_api_token(300)
    response = await channel.gateway.http.settings_routes.dispatch(
        _LOCAL,
        _FakeReq(
            {
                "Authorization": f"Bearer {token}",
                "Host": "127.0.0.1:8765",
                "X-Nanobot-Channel-Values": json.dumps(
                    {
                        "channels.discord.token": "discord-token",
                        "channels.discord.allowChannels": "123, 456",
                        "channels.discord.groupPolicy": "open",
                    }
                ),
            },
            path="/api/settings/channels/configure?name=discord&enable=true",
        ),
        "/api/settings/channels/configure",
    )

    assert response is not None
    assert response.status_code == 200
    body = json.loads(response.body.decode())
    assert body["saved"] is True
    assert body["name"] == "discord"
    assert "discord-token" not in response.body.decode()
    assert calls == [("enable", "discord")]
    assert body["nanobot_features"]["requires_restart"] is False
    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert data["channels"]["discord"] == {
        "token": "discord-token",
        "allowChannels": ["123", "456"],
        "groupPolicy": "open",
        "enabled": True,
    }


@pytest.mark.asyncio
async def test_channel_configure_route_preserves_existing_channel_values(
    bus: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nanobot.config import loader
    from nanobot.config.schema import Config

    config_path = tmp_path / "config.json"
    config = Config()
    setattr(
        config.channels,
        "discord",
        {
            "enabled": True,
            "token": "old-discord-token",
            "allowChannels": ["old-channel"],
            "groupPolicy": "mention",
            "customExtra": "keep-me",
            "nested": {"value": 42},
        },
    )
    loader.save_config(config, config_path)
    monkeypatch.setattr(loader, "_current_config_path", config_path)

    channel = _ch(bus, session_manager=_seed_session(tmp_path), port=_free_port())
    token = channel.gateway.tokens.issue_api_token(300)
    response = await channel.gateway.http.settings_routes.dispatch(
        _LOCAL,
        _FakeReq(
            {
                "Authorization": f"Bearer {token}",
                "Host": "127.0.0.1:8765",
                "X-Nanobot-Channel-Values": json.dumps(
                    {
                        "channels.discord.token": "",
                        "channels.discord.allowChannels": "new-channel",
                    }
                ),
            },
            path="/api/settings/channels/configure?name=discord",
        ),
        "/api/settings/channels/configure",
    )

    assert response is not None
    assert response.status_code == 200
    body = json.loads(response.body.decode())
    assert body["saved_keys"] == ["channels.discord.allowChannels"]
    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert data["channels"]["discord"] == {
        "enabled": True,
        "token": "old-discord-token",
        "allowChannels": ["new-channel"],
        "groupPolicy": "mention",
        "customExtra": "keep-me",
        "nested": {"value": 42},
    }


@pytest.mark.asyncio
async def test_channel_configure_route_saves_matrix_device_id_without_replacing_token(
    bus: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nanobot.config import loader
    from nanobot.config.schema import Config

    config_path = tmp_path / "config.json"
    config = Config()
    setattr(
        config.channels,
        "matrix",
        {
            "enabled": False,
            "homeserver": "https://matrix.example",
            "userId": "@nanobot:matrix.example",
            "accessToken": "saved-token",
        },
    )
    loader.save_config(config, config_path)
    monkeypatch.setattr(loader, "_current_config_path", config_path)

    channel = _ch(bus, session_manager=_seed_session(tmp_path), port=_free_port())
    token = channel.gateway.tokens.issue_api_token(300)
    response = await channel.gateway.http.settings_routes.dispatch(
        _LOCAL,
        _FakeReq(
            {
                "Authorization": f"Bearer {token}",
                "Host": "127.0.0.1:8765",
                "X-Nanobot-Channel-Values": json.dumps(
                    {
                        "channels.matrix.accessToken": "",
                        "channels.matrix.deviceId": "DEVICE-ID",
                    }
                ),
            },
            path="/api/settings/channels/configure?name=matrix",
        ),
        "/api/settings/channels/configure",
    )

    assert response is not None
    assert response.status_code == 200
    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert data["channels"]["matrix"]["accessToken"] == "saved-token"
    assert data["channels"]["matrix"]["deviceId"] == "DEVICE-ID"


@pytest.mark.asyncio
async def test_channel_configure_route_saves_mattermost_setup(
    bus: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nanobot.config import loader
    from nanobot.config.schema import Config

    config_path = tmp_path / "config.json"
    loader.save_config(Config(), config_path)
    monkeypatch.setattr(loader, "_current_config_path", config_path)

    channel = _ch(bus, session_manager=_seed_session(tmp_path), port=_free_port())
    token = channel.gateway.tokens.issue_api_token(300)
    response = await channel.gateway.http.settings_routes.dispatch(
        _LOCAL,
        _FakeReq(
            {
                "Authorization": f"Bearer {token}",
                "Host": "127.0.0.1:8765",
                "X-Nanobot-Channel-Values": json.dumps(
                    {
                        "channels.mattermost.serverUrl": "https://chat.example.com",
                        "channels.mattermost.token": "mattermost-token",
                        "channels.mattermost.teamId": "platform",
                    }
                ),
            },
            path="/api/settings/channels/configure?name=mattermost",
        ),
        "/api/settings/channels/configure",
    )

    assert response is not None
    assert response.status_code == 200
    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert data["channels"]["mattermost"] == {
        "serverUrl": "https://chat.example.com",
        "token": "mattermost-token",
        "teamId": "platform",
    }


@pytest.mark.asyncio
async def test_nanobot_feature_loopback_reverse_proxy_install_requires_opt_in(
    bus: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    install_calls: list[str] = []
    _stub_matrix_feature(
        monkeypatch,
        config_path,
        deps=["matrix-nio>=0.25.2"],
        installed=False,
        install_calls=install_calls,
    )
    channel = _ch(bus, session_manager=_seed_session(tmp_path), port=_free_port())
    token = channel.gateway.tokens.issue_api_token(300)
    request = _FakeReq(
        {
            "Authorization": f"Bearer {token}",
            "Host": "nanobot.example",
            "X-Forwarded-For": "203.0.113.42",
        },
        path="/api/settings/nanobot-features/enable?name=matrix",
    )

    blocked = await channel.gateway.http.settings_routes.dispatch(
        _LOCAL,
        request,
        "/api/settings/nanobot-features/enable",
    )

    assert blocked is not None
    assert blocked.status_code == 403
    assert install_calls == []

    config_path.write_text(
        json.dumps({"tools": {"webuiAllowRemotePackageInstall": True}}),
        encoding="utf-8",
    )

    allowed = await channel.gateway.http.settings_routes.dispatch(
        _LOCAL,
        request,
        "/api/settings/nanobot-features/enable",
    )

    assert allowed is not None
    assert allowed.status_code == 200
    assert install_calls == ["matrix"]


@pytest.mark.asyncio
async def test_nanobot_feature_remote_enable_without_install_is_allowed(
    bus: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    install_calls: list[str] = []
    _stub_matrix_feature(
        monkeypatch,
        config_path,
        deps=["matrix-nio>=0.25.2"],
        installed=True,
        install_calls=install_calls,
    )
    channel = _ch(bus, session_manager=_seed_session(tmp_path), port=_free_port())
    token = channel.gateway.tokens.issue_api_token(300)
    request = _FakeReq(
        {"Authorization": f"Bearer {token}"},
        path="/api/settings/nanobot-features/enable?name=matrix",
    )

    response = await channel.gateway.http.settings_routes.dispatch(
        _REMOTE,
        request,
        "/api/settings/nanobot-features/enable",
    )

    assert response is not None
    assert response.status_code == 200
    assert install_calls == []
    assert json.loads(config_path.read_text(encoding="utf-8"))["channels"]["matrix"][
        "enabled"
    ] is True


@pytest.mark.asyncio
async def test_nanobot_feature_remote_disable_does_not_need_install_policy(
    bus: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"channels": {"matrix": {"enabled": True, "homeserver": "keep"}}}),
        encoding="utf-8",
    )
    _stub_matrix_feature(monkeypatch, config_path, deps=["matrix-nio>=0.25.2"], installed=False)

    channel = _ch(bus, session_manager=_seed_session(tmp_path), port=_free_port())
    token = channel.gateway.tokens.issue_api_token(300)
    request = _FakeReq(
        {"Authorization": f"Bearer {token}"},
        path="/api/settings/nanobot-features/disable?name=matrix",
    )

    response = await channel.gateway.http.settings_routes.dispatch(
        _REMOTE,
        request,
        "/api/settings/nanobot-features/disable",
    )

    assert response is not None
    assert response.status_code == 200
    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert data["channels"]["matrix"]["enabled"] is False
    assert data["channels"]["matrix"]["homeserver"] == "keep"


@pytest.mark.asyncio
async def test_cli_apps_catalog_does_not_block_other_webui_http_routes(
    bus: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    async def slow_payload(*, installed_only: bool = False) -> dict[str, Any]:
        assert installed_only is False
        entered.set()
        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(release.wait(), 2.0)
        return {"apps": [], "installed_count": 0, "catalog_updated_at": None}

    monkeypatch.setattr("nanobot.webui.settings_routes.cli_apps_payload", slow_payload)
    channel = _ch(bus, session_manager=_seed_session(tmp_path), port=29935)
    server_task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)
    try:
        token = channel.gateway.tokens.issue_api_token(300)
        auth = {"Authorization": f"Bearer {token}"}

        catalog_task = asyncio.create_task(
            _http_get("http://127.0.0.1:29935/api/settings/cli-apps", headers=auth)
        )
        assert await asyncio.wait_for(entered.wait(), 2.0)
        assert not catalog_task.done()

        workspaces_started = time.perf_counter()
        workspaces = await _http_get("http://127.0.0.1:29935/api/workspaces", headers=auth)
        assert time.perf_counter() - workspaces_started < 1.0
        assert workspaces.status_code == 200

        release.set()
        catalog = await catalog_task
        assert catalog.status_code == 200
        assert catalog.json()["apps"] == []
    finally:
        release.set()
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_cli_apps_route_supports_installed_only_payload(
    bus: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[bool] = []

    async def payload(*, installed_only: bool = False) -> dict[str, Any]:
        calls.append(installed_only)
        return {"apps": [], "installed_count": 0, "catalog_updated_at": None}

    monkeypatch.setattr("nanobot.webui.settings_routes.cli_apps_payload", payload)
    channel = _ch(bus, session_manager=_seed_session(tmp_path), port=29936)
    server_task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)
    try:
        token = channel.gateway.tokens.issue_api_token(300)
        auth = {"Authorization": f"Bearer {token}"}

        resp = await _http_get(
            "http://127.0.0.1:29936/api/settings/cli-apps?installed_only=1",
            headers=auth,
        )

        assert resp.status_code == 200
        assert resp.json()["apps"] == []
        assert calls == [True]
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_mcp_presets_routes_require_token_and_return_payload(
    bus: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "nanobot.webui.mcp_presets_api.mcp_presets_payload",
        lambda: {
            "presets": [
                {
                    "name": "browserbase",
                    "display_name": "Browserbase",
                    "category": "browser",
                    "description": "Cloud browser automation",
                    "docs_url": "https://docs.browserbase.com/integrations/mcp/configuration",
                    "transport": "streamableHttp",
                    "requires": "Browserbase API key",
                    "note": "",
                    "install_supported": True,
                    "installed": False,
                    "configured": False,
                    "available": False,
                    "status": "not_installed",
                    "logo_url": None,
                    "brand_color": "#111827",
                    "required_fields": [],
                    "connection_summary": "",
                }
            ],
            "installed_count": 0,
        },
    )
    preset_queries: list[tuple[str, dict[str, list[str]]]] = []
    custom_queries: list[tuple[str, dict[str, list[str]]]] = []

    def _mcp_preset_action(action: str, query: dict[str, list[str]]) -> dict[str, Any]:
        preset_queries.append((action, query))
        return {
            "presets": [],
            "installed_count": 1,
            "requires_restart": action != "test",
            "last_action": {"ok": True, "message": f"{action}:{query['name'][0]}"},
        }

    def _custom_action(action: str, query: dict[str, list[str]]) -> dict[str, Any]:
        custom_queries.append((action, query))
        return {
            "presets": [],
            "installed_count": 1,
            "requires_restart": True,
            "last_action": {
                "ok": True,
                "message": f"{action}:{query.get('name', ['config'])[0]}",
            },
        }

    monkeypatch.setattr(
        "nanobot.webui.mcp_presets_api.mcp_presets_action",
        _mcp_preset_action,
    )
    monkeypatch.setattr(
        "nanobot.webui.mcp_presets_api.custom_mcp_action",
        _custom_action,
    )

    async def _hot_reload(_bus):
        return {"ok": True, "message": "MCP config reloaded.", "requires_restart": False}

    monkeypatch.setattr(
        "nanobot.webui.settings_routes.request_mcp_reload",
        _hot_reload,
    )
    channel = _ch(bus, session_manager=_seed_session(tmp_path), port=29913)
    server_task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)
    try:
        deny = await _http_get("http://127.0.0.1:29913/api/settings/mcp-presets")
        assert deny.status_code == 401

        token = channel.gateway.tokens.issue_api_token(300)
        auth = {"Authorization": f"Bearer {token}"}

        catalog = await _http_get(
            "http://127.0.0.1:29913/api/settings/mcp-presets",
            headers=auth,
        )
        assert catalog.status_code == 200
        assert catalog.json()["presets"][0]["name"] == "browserbase"

        enabled = await _http_get(
            "http://127.0.0.1:29913/api/settings/mcp-presets/enable?name=browserbase",
            headers={
                **auth,
                "X-Nanobot-MCP-Values": json.dumps(
                    {"browserbase_api_key": "bb_live_secret"}
                ),
            },
        )
        assert enabled.status_code == 200
        assert preset_queries[-1][1]["browserbase_api_key"] == ["bb_live_secret"]
        body = enabled.json()
        assert "bb_live_secret" not in enabled.text
        assert body["last_action"]["message"] == "enable:browserbase MCP config reloaded."
        assert body["hot_reload"]["ok"] is True
        assert body["restart_required_sections"] == []

        bad_header = await _http_get(
            "http://127.0.0.1:29913/api/settings/mcp-presets/enable?name=browserbase",
            headers={**auth, "X-Nanobot-MCP-Values": "[]"},
        )
        assert bad_header.status_code == 400

        custom = await _http_get(
            "http://127.0.0.1:29913/api/settings/mcp-presets/custom",
            headers={
                **auth,
                "X-Nanobot-MCP-Values": json.dumps(
                    {"name": "docs", "command": "npx"}
                ),
            },
        )
        assert custom.status_code == 200
        assert custom_queries[-1][1]["command"] == ["npx"]
        assert custom.json()["last_action"]["message"] == "custom:docs MCP config reloaded."

        imported = await _http_get(
            "http://127.0.0.1:29913/api/settings/mcp-presets/import",
            headers={**auth, "X-Nanobot-MCP-Values": json.dumps({"config": "{}"})},
        )
        assert imported.status_code == 200
        assert imported.json()["last_action"]["message"] == "import:config MCP config reloaded."

        tools = await _http_get(
            "http://127.0.0.1:29913/api/settings/mcp-presets/tools",
            headers={
                **auth,
                "X-Nanobot-MCP-Values": json.dumps(
                    {"name": "docs", "enabled_tools": []}
                ),
            },
        )
        assert tools.status_code == 200
        assert tools.json()["last_action"]["message"] == "tools:docs MCP config reloaded."
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_sessions_list_only_returns_websocket_sessions_by_default(
    bus: MagicMock, tmp_path: Path
) -> None:
    # Seed a realistic multi-channel disk state: CLI, Slack, Lark and
    # websocket sessions all live in the same ``sessions/`` directory.
    sm = _seed_many(
        tmp_path,
        [
            "cli:direct",
            "slack:C123",
            "lark:oc_abc",
            "websocket:alpha",
            "websocket:beta",
        ],
    )
    channel = _ch(bus, session_manager=sm, port=29906)
    server_task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)
    try:
        token = channel.gateway.tokens.issue_api_token(300)
        auth = {"Authorization": f"Bearer {token}"}

        listing = await _http_get(
            "http://127.0.0.1:29906/api/sessions", headers=auth
        )
        assert listing.status_code == 200
        keys = {s["key"] for s in listing.json()["sessions"]}
        # Only websocket-channel sessions are part of the webui surface; CLI /
        # Slack / Lark rows would be non-resumable from the browser.
        assert keys == {"websocket:alpha", "websocket:beta"}
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_webui_sidebar_state_routes_are_config_dir_scoped(
    bus: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    sm = _seed_session(tmp_path, key="websocket:sidebar")
    channel = _ch(bus, session_manager=sm, port=29911)
    server_task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)
    try:
        token = channel.gateway.tokens.issue_api_token(300)
        auth = {"Authorization": f"Bearer {token}"}

        initial = await _http_get(
            "http://127.0.0.1:29911/api/webui/sidebar-state",
            headers=auth,
        )
        assert initial.status_code == 200
        assert initial.json()["schema_version"] == 1
        assert initial.json()["pinned_keys"] == []

        payload = {
            "pinned_keys": ["websocket:sidebar"],
            "archived_keys": ["websocket:old"],
            "title_overrides": {"websocket:sidebar": "Pinned work"},
            "view": {"density": "compact", "show_archived": True},
        }
        query = urlencode({"state": json.dumps(payload)})
        updated = await _http_get(
            f"http://127.0.0.1:29911/api/webui/sidebar-state/update?{query}",
            headers=auth,
        )
        assert updated.status_code == 200
        body = updated.json()
        assert body["pinned_keys"] == ["websocket:sidebar"]
        assert body["title_overrides"] == {"websocket:sidebar": "Pinned work"}
        assert body["view"]["density"] == "compact"

        state_path = tmp_path / "webui" / "sidebar-state.json"
        assert state_path.is_file()
        assert json.loads(state_path.read_text(encoding="utf-8"))["pinned_keys"] == [
            "websocket:sidebar"
        ]
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_session_delete_removes_file(
    bus: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    sm = _seed_session(tmp_path, key="websocket:doomed")
    from nanobot.webui.transcript import append_transcript_object

    append_transcript_object("websocket:doomed", {"event": "user", "chat_id": "doomed", "text": "x"})
    channel = _ch(bus, session_manager=sm, port=29903)
    server_task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)
    try:
        token = channel.gateway.tokens.issue_api_token(300)
        auth = {"Authorization": f"Bearer {token}"}

        path = sm._get_session_path("websocket:doomed")
        assert path.exists()
        webui_path = tmp_path / "webui" / f"{SessionManager.safe_key('websocket:doomed')}.jsonl"
        assert webui_path.is_file()
        resp = await _http_get(
            "http://127.0.0.1:29903/api/sessions/websocket:doomed/delete",
            headers=auth,
        )
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True
        assert not path.exists()
        assert not webui_path.exists()
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_webui_automations_route_lists_all_jobs_and_allows_user_actions(
    bus: MagicMock, tmp_path: Path
) -> None:
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    cron = CronService(tmp_path / "cron" / "jobs.json")
    user_job = cron.add_job(
        name="Daily repo check",
        schedule=CronSchedule(kind="every", every_ms=86_400_000),
        message="Check the repo status",
        session_key="websocket:abc",
        origin_channel="websocket",
        origin_chat_id="abc",
    )
    incomplete_job = cron.add_job(
        name="english-quiz",
        schedule=CronSchedule(kind="every", every_ms=3_600_000),
        message="Practice English",
        session_key="unified:default",
    )
    external_job = cron.add_job(
        name="WeChat quiz",
        schedule=CronSchedule(kind="every", every_ms=3_600_000),
        message="Send a quiz",
        session_key="weixin:wx-chat",
        origin_channel="weixin",
        origin_chat_id="wx-chat",
    )
    past_one_shot_job = cron.add_job(
        name="Past one-shot",
        schedule=CronSchedule(kind="at", at_ms=1),
        message="Old one-shot message",
        session_key="websocket:abc",
        origin_channel="websocket",
        origin_chat_id="abc",
        delete_after_run=True,
    )
    cron.register_system_job(
        CronJob(
            id="heartbeat",
            name="heartbeat",
            schedule=CronSchedule(kind="every", every_ms=60_000),
            payload=CronPayload(kind="system_event"),
        )
    )
    session_manager = _seed_session(tmp_path, key="websocket:abc")
    external_session = Session(key="weixin:wx-chat")
    external_session.add_message("user", "Scheduled cron job triggered")
    session_manager.save(external_session)
    channel = _ch(
        bus,
        session_manager=session_manager,
        cron_service=cron,
        cron_pending_job_ids=lambda key: {user_job.id} if key == "websocket:abc" else set(),
        port=port,
    )
    server_task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)
    try:
        deny = await _http_get(f"{base_url}/api/webui/automations")
        assert deny.status_code == 401, deny.text

        token = channel.gateway.tokens.issue_api_token(300)
        auth = {"Authorization": f"Bearer {token}"}
        resp = await _http_get(
            f"{base_url}/api/webui/automations",
            headers=auth,
        )
        assert resp.status_code == 200
        assert "wx-chat" not in resp.text
        assert "unified:default" not in resp.text
        body = resp.json()
        by_id = {job["id"]: job for job in body["jobs"]}
        assert by_id[user_job.id]["protected"] is False
        assert by_id[user_job.id]["state"]["pending"] is True
        assert by_id[user_job.id]["state"]["run_history"] == []
        assert by_id[user_job.id]["origin"]["session_key"] == "websocket:abc"
        assert by_id[user_job.id]["origin"]["preview"] == "hi"
        assert "session_key" not in by_id[incomplete_job.id]["payload"]
        assert "origin_channel" not in by_id[incomplete_job.id]["payload"]
        assert "origin_chat_id" not in by_id[incomplete_job.id]["payload"]
        assert by_id[incomplete_job.id]["origin"] is None
        assert "session_key" not in by_id[external_job.id]["payload"]
        assert "origin_channel" not in by_id[external_job.id]["payload"]
        assert "origin_chat_id" not in by_id[external_job.id]["payload"]
        assert by_id[external_job.id]["origin"]["channel"] == "weixin"
        assert "session_key" not in by_id[external_job.id]["origin"]
        assert "chat_id" not in by_id[external_job.id]["origin"]
        assert by_id[external_job.id]["origin"]["preview"] == ""
        assert by_id["heartbeat"]["protected"] is True

        updated = await _http_get(
            f"{base_url}/api/webui/automations/update?id={user_job.id}",
            headers={
                **auth,
                "X-Nanobot-Automation-Values": json.dumps(
                    {
                        "name": "Daily quiz",
                        "message": "Ask the daily quiz",
                        "schedule": {
                            "kind": "cron",
                            "expr": "0 9 * * *",
                            "tz": "UTC",
                        },
                    }
                ),
            },
        )
        assert updated.status_code == 200
        by_id = {job["id"]: job for job in updated.json()["jobs"]}
        assert by_id[user_job.id]["name"] == "Daily quiz"
        assert by_id[user_job.id]["payload"]["message"] == "Ask the daily quiz"
        assert by_id[user_job.id]["schedule"]["kind"] == "cron"
        assert by_id[user_job.id]["schedule"]["expr"] == "0 9 * * *"
        assert by_id[user_job.id]["schedule"]["tz"] == "UTC"

        unicode_update = await _http_get(
            f"{base_url}/api/webui/automations/update?id={user_job.id}",
            headers={
                **auth,
                "X-Nanobot-Automation-Values": quote(
                    json.dumps(
                        {
                            "name": "每日测验",
                            "message": "问今日测验",
                        },
                        ensure_ascii=False,
                    ),
                    safe="",
                ),
            },
        )
        assert unicode_update.status_code == 200
        assert cron.get_job(user_job.id).name == "每日测验"
        assert cron.get_job(user_job.id).payload.message == "问今日测验"

        malformed_update = await _http_get(
            f"{base_url}/api/webui/automations/update?id={user_job.id}",
            headers={
                **auth,
                "X-Nanobot-Automation-Values": json.dumps({"message": ["bad"]}),
            },
        )
        assert malformed_update.status_code == 400
        assert cron.get_job(user_job.id).payload.message == "问今日测验"

        invalid_cron_update = await _http_get(
            f"{base_url}/api/webui/automations/update?id={user_job.id}",
            headers={
                **auth,
                "X-Nanobot-Automation-Values": json.dumps(
                    {"schedule": {"kind": "cron", "expr": "not a cron", "tz": "UTC"}}
                ),
            },
        )
        assert invalid_cron_update.status_code == 400
        assert cron.get_job(user_job.id).schedule.expr == "0 9 * * *"

        past_one_shot_update = await _http_get(
            f"{base_url}/api/webui/automations/update?id={past_one_shot_job.id}",
            headers={
                **auth,
                "X-Nanobot-Automation-Values": json.dumps(
                    {
                        "message": "Updated one-shot message",
                        "schedule": {"kind": "at", "at_ms": 1},
                    }
                ),
            },
        )
        assert past_one_shot_update.status_code == 200
        assert cron.get_job(past_one_shot_job.id).payload.message == "Updated one-shot message"
        assert cron.get_job(past_one_shot_job.id).schedule.at_ms == 1

        protected_update = await _http_get(
            f"{base_url}/api/webui/automations/update?id=heartbeat",
            headers={
                **auth,
                "X-Nanobot-Automation-Values": json.dumps({"name": "bad"}),
            },
        )
        assert protected_update.status_code == 403

        disabled = await _http_get(
            f"{base_url}/api/webui/automations/disable?id={user_job.id}",
            headers=auth,
        )
        assert disabled.status_code == 200
        by_id = {job["id"]: job for job in disabled.json()["jobs"]}
        assert by_id[user_job.id]["enabled"] is False

        disabled_run = await _http_get(
            f"{base_url}/api/webui/automations/run?id={user_job.id}",
            headers=auth,
        )
        assert disabled_run.status_code == 409

        unbound_run = await _http_get(
            f"{base_url}/api/webui/automations/run?id={incomplete_job.id}",
            headers=auth,
        )
        assert unbound_run.status_code == 409
        assert "no linked chat" in unbound_run.text

        unbound_enable = await _http_get(
            f"{base_url}/api/webui/automations/enable?id={incomplete_job.id}",
            headers=auth,
        )
        assert unbound_enable.status_code == 409
        assert "no linked chat" in unbound_enable.text

        protected_delete = await _http_get(
            f"{base_url}/api/webui/automations/delete?id=heartbeat",
            headers=auth,
        )
        assert protected_delete.status_code == 403
        protected_disable = await _http_get(
            f"{base_url}/api/webui/automations/disable?id=heartbeat",
            headers=auth,
        )
        assert protected_disable.status_code == 403
        protected_run = await _http_get(
            f"{base_url}/api/webui/automations/run?id=heartbeat",
            headers=auth,
        )
        assert protected_run.status_code == 403

        enabled = await _http_get(
            f"{base_url}/api/webui/automations/enable?id={user_job.id}",
            headers=auth,
        )
        assert enabled.status_code == 200
        by_id = {job["id"]: job for job in enabled.json()["jobs"]}
        assert by_id[user_job.id]["enabled"] is True

        deleted = await _http_get(
            f"{base_url}/api/webui/automations/delete?id={user_job.id}",
            headers=auth,
        )
        assert deleted.status_code == 200
        assert user_job.id not in {job["id"] for job in deleted.json()["jobs"]}
        assert "heartbeat" in {job["id"] for job in deleted.json()["jobs"]}
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_webui_automations_route_manages_local_triggers(
    bus: MagicMock, tmp_path: Path
) -> None:
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    trigger_store = LocalTriggerStore(tmp_path)
    trigger = trigger_store.create(
        name="PR review",
        channel="websocket",
        chat_id="abc",
        session_key="websocket:abc",
    )
    delivery = trigger_store.enqueue(trigger.id, "Review queued PR")
    assert delivery.path is not None
    channel = _ch(
        bus,
        session_manager=_seed_session(tmp_path, key="websocket:abc"),
        local_trigger_store=trigger_store,
        local_trigger_pending_ids=lambda key: (
            {trigger.id} if key == "websocket:abc" else set()
        ),
        port=port,
    )
    server_task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)
    try:
        token = channel.gateway.tokens.issue_api_token(300)
        auth = {"Authorization": f"Bearer {token}"}

        listed = await _http_get(f"{base_url}/api/webui/automations", headers=auth)
        assert listed.status_code == 200
        by_id = {job["id"]: job for job in listed.json()["jobs"]}
        assert by_id[trigger.id]["kind"] == "local_trigger"
        assert by_id[trigger.id]["state"]["pending"] is True
        assert by_id[trigger.id]["trigger"]["command"] == f'nanobot trigger {trigger.id} "message"'

        disabled = await _http_get(
            f"{base_url}/api/webui/automations/disable?id={trigger.id}",
            headers=auth,
        )
        assert disabled.status_code == 200
        stored = trigger_store.get(trigger.id)
        assert stored is not None
        assert stored.enabled is False

        run = await _http_get(
            f"{base_url}/api/webui/automations/run?id={trigger.id}",
            headers=auth,
        )
        assert run.status_code == 409
        assert "CLI message" in run.text

        renamed = await _http_get(
            f"{base_url}/api/webui/automations/update?id={trigger.id}",
            headers={
                **auth,
                "X-Nanobot-Automation-Values": json.dumps({"name": "Release review"}),
            },
        )
        assert renamed.status_code == 200
        stored = trigger_store.get(trigger.id)
        assert stored is not None
        assert stored.name == "Release review"

        bad_update = await _http_get(
            f"{base_url}/api/webui/automations/update?id={trigger.id}",
            headers={
                **auth,
                "X-Nanobot-Automation-Values": json.dumps({"message": "coupled"}),
            },
        )
        assert bad_update.status_code == 400

        deleted = await _http_get(
            f"{base_url}/api/webui/automations/delete?id={trigger.id}",
            headers=auth,
        )
        assert deleted.status_code == 200
        assert trigger_store.get(trigger.id) is None
        assert not delivery.path.exists()
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_session_delete_blocks_when_bound_automation_exists(
    bus: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    sm = _seed_session(tmp_path, key="websocket:doomed")
    cron = CronService(tmp_path / "cron" / "jobs.json")
    cron.add_job(
        name="Daily check",
        schedule=CronSchedule(kind="every", every_ms=86_400_000),
        message="Check the repo",
        session_key="websocket:doomed",
        origin_channel="websocket",
        origin_chat_id="doomed",
    )
    channel = _ch(bus, session_manager=sm, cron_service=cron, port=29915)
    server_task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)
    try:
        token = channel.gateway.tokens.issue_api_token(300)
        auth = {"Authorization": f"Bearer {token}"}

        path = sm._get_session_path("websocket:doomed")
        resp = await _http_get(
            "http://127.0.0.1:29915/api/sessions/websocket:doomed/delete",
            headers=auth,
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["deleted"] is False
        assert body["blocked_by_automations"] is True
        assert [job["name"] for job in body["automations"]] == ["Daily check"]
        assert path.exists()
        assert cron.list_bound_cron_jobs_for_session("websocket:doomed")
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_session_delete_blocks_and_cascades_local_triggers(
    bus: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    sm = _seed_session(tmp_path, key="websocket:doomed")
    trigger_store = LocalTriggerStore(tmp_path)
    trigger = trigger_store.create(
        name="PR review",
        channel="websocket",
        chat_id="doomed",
        session_key="websocket:doomed",
    )
    channel = _ch(
        bus,
        session_manager=sm,
        local_trigger_store=trigger_store,
        port=port,
    )
    server_task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)
    try:
        token = channel.gateway.tokens.issue_api_token(300)
        auth = {"Authorization": f"Bearer {token}"}

        blocked = await _http_get(
            f"{base_url}/api/sessions/websocket:doomed/delete",
            headers=auth,
        )
        assert blocked.status_code == 200
        assert blocked.json()["blocked_by_automations"] is True
        assert trigger_store.get(trigger.id) is not None

        deleted = await _http_get(
            f"{base_url}/api/sessions/websocket:doomed/delete?delete_automations=true",
            headers=auth,
        )
        assert deleted.status_code == 200
        assert deleted.json()["deleted"] is True
        assert trigger_store.get(trigger.id) is None
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_session_delete_can_cascade_bound_automations(
    bus: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    sm = _seed_session(tmp_path, key="websocket:doomed")
    cron = CronService(tmp_path / "cron" / "jobs.json")
    cron.add_job(
        name="Daily check",
        schedule=CronSchedule(kind="every", every_ms=86_400_000),
        message="Check the repo",
        session_key="websocket:doomed",
        origin_channel="websocket",
        origin_chat_id="doomed",
    )
    cron.add_job(
        name="Legacy same target",
        schedule=CronSchedule(kind="every", every_ms=86_400_000),
        message="Legacy job remains",
        channel="websocket",
        to="doomed",
    )
    channel = _ch(bus, session_manager=sm, cron_service=cron, port=29916)
    server_task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)
    try:
        token = channel.gateway.tokens.issue_api_token(300)
        auth = {"Authorization": f"Bearer {token}"}

        path = sm._get_session_path("websocket:doomed")
        resp = await _http_get(
            "http://127.0.0.1:29916/api/sessions/websocket:doomed/delete?delete_automations=true",
            headers=auth,
        )

        assert resp.status_code == 200
        assert resp.json()["deleted"] is True
        assert not path.exists()
        assert cron.list_bound_cron_jobs_for_session("websocket:doomed") == []
        assert cron.list_jobs(include_disabled=True) == []
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_session_delete_blocks_origin_automation_when_unified_enabled(
    bus: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    sm = _seed_session(tmp_path, key="websocket:doomed")
    cron = CronService(tmp_path / "cron" / "jobs.json")
    cron.add_job(
        name="Chat daily check",
        schedule=CronSchedule(kind="every", every_ms=86_400_000),
        message="Check this chat",
        session_key="websocket:doomed",
        origin_channel="websocket",
        origin_chat_id="doomed",
    )
    channel = _ch(
        bus,
        session_manager=sm,
        cron_service=cron,
        port=29918,
    )
    server_task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)
    try:
        token = channel.gateway.tokens.issue_api_token(300)
        auth = {"Authorization": f"Bearer {token}"}

        path = sm._get_session_path("websocket:doomed")
        resp = await _http_get(
            "http://127.0.0.1:29918/api/sessions/websocket:doomed/delete",
            headers=auth,
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["deleted"] is False
        assert body["blocked_by_automations"] is True
        assert [job["name"] for job in body["automations"]] == ["Chat daily check"]
        assert path.exists()
        assert [job.name for job in cron.list_bound_cron_jobs_for_session("websocket:doomed")] == [
            "Chat daily check"
        ]
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_session_routes_accept_percent_encoded_websocket_keys(
    bus: MagicMock, tmp_path: Path
) -> None:
    sm = _seed_session(tmp_path, key="websocket:encoded-key")
    channel = _ch(bus, session_manager=sm, port=29910)
    server_task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)
    try:
        token = channel.gateway.tokens.issue_api_token(300)
        auth = {"Authorization": f"Bearer {token}"}

        msgs = await _http_get(
            "http://127.0.0.1:29910/api/sessions/websocket%3Aencoded-key/messages",
            headers=auth,
        )
        assert msgs.status_code == 200
        assert msgs.json()["key"] == "websocket:encoded-key"

        path = sm._get_session_path("websocket:encoded-key")
        assert path.exists()
        deleted = await _http_get(
            "http://127.0.0.1:29910/api/sessions/websocket%3Aencoded-key/delete",
            headers=auth,
        )
        assert deleted.status_code == 200
        assert deleted.json()["deleted"] is True
        assert not path.exists()
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_session_messages_hide_persisted_runtime_context(
    bus: MagicMock, tmp_path: Path
) -> None:
    sm = SessionManager(tmp_path)
    session = sm.get_or_create("websocket:runtime-context")
    content, marker = append_runtime_context(
        "visible user text",
        [RuntimeContextBlock(source="goal", content="private goal context")],
    )
    session.add_message(
        "user",
        content,
        **{RUNTIME_CONTEXT_HISTORY_META: marker},
    )
    sm.save(session)
    channel = _ch(bus, session_manager=sm, port=29919)
    server_task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)
    try:
        token = channel.gateway.tokens.issue_api_token(300)
        response = await _http_get(
            "http://127.0.0.1:29919/api/sessions/websocket:runtime-context/messages",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        message = response.json()["messages"][0]
        assert message["content"] == "visible user text"
        assert RUNTIME_CONTEXT_HISTORY_META not in message
        assert "private goal context" not in response.text
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_webui_thread_resigns_assistant_media_urls(
    bus: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nanobot.webui.transcript import append_transcript_object

    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    media_root = tmp_path / "media"
    websocket_media = media_root / "websocket"
    websocket_media.mkdir(parents=True)
    external = tmp_path / "clip.mp4"
    external.write_bytes(b"video")

    def fake_media_dir(channel: str | None = None) -> Path:
        return websocket_media if channel == "websocket" else media_root

    monkeypatch.setattr("nanobot.channels.websocket.get_media_dir", fake_media_dir)

    append_transcript_object(
        "websocket:video-replay",
        {"event": "user", "chat_id": "video-replay", "text": "make a video"},
    )
    append_transcript_object(
        "websocket:video-replay",
        {
            "event": "message",
            "chat_id": "video-replay",
            "text": "video ready",
            "media": [str(external)],
            "media_urls": [{"url": "/api/media/old-sig/old-payload", "name": "clip.mp4"}],
        },
    )

    channel = _ch(bus, port=29914)
    server_task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)
    try:
        token = channel.gateway.tokens.issue_api_token(300)
        auth = {"Authorization": f"Bearer {token}"}
        resp = await _http_get(
            "http://127.0.0.1:29914/api/sessions/websocket:video-replay/webui-thread",
            headers=auth,
        )
        assert resp.status_code == 200
        assistant = next(m for m in resp.json()["messages"] if m["role"] == "assistant")
        media = assistant["media"]
        assert media[0]["kind"] == "video"
        assert media[0]["name"] == "clip.mp4"
        assert media[0]["url"].startswith("/api/media/")
        assert media[0]["url"] != "/api/media/old-sig/old-payload"

        fetched = await _http_get(f"http://127.0.0.1:29914{media[0]['url']}")
        assert fetched.status_code == 200
        assert fetched.content == b"video"
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_session_routes_reject_non_websocket_keys(
    bus: MagicMock, tmp_path: Path
) -> None:
    sm = _seed_many(
        tmp_path,
        [
            "websocket:kept",
            "cli:direct",
            "slack:C123",
        ],
    )
    channel = _ch(bus, session_manager=sm, port=29909)
    server_task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)
    try:
        token = channel.gateway.tokens.issue_api_token(300)
        auth = {"Authorization": f"Bearer {token}"}

        # The webui list already hides non-websocket sessions; handcrafted URLs
        # should hit the same boundary rather than exposing or deleting them.
        msgs = await _http_get(
            "http://127.0.0.1:29909/api/sessions/cli:direct/messages",
            headers=auth,
        )
        assert msgs.status_code == 404

        doomed = sm._get_session_path("slack:C123")
        assert doomed.exists()
        deny_delete = await _http_get(
            "http://127.0.0.1:29909/api/sessions/slack:C123/delete",
            headers=auth,
        )
        assert deny_delete.status_code == 404
        assert doomed.exists()
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_session_routes_reject_invalid_key(
    bus: MagicMock, tmp_path: Path
) -> None:
    sm = _seed_session(tmp_path)
    channel = _ch(bus, session_manager=sm, port=29904)
    server_task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)
    try:
        token = channel.gateway.tokens.issue_api_token(300)
        auth = {"Authorization": f"Bearer {token}"}

        # Invalid characters in the key -> regex match fails -> 404
        # (route doesn't match, falls through to channel 404).
        resp = await _http_get(
            "http://127.0.0.1:29904/api/sessions/bad%20key/messages",
            headers=auth,
        )
        assert resp.status_code in {400, 404}
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_static_serves_index_when_dist_present(
    bus: MagicMock, tmp_path: Path
) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>nbweb</title>")
    (dist / "favicon.svg").write_text("<svg/>")
    sm = _seed_session(tmp_path / "ws_state")
    channel = _ch(bus, session_manager=sm, static_dist_path=dist, port=29905)
    server_task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)
    try:
        # Bare ``GET /`` is a browser opening the app: it must return the SPA
        # index.html, not the WS-upgrade handler's 401/426.
        root = await _http_get("http://127.0.0.1:29905/")
        assert root.status_code == 200
        assert "nbweb" in root.text
        asset = await _http_get("http://127.0.0.1:29905/favicon.svg")
        assert asset.status_code == 200
        assert "<svg" in asset.text
        # Unknown SPA route falls back to index.html.
        spa = await _http_get("http://127.0.0.1:29905/sessions/abc")
        assert spa.status_code == 200
        assert "nbweb" in spa.text
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_static_rejects_path_traversal(
    bus: MagicMock, tmp_path: Path
) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("ok")
    secret = tmp_path / "secret.txt"
    secret.write_text("classified")
    channel = _ch(bus, static_dist_path=dist, port=29906)
    server_task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)
    try:
        resp = await _http_get("http://127.0.0.1:29906/../secret.txt")
        # Normalized by httpx into /secret.txt → falls back to index.html, not 'classified'.
        assert "classified" not in resp.text
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_unknown_route_returns_404(bus: MagicMock) -> None:
    channel = _ch(bus, port=29907)
    server_task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)
    try:
        resp = await _http_get("http://127.0.0.1:29907/api/unknown")
        assert resp.status_code == 404
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_api_token_pool_purges_expired(bus: MagicMock, tmp_path: Path) -> None:
    sm = _seed_session(tmp_path)
    channel = _ch(bus, session_manager=sm, port=29908)
    # Don't start a server — directly inject and validate.
    import time as _time
    channel.gateway.tokens.api_tokens["expired"] = _time.monotonic() - 1
    channel.gateway.tokens.api_tokens["live"] = _time.monotonic() + 60

    class _FakeReq:
        path = "/api/sessions"
        headers = {"Authorization": "Bearer expired"}

    assert channel.gateway.tokens.check_api_token(_FakeReq()) is False

    class _LiveReq:
        path = "/api/sessions"
        headers = {"Authorization": "Bearer live"}

    assert channel.gateway.tokens.check_api_token(_LiveReq()) is True


class _FakeConn:
    """Minimal connection stub with a configurable remote_address."""

    def __init__(self, remote_address: tuple[str, int]):
        self.remote_address = remote_address

    def respond(self, status: int, body: str) -> Any:
        from websockets.http11 import Response

        return Response(status=status, body=body.encode())


class _FakeReq:
    """Minimal request stub with configurable headers."""

    def __init__(self, headers: dict[str, str] | None = None, *, path: str = "/"):
        self.headers = headers or {}
        self.path = path


_REMOTE = _FakeConn(("192.168.1.5", 12345))
_LOCAL = _FakeConn(("127.0.0.1", 12345))
_NO_HEADERS = _FakeReq()
_LOCAL_BROWSER_REQ = _FakeReq({"Host": "127.0.0.1:8765"})


def test_local_browser_request_requires_loopback_host_and_forwarded_origin() -> None:
    from nanobot.webui.http_utils import is_local_browser_request

    assert is_local_browser_request(_LOCAL, {"Host": "127.0.0.1:8765"}) is True
    assert is_local_browser_request(_LOCAL, {"Host": "localhost:8765"}) is True
    assert (
        is_local_browser_request(
            _LOCAL,
            {"Host": "localhost:8765", "X-Forwarded-For": "127.0.0.1"},
        )
        is True
    )
    assert is_local_browser_request(_REMOTE, {"Host": "127.0.0.1:8765"}) is False
    assert is_local_browser_request(_LOCAL, {"Host": "nanobot.example"}) is False
    assert (
        is_local_browser_request(
            _LOCAL,
            {"Host": "127.0.0.1:8765", "X-Forwarded-For": "203.0.113.42"},
        )
        is False
    )
    assert (
        is_local_browser_request(
            _LOCAL,
            {"Host": "127.0.0.1:8765", "X-Forwarded-Host": "nanobot.example"},
        )
        is False
    )
    assert (
        is_local_browser_request(
            _LOCAL,
            {"Host": "127.0.0.1:8765", "Forwarded": "for=203.0.113.42;host=nanobot.example"},
        )
        is False
    )


def test_wildcard_host_without_auth_raises_on_startup(bus: MagicMock) -> None:
    import pytest
    from pydantic_core import ValidationError

    with pytest.raises(ValidationError, match="token"):
        _ch(bus, host="0.0.0.0")


def test_wildcard_host_with_token_is_valid(bus: MagicMock) -> None:
    channel = _ch(bus, host="0.0.0.0", token="my-token")
    assert channel.config.host == "0.0.0.0"


def test_wildcard_host_with_secret_is_valid(bus: MagicMock) -> None:
    channel = _ch(bus, host="0.0.0.0", tokenIssueSecret="s3cret")
    assert channel.config.host == "0.0.0.0"


def test_wildcard_ipv6_without_auth_raises(bus: MagicMock) -> None:
    import pytest
    from pydantic_core import ValidationError

    with pytest.raises(ValidationError, match="token"):
        _ch(bus, host="::")


def test_wildcard_ipv6_with_secret_is_valid(bus: MagicMock) -> None:
    channel = _ch(bus, host="::", tokenIssueSecret="s3cret")
    resp = channel.gateway.http._handle_bootstrap(
        _REMOTE, _FakeReq({"X-Nanobot-Auth": "s3cret"})
    )
    assert resp.status_code == 200


def test_bootstrap_accepts_static_token_as_secret(bus: MagicMock) -> None:
    """When only token (not token_issue_secret) is set, bootstrap accepts it."""
    channel = _ch(bus, host="0.0.0.0", token="static-tok")
    resp = channel.gateway.http._handle_bootstrap(
        _REMOTE, _FakeReq({"Authorization": "Bearer static-tok"})
    )
    assert resp.status_code == 200
    body = json.loads(resp.body)
    assert body["token"].startswith("nbwt_")
    assert body["api_token"].startswith("nbwt_")
    assert body["api_token"] != body["token"]


def test_bootstrap_ws_url_uses_forwarded_https_host(bus: MagicMock) -> None:
    channel = _ch(bus, host="127.0.0.1", port=29931, tokenIssueSecret="s3cret")
    resp = channel.gateway.http._handle_bootstrap(
        _LOCAL,
        _FakeReq(
            {
                "Authorization": "Bearer s3cret",
                "Host": "nanobot.example",
                "X-Forwarded-Proto": "https",
            }
        ),
    )
    assert resp.status_code == 200
    body = json.loads(resp.body)
    assert body["ws_url"] == "wss://nanobot.example/"


def test_bootstrap_without_auth_rejects_remote_requests(bus: MagicMock) -> None:
    channel = _ch(bus, host="127.0.0.1")
    resp = channel.gateway.http._handle_bootstrap(_REMOTE, _NO_HEADERS)
    assert resp.status_code == 403


def test_bootstrap_without_auth_rejects_reverse_proxy_remote_headers(bus: MagicMock) -> None:
    channel = _ch(bus, host="127.0.0.1")
    resp = channel.gateway.http._handle_bootstrap(
        _LOCAL,
        _FakeReq({"Host": "nanobot.example", "X-Forwarded-For": "203.0.113.42"}),
    )
    assert resp.status_code == 403


def test_localhost_without_auth_is_valid(bus: MagicMock) -> None:
    channel = _ch(bus, host="127.0.0.1")
    resp = channel.gateway.http._handle_bootstrap(_LOCAL, _LOCAL_BROWSER_REQ)
    assert resp.status_code == 200
    body = json.loads(resp.body)
    assert body["token"].startswith("nbwt_")
    assert body["api_token"].startswith("nbwt_")
    assert body["api_token"] != body["token"]
    assert not channel.gateway.tokens.check_api_token(
        _FakeReq({"Authorization": f"Bearer {body['token']}"})
    )
    assert channel.gateway.tokens.check_api_token(
        _FakeReq({"Authorization": f"Bearer {body['api_token']}"})
    )


def test_authenticated_bootstrap_returns_distinct_api_token(bus: MagicMock) -> None:
    channel = _ch(bus, host="127.0.0.1", tokenIssueSecret="s3cret")
    resp = channel.gateway.http._handle_bootstrap(
        _LOCAL, _FakeReq({"Authorization": "Bearer s3cret"})
    )
    assert resp.status_code == 200
    body = json.loads(resp.body)
    assert body["token"].startswith("nbwt_")
    assert body["api_token"].startswith("nbwt_")
    assert body["api_token"] != body["token"]
    assert not channel.gateway.tokens.check_api_token(
        _FakeReq({"Authorization": f"Bearer {body['token']}"})
    )
    assert channel.gateway.tokens.check_api_token(
        _FakeReq({"Authorization": f"Bearer {body['api_token']}"})
    )


def test_bootstrap_prefers_runtime_model_name(bus: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "nanobot.webui.ws_http._default_model_name_from_config",
        lambda: "from-disk",
    )
    channel = _ch(bus, host="127.0.0.1", runtime_model_name=lambda: "  live/model  ")
    resp = channel.gateway.http._handle_bootstrap(_LOCAL, _LOCAL_BROWSER_REQ)
    assert resp.status_code == 200
    body = json.loads(resp.body)
    assert body["model_name"] == "live/model"


def test_bootstrap_falls_back_when_runtime_returns_empty(bus: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "nanobot.webui.ws_http._default_model_name_from_config",
        lambda: "from-disk",
    )
    channel = _ch(bus, host="127.0.0.1", runtime_model_name=lambda: "   ")
    resp = channel.gateway.http._handle_bootstrap(_LOCAL, _LOCAL_BROWSER_REQ)
    assert resp.status_code == 200
    body = json.loads(resp.body)
    assert body["model_name"] == "from-disk"


def test_bootstrap_falls_back_when_runtime_raises(bus: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "nanobot.webui.ws_http._default_model_name_from_config",
        lambda: "from-disk",
    )

    def boom():
        raise RuntimeError("resolver failed")

    channel = _ch(bus, host="127.0.0.1", runtime_model_name=boom)
    resp = channel.gateway.http._handle_bootstrap(_LOCAL, _LOCAL_BROWSER_REQ)
    assert resp.status_code == 200
    body = json.loads(resp.body)
    assert body["model_name"] == "from-disk"


def test_bootstrap_rejects_wrong_secret(bus: MagicMock) -> None:
    channel = _ch(bus, host="0.0.0.0", tokenIssueSecret="correct")
    resp = channel.gateway.http._handle_bootstrap(
        _REMOTE, _FakeReq({"Authorization": "Bearer wrong"})
    )
    assert resp.status_code == 401


def test_bootstrap_accepts_remote_with_valid_secret(bus: MagicMock) -> None:
    channel = _ch(bus, host="0.0.0.0", tokenIssueSecret="s3cret")
    resp = channel.gateway.http._handle_bootstrap(
        _REMOTE, _FakeReq({"Authorization": "Bearer s3cret"})
    )
    assert resp.status_code == 200
    body = json.loads(resp.body)
    assert body["token"].startswith("nbwt_")


def test_bootstrap_accepts_x_nanobot_auth_header(bus: MagicMock) -> None:
    channel = _ch(bus, host="0.0.0.0", tokenIssueSecret="s3cret")
    resp = channel.gateway.http._handle_bootstrap(
        _REMOTE, _FakeReq({"X-Nanobot-Auth": "s3cret"})
    )
    assert resp.status_code == 200


def test_bootstrap_secret_also_enforced_on_localhost(bus: MagicMock) -> None:
    """When secret is set, even localhost must provide it (reverse-proxy safety)."""
    channel = _ch(bus, host="0.0.0.0", tokenIssueSecret="s3cret")
    resp = channel.gateway.http._handle_bootstrap(_LOCAL, _NO_HEADERS)
    assert resp.status_code == 401
