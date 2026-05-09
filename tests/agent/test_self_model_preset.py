from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.self import MyTool
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import ModelPresetConfig


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


def test_from_config_preserves_existing_default_preset(tmp_path) -> None:
    from unittest.mock import patch

    from nanobot.config.schema import Config
    config = Config.model_validate({
        "agents": {"defaults": {"model": "openai/gpt-4.1", "workspace": str(tmp_path)}},
        "model_presets": {
            "default": {"model": "custom-model"}
        },
    })
    fake_provider = _provider("openai/gpt-4.1")
    with patch("nanobot.providers.factory.make_provider", return_value=fake_provider):
        loop = AgentLoop.from_config(config)
    assert loop.model_presets["default"].model == "custom-model"
