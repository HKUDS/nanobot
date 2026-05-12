from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.self import MyTool
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import ModelPresetConfig
from nanobot.providers.factory import ProviderSnapshot


def _provider(default_model: str, max_tokens: int = 123) -> MagicMock:
    provider = MagicMock()
    provider.get_default_model.return_value = default_model
    provider.generation = SimpleNamespace(
        max_tokens=max_tokens, temperature=0.1, reasoning_effort=None
    )
    return provider


def _make_loop(tmp_path, presets=None, active_preset=None):
    provider = _provider("base-model")
    return AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="base-model",
        context_window_tokens=1000,
        model_presets=presets or {},
        model_preset=active_preset,
    )


def test_model_preset_getter_none_when_not_set(tmp_path) -> None:
    loop = _make_loop(tmp_path)
    assert loop.model_preset is None


def test_model_preset_setter_updates_state(tmp_path) -> None:
    presets = {
        "fast": ModelPresetConfig(
            model="openai/gpt-4.1",
            provider="openai",
            max_tokens=4096,
            context_window_tokens=32_768,
            temperature=0.5,
            reasoning_effort="low",
        )
    }
    loop = _make_loop(tmp_path, presets=presets)
    loop.model_preset = "fast"

    assert loop.model_preset == "fast"
    assert loop.model == "openai/gpt-4.1"
    assert loop.context_window_tokens == 32_768
    assert loop.provider.generation.temperature == 0.5
    assert loop.provider.generation.max_tokens == 4096
    assert loop.provider.generation.reasoning_effort == "low"
    assert loop.subagents.model == "openai/gpt-4.1"
    assert loop.consolidator.model == "openai/gpt-4.1"
    assert loop.consolidator.context_window_tokens == 32_768
    assert loop.consolidator.max_completion_tokens == 4096
    assert loop.dream.model == "openai/gpt-4.1"


def test_model_preset_setter_publishes_runtime_model_event(tmp_path) -> None:
    bus = MessageBus()
    loop = AgentLoop(
        bus=bus,
        provider=_provider("base-model", max_tokens=123),
        workspace=tmp_path,
        model="base-model",
        context_window_tokens=1000,
        model_presets={"fast": ModelPresetConfig(model="openai/gpt-4.1")},
    )

    loop.set_model_preset("fast")

    event = bus.outbound.get_nowait()
    assert event.channel == "websocket"
    assert event.chat_id == "*"
    assert event.content == ""
    assert event.metadata == {
        "_runtime_model_updated": True,
        "model": "openai/gpt-4.1",
        "model_preset": "fast",
    }


def test_model_preset_setter_replaces_provider_from_snapshot(tmp_path) -> None:
    old_provider = _provider("base-model", max_tokens=123)
    new_provider = _provider("anthropic/claude-opus-4-5", max_tokens=2048)
    preset = ModelPresetConfig(
        model="anthropic/claude-opus-4-5",
        provider="anthropic",
        max_tokens=2048,
        context_window_tokens=200_000,
    )
    loop = AgentLoop(
        bus=MessageBus(),
        provider=old_provider,
        workspace=tmp_path,
        model="base-model",
        context_window_tokens=1000,
        model_presets={"deep": preset},
        preset_snapshot_loader=lambda name: ProviderSnapshot(
            provider=new_provider,
            model=preset.model,
            context_window_tokens=preset.context_window_tokens,
            signature=(name, preset.model),
        ),
    )

    loop.set_model_preset("deep")

    assert loop.provider is new_provider
    assert loop.runner.provider is new_provider
    assert loop.subagents.provider is new_provider
    assert loop.subagents.runner.provider is new_provider
    assert loop.consolidator.provider is new_provider
    assert loop.dream.provider is new_provider
    assert loop.dream._runner.provider is new_provider
    assert loop.model == "anthropic/claude-opus-4-5"
    assert loop.context_window_tokens == 200_000
    assert loop.consolidator.max_completion_tokens == 2048


def test_model_preset_setter_failure_leaves_old_state(tmp_path) -> None:
    preset = ModelPresetConfig(model="openai/gpt-4.1", max_tokens=4096)
    loop = AgentLoop(
        bus=MessageBus(),
        provider=_provider("base-model", max_tokens=123),
        workspace=tmp_path,
        model="base-model",
        context_window_tokens=1000,
        model_presets={"fast": preset},
        preset_snapshot_loader=lambda _name: (_ for _ in ()).throw(
            RuntimeError("provider unavailable")
        ),
    )

    with pytest.raises(RuntimeError, match="provider unavailable"):
        loop.set_model_preset("fast")

    assert loop.model_preset is None
    assert loop.model == "base-model"
    assert loop.subagents.model == "base-model"
    assert loop.consolidator.model == "base-model"
    assert loop.dream.model == "base-model"
    assert loop.context_window_tokens == 1000
    assert loop.consolidator.max_completion_tokens == 123


