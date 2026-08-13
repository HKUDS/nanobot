from __future__ import annotations

import threading
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

    def controlled_load(path: Path | None) -> Config:
        config = original_load(path)
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
