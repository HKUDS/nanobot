"""End-to-end tests for the embedded webui's HTTP routes on the WebSocket channel."""

import asyncio
import json
import random
import socket
import time
from contextlib import suppress
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.channels.base import BaseChannel
from nanobot.channels.websocket.runtime import WebSocketChannel, WebSocketConfig
from nanobot.config.loader import load_config, save_config
from nanobot.cron.service import CronService
from nanobot.cron.types import CronJob, CronPayload, CronSchedule
from nanobot.optional_features import InstallResult
from nanobot.security.workspace_access import WORKSPACE_SCOPE_METADATA_KEY
from nanobot.session.keys import UNIFIED_SESSION_KEY
from nanobot.session.manager import Session, SessionManager
from nanobot.session.session_handles import SessionHandleResolver
from nanobot.triggers.local_store import LocalTriggerStore
from nanobot.webui.gateway_services import GatewayServices, build_gateway_services

from .ws_test_client import InProcessHttpChannel
from .ws_test_client import http_get as _http_get

_PORT = 29900


@pytest.fixture(autouse=True)
def _isolate_runtime_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)


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
    channel_runtime_status: Any | None = None,
    mcp_reload: Any | None = None,
    recovery_action: Any | None = None,
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
        channel_runtime_status=channel_runtime_status,
        mcp_reload=mcp_reload,
        recovery_action=recovery_action,
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
    channel_runtime_status: Any | None = None,
    mcp_reload: Any | None = None,
    recovery_action: Any | None = None,
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
        channel_runtime_status=channel_runtime_status,
        mcp_reload=mcp_reload,
        recovery_action=recovery_action,
    )
    return InProcessHttpChannel(cfg, bus, gateway=gateway)