def test_active_model_preset_survives_unchanged_config_refresh(tmp_path) -> None:
    base_provider = _provider("base-model", max_tokens=123)
    fast_provider = _provider("openai/gpt-4.1", max_tokens=4096)
    default_snapshot = ProviderSnapshot(
        provider=base_provider,
        model="base-model",
        context_window_tokens=1000,
        signature=("base-model", "auto", "openai", "sk-old"),
    )
    fast_snapshot = ProviderSnapshot(
        provider=fast_provider,
        model="openai/gpt-4.1",
        context_window_tokens=32_768,
        signature=("openai/gpt-4.1", "auto", "openai", "sk-old"),
    )
    loop = AgentLoop(
        bus=MessageBus(),
        provider=base_provider,
        workspace=tmp_path,
        model="base-model",
        context_window_tokens=1000,
        provider_signature=default_snapshot.signature,
        model_presets={"fast": ModelPresetConfig(model="openai/gpt-4.1")},
        provider_snapshot_loader=lambda: default_snapshot,
        preset_snapshot_loader=lambda _name: fast_snapshot,
    )

    loop.set_model_preset("fast")
    loop._refresh_provider_snapshot()

    assert loop.model_preset == "fast"
    assert loop.provider is fast_provider
    assert loop.model == "openai/gpt-4.1"


def test_config_model_refresh_clears_active_model_preset(tmp_path) -> None:
    base_provider = _provider("base-model", max_tokens=123)
    fast_provider = _provider("openai/gpt-4.1", max_tokens=4096)
    webui_provider = _provider("anthropic/claude-opus-4-5", max_tokens=2048)
    webui_snapshot = ProviderSnapshot(
        provider=webui_provider,
        model="anthropic/claude-opus-4-5",
        context_window_tokens=200_000,
        signature=("anthropic/claude-opus-4-5", "anthropic", "anthropic", "sk-old"),
    )
    fast_snapshot = ProviderSnapshot(
        provider=fast_provider,
        model="openai/gpt-4.1",
        context_window_tokens=32_768,
        signature=("openai/gpt-4.1", "auto", "openai", "sk-old"),
    )
    loop = AgentLoop(
        bus=MessageBus(),
        provider=base_provider,
        workspace=tmp_path,
        model="base-model",
        context_window_tokens=1000,
        provider_snapshot_loader=lambda: webui_snapshot,
        provider_signature=("base-model", "auto", "openai", "sk-old"),
        model_presets={"fast": ModelPresetConfig(model="openai/gpt-4.1")},
        preset_snapshot_loader=lambda _name: fast_snapshot,
    )

    loop.set_model_preset("fast")
    loop._refresh_provider_snapshot()

    assert loop.model_preset is None
    assert loop.provider is webui_provider
    assert loop.model == "anthropic/claude-opus-4-5"
    assert loop.context_window_tokens == 200_000


def test_model_preset_setter_raises_on_unknown(tmp_path) -> None:
    loop = _make_loop(tmp_path)
    with pytest.raises(KeyError, match="model_preset 'missing' not found"):
        loop.model_preset = "missing"


def test_model_preset_setter_raises_on_empty_string(tmp_path) -> None:
    loop = _make_loop(tmp_path)
    with pytest.raises(ValueError, match="model_preset must be a non-empty string"):
        loop.model_preset = ""


def test_self_tool_inspect_shows_model_preset(tmp_path) -> None:
    presets = {
        "fast": ModelPresetConfig(model="openai/gpt-4.1"),
    }
    loop = _make_loop(tmp_path, presets=presets, active_preset="fast")
    tool = MyTool(runtime_state=loop, modify_allowed=True)
    output = tool._inspect_all()
    assert "model_preset: 'fast'" in output


def test_self_tool_set_model_preset_via_modify(tmp_path) -> None:
    presets = {
        "fast": ModelPresetConfig(model="openai/gpt-4.1"),
    }
    loop = _make_loop(tmp_path, presets=presets)
    tool = MyTool(runtime_state=loop, modify_allowed=True)
    result = tool._modify("model_preset", "fast")
    assert "Error" not in result
    assert loop.model_preset == "fast"
    assert loop.model == "openai/gpt-4.1"


def test_self_tool_set_model_clears_active_preset(tmp_path) -> None:
    presets = {
        "fast": ModelPresetConfig(model="openai/gpt-4.1"),
    }
    loop = _make_loop(tmp_path, presets=presets, active_preset="fast")
    tool = MyTool(runtime_state=loop, modify_allowed=True)
    result = tool._modify("model", "anthropic/claude-opus-4-5")
    assert "Error" not in result
    assert loop._active_preset is None
    assert loop.model == "anthropic/claude-opus-4-5"


def test_from_config_injects_default_preset(tmp_path) -> None:
    from unittest.mock import patch

    from nanobot.config.schema import Config
    config = Config.model_validate({
        "agents": {"defaults": {"model": "openai/gpt-4.1", "workspace": str(tmp_path)}},
    })
    fake_provider = _provider("openai/gpt-4.1")
    with patch("nanobot.providers.factory.make_provider", return_value=fake_provider):
        loop = AgentLoop.from_config(config)
    assert "default" in loop.model_presets
    assert loop.model_presets["default"].model == "openai/gpt-4.1"


def test_from_config_static_preset_loader_does_not_enable_hot_reload(tmp_path) -> None:
    from unittest.mock import patch

    from nanobot.config.schema import Config
    config = Config.model_validate({
        "agents": {"defaults": {"model": "openai/gpt-4.1", "workspace": str(tmp_path)}},
        "model_presets": {"fast": {"model": "openai/gpt-4.1-mini"}},
    })
    fake_provider = _provider("openai/gpt-4.1")
    with patch("nanobot.providers.factory.make_provider", return_value=fake_provider):
        loop = AgentLoop.from_config(config)
    assert loop._provider_snapshot_loader is None
    assert loop._preset_snapshot_loader is not None
