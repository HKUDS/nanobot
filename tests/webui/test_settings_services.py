from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nanobot.channels.websocket.runtime import WebSocketConfig
from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import Config
from nanobot.webui.gateway_services import build_gateway_services
from nanobot.webui.settings_api import settings_payload, update_agent_settings, update_api_settings
from nanobot.webui.settings_services import (
    WebUIOAuthFlowRegistry,
    WebUISettingsServices,
)


class _Flow:
    def __init__(self, *, expired: bool = False) -> None:
        self.expired = expired
        self.cancel_count = 0

    def cancel(self) -> None:
        self.cancel_count += 1


def _gateway(config_path: Path, workspace: Path):
    return build_gateway_services(
        config=WebSocketConfig(),
        bus=MagicMock(),
        session_manager=None,
        static_dist_path=None,
        workspace_path=workspace,
        default_restrict_to_workspace=False,
        config_path=config_path,
        runtime_model_name=None,
        runtime_surface="browser",
        runtime_capabilities_overrides=None,
    )


def test_gateway_settings_services_isolate_config_paths_and_oauth_flows(
    tmp_path: Path,
) -> None:
    first_path = tmp_path / "first" / "config.json"
    second_path = tmp_path / "second" / "config.json"
    first_config = Config()
    first_config.api.host = "127.0.0.2"
    second_config = Config()
    second_config.api.host = "127.0.0.3"
    save_config(first_config, first_path)
    save_config(second_config, second_path)

    first = _gateway(first_path, tmp_path / "first-workspace")
    second = _gateway(second_path, tmp_path / "second-workspace")

    assert first.settings.config.path == first_path.resolve()
    assert second.settings.config.path == second_path.resolve()
    assert first.http.settings_routes.settings is first.settings
    assert second.http.settings_routes.settings is second.settings
    assert first.settings.config.load().api.host == "127.0.0.2"
    assert second.settings.config.load().api.host == "127.0.0.3"
    assert first.settings.read(settings_payload)["api"]["host"] == "127.0.0.2"
    assert second.settings.read(settings_payload)["api"]["host"] == "127.0.0.3"

    first.settings.mutate(update_api_settings, {"port": ["19001"]})
    assert load_config(first_path).api.port == 19001
    assert load_config(second_path).api.port != 19001

    first_flow = _Flow()
    second_flow = _Flow()
    first.settings.oauth_flows.register("openai_codex", "same-id", first_flow)
    second.settings.oauth_flows.register("openai_codex", "same-id", second_flow)

    assert first.settings.oauth_flows.get("openai_codex", "same-id") is first_flow
    assert second.settings.oauth_flows.get("openai_codex", "same-id") is second_flow
    first.settings.oauth_flows.clear("openai_codex")
    assert first_flow.cancel_count == 1
    assert second_flow.cancel_count == 0


def test_settings_service_supports_a_new_config_directory(tmp_path: Path) -> None:
    config_path = tmp_path / "new" / "nested" / "config.json"

    services = WebUISettingsServices.create(config_path)
    services.mutate(update_api_settings, {"port": ["19001"]})

    assert load_config(config_path).api.port == 19001


def test_settings_mutations_serialize_read_modify_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    save_config(Config(), config_path)
    services = WebUISettingsServices.create(config_path)
    first_loaded = threading.Event()
    release_first = threading.Event()
    second_started = threading.Event()
    second_loaded = threading.Event()
    errors: list[BaseException] = []

    from nanobot.webui import settings_api

    original_load = settings_api._load_settings_config

    def controlled_load(path: Path | None, *, home: Path | None = None) -> Config:
        config = original_load(path, home=home)
        if threading.current_thread().name == "settings-first":
            first_loaded.set()
            if not release_first.wait(timeout=2):
                raise TimeoutError("timed out waiting to release first settings mutation")
        elif threading.current_thread().name == "settings-second":
            second_loaded.set()
        return config

    monkeypatch.setattr(settings_api, "_load_settings_config", controlled_load)

    def run_first() -> None:
        try:
            services.mutate(update_agent_settings, {"timezone": ["Asia/Tokyo"]})
        except BaseException as exc:  # noqa: BLE001 - re-raised in the test thread
            errors.append(exc)

    def run_second() -> None:
        try:
            second_started.set()
            services.mutate(update_api_settings, {"host": ["127.0.0.9"]})
        except BaseException as exc:  # noqa: BLE001 - re-raised in the test thread
            errors.append(exc)

    first = threading.Thread(target=run_first, name="settings-first")
    second = threading.Thread(target=run_second, name="settings-second")
    first.start()
    assert first_loaded.wait(timeout=2)
    second.start()
    assert second_started.wait(timeout=2)
    assert not second_loaded.wait(timeout=0.1)
    release_first.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert not first.is_alive()
    assert not second.is_alive()
    assert not errors
    saved = load_config(config_path)
    assert saved.agents.defaults.timezone == "Asia/Tokyo"
    assert saved.api.host == "127.0.0.9"


