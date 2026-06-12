"""End-to-end tests for the embedded webui's HTTP routes on the WebSocket channel."""

import asyncio
import functools
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import urlencode

import httpx
import pytest

from blackcat.channels.websocket import WebSocketChannel, WebSocketConfig
from blackcat.cron.service import CronService
from blackcat.cron.types import CronJob, CronPayload, CronSchedule
from blackcat.session.keys import UNIFIED_SESSION_KEY
from blackcat.session.manager import Session, SessionManager
from blackcat.webui.gateway_services import GatewayServices, build_gateway_services

_PORT = 29900


def _make_handler(
    cfg: dict[str, Any] | WebSocketConfig,
    bus: Any,
    *,
    session_manager: SessionManager | None = None,
    static_dist_path: Path | None = None,
    workspace_path: Path | None = None,
    runtime_model_name: Any | None = None,
    cron_service: CronService | None = None,
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
        functools.partial(httpx.get, url, headers=headers or {}, timeout=5.0)
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

        # Mint a token via bootstrap, then call the API with it.
        boot = await _http_get("http://127.0.0.1:29902/webui/bootstrap")
        token = boot.json()["token"]
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
    for name, message, to in (
        ("Morning check", "Check the project status", "abc"),
        ("Other session", "Do not show", "other"),
    ):
        cron.add_job(
            name=name,
            schedule=hourly,
            message=message,
            session_key=f"websocket:{to}",
        )
    cron.add_job(
        name="Legacy same target",
        schedule=hourly,
        message="Legacy job should not be treated as bound",
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
        port=29914,
    )
    server_task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)
    try:
        deny = await _http_get(
            "http://127.0.0.1:29914/api/sessions/websocket:abc/automations"
        )
        assert deny.status_code == 401

        boot = await _http_get("http://127.0.0.1:29914/webui/bootstrap")
        token = boot.json()["token"]
        auth = {"Authorization": f"Bearer {token}"}
        resp = await _http_get(
            "http://127.0.0.1:29914/api/sessions/websocket%3Aabc/automations",
            headers=auth,
        )

        assert resp.status_code == 200
        body = resp.json()
        assert [job["name"] for job in body["jobs"]] == ["Morning check"]
        job = body["jobs"][0]
        assert job["schedule"]["kind"] == "every"
        assert job["schedule"]["every_ms"] == 3_600_000
        assert job["payload"]["message"] == "Check the project status"
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
    )
    cron.add_job(
        name="Visible chat job",
        schedule=hourly,
        message="Show for this chat",
        session_key="websocket:abc",
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
        boot = await _http_get("http://127.0.0.1:29917/webui/bootstrap")
        token = boot.json()["token"]
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
            "  blackcat:",
            "    requires:",
            "      bins:",
            "        - definitely-missing-blackcat-skill-cli",
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

        boot = await _http_get("http://127.0.0.1:29920/webui/bootstrap")
        token = boot.json()["token"]
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
            "CLI: definitely-missing-blackcat-skill-cli, "
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
            "bins": ["definitely-missing-blackcat-skill-cli"],
            "env": ["DEFINITELY_MISSING_NANOBOT_SKILL_ENV"],
            "missing_bins": ["definitely-missing-blackcat-skill-cli"],
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
    monkeypatch.setattr(
        "blackcat.webui.settings_routes.cli_apps_payload",
        lambda: {
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
        },
    )
    monkeypatch.setattr(
        "blackcat.webui.settings_routes.cli_apps_action",
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

        boot = await _http_get("http://127.0.0.1:29912/webui/bootstrap")
        token = boot.json()["token"]
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
async def test_mcp_presets_routes_require_token_and_return_payload(
    bus: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "blackcat.webui.mcp_presets_api.mcp_presets_payload",
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
        "blackcat.webui.mcp_presets_api.mcp_presets_action",
        _mcp_preset_action,
    )
    monkeypatch.setattr(
        "blackcat.webui.mcp_presets_api.custom_mcp_action",
        _custom_action,
    )

    async def _hot_reload(_bus):
        return {"ok": True, "message": "MCP config reloaded.", "requires_restart": False}

    monkeypatch.setattr(
        "blackcat.webui.settings_routes.request_mcp_reload",
        _hot_reload,
    )
    channel = _ch(bus, session_manager=_seed_session(tmp_path), port=29913)
    server_task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)
    try:
        deny = await _http_get("http://127.0.0.1:29913/api/settings/mcp-presets")
        assert deny.status_code == 401

        boot = await _http_get("http://127.0.0.1:29913/webui/bootstrap")
        token = boot.json()["token"]
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
        boot = await _http_get("http://127.0.0.1:29906/webui/bootstrap")
        token = boot.json()["token"]
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
    monkeypatch.setattr("blackcat.config.paths.get_data_dir", lambda: tmp_path)
    sm = _seed_session(tmp_path, key="websocket:sidebar")
    channel = _ch(bus, session_manager=sm, port=29911)
    server_task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)
    try:
        boot = await _http_get("http://127.0.0.1:29911/webui/bootstrap")
        token = boot.json()["token"]
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
    monkeypatch.setattr("blackcat.config.paths.get_data_dir", lambda: tmp_path)
    sm = _seed_session(tmp_path, key="websocket:doomed")
    from blackcat.webui.transcript import append_transcript_object

    append_transcript_object("websocket:doomed", {"event": "user", "chat_id": "doomed", "text": "x"})
    channel = _ch(bus, session_manager=sm, port=29903)
    server_task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)
    try:
        boot = await _http_get("http://127.0.0.1:29903/webui/bootstrap")
        token = boot.json()["token"]
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
async def test_session_delete_blocks_when_bound_automation_exists(
    bus: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("blackcat.config.paths.get_data_dir", lambda: tmp_path)
    sm = _seed_session(tmp_path, key="websocket:doomed")
    cron = CronService(tmp_path / "cron" / "jobs.json")
    cron.add_job(
        name="Daily check",
        schedule=CronSchedule(kind="every", every_ms=86_400_000),
        message="Check the repo",
        session_key="websocket:doomed",
    )
    channel = _ch(bus, session_manager=sm, cron_service=cron, port=29915)
    server_task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.3)
    try:
        boot = await _http_get("http://127.0.0.1:29915/webui/bootstrap")
        token = boot.json()["token"]
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
async def test_session_delete_can_cascade_bound_automations(
    bus: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("blackcat.config.paths.get_data_dir", lambda: tmp_path)
    sm = _seed_session(tmp_path, key="websocket:doomed")
    cron = CronService(tmp_path / "cron" / "jobs.json")
    cron.add_job(
        name="Daily check",
        schedule=CronSchedule(kind="every", every_ms=86_400_000),
        message="Check the repo",
        session_key="websocket:doomed",
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
        boot = await _http_get("http://127.0.0.1:29916/webui/bootstrap")
        token = boot.json()["token"]
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
        assert [job.name for job in cron.list_jobs(include_disabled=True)] == [
            "Legacy same target"
        ]
    finally:
        await channel.stop()
        await server_task


@pytest.mark.asyncio
async def test_session_delete_blocks_origin_automation_when_unified_enabled(
    bus: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("blackcat.config.paths.get_data_dir", lambda: tmp_path)
    sm = _seed_session(tmp_path, key="websocket:doomed")
    cron = CronService(tmp_path / "cron" / "jobs.json")
    cron.add_job(
        name="Chat daily check",
        schedule=CronSchedule(kind="every", every_ms=86_400_000),
        message="Check this chat",
        session_key="websocket:doomed",
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
        boot = await _http_get("http://127.0.0.1:29918/webui/bootstrap")
        token = boot.json()["token"]
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
        boot = await _http_get("http://127.0.0.1:29910/webui/bootstrap")
        token = boot.json()["token"]
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
async def test_webui_thread_resigns_assistant_media_urls(
    bus: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from blackcat.webui.transcript import append_transcript_object

    monkeypatch.setattr("blackcat.config.paths.get_data_dir", lambda: tmp_path)
    media_root = tmp_path / "media"
    websocket_media = media_root / "websocket"
    websocket_media.mkdir(parents=True)
    external = tmp_path / "clip.mp4"
    external.write_bytes(b"video")

    def fake_media_dir(channel: str | None = None) -> Path:
        return websocket_media if channel == "websocket" else media_root

    monkeypatch.setattr("blackcat.channels.websocket.get_media_dir", fake_media_dir)

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
        boot = await _http_get("http://127.0.0.1:29914/webui/bootstrap")
        token = boot.json()["token"]
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
        boot = await _http_get("http://127.0.0.1:29909/webui/bootstrap")
        token = boot.json()["token"]
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
        boot = await _http_get("http://127.0.0.1:29904/webui/bootstrap")
        token = boot.json()["token"]
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

    def __init__(self, headers: dict[str, str] | None = None):
        self.headers = headers or {}


_REMOTE = _FakeConn(("192.168.1.5", 12345))
_LOCAL = _FakeConn(("127.0.0.1", 12345))
_NO_HEADERS = _FakeReq()


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


def test_bootstrap_ws_url_uses_forwarded_https_host(bus: MagicMock) -> None:
    channel = _ch(bus, host="127.0.0.1", port=29931)
    resp = channel.gateway.http._handle_bootstrap(
        _LOCAL,
        _FakeReq({"Host": "blackcat.example", "X-Forwarded-Proto": "https"}),
    )
    assert resp.status_code == 200
    body = json.loads(resp.body)
    assert body["ws_url"] == "wss://blackcat.example/"


def test_localhost_without_auth_is_valid(bus: MagicMock) -> None:
    channel = _ch(bus, host="127.0.0.1")
    resp = channel.gateway.http._handle_bootstrap(_LOCAL, _NO_HEADERS)
    assert resp.status_code == 200


def test_bootstrap_prefers_runtime_model_name(bus: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "blackcat.webui.ws_http._default_model_name_from_config",
        lambda: "from-disk",
    )
    channel = _ch(bus, host="127.0.0.1", runtime_model_name=lambda: "  live/model  ")
    resp = channel.gateway.http._handle_bootstrap(_LOCAL, _NO_HEADERS)
    assert resp.status_code == 200
    body = json.loads(resp.body)
    assert body["model_name"] == "live/model"


def test_bootstrap_falls_back_when_runtime_returns_empty(bus: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "blackcat.webui.ws_http._default_model_name_from_config",
        lambda: "from-disk",
    )
    channel = _ch(bus, host="127.0.0.1", runtime_model_name=lambda: "   ")
    resp = channel.gateway.http._handle_bootstrap(_LOCAL, _NO_HEADERS)
    assert resp.status_code == 200
    body = json.loads(resp.body)
    assert body["model_name"] == "from-disk"


def test_bootstrap_falls_back_when_runtime_raises(bus: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "blackcat.webui.ws_http._default_model_name_from_config",
        lambda: "from-disk",
    )

    def boom():
        raise RuntimeError("resolver failed")

    channel = _ch(bus, host="127.0.0.1", runtime_model_name=boom)
    resp = channel.gateway.http._handle_bootstrap(_LOCAL, _NO_HEADERS)
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


def test_bootstrap_accepts_x_blackcat_auth_header(bus: MagicMock) -> None:
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
