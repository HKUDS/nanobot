from nanobot.config.schema import Config


def test_resolve_preset_returns_defaults_when_no_preset() -> None:
    config = Config()
    resolved = config.resolve_preset()
    assert resolved.model == config.agents.defaults.model
    assert resolved.provider == config.agents.defaults.provider
    assert resolved.max_tokens == config.agents.defaults.max_tokens
    assert resolved.context_window_tokens == config.agents.defaults.context_window_tokens
    assert resolved.temperature == config.agents.defaults.temperature
    assert resolved.reasoning_effort == config.agents.defaults.reasoning_effort


def test_resolve_preset_returns_active_preset() -> None:
    config = Config.model_validate({
        "model_presets": {
            "fast": {
                "model": "openai/gpt-4.1",
                "provider": "openai",
                "maxTokens": 4096,
                "contextWindowTokens": 32_768,
                "temperature": 0.5,
                "reasoningEffort": "low",
            }
        },
        "agents": {
            "defaults": {
                "modelPreset": "fast",
            }
        },
    })
    resolved = config.resolve_preset()
    assert resolved.model == "openai/gpt-4.1"
    assert resolved.provider == "openai"
    assert resolved.max_tokens == 4096
    assert resolved.context_window_tokens == 32_768
    assert resolved.temperature == 0.5
    assert resolved.reasoning_effort == "low"


def test_resolve_preset_can_target_named_preset_without_activating() -> None:
    config = Config.model_validate({
        "model_presets": {
            "fast": {"model": "openai/gpt-4.1", "provider": "openai"},
            "deep": {"model": "anthropic/claude-opus-4-5", "provider": "anthropic"},
        },
        "agents": {"defaults": {"modelPreset": "fast"}},
    })

    resolved = config.resolve_preset("deep")
    assert resolved.model == "anthropic/claude-opus-4-5"
    assert resolved.provider == "anthropic"


def test_validator_rejects_unknown_preset() -> None:
    import pytest
    with pytest.raises(ValueError, match="model_preset 'unknown' not found in model_presets"):
        Config.model_validate({
            "agents": {
                "defaults": {
                    "modelPreset": "unknown",
                }
            }
        })


def test_resolve_preset_rejects_unknown_named_preset() -> None:
    import pytest
    with pytest.raises(KeyError, match="model_preset 'missing' not found"):
        Config().resolve_preset("missing")


def test_match_provider_uses_preset_model() -> None:
    config = Config.model_validate({
        "providers": {
            "openai": {"apiKey": "sk-test"},
        },
        "model_presets": {
            "fast": {
                "model": "openai/gpt-4.1",
                "provider": "openai",
            }
        },
        "agents": {
            "defaults": {
                "modelPreset": "fast",
            }
        },
    })
    name = config.get_provider_name()
    assert name == "openai"


def test_match_provider_uses_preset_provider_when_forced() -> None:
    config = Config.model_validate({
        "providers": {
            "anthropic": {"apiKey": "sk-test"},
        },
        "model_presets": {
            "fast": {
                "model": "anthropic/claude-opus-4-5",
                "provider": "anthropic",
            }
        },
        "agents": {
            "defaults": {
                "modelPreset": "fast",
            }
        },
    })
    name = config.get_provider_name()
    assert name == "anthropic"