def test_distinct_gateways_serialize_mutations_for_the_same_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    save_config(Config(), config_path)
    first_services = WebUISettingsServices.create(config_path)
    second_services = WebUISettingsServices.create(config_path)
    first_loaded = threading.Event()
    release_first = threading.Event()
    second_loaded = threading.Event()
    errors: list[BaseException] = []

    from nanobot.webui import settings_api

    original_load = settings_api._load_settings_config

    def controlled_load(path: Path | None, *, home: Path | None = None) -> Config:
        config = original_load(path, home=home)
        if threading.current_thread().name == "gateway-first":
            first_loaded.set()
            if not release_first.wait(timeout=2):
                raise TimeoutError("timed out waiting to release first gateway")
        elif threading.current_thread().name == "gateway-second":
            second_loaded.set()
        return config

    monkeypatch.setattr(settings_api, "_load_settings_config", controlled_load)

    def mutate(
        services: WebUISettingsServices,
        operation: Callable[..., object],
        query: dict[str, list[str]],
    ) -> None:
        try:
            services.mutate(operation, query)
        except BaseException as exc:  # noqa: BLE001 - re-raised in the test thread
            errors.append(exc)

    first = threading.Thread(
        target=mutate,
        args=(first_services, update_agent_settings, {"timezone": ["Asia/Tokyo"]}),
        name="gateway-first",
    )
    second = threading.Thread(
        target=mutate,
        args=(second_services, update_api_settings, {"host": ["127.0.0.9"]}),
        name="gateway-second",
    )
    first.start()
    assert first_loaded.wait(timeout=2)
    second.start()
    assert not second_loaded.wait(timeout=0.1)
    release_first.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert not first.is_alive()
    assert not second.is_alive()
    assert not errors
    saved = load_config(config_path)
    assert saved.agents.defaults.timezone == "Asia/Tokyo"
    assert saved.api.host == "127.0.0.9"


def test_oauth_registry_preserves_expiry_capacity_completion_and_cancel() -> None:
    registry = WebUIOAuthFlowRegistry(max_flows=2)
    expired = _Flow(expired=True)
    oldest = _Flow()
    newest = _Flow()
    replacement = _Flow()

    registry.register("openai_codex", "expired", expired)
    registry.register("openai_codex", "oldest", oldest)
    assert expired.cancel_count == 1
    assert registry.get("openai_codex", "expired") is None

    registry.register("xai_grok", "newest", newest)
    registry.register("openai_codex", "replacement", replacement)
    assert oldest.cancel_count == 1
    assert registry.get("openai_codex", "oldest") is None
    assert registry.get("xai_grok", "newest") is newest
    assert registry.get("openai_codex", "newest") is None

    registry.remove("xai_grok", "newest", newest, cancel=False)
    assert newest.cancel_count == 0
    assert registry.get("xai_grok", "newest") is None

    registry.clear("openai_codex")
    assert replacement.cancel_count == 1
    assert registry.get("openai_codex", "replacement") is None


