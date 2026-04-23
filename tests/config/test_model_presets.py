from nanobot.config.schema import Config, ModelPresetConfig


def test_model_preset_config_accepts_model_and_provider_separately() -> None:
    preset = ModelPresetConfig(model="gpt-5", provider="openai")
    assert preset.model == "gpt-5"
    assert preset.provider == "openai"


def test_model_preset_config_defaults() -> None:
    preset = ModelPresetConfig(model="test-model")
    assert preset.provider == "auto"
    assert preset.max_tokens == 8192
    assert preset.context_window_tokens == 65_536
    assert preset.temperature == 0.1
    assert preset.reasoning_effort is None


def test_model_preset_config_all_fields() -> None:
    preset = ModelPresetConfig(
        model="deepseek-r1",
        provider="deepseek",
        max_tokens=16384,
        context_window_tokens=131072,
        temperature=0.2,
        reasoning_effort="high",
    )
    assert preset.model == "deepseek-r1"
    assert preset.provider == "deepseek"
    assert preset.max_tokens == 16384
    assert preset.context_window_tokens == 131072
    assert preset.temperature == 0.2
    assert preset.reasoning_effort == "high"


def test_config_accepts_model_presets_dict() -> None:
    cfg = Config(model_presets={
        "gpt5": ModelPresetConfig(model="gpt-5", provider="openai", max_tokens=16384),
        "ds": ModelPresetConfig(model="deepseek-chat", provider="deepseek"),
    })
    assert "gpt5" in cfg.model_presets
    assert cfg.model_presets["gpt5"].max_tokens == 16384
    assert cfg.model_presets["ds"].model == "deepseek-chat"


def test_resolve_preset_returns_preset_values() -> None:
    cfg = Config.model_validate({
        "model_presets": {
            "gpt5": {
                "model": "gpt-5",
                "provider": "openai",
                "max_tokens": 16384,
                "context_window_tokens": 128000,
                "temperature": 0.2,
            },
        },
        "agents": {"defaults": {"model_preset": "gpt5"}},
    })
    r = cfg.resolve_preset()
    assert r.model == "gpt-5"
    assert r.provider == "openai"
    assert r.max_tokens == 16384
    assert r.context_window_tokens == 128000
    assert r.temperature == 0.2


def test_resolve_preset_ignores_old_config_fields() -> None:
    """Preset wins completely — old config remnants are ignored."""
    cfg = Config.model_validate({
        "model_presets": {
            "gpt5": {
                "model": "gpt-5",
                "provider": "openai",
                "max_tokens": 16384,
                "context_window_tokens": 128000,
                "temperature": 0.2,
            },
        },
        "agents": {
            "defaults": {
                "model_preset": "gpt5",
                "model": "old-model",
                "temperature": 0.5,
            },
        },
    })
    r = cfg.resolve_preset()
    assert r.model == "gpt-5"
    assert r.temperature == 0.2
    assert r.max_tokens == 16384


def test_preset_not_found_raises_error() -> None:
    import pytest
    with pytest.raises(Exception, match="model_preset.*not found"):
        Config.model_validate({
            "model_presets": {},
            "agents": {"defaults": {"model_preset": "nonexistent"}},
        })


def test_resolve_preset_without_preset_returns_defaults() -> None:
    """Backward compat: no preset → resolve_preset returns individual field values."""
    cfg = Config.model_validate({
        "agents": {"defaults": {"model": "deepseek-chat"}},
    })
    r = cfg.resolve_preset()
    assert r.model == "deepseek-chat"
    assert r.max_tokens == 8192


def test_agent_loop_stores_model_presets() -> None:
    from pathlib import Path
    from unittest.mock import MagicMock

    from nanobot.agent.loop import AgentLoop

    presets = {
        "gpt5": ModelPresetConfig(model="gpt-5", provider="openai"),
    }
    provider = MagicMock()
    provider.get_default_model.return_value = "test"

    loop = AgentLoop(
        bus=MagicMock(),
        provider=provider,
        workspace=Path("/tmp/test"),
        model_presets=presets,
    )
    assert loop.model_presets == presets


def test_resolve_preset_with_reasoning_effort() -> None:
    cfg = Config.model_validate({
        "model_presets": {
            "ds-r1": {
                "model": "deepseek-r1",
                "provider": "deepseek",
                "reasoning_effort": "high",
            },
        },
        "agents": {"defaults": {"model_preset": "ds-r1"}},
    })
    assert cfg.resolve_preset().reasoning_effort == "high"


def test_preset_routes_to_correct_provider() -> None:
    """resolve_preset + _match_provider uses the preset's model+provider."""
    cfg = Config.model_validate({
        "model_presets": {
            "ds": {"model": "deepseek-chat", "provider": "deepseek"},
        },
        "providers": {"deepseek": {"api_key": "test-key"}},
        "agents": {"defaults": {"model_preset": "ds"}},
    })
    provider_name = cfg.get_provider_name()
    assert provider_name == "deepseek"


def test_preset_with_auto_provider_uses_keyword_matching() -> None:
    cfg = Config.model_validate({
        "model_presets": {
            "auto-ds": {"model": "deepseek-chat", "provider": "auto"},
        },
        "providers": {"deepseek": {"api_key": "test-key"}},
        "agents": {"defaults": {"model_preset": "auto-ds"}},
    })
    provider_name = cfg.get_provider_name()
    assert provider_name == "deepseek"


def test_backward_compat_no_preset() -> None:
    """Existing configs without model_presets work exactly as before."""
    cfg = Config.model_validate({
        "providers": {"anthropic": {"api_key": "test-key"}},
        "agents": {"defaults": {"model": "anthropic/claude-opus-4-5"}},
    })
    assert cfg.resolve_preset().model == "anthropic/claude-opus-4-5"
    assert cfg.agents.defaults.model_preset is None
    assert cfg.get_provider_name() == "anthropic"


def test_resolve_preset_overrides_all_model_fields() -> None:
    """When model_preset is set, resolve_preset returns preset values, not individual fields."""
    cfg = Config.model_validate({
        "model_presets": {
            "gpt5": {"model": "gpt-5", "provider": "openai", "max_tokens": 16384},
        },
        "providers": {"openai": {"api_key": "test-key"}},
        "agents": {
            "defaults": {
                "model_preset": "gpt5",
                "model": "legacy-model",
                "max_tokens": 4096,
            },
        },
    })
    r = cfg.resolve_preset()
    assert r.model == "gpt-5"
    assert r.provider == "openai"
    assert r.max_tokens == 16384


def test_empty_model_presets_dict_is_harmless() -> None:
    cfg = Config.model_validate({"model_presets": {}})
    assert cfg.resolve_preset().model == "anthropic/claude-opus-4-5"
