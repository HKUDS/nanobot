from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.config.loader import save_config
from nanobot.config.schema import Config
from nanobot.providers.factory import ProviderSnapshot, load_provider_snapshot
from nanobot.webui.settings_api import update_agent_settings


def _provider(default_model: str, max_tokens: int = 123) -> MagicMock:
    provider = MagicMock()
    provider.get_default_model.return_value = default_model
    provider.generation = SimpleNamespace(max_tokens=max_tokens)
    return provider


def test_provider_refresh_updates_all_model_dependents(tmp_path: Path) -> None:
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

    loop._refresh_provider_snapshot()

    assert loop.provider is new_provider
    assert loop.model == "new-model"
    assert loop.context_window_tokens == 2000
    assert loop.runner.provider is new_provider
    assert loop.subagents.provider is new_provider
    assert loop.subagents.model == "new-model"
    assert loop.subagents.runner.provider is new_provider
    assert loop.consolidator.provider is new_provider
    assert loop.consolidator.model == "new-model"
    assert loop.consolidator.context_window_tokens == 2000
    assert loop.consolidator.max_completion_tokens == 456
    assert loop.dream.provider is new_provider
    assert loop.dream.model == "new-model"
    assert loop.dream._runner.provider is new_provider


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

    runtime = loop.llm_runtime()

    assert runtime.provider is new_provider
    assert runtime.model == "new-model"
    assert loop.provider is new_provider
    assert loop.runner.provider is new_provider


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
    loop._refresh_provider_snapshot()

    assert payload["requires_restart"] is False
    assert loop.context_window_tokens == 262_144
    assert loop.consolidator.context_window_tokens == 262_144