def test_settings_keep_external_config_and_oauth_home_after_selection_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from oauth_cli_kit.models import OAuthToken

    from nanobot.providers.oauth_storage import codex_token_storage
    from nanobot.webui.settings_api import logout_oauth_provider, update_network_safety_settings
    from nanobot.webui.workspaces import read_webui_default_access_mode

    config_path = tmp_path / "external" / "settings.json"
    save_config(Config(), config_path)
    first_home, second_home = tmp_path / "a", tmp_path / "b"
    first = WebUISettingsServices.create(config_path, home=first_home)
    second = WebUISettingsServices.create(config_path, home=second_home)
    for home, account in ((first_home, "first"), (second_home, "second")):
        codex_token_storage(home).save(OAuthToken(
            access=account, refresh="refresh", expires=9999999999999, account_id=account,
        ))
    monkeypatch.setattr("nanobot.config.home._home_path", tmp_path / "other")
    monkeypatch.setattr("nanobot.config.loader._current_config_path", tmp_path / "other.json")

    for services, home, account in ((first, first_home, "first"), (second, second_home, "second")):
        assert services.config.load().instance_home == home
        payload = services.read(settings_payload)
        rows = {row["name"]: row for row in payload["providers"]}
        assert rows["openai_codex"]["oauth_account"] == account
        assert rows["openai_codex"]["configured"] is True

    first.mutate(update_api_settings, {"port": ["19002"]})
    first.config.update(lambda config: setattr(config.api, "host", "127.0.0.4"))
    assert load_config(config_path, home=first_home).api.port == 19002
    assert load_config(config_path, home=first_home).api.host == "127.0.0.4"
    assert not (first_home / "config.json").exists()
    first.mutate(update_network_safety_settings, {"webui_default_access_mode": ["full"]})
    assert first.read(settings_payload)["advanced"]["webui_default_access_mode"] == "full"
    assert read_webui_default_access_mode(home=first_home) == "full"
    assert read_webui_default_access_mode(home=second_home) == "default"
    first.read(
        logout_oauth_provider, {"provider": ["openai_codex"]}, oauth_flows=first.oauth_flows,
    )
    assert codex_token_storage(first_home).load() is None
    assert codex_token_storage(second_home).load().account_id == "second"


def test_gateway_media_remains_bound_to_selected_home(tmp_path: Path, monkeypatch) -> None:
    first_home = tmp_path / "a"
    gateway = build_gateway_services(
        config=WebSocketConfig(), bus=MagicMock(), session_manager=None, static_dist_path=None,
        workspace_path=tmp_path / "workspace", default_restrict_to_workspace=False,
        config_path=tmp_path / "external" / "config.json", instance_home=first_home,
        runtime_model_name=None, runtime_surface="browser", runtime_capabilities_overrides=None,
    )
    monkeypatch.setattr("nanobot.config.home._home_path", tmp_path / "b")
    image_path = first_home / "media" / "test.png"
    image_path.write_bytes(b"image")
    assert gateway.media.sign_or_stage_media_path(image_path) is not None
    assert gateway.settings.config.load().instance_home == first_home
    assert not (tmp_path / "b").exists()


def test_gateway_workspace_policy_and_projects_remain_bound_to_home(tmp_path, monkeypatch):
    from nanobot.webui.settings_api import update_network_safety_settings
    from nanobot.webui.settings_capabilities import network_safety_payload
    from nanobot.webui.workspaces import read_webui_workspace_state, write_webui_default_access_mode

    first_home = tmp_path / "a"
    second_home = tmp_path / "b"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    config_path = tmp_path / "external" / "config.json"
    config = load_config(config_path, home=first_home)
    config.tools.restrict_to_workspace = True
    save_config(config)
    write_webui_default_access_mode("full", home=second_home)
    monkeypatch.setattr("nanobot.config.home._home_path", second_home)
    gateway = build_gateway_services(
        config=WebSocketConfig(), bus=MagicMock(), session_manager=None, static_dist_path=None,
        workspace_path=workspace, default_restrict_to_workspace=True,
        config_path=config_path, instance_home=first_home, runtime_model_name=None,
        runtime_surface="browser", runtime_capabilities_overrides=None,
    )

    assert network_safety_payload(gateway.settings.config.load())["webui_default_access_mode"] == "default"
    assert gateway.workspaces.default_scope().restrict_to_workspace is True
    assert gateway.workspaces.payload(can_change_project=True)["default_access_mode"] == "default"
    gateway.workspaces.resolve_project(str(project))
    gateway.workspaces.set_favorite_project(str(project), True)
    assert read_webui_workspace_state(home=first_home)["recent_projects"] == [str(project)]
    assert read_webui_workspace_state(home=first_home)["favorite_projects"] == [str(project)]
    assert read_webui_workspace_state(home=second_home)["recent_projects"] == []
    assert read_webui_workspace_state(home=second_home)["favorite_projects"] == []
    gateway.settings.mutate(
        update_network_safety_settings,
        {"webui_default_access_mode": ["full"]},
    )
    assert gateway.workspaces.default_scope().restrict_to_workspace is False


