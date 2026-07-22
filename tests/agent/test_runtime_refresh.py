import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.bus.runtime_events import RuntimeModelChanged
from nanobot.config.loader import save_config
from nanobot.config.schema import Config, ModelPresetConfig
from nanobot.providers.base import GenerationSettings
from nanobot.providers.factory import ProviderSnapshot, load_provider_snapshot
from nanobot.session.model_selection import (
    SESSION_MODEL_PRESET_METADATA_KEY,
    model_preset_from_metadata,
)
from nanobot.webui.settings_api import update_agent_settings


def _provider(default_model: str, max_tokens: int = 123) -> MagicMock:
    provider = MagicMock()
    provider.get_default_model.return_value = default_model
    provider.generation = SimpleNamespace(max_tokens=max_tokens)
    return provider


def test_provider_refresh_updates_only_runtime_resolver(tmp_path: Path) -> None:
    old_provider = _provider("old-model")
    new_provider = _provider("new-model", max_tokens=456)
    loop = AgentLoop(
        bus=MessageBus(),
        provider=old_provider,
        workspace=tmp_path,
        model="old-model",
        context_window_tokens=1000,
        provider_snapshot_loader=lambda: ProviderSnapshot(
            provider=new_provider,
            model="new-model",
            context_window_tokens=2000,
            signature=("new-model",),
        ),
    )
    loop.runtime_resolver.invalidate()

    runtime = loop.llm_runtime()

    assert runtime is loop.runtime_resolver.runtime
    assert loop.provider is new_provider
    assert loop.model == "new-model"
    assert loop.context_window_tokens == 2000
    assert not hasattr(loop.runner, "provider")
    assert not hasattr(loop.subagents, "provider")
    assert not hasattr(loop.subagents, "model")
    assert not hasattr(loop.subagents.runner, "provider")
    assert not hasattr(loop.consolidator, "provider")
    assert not hasattr(loop.consolidator, "model")
    assert not hasattr(loop.consolidator, "context_window_tokens")
    assert not hasattr(loop.consolidator, "max_completion_tokens")


def test_loop_has_no_mutable_runtime_mirrors_or_legacy_snapshot_api(tmp_path: Path) -> None:
    loop = AgentLoop(
        bus=MessageBus(),
        provider=_provider("test-model"),
        workspace=tmp_path,
        model="test-model",
        context_window_tokens=1000,
    )

    assert {
        "provider",
        "model",
        "context_window_tokens",
        "model_presets",
        "_active_preset",
        "_provider_signature",
        "_max_messages",
    }.isdisjoint(loop.__dict__)
    assert not hasattr(loop, "_apply_provider_snapshot")
    assert not hasattr(loop, "_build_model_preset_snapshot")
    assert not hasattr(loop, "_sync_replay_max_messages")


def test_llm_runtime_refreshes_provider_snapshot(tmp_path: Path) -> None:
    old_provider = _provider("old-model")
    new_provider = _provider("new-model", max_tokens=456)
    loop = AgentLoop(
        bus=MessageBus(),
        provider=old_provider,
        workspace=tmp_path,
        model="old-model",
        context_window_tokens=1000,
        provider_snapshot_loader=lambda: ProviderSnapshot(
            provider=new_provider,
            model="new-model",
            context_window_tokens=2000,
            signature=("new-model",),
        ),
    )
    loop.runtime_resolver.invalidate()

    runtime = loop.llm_runtime()

    assert runtime.provider is new_provider
    assert runtime.model == "new-model"
    assert loop.provider is new_provider
    assert not hasattr(loop.runner, "provider")


def test_llm_runtime_surfaces_invalidated_config_errors(tmp_path: Path) -> None:
    def fail_refresh() -> ProviderSnapshot:
        raise ValueError("invalid config")

    loop = AgentLoop(
        bus=MessageBus(),
        provider=_provider("old-model"),
        workspace=tmp_path,
        model="old-model",
        context_window_tokens=1000,
        provider_snapshot_loader=fail_refresh,
    )
    loop.runtime_resolver.invalidate()

    with pytest.raises(ValueError, match="invalid config"):
        loop.llm_runtime()


def test_same_snapshot_default_clears_preset_and_publishes_update(tmp_path: Path) -> None:
    base_provider = _provider("base-model")
    fast_provider = _provider("fast-model")
    fast_snapshot = ProviderSnapshot(
        provider=fast_provider,
        model="fast-model",
        context_window_tokens=2000,
        signature=("fast-model", "auto", "same-runtime"),
    )
    published: list[tuple[str, str | None]] = []
    loop = AgentLoop(
        bus=MessageBus(),
        provider=base_provider,
        workspace=tmp_path,
        model="base-model",
        context_window_tokens=1000,
        provider_signature=("base-model", "auto", "initial"),
        provider_snapshot_loader=lambda: fast_snapshot,
        model_presets={"fast": ModelPresetConfig(model="fast-model")},
        model_preset="fast",
        preset_snapshot_loader=lambda _name: fast_snapshot,
        runtime_model_publisher=lambda model, preset: published.append((model, preset)),
    )
    loop.runtime_resolver.invalidate()

    runtime = loop.llm_runtime()

    assert runtime.model_preset is None
    assert loop.model_preset is None
    assert published == [("fast-model", None)]


