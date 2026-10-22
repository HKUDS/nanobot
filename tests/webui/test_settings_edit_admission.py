"""Model editing commits disk settings before admitting a refreshed runtime."""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from websockets.datastructures import Headers

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import Config, ModelPresetConfig, ProviderConfig
from nanobot.providers.factory import load_provider_snapshot
from nanobot.session.model_selection import SESSION_MODEL_PRESET_METADATA_KEY
from nanobot.webui import settings_api
from nanobot.webui.http_utils import http_json_response
from nanobot.webui.settings_routes import WebUISettingsRouter
from nanobot.webui.settings_services import WebUISettingsServices


@pytest.mark.asyncio
async def test_model_save_commits_before_refreshing_next_session_admission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    config = Config()
    config.providers.openai = ProviderConfig(api_key="test-only-not-a-real-key")
    config.model_presets = {
        "chat": ModelPresetConfig(
            model="gpt-4o", provider="openai", context_window_tokens=100_000,
        ),
    }
    config.agents.defaults.model_preset = "chat"
    save_config(config, config_path)
    snapshot = load_provider_snapshot(config_path)
    agent = AgentLoop(
        bus=MessageBus(),
        provider=snapshot.provider,
        workspace=tmp_path / "workspace",
        model=snapshot.model,
        context_window_tokens=snapshot.context_window_tokens,
        provider_signature=snapshot.signature,
        model_preset=snapshot.model_preset,
        model_presets=config.model_presets,
        provider_snapshot_loader=lambda: load_provider_snapshot(config_path),
        preset_catalog_loader=lambda: load_config(config_path).model_presets,
        preset_snapshot_loader=lambda name: load_provider_snapshot(config_path, preset_name=name),
    )
    router = WebUISettingsRouter(
        settings=WebUISettingsServices.create(
            config_path, refresh_runtime_config=agent.refresh_runtime_config,
        ),
        bus=agent.bus,
        logger=SimpleNamespace(exception=lambda *_args: None, warning=lambda *_args: None),
        check_api_token=lambda _request: True,
        parse_query=lambda path: parse_qs(urlsplit(path).query),
        json_response=http_json_response,
        error_response=lambda status, message: http_json_response({"error": message}, status=status),
        runtime_surface="browser",
        runtime_capabilities={},
        mcp_oauth_redirect_uri=lambda _request: "https://gateway.example/auth/mcp/callback",
    )
    before_save, allow_save = threading.Event(), threading.Event()
    disk_saved, allow_return = threading.Event(), threading.Event()

    def controlled_save(updated: Config, path: Path | None = None) -> None:
        assert path == config_path
        assert updated.model_presets["chat"].context_window_tokens == 500_000
        before_save.set()
        assert allow_save.wait(5), "test did not release the disk commit"
        save_config(updated, path)
        disk_saved.set()
        assert allow_return.wait(5), "test did not release the save response"

    monkeypatch.setattr(settings_api, "save_config", controlled_save)

    async def admit(name: str, *, explicit_preset: bool = False):
        session = agent.sessions.get_or_create(f"websocket:{name}")
        if explicit_preset:
            session.metadata[SESSION_MODEL_PRESET_METADATA_KEY] = "chat"
        return await agent.runtime_for_session(session)

    def disk_window() -> int:
        return load_config(config_path).model_presets["chat"].context_window_tokens

    pending_save = None
    try:
        prior = await admit("prior")
        cached_preset = await admit("prior-preset", explicit_preset=True)
        draft = {"name": "chat", "context_window_tokens": 500_000}
        # A draft is just client-owned data, not disk or runtime state.
        assert disk_window() == 100_000
        assert prior.context_window_tokens == cached_preset.context_window_tokens == 100_000
        assert (await admit("draft-only")).context_window_tokens == 100_000

        path = "/api/settings/model-configurations/update"
        request = SimpleNamespace(path=path, headers=Headers())
        request._nanobot_webui_mutation_request = True
        request._nanobot_webui_mutation_payload = draft
        request._nanobot_trusted_proxy_authenticated = True
        pending_save = asyncio.create_task(router.dispatch(None, request, path))
        assert await asyncio.to_thread(before_save.wait, 5)
        assert not pending_save.done()
        assert disk_window() == 100_000
        during_save = await admit("save-pending")
        assert during_save.context_window_tokens == 100_000
        assert await admit("cached-during-save", explicit_preset=True) is cached_preset

        allow_save.set()
        assert await asyncio.to_thread(disk_saved.wait, 5)
        # Disk can be committed while the route still owns a pending mutation;
        # admission uses the old snapshot until its synchronous refresh runs.
        assert not pending_save.done()
        assert disk_window() == 500_000
        assert (await admit("disk-committed-response-pending")).context_window_tokens == 100_000

        allow_return.set()
        response = await asyncio.wait_for(pending_save, 5)
        assert response.status_code == 200, json.loads(response.body)
        assert agent.runtime_resolver.runtime.context_window_tokens == 500_000
        next_runtime = await admit("after-success")
        next_preset = await admit("after-success-preset", explicit_preset=True)
        assert next_runtime.context_window_tokens == disk_window() == 500_000
        assert next_preset.context_window_tokens == 500_000
        assert next_preset is not cached_preset
        assert agent.runtime_resolver.model_presets["chat"].context_window_tokens == 500_000
        # Refresh replaces admission values; already-admitted turns do not change.
        assert prior.context_window_tokens == during_save.context_window_tokens == 100_000
        assert cached_preset.context_window_tokens == 100_000
    finally:
        allow_save.set()
        allow_return.set()
        if pending_save is not None:
            await asyncio.wait_for(pending_save, 5)
        await router.close()
        await agent.runtime_resolver.aclose()