async def test_gateway_file_and_skill_reads_remain_bound_to_home(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    from urllib.parse import urlencode

    import httpx
    from websockets.datastructures import Headers
    from websockets.http11 import Request

    from nanobot.agent.plugins import AGENT_PLUGIN_SCHEMA, set_agent_plugin_enabled

    first_home, second_home = tmp_path / "a", tmp_path / "b"
    workspace = tmp_path / "workspace"
    plugin = workspace / "plugins" / "demo"
    skill = plugin / "skills" / "demo-skill"
    skill.mkdir(parents=True)
    (plugin / "plugin.json").write_text(
        json.dumps({"$schema": AGENT_PLUGIN_SCHEMA, "name": "demo"}), encoding="utf-8",
    )
    (skill / "SKILL.md").write_text(
        "---\nname: demo-skill\ndescription: Approved skill.\n---\nApproved content.", encoding="utf-8",
    )
    set_agent_plugin_enabled(workspace, "demo", True, home=first_home)
    gateway = build_gateway_services(
        config=WebSocketConfig(), bus=MagicMock(), session_manager=None, static_dist_path=None,
        workspace_path=workspace, default_restrict_to_workspace=True,
        config_path=tmp_path / "external.json", instance_home=first_home,
        runtime_model_name=None, runtime_surface="browser", runtime_capabilities_overrides=None,
    )
    files = []
    for home in (first_home, second_home):
        path = home / "media" / "upload.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("uploaded attachment", encoding="utf-8")
        files.append(path)
    monkeypatch.setattr("nanobot.config.home._home_path", second_home)
    catalog = httpx.MockTransport(lambda request: httpx.Response(200, json={"skills": [{
        "skillId": "demo-skill", "source": "acme/skills", "installs": 42,
    }]}))
    monkeypatch.setattr(
        "nanobot.webui.skills_marketplace._skills_client",
        lambda: httpx.AsyncClient(transport=catalog),
    )
    connection = SimpleNamespace(
        remote_address=("127.0.0.1", 10000),
        request=Request("/ws", Headers({"Host": "127.0.0.1:8765"})),
    )
    token = gateway.tokens.issue_api_token(60)

    async def request(path):
        return await gateway.http.dispatch(
            connection, Request(path, Headers({"Authorization": f"Bearer {token}"})),
        )

    for options, key, expected in (
        ({}, "content", "uploaded attachment"),
        ({"metadata": "1"}, "path", str(files[0])),
        ({"probe": "1"}, "available", True),
    ):
        response = await request(
            "/api/sessions/websocket%3Ademo/file-preview?" + urlencode({"path": str(files[0]), **options}),
        )
        assert response.status_code == 200
        payload = json.loads(response.body)
        assert payload[key] == expected
        denied = await request(
            "/api/sessions/websocket%3Ademo/file-preview?" + urlencode({"path": str(files[1]), **options}),
        )
        if options.get("probe"):
            assert json.loads(denied.body) == {"available": False}
        else:
            assert denied.status_code == 403
    skills = json.loads((await request("/api/webui/skills")).body)["skills"]
    assert any(row["name"] == "demo-skill" and row["source"] == "plugin" for row in skills)
    detail = await request("/api/webui/skills/demo-skill")
    assert detail.status_code == 200
    assert json.loads(detail.body)["name"] == "demo-skill"
    results = await request("/api/webui/skills/search?q=demo&provider=skills_sh")
    assert results.status_code == 200
    assert json.loads(results.body)["skills"][0]["installed"] is True

    installed = await gateway.http.dispatch_webui_mutation(
        connection, "skill.install", {"source": "acme/skills", "skill": "demo-skill"},
    )
    assert installed.status_code == 200
    assert json.loads(installed.body)["last_action"]["already_installed"] is True
    updated = await gateway.http.dispatch_webui_mutation(
        connection, "skill.update", {"name": "demo-skill", "enabled": False},
    )
    assert updated.status_code == 200
    assert gateway.settings.config.load().agents.defaults.disabled_skills == ["demo-skill"]