@pytest.fixture()
def bus() -> MagicMock:
    b = MagicMock()
    b.publish_inbound = AsyncMock()
    return b


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
    from nanobot.channels.plugin import ChannelPlugin, load_channel_package

    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)
    requested = channels or ["matrix"]
    matrix = ChannelPlugin(
        name="matrix",
        display_name="Matrix",
        runtime=f"{__name__}:_MatrixChannel",
        dependencies=("matrix-nio>=0.25.2",),
    )
    plugins = {"matrix": matrix}
    if "websocket" in requested:
        websocket = load_channel_package("websocket")
        assert websocket is not None
        plugins["websocket"] = websocket
    monkeypatch.setattr(
        "nanobot.channels.registry.discover_plugins",
        lambda enabled_names=None: {
            name: plugin
            for name, plugin in plugins.items()
            if enabled_names is None or name in enabled_names
        },
    )
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
    channel = _ch(
        bus,
        session_manager=sm,
        port=29901,
        maxMessageBytes=1_048_576,
    )
    server_task = asyncio.create_task(channel.start())
    try:
        resp = await _http_get("http://127.0.0.1:29901/webui/bootstrap")
        assert resp.status_code == 200
        assert resp.headers["Cache-Control"] == "no-store"
        body = resp.json()
        assert body["token"].startswith("nbwt_")
        assert channel.gateway.tokens.issued_token_audiences[body["token"]] == "webui"
        assert body["api_token"].startswith("nbwt_")
        assert body["api_token"] != body["token"]
        assert body["ws_path"] == "/"
        assert body["ws_url"] == "ws://127.0.0.1:29901/"
        assert body["expires_in"] > 0
        assert body["limits"] == {
            "transport": {
                "max_frame_bytes": 1_048_576,
                "envelope_reserve_bytes": 65_536,
            },
            "message": {"max_text_bytes": 65_536},
            "attachments": {
                "max_count": 4,
                "max_file_bytes": 6_291_456,
                "max_total_bytes": 25_165_824,
            },
        }
        assert "max_message_bytes" not in body
        assert isinstance(body.get("model_name"), str)
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_sessions_list_requires_bearer_token(
    bus: MagicMock, tmp_path: Path
) -> None:
    sm = _seed_session(tmp_path, key="websocket:abc")
    channel = _ch(bus, session_manager=sm, port=29902)
    server_task = asyncio.create_task(channel.start())
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

    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_sessions_list_and_thread_restore_transcript_without_canonical_file(
    bus: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    sm = SessionManager(tmp_path / "workspace")
    from nanobot.webui.transcript import append_transcript_object

    key = "websocket:restored-history"
    append_transcript_object(
        key,
        {"event": "user", "chat_id": "restored-history", "text": "original question"},
    )
    append_transcript_object(
        key,
        {"event": "message", "chat_id": "restored-history", "text": "original answer"},
    )
    assert not sm._get_session_path(key).exists()

    port = _free_port()
    channel = _ch(bus, session_manager=sm, port=port)
    server_task = asyncio.create_task(channel.start())
    try:
        token = channel.gateway.tokens.issue_api_token(300)
        auth = {"Authorization": f"Bearer {token}"}

        listing = await _http_get(f"http://127.0.0.1:{port}/api/sessions", headers=auth)
        thread = await _http_get(
            f"http://127.0.0.1:{port}/api/sessions/"
            "websocket%3Arestored-history/webui-thread",
            headers=auth,
        )

        assert listing.status_code == 200
        assert [row["key"] for row in listing.json()["sessions"]] == [key]
        assert listing.json()["sessions"][0]["preview"] == "original question"
        assert thread.status_code == 200
        assert [message["content"] for message in thread.json()["messages"]] == [
            "original question",
            "original answer",
        ]
        assert not sm._get_session_path(key).exists()
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_legacy_session_messages_route_is_not_exposed(
    bus: MagicMock, tmp_path: Path
) -> None:
    sm = _seed_session(tmp_path, key="websocket:legacy")
    channel = _ch(bus, session_manager=sm, port=29919)
    server_task = asyncio.create_task(channel.start())
    try:
        token = channel.gateway.tokens.issue_api_token(300)
        response = await _http_get(
            "http://127.0.0.1:29919/api/sessions/websocket:legacy/messages",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 404
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
    trigger_store.enqueue(trigger.id, "Review PR #4591")
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
        assert job["payload"]["message"] == "Review PR #4591"
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
            "enabled": True,
            "deletable": True,
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
async def test_webui_skill_management_routes(
    bus: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skill_dir = tmp_path / "skills" / "custom-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: custom-skill\ndescription: Custom skill.\n---\n",
        encoding="utf-8",
    )

    def set_enabled(
        workspace: Path,
        name: str,
        *,
        enabled: bool,
        disabled_skills: set[str],
        config_path: Path | None = None,
    ) -> dict[str, Any]:
        assert workspace == tmp_path
        assert name == "custom-skill"
        assert enabled is False
        disabled_skills.add(name)
        return {"name": name, "enabled": enabled, "deleted": False}

    def delete(
        workspace: Path,
        name: str,
        *,
        disabled_skills: set[str],
        config_path: Path | None = None,
    ) -> dict[str, Any]:
        assert workspace == tmp_path
        assert name == "custom-skill"
        disabled_skills.discard(name)
        for child in skill_dir.iterdir():
            child.unlink()
        skill_dir.rmdir()
        return {"name": name, "enabled": False, "deleted": True}

    monkeypatch.setattr("nanobot.webui.ws_http.set_webui_skill_enabled", set_enabled)
    monkeypatch.setattr("nanobot.webui.ws_http.delete_webui_skill", delete)

    port = _free_port()
    channel = _ch(
        bus,
        session_manager=_seed_session(tmp_path),
        workspace_path=tmp_path,
        port=port,
    )
    server_task = asyncio.create_task(channel.start())
    try:
        token = channel.gateway.tokens.issue_api_token(300)
        headers = {"Authorization": f"Bearer {token}"}
        update_response = await _webui_mutate(
            channel,
            "skill.update",
            {"name": "custom-skill", "enabled": False},
            headers=headers,
        )
        assert update_response.status_code == 200
        assert update_response.json()["last_action"]["enabled"] is False
        custom = next(
            item
            for item in update_response.json()["skills"]
            if item["name"] == "custom-skill"
        )
        assert custom["enabled"] is False

        delete_response = await _webui_mutate(
            channel,
            "skill.delete",
            {"name": "custom-skill"},
            headers=headers,
        )
        assert delete_response.status_code == 200
        assert delete_response.json()["last_action"]["deleted"] is True
        assert all(
            item["name"] != "custom-skill"
            for item in delete_response.json()["skills"]
        )
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_webui_skills_marketplace_routes_search_and_install(
    bus: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    search = AsyncMock(return_value={
        "query": "react",
        "install_supported": True,
        "skills": [{
            "id": "acme/agent-skills/react-testing",
            "skill_id": "react-testing",
            "name": "React Testing",
            "source": "acme/agent-skills",
            "installs": 42,
            "url": "https://skills.sh/acme/agent-skills/react-testing",
            "installed": False,
        }],
    })
    trending = AsyncMock(return_value={
        "period": "24h",
        "install_supported": True,
        "skills": [{
            "id": "acme/agent-skills/react-testing",
            "skill_id": "react-testing",
            "name": "React Testing",
            "source": "acme/agent-skills",
            "installs": 12,
            "url": "https://skills.sh/acme/agent-skills/react-testing",
            "installed": False,
            "rank": 1,
        }],
    })
    trends = AsyncMock(return_value={
        "trends": {"acme/agent-skills/react-testing": [2, 4, 3, 8]},
    })

    async def install(
        source: str,
        skill_id: str,
        workspace: Path,
        *,
        provider: str,
        version: str,
    ) -> dict[str, Any]:
        assert source == "acme/agent-skills"
        assert skill_id == "react-testing"
        assert workspace == tmp_path
        assert provider == "skills_sh"
        assert version == ""
        skill_dir = workspace / "skills" / skill_id
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: react-testing\ndescription: Test React apps.\n---\n",
            encoding="utf-8",
        )
        return {"installed": True, "already_installed": False, "name": skill_id}

    install_mock = AsyncMock(side_effect=install)
    monkeypatch.setattr("nanobot.webui.ws_http.search_marketplace_skills", search)
    monkeypatch.setattr("nanobot.webui.ws_http.trending_marketplace_skills", trending)
    monkeypatch.setattr("nanobot.webui.ws_http.marketplace_skill_trends", trends)
    monkeypatch.setattr("nanobot.webui.ws_http.install_marketplace_skill", install_mock)

    port = _free_port()
    channel = _ch(
        bus,
        session_manager=_seed_session(tmp_path),
        workspace_path=tmp_path,
        port=port,
    )
    server_task = asyncio.create_task(channel.start())
    try:
        denied = await _http_get(
            f"http://127.0.0.1:{port}/api/webui/skills/search?q=react"
        )
        assert denied.status_code == 401

        token = channel.gateway.tokens.issue_api_token(300)
        headers = {"Authorization": f"Bearer {token}"}
        search_response = await _http_get(
            f"http://127.0.0.1:{port}/api/webui/skills/search?q=react",
            headers=headers,
        )
        assert search_response.status_code == 200
        assert search_response.json()["skills"][0]["skill_id"] == "react-testing"
        search.assert_awaited_once_with("react", tmp_path, provider="all")

        trending_response = await _http_get(
            f"http://127.0.0.1:{port}/api/webui/skills/trending",
            headers=headers,
        )
        assert trending_response.status_code == 200
        assert trending_response.json()["period"] == "24h"
        trending.assert_awaited_once_with(tmp_path, provider="all")

        trends_response = await _http_get(
            f"http://127.0.0.1:{port}/api/webui/skills/trends"
            "?id=acme%2Fagent-skills%2Freact-testing",
            headers=headers,
        )
        assert trends_response.status_code == 200
        assert trends_response.json()["trends"] == {
            "acme/agent-skills/react-testing": [2, 4, 3, 8],
        }
        trends.assert_awaited_once_with(["acme/agent-skills/react-testing"])

        install_response = await _webui_mutate(
            channel,
            "skill.install",
            {"source": "acme/agent-skills", "skill": "react-testing"},
            headers=headers,
        )
        assert install_response.status_code == 200
        body = install_response.json()
        assert body["last_action"] == {
            "installed": True,
            "already_installed": False,
            "name": "react-testing",
        }
        assert next(
            skill for skill in body["skills"] if skill["name"] == "react-testing"
        )["source"] == "workspace"
        install_mock.assert_awaited_once()
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_webui_skill_install_rejects_overlapping_requests(
    bus: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = asyncio.Event()
    finish = asyncio.Event()

    async def install(
        source: str,
        skill_id: str,
        workspace: Path,
        *,
        provider: str,
        version: str,
    ) -> dict[str, Any]:
        started.set()
        await finish.wait()
        skill_dir = workspace / "skills" / skill_id
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: react-testing\ndescription: Test React apps.\n---\n",
            encoding="utf-8",
        )
        return {"installed": True, "already_installed": False, "name": skill_id}

    install_mock = AsyncMock(side_effect=install)
    monkeypatch.setattr("nanobot.webui.ws_http.install_marketplace_skill", install_mock)
    channel = _ch(
        bus,
        session_manager=_seed_session(tmp_path),
        workspace_path=tmp_path,
        port=_free_port(),
    )
    first = asyncio.create_task(
        _webui_mutate(
            channel,
            "skill.install",
            {"source": "acme/agent-skills", "skill": "react-testing"},
        )
    )
    await started.wait()
    overlapping = await _webui_mutate(
        channel,
        "skill.install",
        {"source": "acme/agent-skills", "skill": "react-testing"},
    )

    assert overlapping.status_code == 409
    assert "already in progress" in overlapping.text
    assert install_mock.await_count == 1

    finish.set()
    completed = await first
    assert completed.status_code == 200
    assert install_mock.await_count == 1


@pytest.mark.asyncio
async def test_webui_skill_delete_remains_local_only(
    bus: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delete = MagicMock()
    policy = MagicMock()
    policy.tools.webui_allow_remote_package_install = True
    monkeypatch.setattr("nanobot.config.loader.load_config", lambda: policy)
    monkeypatch.setattr("nanobot.webui.ws_http.delete_webui_skill", delete)
    channel = _ch(
        bus,
        session_manager=_seed_session(tmp_path),
        workspace_path=tmp_path,
        port=_free_port(),
    )
    response = await _webui_mutate(
        channel,
        "skill.delete",
        {"name": "custom-skill"},
        connection=_REMOTE,
    )

    assert response.status_code == 403
    assert "remote skill deletion is disabled" in response.text
    delete.assert_not_called()


@pytest.mark.asyncio
async def test_webui_skill_install_honors_remote_install_opt_in(
    bus: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def install(
        source: str,
        skill_id: str,
        workspace: Path,
        *,
        provider: str,
        version: str,
    ) -> dict[str, Any]:
        skill_dir = workspace / "skills" / skill_id
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: react-testing\ndescription: Test React apps.\n---\n",
            encoding="utf-8",
        )
        return {"installed": True, "already_installed": False, "name": skill_id}

    monkeypatch.setattr(
        "nanobot.webui.ws_http.install_marketplace_skill",
        AsyncMock(side_effect=install),
    )
    channel = _ch(
        bus,
        session_manager=_seed_session(tmp_path),
        workspace_path=tmp_path,
        port=_free_port(),
    )
    policy = load_config(channel.gateway.settings.config.path)
    policy.tools.webui_allow_remote_package_install = True
    save_config(policy, channel.gateway.settings.config.path)
    response = await _webui_mutate(
        channel,
        "skill.install",
        {"source": "acme/agent-skills", "skill": "react-testing"},
        connection=_REMOTE,
    )

    assert response.status_code == 200
    assert response.json()["last_action"]["name"] == "react-testing"


@pytest.mark.asyncio
async def test_cli_apps_routes_require_token_and_return_payload(
    bus: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def payload(
        *,
        installed_only: bool = False,
        config_path: Path | None = None,
    ) -> dict[str, Any]:
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
        lambda action, query, *, config_path=None: {
            "apps": [],
            "installed_count": 1,
            "catalog_updated_at": "2026-04-18",
            "last_action": {"ok": True, "message": f"{action}:{query['name'][0]}"},
        },
    )
    channel = _ch(bus, session_manager=_seed_session(tmp_path), port=29912)
    server_task = asyncio.create_task(channel.start())
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

        installed = await _webui_mutate(
            channel,
            "settings.cli_app.install",
            {"name": "gimp"},
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

        enabled = await _webui_mutate(
            channel,
            "settings.feature.enable",
            {"name": "matrix"},
        )
        assert enabled.status_code == 200
        body = enabled.json()
        assert body["last_action"]["message"] == "Enabled channel 'matrix'"
        assert body["restart_required_sections"] == ["runtime"]

        disabled_websocket = await _webui_mutate(
            channel,
            "settings.feature.disable",
            {"name": "websocket"},
        )
        assert disabled_websocket.status_code == 400
        assert "cannot be disabled from WebUI" in disabled_websocket.text
        assert "websocket" not in json.loads(config_path.read_text(encoding="utf-8"))["channels"]

        disabled = await _webui_mutate(
            channel,
            "settings.feature.disable",
            {"name": "matrix"},
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
async def test_nanobot_feature_route_reports_live_channel_failure(
    bus: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"channels": {"matrix": {"enabled": True}}}),
        encoding="utf-8",
    )
    _stub_matrix_feature(monkeypatch, config_path, channels=["matrix", "websocket"])
    channel = _ch(
        bus,
        session_manager=_seed_session(tmp_path),
        port=29946,
        channel_runtime_status=lambda: {
            "websocket": {
                "owner": "websocket",
                "instance_id": "default",
                "state": "running",
                "running": True,
            },
            "matrix": {
                "owner": "matrix",
                "instance_id": "default",
                "state": "failed",
                "running": False,
                "error": "Channel failed to start. Check gateway logs.",
            },
        },
    )
    server_task = asyncio.create_task(channel.start())
    try:
        token = channel.gateway.tokens.issue_api_token(300)
        response = await _http_get(
            "http://127.0.0.1:29946/api/settings/nanobot-features",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        body = response.json()
        matrix = next(feature for feature in body["features"] if feature["name"] == "matrix")
        assert matrix["enabled"] is True
        assert matrix["running"] is False
        assert matrix["ready"] is False
        assert matrix["runtime_status"] == "failed"
        assert matrix["runtime_error"] == "Channel failed to start. Check gateway logs."
        assert body["enabled_count"] == 1
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

    approved_response = await _webui_mutate(
        channel,
        "settings.pairing.approve",
        {"code": "ABCD-EFGH"},
    )
    assert approved_response.status_code == 200
    body = approved_response.json()
    assert body["last_action"]["action"] == "approve"
    assert body["last_action"]["sender_id"] == "ou_123"
    assert approved == ["ABCD-EFGH"]

    denied_action = await _webui_mutate(
        channel,
        "settings.pairing.deny",
        {"code": "ABCD-EFGH"},
    )
    assert denied_action.status_code == 200
    assert denied_action.json()["last_action"]["action"] == "deny"
    assert denied == ["ABCD-EFGH"]

    missing_code = await _webui_mutate(
        channel,
        "settings.pairing.approve",
    )
    assert missing_code.status_code == 400
    assert "Missing pairing code" in missing_code.text


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
    blocked = await _webui_mutate(
        channel,
        "settings.feature.enable",
        {"name": "matrix"},
        connection=_REMOTE,
    )

    assert blocked.status_code == 403
    assert "remote WebUI is disabled" in blocked.text
    assert install_calls == []

    config_path.write_text(
        json.dumps({"tools": {"webuiAllowRemotePackageInstall": True}}),
        encoding="utf-8",
    )

    allowed = await _webui_mutate(
        channel,
        "settings.feature.enable",
        {"name": "matrix"},
        connection=_REMOTE,
    )

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
    response = await _webui_mutate(
        channel,
        "settings.feature.enable",
        {"name": "matrix"},
    )

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
    calls: list[tuple[str, str, str | None]] = []

    async def channel_feature_action(
        action: str,
        name: str,
        instance_id: str | None,
    ) -> dict[str, Any]:
        calls.append((action, name, instance_id))
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
    response = await _webui_mutate(
        channel,
        "settings.feature.enable",
        {"name": "matrix"},
    )

    assert response.status_code == 200
    body = response.json()
    assert calls == [("enable", "matrix", None)]
    assert body["requires_restart"] is False
    assert body["restart_required_sections"] == []
    assert body["last_action"]["hot_reload"] is True
    assert body["last_action"]["message"].endswith("Matrix channel applied without restart.")


@pytest.mark.asyncio
async def test_channel_connect_runtime_import_error_is_not_reported_as_unsupported(
    bus: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenConnector:
        async def handle(self, _action: str, _query: dict[str, list[str]]) -> dict[str, Any]:
            raise ImportError("missing optional sdk")

    class FakePlugin:
        @staticmethod
        def load_connector() -> BrokenConnector:
            return BrokenConnector()

    monkeypatch.setattr(
        "nanobot.webui.settings_routes.load_channel_plugin",
        lambda _name: FakePlugin(),
    )
    channel = _ch(bus, session_manager=_seed_session(tmp_path), port=_free_port())
    response = await _webui_mutate(
        channel,
        "settings.channel.connect.start",
        {"channel": "fake"},
    )

    assert response.status_code == 500
    assert "failed to start fake connection" in response.text


@pytest.mark.asyncio
async def test_feishu_connect_routes_write_config_and_hot_reload(
    bus: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nanobot.channels.feishu import runtime as feishu_module
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
        lambda _action, _query, *, allow_install=True, config_path=None: {
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
    calls: list[tuple[str, str, str]] = []

    async def channel_feature_action(action: str, name: str, instance_id: str) -> dict[str, Any]:
        calls.append((action, name, instance_id))
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
    started = await _webui_mutate(
        channel,
        "settings.channel.connect.start",
        {"channel": "feishu", "domain": "feishu", "instance_id": "default"},
    )

    assert started.status_code == 200
    start_body = started.json()
    assert start_body["status"] == "pending"
    assert start_body["instance_id"] == "default"
    assert start_body["qr_url"].startswith("https://accounts.feishu.cn/")

    polled = await _webui_mutate(
        channel,
        "settings.channel.connect.poll",
        {"channel": "feishu", "session_id": start_body["session_id"]},
    )

    assert polled.status_code == 200
    body = polled.json()
    assert body["status"] == "succeeded"
    assert body["instance_id"] == "default"
    assert "app_secret" not in body
    assert calls == [("enable", "feishu", "default")]
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
    from nanobot.channels.feishu import runtime as feishu_module
    from nanobot.channels.feishu.connect import FeishuConnectStore
    from nanobot.config import loader

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

    duplicate_started = store.start(mode="create")
    duplicate_polled = store.poll(duplicate_started["session_id"])
    duplicate_instances = json.loads(config_path.read_text(encoding="utf-8"))[
        "channels"
    ]["feishu"]["instances"]

    assert duplicate_polled["instance_id"] == polled["instance_id"]
    assert len(duplicate_instances) == 2


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
        config_path: Path | None = None,
    ) -> dict[str, Any]:
        assert action == "enable"
        assert query == {"name": ["discord"], "instance_id": ["default"]}
        cfg = loader.load_config()
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
    calls: list[tuple[str, str, str]] = []

    async def channel_feature_action(action: str, name: str, instance_id: str) -> dict[str, Any]:
        calls.append((action, name, instance_id))
        cfg = loader.load_config()
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
    response = await _webui_mutate(
        channel,
        "settings.channel.configure",
        {
            "name": "discord",
            "enable": True,
            "values": {
                "channels.discord.token": "discord-token",
                "channels.discord.allowChannels": "123, 456",
                "channels.discord.groupPolicy": "open",
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["saved"] is True
    assert body["name"] == "discord"
    assert "discord-token" not in response.text
    assert calls == [("enable", "discord", "default")]
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
    response = await _webui_mutate(
        channel,
        "settings.channel.configure",
        {
            "name": "discord",
            "values": {
                "channels.discord.token": "",
                "channels.discord.allowChannels": "new-channel",
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["saved_keys"] == ["channels.discord.allowChannels"]
    discord = next(
        feature
        for feature in body["nanobot_features"]["features"]
        if feature["name"] == "discord"
    )
    assert discord["configured"] is True
    assert discord["config_values"]["channels.discord.allowChannels"] == "new-channel"
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
    response = await _webui_mutate(
        channel,
        "settings.channel.configure",
        {
            "name": "matrix",
            "values": {
                "channels.matrix.accessToken": "",
                "channels.matrix.deviceId": "DEVICE-ID",
            },
        },
    )

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
    response = await _webui_mutate(
        channel,
        "settings.channel.configure",
        {
            "name": "mattermost",
            "values": {
                "channels.mattermost.serverUrl": "https://chat.example.com",
                "channels.mattermost.token": "mattermost-token",
                "channels.mattermost.teamId": "platform",
            },
        },
    )

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
    forwarded_headers = {
        "Host": "nanobot.example",
        "X-Forwarded-For": "203.0.113.42",
    }
    blocked = await _webui_mutate(
        channel,
        "settings.feature.enable",
        {"name": "matrix"},
        headers=forwarded_headers,
    )

    assert blocked.status_code == 403
    assert install_calls == []

    config_path.write_text(
        json.dumps({"tools": {"webuiAllowRemotePackageInstall": True}}),
        encoding="utf-8",
    )

    allowed = await _webui_mutate(
        channel,
        "settings.feature.enable",
        {"name": "matrix"},
        headers=forwarded_headers,
    )

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
    response = await _webui_mutate(
        channel,
        "settings.feature.enable",
        {"name": "matrix"},
        connection=_REMOTE,
    )

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
    response = await _webui_mutate(
        channel,
        "settings.feature.disable",
        {"name": "matrix"},
        connection=_REMOTE,
    )

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

    async def slow_payload(
        *,
        installed_only: bool = False,
        config_path: Path | None = None,
    ) -> dict[str, Any]:
        assert installed_only is False
        entered.set()
        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(release.wait(), 2.0)
        return {"apps": [], "installed_count": 0, "catalog_updated_at": None}

    monkeypatch.setattr("nanobot.webui.settings_routes.cli_apps_payload", slow_payload)
    channel = _ch(bus, session_manager=_seed_session(tmp_path), port=29935)
    server_task = asyncio.create_task(channel.start())
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

    async def payload(
        *,
        installed_only: bool = False,
        config_path: Path | None = None,
    ) -> dict[str, Any]:
        calls.append(installed_only)
        return {"apps": [], "installed_count": 0, "catalog_updated_at": None}

    monkeypatch.setattr("nanobot.webui.settings_routes.cli_apps_payload", payload)
    channel = _ch(bus, session_manager=_seed_session(tmp_path), port=29936)
    server_task = asyncio.create_task(channel.start())
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
        lambda **_kwargs: {
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

    def _mcp_preset_action(
        action: str,
        query: dict[str, list[str]],
        *,
        config_path: Path | None = None,
    ) -> dict[str, Any]:
        preset_queries.append((action, query))
        return {
            "presets": [],
            "installed_count": 1,
            "requires_restart": action != "test",
            "last_action": {"ok": True, "message": f"{action}:{query['name'][0]}"},
        }

    def _custom_action(
        action: str,
        query: dict[str, list[str]],
        *,
        config_path: Path | None = None,
    ) -> dict[str, Any]:
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

    async def _hot_reload():
        return {"ok": True, "message": "MCP config reloaded.", "requires_restart": False}

    channel = _ch(
        bus,
        session_manager=_seed_session(tmp_path),
        port=29913,
        mcp_reload=_hot_reload,
    )
    server_task = asyncio.create_task(channel.start())
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

        enabled = await _webui_mutate(
            channel,
            "settings.mcp.enable",
            {"name": "browserbase", "browserbase_api_key": "bb_live_secret"},
        )
        assert enabled.status_code == 200
        assert preset_queries[-1][1]["browserbase_api_key"] == ["bb_live_secret"]
        body = enabled.json()
        assert "bb_live_secret" not in enabled.text
        assert body["last_action"]["message"] == "enable:browserbase MCP config reloaded."
        assert body["hot_reload"]["ok"] is True
        assert body["restart_required_sections"] == []

        disabled = await _webui_mutate(
            channel,
            "settings.mcp.disable",
            {"name": "browserbase"},
        )
        assert disabled.status_code == 200
        assert preset_queries[-1][0] == "disable"

        custom = await _webui_mutate(
            channel,
            "settings.mcp.custom",
            {"name": "docs", "command": "npx"},
        )
        assert custom.status_code == 200
        assert custom_queries[-1][1]["command"] == ["npx"]
        assert custom.json()["last_action"]["message"] == "custom:docs MCP config reloaded."

        imported = await _webui_mutate(
            channel,
            "settings.mcp.import",
            {"config": "{}"},
        )
        assert imported.status_code == 200
        assert imported.json()["last_action"]["message"] == "import:config MCP config reloaded."

        tools = await _webui_mutate(
            channel,
            "settings.mcp.tools",
            {"name": "docs", "enabled_tools": []},
        )
        assert tools.status_code == 200
        assert tools.json()["last_action"]["message"] == "tools:docs MCP config reloaded."
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_sessions_list_only_returns_websocket_sessions_by_default(
    bus: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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
    project = tmp_path / "project"
    project.mkdir()
    scoped = sm.get_or_create("websocket:beta")
    scoped.metadata[WORKSPACE_SCOPE_METADATA_KEY] = {
        "project_path": str(project),
        "access_mode": "restricted",
    }
    sm.save(scoped)

    channel = _ch(bus, session_manager=sm, workspace_path=tmp_path, port=29906)
    server_task = asyncio.create_task(channel.start())
    try:
        token = channel.gateway.tokens.issue_api_token(300)
        auth = {"Authorization": f"Bearer {token}"}

        listing = await _http_get(
            "http://127.0.0.1:29906/api/sessions", headers=auth
        )
        assert listing.status_code == 200
        sessions = listing.json()["sessions"]
        keys = {s["key"] for s in sessions}
        # Only websocket-channel sessions are part of the webui surface; CLI /
        # Slack / Lark rows would be non-resumable from the browser.
        assert keys == {"websocket:alpha", "websocket:beta"}
        rows = {row["key"]: row for row in sessions}
        handles = {
            handle.session_key: handle
            for handle in SessionHandleResolver(sm).list_all()
        }
        assert rows["websocket:alpha"]["handle"] == handles[
            "websocket:alpha"
        ].public_payload()
        assert rows["websocket:beta"]["handle"] == handles[
            "websocket:beta"
        ].public_payload()
        assert rows["websocket:beta"]["workspace_scope"]["project_path"] == str(
            project.resolve()
        )
        assert rows["websocket:beta"]["workspace_scope"]["access_mode"] == "restricted"
        assert all(not any(key.startswith("_") for key in row) for row in sessions)
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
            "session_order": ["websocket:old", "websocket:sidebar"],
            "title_overrides": {"websocket:sidebar": "Pinned work"},
            "view": {"density": "compact", "show_archived": True},
        }
        updated = await _webui_mutate(
            channel,
            "sidebar.update",
            {"state": payload},
        )
        assert updated.status_code == 200
        body = updated.json()
        assert body["pinned_keys"] == ["websocket:sidebar"]
        assert body["session_order"] == ["websocket:old", "websocket:sidebar"]
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
    try:
        path = sm._get_session_path("websocket:doomed")
        assert path.exists()
        webui_path = tmp_path / "webui" / f"{SessionManager.safe_key('websocket:doomed')}.jsonl"
        assert webui_path.is_file()
        resp = await _webui_mutate(
            channel,
            "session.delete",
            {"key": "websocket:doomed"},
        )
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True
        assert not path.exists()
        assert not webui_path.exists()
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_session_delete_removes_transcript_without_canonical_file(
    bus: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    sm = SessionManager(tmp_path / "workspace")
    from nanobot.webui.transcript import append_transcript_object

    key = "websocket:transcript-only"
    append_transcript_object(
        key,
        {"event": "user", "chat_id": "transcript-only", "text": "recover me"},
    )
    assert not sm._get_session_path(key).exists()
    webui_path = tmp_path / "webui" / f"{SessionManager.safe_key(key)}.jsonl"
    assert webui_path.is_file()

    channel = _ch(bus, session_manager=sm, port=_free_port())
    server_task = asyncio.create_task(channel.start())
    try:
        response = await _webui_mutate(
            channel,
            "session.delete",
            {"key": key},
        )

        assert response.status_code == 200
        assert response.json()["deleted"] is True
        assert not webui_path.exists()
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_session_delete_removes_unpersisted_new_chat(
    bus: MagicMock, tmp_path: Path
) -> None:
    sm = SessionManager(tmp_path / "sessions")
    project = tmp_path / "project"
    project.mkdir()
    channel = _ch(bus, session_manager=sm, workspace_path=tmp_path, port=_free_port())
    connection = AsyncMock()
    connection.remote_address = ("127.0.0.1", 50123)

    await channel._dispatch_envelope(
        connection,
        "webui-client",
        {
            "type": "new_chat",
            "workspace_scope": {
                "project_path": str(project),
                "access_mode": "full",
            },
        },
    )

    attached = next(
        payload
        for payload in (
            json.loads(call.args[0]) for call in connection.send.await_args_list
        )
        if payload.get("event") == "attached"
    )
    key = f"websocket:{attached['chat_id']}"

    assert sm.list_sessions() == []
    assert channel.gateway.workspaces.scope_for_session_key(key).project_path == project.resolve()

    response = await _webui_mutate(channel, "session.delete", {"key": key})

    assert response.status_code == 200
    assert response.json()["deleted"] is True
    assert channel.gateway.workspaces.scope_for_session_key(key).project_path == tmp_path.resolve()


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

        updated = await _webui_mutate(
            channel,
            "automation.update",
            {
                "id": user_job.id,
                "values": {
                    "name": "Daily quiz",
                    "message": "Ask the daily quiz",
                    "schedule": {
                        "kind": "cron",
                        "expr": "0 9 * * *",
                        "tz": "UTC",
                    },
                },
            },
        )
        assert updated.status_code == 200
        by_id = {job["id"]: job for job in updated.json()["jobs"]}
        assert by_id[user_job.id]["name"] == "Daily quiz"
        assert by_id[user_job.id]["payload"]["message"] == "Ask the daily quiz"
        assert by_id[user_job.id]["schedule"]["kind"] == "cron"
        assert by_id[user_job.id]["schedule"]["expr"] == "0 9 * * *"
        assert by_id[user_job.id]["schedule"]["tz"] == "UTC"

        unicode_update = await _webui_mutate(
            channel,
            "automation.update",
            {
                "id": user_job.id,
                "values": {"name": "每日测验", "message": "问今日测验"},
            },
        )
        assert unicode_update.status_code == 200
        assert cron.get_job(user_job.id).name == "每日测验"
        assert cron.get_job(user_job.id).payload.message == "问今日测验"

        malformed_update = await _webui_mutate(
            channel,
            "automation.update",
            {"id": user_job.id, "values": {"message": ["bad"]}},
        )
        assert malformed_update.status_code == 400
        assert cron.get_job(user_job.id).payload.message == "问今日测验"

        invalid_cron_update = await _webui_mutate(
            channel,
            "automation.update",
            {
                "id": user_job.id,
                "values": {
                    "schedule": {"kind": "cron", "expr": "not a cron", "tz": "UTC"}
                },
            },
        )
        assert invalid_cron_update.status_code == 400
        assert cron.get_job(user_job.id).schedule.expr == "0 9 * * *"

        past_one_shot_update = await _webui_mutate(
            channel,
            "automation.update",
            {
                "id": past_one_shot_job.id,
                "values": {
                    "message": "Updated one-shot message",
                    "schedule": {"kind": "at", "at_ms": 1},
                },
            },
        )
        assert past_one_shot_update.status_code == 200
        assert cron.get_job(past_one_shot_job.id).payload.message == "Updated one-shot message"
        assert cron.get_job(past_one_shot_job.id).schedule.at_ms == 1

        protected_update = await _webui_mutate(
            channel,
            "automation.update",
            {"id": "heartbeat", "values": {"name": "bad"}},
        )
        assert protected_update.status_code == 403

        disabled = await _webui_mutate(
            channel,
            "automation.disable",
            {"id": user_job.id},
        )
        assert disabled.status_code == 200
        by_id = {job["id"]: job for job in disabled.json()["jobs"]}
        assert by_id[user_job.id]["enabled"] is False

        disabled_run = await _webui_mutate(
            channel,
            "automation.run",
            {"id": user_job.id},
        )
        assert disabled_run.status_code == 409

        unbound_run = await _webui_mutate(
            channel,
            "automation.run",
            {"id": incomplete_job.id},
        )
        assert unbound_run.status_code == 409
        assert "no linked chat" in unbound_run.text

        unbound_enable = await _webui_mutate(
            channel,
            "automation.enable",
            {"id": incomplete_job.id},
        )
        assert unbound_enable.status_code == 409
        assert "no linked chat" in unbound_enable.text

        protected_delete = await _webui_mutate(
            channel,
            "automation.delete",
            {"id": "heartbeat"},
        )
        assert protected_delete.status_code == 403
        protected_disable = await _webui_mutate(
            channel,
            "automation.disable",
            {"id": "heartbeat"},
        )
        assert protected_disable.status_code == 403
        protected_run = await _webui_mutate(
            channel,
            "automation.run",
            {"id": "heartbeat"},
        )
        assert protected_run.status_code == 403

        enabled = await _webui_mutate(
            channel,
            "automation.enable",
            {"id": user_job.id},
        )
        assert enabled.status_code == 200
        by_id = {job["id"]: job for job in enabled.json()["jobs"]}
        assert by_id[user_job.id]["enabled"] is True

        deleted = await _webui_mutate(
            channel,
            "automation.delete",
            {"id": user_job.id},
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
    try:
        token = channel.gateway.tokens.issue_api_token(300)
        auth = {"Authorization": f"Bearer {token}"}

        listed = await _http_get(f"{base_url}/api/webui/automations", headers=auth)
        assert listed.status_code == 200
        by_id = {job["id"]: job for job in listed.json()["jobs"]}
        assert by_id[trigger.id]["kind"] == "local_trigger"
        assert by_id[trigger.id]["state"]["pending"] is True
        assert by_id[trigger.id]["payload"]["message"] == "Review queued PR"
        assert by_id[trigger.id]["trigger"]["command"] == f'nanobot trigger {trigger.id} "message"'

        disabled = await _webui_mutate(
            channel,
            "automation.disable",
            {"id": trigger.id},
        )
        assert disabled.status_code == 200
        stored = trigger_store.get(trigger.id)
        assert stored is not None
        assert stored.enabled is False

        run = await _webui_mutate(
            channel,
            "automation.run",
            {"id": trigger.id},
        )
        assert run.status_code == 409
        assert "CLI message" in run.text

        renamed = await _webui_mutate(
            channel,
            "automation.update",
            {"id": trigger.id, "values": {"name": "Release review"}},
        )
        assert renamed.status_code == 200
        stored = trigger_store.get(trigger.id)
        assert stored is not None
        assert stored.name == "Release review"

        bad_update = await _webui_mutate(
            channel,
            "automation.update",
            {"id": trigger.id, "values": {"message": "coupled"}},
        )
        assert bad_update.status_code == 400

        deleted = await _webui_mutate(
            channel,
            "automation.delete",
            {"id": trigger.id},
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
    try:
        path = sm._get_session_path("websocket:doomed")
        resp = await _webui_mutate(
            channel,
            "session.delete",
            {"key": "websocket:doomed"},
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
    try:
        blocked = await _webui_mutate(
            channel,
            "session.delete",
            {"key": "websocket:doomed"},
        )
        assert blocked.status_code == 200
        assert blocked.json()["blocked_by_automations"] is True
        assert trigger_store.get(trigger.id) is not None

        deleted = await _webui_mutate(
            channel,
            "session.delete",
            {"key": "websocket:doomed", "delete_automations": True},
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
    try:
        path = sm._get_session_path("websocket:doomed")
        resp = await _webui_mutate(
            channel,
            "session.delete",
            {"key": "websocket:doomed", "delete_automations": True},
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
    try:
        path = sm._get_session_path("websocket:doomed")
        resp = await _webui_mutate(
            channel,
            "session.delete",
            {"key": "websocket:doomed"},
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
async def test_session_delete_action_accepts_websocket_keys(
    bus: MagicMock, tmp_path: Path
) -> None:
    sm = _seed_session(tmp_path, key="websocket:encoded-key")
    channel = _ch(bus, session_manager=sm, port=29910)
    server_task = asyncio.create_task(channel.start())
    try:
        path = sm._get_session_path("websocket:encoded-key")
        assert path.exists()
        deleted = await _webui_mutate(
            channel,
            "session.delete",
            {"key": "websocket:encoded-key"},
        )
        assert deleted.status_code == 200
        assert deleted.json()["deleted"] is True
        assert not path.exists()
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

    monkeypatch.setattr("nanobot.webui.media_gateway.get_media_dir", fake_media_dir)

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

        repeated = await _http_get(
            "http://127.0.0.1:29914/api/sessions/websocket:video-replay/webui-thread",
            headers=auth,
        )
        repeated_assistant = next(
            m for m in repeated.json()["messages"] if m["role"] == "assistant"
        )
        assert repeated_assistant["id"] == assistant["id"]
        assert repeated_assistant["media"][0]["url"] == media[0]["url"]
        assert len(list(websocket_media.iterdir())) == 1

        fetched = await _http_get(f"http://127.0.0.1:29914{media[0]['url']}")
        assert fetched.status_code == 200
        assert fetched.content == b"video"
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_sessions_list_negotiates_gzip_across_repeated_headers(
    bus: MagicMock, tmp_path: Path
) -> None:
    sm = _seed_many(tmp_path, [f"websocket:gzip-{index:03d}" for index in range(80)])
    port = _free_port()
    channel = _ch(bus, session_manager=sm, workspace_path=tmp_path, port=port)
    server_task = asyncio.create_task(channel.start())
    try:
        token = channel.gateway.tokens.issue_api_token(300)
        response = await _http_get(
            f"http://127.0.0.1:{port}/api/sessions",
            headers=[
                ("Authorization", f"Bearer {token}"),
                ("Accept-Encoding", "identity;q=0"),
                ("Accept-Encoding", "gzip"),
            ],
        )

        assert response.status_code == 200
        assert response.headers["Content-Encoding"] == "gzip"
        assert response.headers["Vary"] == "Accept-Encoding"
        assert len(response.json()["sessions"]) == 80
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_webui_thread_complete_transcript_skips_session_history_read(
    bus: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nanobot.webui.transcript import append_transcript_object

    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:fast-thread"
    sm = _seed_session(tmp_path, key=key)
    for event in (
        {"event": "user", "chat_id": "fast-thread", "text": "hi"},
        {"event": "message", "chat_id": "fast-thread", "text": "hello back"},
        {"event": "turn_end", "chat_id": "fast-thread"},
    ):
        append_transcript_object(key, event)

    read_session_file = MagicMock(
        side_effect=AssertionError("complete transcripts must not read canonical history")
    )
    monkeypatch.setattr(sm, "read_session_file", read_session_file)
    port = _free_port()
    channel = _ch(
        bus,
        session_manager=sm,
        workspace_path=tmp_path,
        port=port,
    )
    server_task = asyncio.create_task(channel.start())
    try:
        token = channel.gateway.tokens.issue_api_token(300)
        response = await _http_get(
            f"http://127.0.0.1:{port}/api/sessions/"
            "websocket%3Afast-thread/webui-thread?limit=160&direction=latest",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        assert [message["content"] for message in response.json()["messages"]] == [
            "hi",
            "hello back",
        ]
        read_session_file.assert_not_called()
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_webui_thread_negotiates_gzip_for_large_payloads(
    bus: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nanobot.webui.transcript import append_transcript_object

    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    sm = SessionManager(tmp_path)
    append_transcript_object(
        "websocket:gzip-thread",
        {
            "event": "user",
            "chat_id": "gzip-thread",
            "text": "compress me " * 1_000,
        },
    )
    port = _free_port()
    channel = _ch(bus, session_manager=sm, workspace_path=tmp_path, port=port)
    server_task = asyncio.create_task(channel.start())
    try:
        token = channel.gateway.tokens.issue_api_token(300)
        url = (
            f"http://127.0.0.1:{port}/api/sessions/"
            "websocket%3Agzip-thread/webui-thread?limit=80&direction=latest"
        )
        compressed = await _http_get(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept-Encoding": "br, gzip",
            },
        )

        assert compressed.status_code == 200
        assert compressed.headers["Content-Encoding"] == "gzip"
        assert compressed.headers["Vary"] == "Accept-Encoding"
        assert int(compressed.headers["Content-Length"]) < len(compressed.content)
        assert compressed.json()["messages"][0]["content"].startswith("compress me")

        identity = await _http_get(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept-Encoding": "gzip;q=0, br",
            },
        )
        assert identity.status_code == 200
        assert "Content-Encoding" not in identity.headers
        assert identity.json() == compressed.json()

        unauthorized = await _http_get(url, headers={"Accept-Encoding": "gzip"})
        assert unauthorized.status_code == 401
        assert "Content-Encoding" not in unauthorized.headers
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_session_delete_rejects_non_websocket_keys(
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
    try:
        token = channel.gateway.tokens.issue_api_token(300)
        auth = {"Authorization": f"Bearer {token}"}

        doomed = sm._get_session_path("slack:C123")
        assert doomed.exists()
        get_delete = await _http_get(
            "http://127.0.0.1:29909/api/sessions/slack:C123/delete",
            headers=auth,
        )
        assert get_delete.status_code == 405

        deny_delete = await _webui_mutate(
            channel,
            "session.delete",
            {"key": "slack:C123"},
        )
        assert deny_delete.status_code == 404
        assert doomed.exists()
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_session_delete_rejects_invalid_key(
    bus: MagicMock, tmp_path: Path
) -> None:
    sm = _seed_session(tmp_path)
    channel = _ch(bus, session_manager=sm, port=29904)
    server_task = asyncio.create_task(channel.start())
    try:
        # Invalid characters in the key -> regex match fails -> 404
        # (route doesn't match, falls through to channel 404).
        resp = await _webui_mutate(
            channel,
            "session.delete",
            {"key": "bad key"},
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


async def _webui_mutate(
    channel: WebSocketChannel,
    action: str,
    payload: dict[str, Any] | None = None,
    *,
    headers: dict[str, str] | None = None,
    connection: _FakeConn = _LOCAL,
) -> httpx.Response:
    request_headers = {"Host": "127.0.0.1:8765", **(headers or {})}
    mutation_connection = _FakeConn(connection.remote_address)
    mutation_connection.request = _FakeReq(request_headers)
    response = await channel.gateway.http.dispatch_webui_mutation(
        mutation_connection,
        action,
        payload or {},
    )
    request = httpx.Request("GET", "http://127.0.0.1/webui-mutation")
    return httpx.Response(
        response.status_code,
        headers=list(response.headers.raw_items()),
        content=response.body,
        request=request,
    )


@pytest.mark.asyncio
async def test_recovery_mutation_uses_authenticated_websocket_action(bus: MagicMock) -> None:
    recovery_action = AsyncMock(return_value={
        "status": "resuming",
        "recovery_id": "recovery-1",
    })
    channel = _ch(bus, recovery_action=recovery_action)

    response = await _webui_mutate(
        channel,
        "recovery.continue",
        {"chat_id": "chat-1", "recovery_id": "recovery-1"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "resuming"
    recovery_action.assert_awaited_once_with(
        "continue",
        {"chat_id": "chat-1", "recovery_id": "recovery-1"},
    )


@pytest.mark.asyncio
async def test_workspace_folder_picker_is_local_authenticated_mutation(
    bus: MagicMock,
    tmp_path: Path,
    monkeypatch,
) -> None:
    selected = tmp_path / "project"
    selected.mkdir()
    pick_folder = AsyncMock(return_value=str(selected))
    monkeypatch.setattr(
        "nanobot.webui.ws_http.native_folder_picker_available",
        lambda: True,
    )
    monkeypatch.setattr("nanobot.webui.ws_http.pick_native_folder", pick_folder)
    channel = _ch(bus)

    response = await _webui_mutate(channel, "workspace.pick_folder")

    assert response.status_code == 200
    assert response.json() == {"path": str(selected)}
    pick_folder.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_workspace_folder_picker_rejects_direct_http(
    bus: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pick_folder = AsyncMock(return_value="/tmp")
    monkeypatch.setattr(
        "nanobot.webui.ws_http.native_folder_picker_available",
        lambda: True,
    )
    monkeypatch.setattr("nanobot.webui.ws_http.pick_native_folder", pick_folder)
    channel = _ch(bus)

    response = await channel.gateway.http.dispatch(
        _LOCAL,
        _FakeReq(
            {"Host": "127.0.0.1:8765"},
            path="/api/workspaces/pick-folder",
        ),
    )

    assert response is not None
    assert response.status_code == 405
    assert b"authenticated WebSocket" in response.body
    pick_folder.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("connection", "host"),
    [(_REMOTE, "127.0.0.1"), (_LOCAL, "0.0.0.0")],
)
async def test_workspace_folder_picker_rejects_nonlocal_surfaces(
    bus: MagicMock,
    monkeypatch,
    connection: _FakeConn,
    host: str,
) -> None:
    pick_folder = AsyncMock(return_value="/tmp")
    monkeypatch.setattr(
        "nanobot.webui.ws_http.native_folder_picker_available",
        lambda: True,
    )
    monkeypatch.setattr("nanobot.webui.ws_http.pick_native_folder", pick_folder)
    channel = _ch(bus, host=host, token="test-token" if host == "0.0.0.0" else "")

    response = await _webui_mutate(
        channel,
        "workspace.pick_folder",
        connection=connection,
    )

    assert response.status_code == 403
    pick_folder.assert_not_awaited()


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


def _trusted_proxy_config(
    cidrs: list[str] | None = None,
    *,
    assertion_header: str = "Cf-Access-Jwt-Assertion",
) -> dict[str, Any]:
    return {
        "trustedProxyAuth": {
            "trustedPeerCidrs": cidrs or ["127.0.0.1/32"],
            "assertionHeader": assertion_header,
        }
    }


def test_trusted_proxy_requires_non_empty_assertion(bus: MagicMock) -> None:
    channel = _ch(bus, **_trusted_proxy_config())
    for assertion in (None, "", "   "):
        headers = {"Cf-Access-Jwt-Assertion": assertion} if assertion is not None else {}
        resp = channel.gateway.http._handle_bootstrap(_LOCAL, _FakeReq(headers))
        assert resp.status_code == 403


def test_trusted_proxy_rejects_untrusted_peer_spoof(bus: MagicMock) -> None:
    channel = _ch(bus, **_trusted_proxy_config())
    resp = channel.gateway.http._handle_bootstrap(
        _REMOTE,
        _FakeReq({"Cf-Access-Jwt-Assertion": "spoofed"}),
    )
    assert resp.status_code == 403


def test_trusted_proxy_bootstrap_has_no_tokens(
    bus: MagicMock,
) -> None:
    assertion = "opaque-upstream-assertion"
    channel = _ch(bus, **_trusted_proxy_config())
    log = MagicMock()
    channel.gateway.http._log = log
    resp = channel.gateway.http._handle_bootstrap(
        _LOCAL,
        _FakeReq(
            {
                "Host": "nanobot.example",
                "X-Forwarded-For": "203.0.113.42",
                "Forwarded": "for=203.0.113.42;host=nanobot.example",
                "X-Real-IP": "203.0.113.42",
                "X-Forwarded-Host": "nanobot.example",
                "Cf-Access-Jwt-Assertion": assertion,
            }
        ),
    )
    assert resp.status_code == 200
    body = resp.body.decode()
    assert assertion not in body
    assert assertion not in repr(log.mock_calls)
    payload = json.loads(body)
    assert "token" not in payload
    assert "api_token" not in payload
    assert payload["ws_path"] == "/"


@pytest.mark.asyncio
async def test_trusted_proxy_authorizes_rest_without_api_token(bus: MagicMock) -> None:
    channel = _ch(bus, **_trusted_proxy_config())
    response = await channel.gateway.http.dispatch(
        _LOCAL,
        _FakeReq(
            {
                "Host": "nanobot.example",
                "Cf-Access-Jwt-Assertion": "present",
            },
            path="/api/sessions",
        ),
    )
    assert response.status_code == 503


def test_trusted_proxy_authorizes_websocket_without_token(bus: MagicMock) -> None:
    channel = _ch(bus, **_trusted_proxy_config())
    response = channel._authorize_websocket_handshake(
        _LOCAL,
        {},
        {"Cf-Access-Jwt-Assertion": "present"},
    )
    assert response is None
    assert _LOCAL in channel._webui_connections


def test_forwarding_headers_alone_never_authorize_bootstrap(bus: MagicMock) -> None:
    channel = _ch(bus)
    resp = channel.gateway.http._handle_bootstrap(
        _REMOTE,
        _FakeReq(
            {
                "Host": "nanobot.example",
                "X-Forwarded-For": "127.0.0.1",
                "Forwarded": "for=127.0.0.1",
                "X-Real-IP": "127.0.0.1",
            }
        ),
    )
    assert resp.status_code == 403


def test_trusted_proxy_bypasses_bootstrap_secret_and_tokens(bus: MagicMock) -> None:
    channel = _ch(
        bus,
        tokenIssueSecret="route-secret",
        **_trusted_proxy_config(),
    )
    resp = channel.gateway.http._handle_bootstrap(
        _LOCAL,
        _FakeReq({"Cf-Access-Jwt-Assertion": "present"}),
    )
    assert resp.status_code == 200
    payload = json.loads(resp.body)
    assert "token" not in payload
    assert "api_token" not in payload


@pytest.mark.parametrize(
    ("peer", "cidr"),
    [
        ("127.0.0.1", "127.0.0.1/32"),
        ("::1", "::1/128"),
        ("::ffff:127.0.0.1", "127.0.0.0/24"),
        ("127.0.0.1", "::ffff:127.0.0.0/120"),
    ],
)
def test_trusted_proxy_matches_ip_versions_and_mapped_peers(
    bus: MagicMock,
    peer: str,
    cidr: str,
) -> None:
    from nanobot.webui.http_utils import is_trusted_proxy_authenticated_request

    config = WebSocketConfig.model_validate(_trusted_proxy_config([cidr]))
    request = _FakeReq({"Cf-Access-Jwt-Assertion": "present"})
    assert is_trusted_proxy_authenticated_request(_FakeConn((peer, 12345)), request.headers, config)


@pytest.mark.parametrize(
    "cidr",
    ["not-a-cidr", "0.0.0.0/0", "::/0", "::/1", "::ffff:0:0/96"],
)
def test_trusted_proxy_rejects_invalid_or_universal_cidrs(
    cidr: str,
) -> None:
    from pydantic_core import ValidationError

    with pytest.raises(ValidationError):
        WebSocketConfig.model_validate(_trusted_proxy_config([cidr]))

@pytest.mark.parametrize(
    "assertion_header",
    ["Host", "Forwarded", "X-Forwarded-For", "X-Real-IP", "CF-Connecting-IP"],
)
def test_trusted_proxy_rejects_routing_headers(assertion_header: str) -> None:
    from pydantic_core import ValidationError

    with pytest.raises(ValidationError, match="proxy-generated"):
        WebSocketConfig.model_validate(_trusted_proxy_config(assertion_header=assertion_header))

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


def test_wildcard_host_with_trusted_proxy_auth_is_valid(bus: MagicMock) -> None:
    channel = _ch(bus, host="0.0.0.0", **_trusted_proxy_config())
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


def test_bootstrap_ws_url_uses_configured_public_url(bus: MagicMock) -> None:
    channel = _ch(
        bus,
        host="127.0.0.1",
        port=29931,
        tokenIssueSecret="s3cret",
        publicWsUrl="wss://claw.wasapi.xyz/",
    )
    resp = channel.gateway.http._handle_bootstrap(
        _LOCAL,
        _FakeReq(
            {
                "Authorization": "Bearer s3cret",
                "Host": "127.0.0.1:29931",
                "X-Forwarded-Proto": "https",
            }
        ),
    )
    assert resp.status_code == 200
    assert json.loads(resp.body)["ws_url"] == "wss://claw.wasapi.xyz/"


def test_public_ws_url_must_match_configured_path() -> None:
    from pydantic_core import ValidationError

    with pytest.raises(ValidationError, match="public_ws_url path must match path"):
        WebSocketConfig.model_validate(
            {
                "path": "/socket",
                "publicWsUrl": "wss://claw.wasapi.xyz/",
            }
        )


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
        lambda _config_path=None: "from-disk",
    )
    channel = _ch(bus, host="127.0.0.1", runtime_model_name=lambda: "  live/model  ")
    resp = channel.gateway.http._handle_bootstrap(_LOCAL, _LOCAL_BROWSER_REQ)
    assert resp.status_code == 200
    body = json.loads(resp.body)
    assert body["model_name"] == "live/model"


def test_bootstrap_falls_back_when_runtime_returns_empty(bus: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "nanobot.webui.ws_http._default_model_name_from_config",
        lambda _config_path=None: "from-disk",
    )
    channel = _ch(bus, host="127.0.0.1", runtime_model_name=lambda: "   ")
    resp = channel.gateway.http._handle_bootstrap(_LOCAL, _LOCAL_BROWSER_REQ)
    assert resp.status_code == 200
    body = json.loads(resp.body)
    assert body["model_name"] == "from-disk"


def test_bootstrap_falls_back_when_runtime_raises(bus: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "nanobot.webui.ws_http._default_model_name_from_config",
        lambda _config_path=None: "from-disk",
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