def test_named_default_refresh_is_used_by_sessions_without_override(tmp_path: Path) -> None:
    provider = _provider("shared-model")
    shared_signature = ("shared-model", "auto", "same-settings")
    snapshots = {
        "fast": ProviderSnapshot(
            provider=provider,
            model="shared-model",
            context_window_tokens=16_000,
            signature=shared_signature,
            model_preset="fast",
        ),
        "deep": ProviderSnapshot(
            provider=provider,
            model="shared-model",
            context_window_tokens=16_000,
            signature=shared_signature,
            model_preset="deep",
        ),
    }
    default_snapshot = snapshots["deep"]
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="shared-model",
        context_window_tokens=16_000,
        provider_signature=shared_signature,
        provider_snapshot_loader=lambda: default_snapshot,
        model_presets={
            name: ModelPresetConfig(model=snapshot.model)
            for name, snapshot in snapshots.items()
        },
        model_preset="fast",
        preset_snapshot_loader=snapshots.__getitem__,
    )

    loop.runtime_resolver.invalidate()
    runtime = loop.llm_runtime()
    session = loop.sessions.get_or_create("sdk:new-after-refresh")

    assert runtime.model_preset == "deep"
    assert loop.runtime_for_session(session).model_preset == "deep"
    assert model_preset_from_metadata(session.metadata) is None


@pytest.mark.asyncio
async def test_config_invalidation_notifies_clients_before_session_runtime_refresh(
    tmp_path: Path,
) -> None:
    provider = _provider("model-a")
    catalog = {"fast": ModelPresetConfig(model="model-a")}
    current_model = "model-a"
    published: list[RuntimeModelChanged] = []

    def load_preset(_name: str) -> ProviderSnapshot:
        return ProviderSnapshot(
            provider=provider,
            model=current_model,
            context_window_tokens=16_000,
            signature=(current_model, "auto"),
            model_preset="fast",
        )

    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="model-a",
        context_window_tokens=16_000,
        provider_signature=("model-a", "auto"),
        provider_snapshot_loader=lambda: load_preset("fast"),
        model_presets=catalog,
        preset_catalog_loader=lambda: catalog,
        model_preset="fast",
        preset_snapshot_loader=load_preset,
    )
    loop.runtime_events.subscribe(published.append, RuntimeModelChanged)
    session = loop.sessions.get_or_create("websocket:chat")
    session.metadata[SESSION_MODEL_PRESET_METADATA_KEY] = "fast"
    current_model = "model-b"
    catalog["fast"] = ModelPresetConfig(model="model-b")

    loop.invalidate_runtime_config()
    runtime = loop.runtime_for_session(session)
    await asyncio.sleep(0)

    assert [(event.model, event.model_preset) for event in published] == [
        ("model-a", "fast"),
    ]
    assert runtime.model == "model-b"
    assert loop.model_presets["fast"].model == "model-b"


def test_next_turn_captures_generation_changed_after_previous_admission(
    tmp_path: Path,
) -> None:
    provider = _provider("test-model")
    provider.generation = GenerationSettings(temperature=0.2, max_tokens=1024)
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        context_window_tokens=16_384,
    )

    first = loop.llm_runtime()
    provider.generation = GenerationSettings(temperature=0.8, max_tokens=512)
    second = loop.llm_runtime()

    assert first.generation.temperature == 0.2
    assert first.generation.max_tokens == 1024
    assert second.generation.temperature == 0.8
    assert second.generation.max_tokens == 512


def test_settings_context_window_refreshes_runtime_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "config.json"
    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "workspace")
    config.agents.defaults.model = "openai/gpt-4o"
    config.agents.defaults.provider = "openai"
    config.agents.defaults.context_window_tokens = 65_536
    config.providers.openai.api_key = "sk-test"
    save_config(config, config_path)
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)

    def loader(*, preset_name: str | None = None) -> ProviderSnapshot:
        return load_provider_snapshot(config_path, preset_name=preset_name)

    loop = AgentLoop.from_config(config, provider_snapshot_loader=loader)

    payload = update_agent_settings({"context_window_tokens": ["262144"]})
    loop.runtime_resolver.invalidate()
    loop.llm_runtime()

    assert payload["requires_restart"] is False
    assert loop.context_window_tokens == 262_144
    assert loop.llm_runtime().context_window_tokens == 262_144
