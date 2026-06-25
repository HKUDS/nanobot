import warnings

import pytest

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


def test_provider_api_type_accepts_exact_values_only() -> None:
    config = Config.model_validate({
        "providers": {
            "openai": {
                "apiKey": "sk-test",
                "apiType": "responses",
            }
        }
    })
    assert config.providers.openai.api_type == "responses"

    with pytest.raises(ValueError):
        Config.model_validate({
            "providers": {
                "openai": {
                    "apiKey": "sk-test",
                    "apiType": "response",
                }
            }
        })


def test_provider_api_type_is_openai_only() -> None:
    with pytest.raises(ValueError, match="only supported"):
        Config.model_validate({
            "providers": {
                "custom": {
                    "apiBase": "https://example.test/v1",
                    "apiType": "responses",
                }
            }
        })

    with pytest.raises(ValueError, match="only supported"):
        Config.model_validate({
            "providers": {
                "my-company-api": {
                    "apiBase": "https://example.test/v1",
                    "apiType": "responses",
                }
            }
        })


@pytest.mark.parametrize("provider_name", ["openai-codex", "github-copilot", "lm-studio"])
def test_dynamic_custom_provider_rejects_builtin_provider_aliases(provider_name: str) -> None:
    with pytest.raises(ValueError, match="conflicts with built-in provider"):
        Config.model_validate({
            "providers": {
                provider_name: {
                    "apiBase": "https://example.test/v1",
                }
            }
        })


def test_custom_provider_fallback_uses_model_extra_without_pydantic_warnings() -> None:
    config = Config.model_validate({
        "agents": {
            "defaults": {
                "model": "unmatched-model",
            }
        },
        "providers": {
            "my-company-api": {
                "apiBase": "https://example.test/v1",
            }
        },
    })

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert config.get_provider_name() == "my-company-api"


def test_dynamic_custom_provider_prefix_matches_camel_case_key() -> None:
    config = Config.model_validate({
        "agents": {
            "defaults": {
                "provider": "auto",
                "model": "companyProxy/gpt-4o-mini",
            }
        },
        "providers": {
            "otherProxy": {
                "apiBase": "https://other.example.test/v1",
            },
            "companyProxy": {
                "apiBase": "https://company.example.test/v1",
            },
        },
    })

    assert config.get_provider_name() == "companyProxy"
    assert config.get_api_base() == "https://company.example.test/v1"


def test_dynamic_custom_provider_prefix_does_not_fall_through_when_base_missing() -> None:
    config = Config.model_validate({
        "agents": {
            "defaults": {
                "provider": "auto",
                "model": "companyProxy/gpt-4o-mini",
            }
        },
        "providers": {
            "otherProxy": {
                "apiBase": "https://other.example.test/v1",
            },
            "companyProxy": {
                "apiKey": "sk-company",
            },
        },
    })

    assert config.get_provider_name() == "companyProxy"
    assert config.get_api_base() is None


def test_legacy_defaults_config_without_presets_still_resolves() -> None:
    config = Config.model_validate({
        "agents": {
            "defaults": {
                "model": "openai/gpt-4.1",
                "provider": "openai",
                "maxTokens": 4096,
                "contextWindowTokens": 128_000,
                "temperature": 0.2,
                "reasoningEffort": "low",
            }
        }
    })

    resolved = config.resolve_preset()
    assert config.agents.defaults.model_preset is None
    assert config.model_presets == {}
    assert resolved.model == "openai/gpt-4.1"
    assert resolved.provider == "openai"
    assert resolved.max_tokens == 4096
    assert resolved.context_window_tokens == 128_000
    assert resolved.temperature == 0.2
    assert resolved.reasoning_effort == "low"


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


def test_default_preset_is_agents_defaults_even_when_named_preset_is_active() -> None:
    config = Config.model_validate({
        "agents": {
            "defaults": {
                "model": "openai/gpt-4.1",
                "provider": "openai",
                "modelPreset": "fast",
            }
        },
        "modelPresets": {
            "fast": {"model": "openai/gpt-4.1-mini", "provider": "openai"},
        },
    })

    assert config.resolve_preset().model == "openai/gpt-4.1-mini"
    assert config.resolve_preset("default").model == "openai/gpt-4.1"


def test_model_presets_accepts_camel_case_root_key() -> None:
    config = Config.model_validate({
        "modelPresets": {
            "fast": {
                "model": "openai/gpt-4.1",
                "provider": "openai",
            }
        },
    })

    assert config.model_presets["fast"].model == "openai/gpt-4.1"
    assert config.model_presets["fast"].provider == "openai"


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


def test_model_preset_accepts_explicit_default_name() -> None:
    config = Config.model_validate({
        "agents": {
            "defaults": {
                "model": "openai/gpt-4.1",
                "modelPreset": "default",
            }
        }
    })

    assert config.resolve_preset().model == "openai/gpt-4.1"


def test_model_presets_rejects_reserved_default_name() -> None:
    import pytest

    with pytest.raises(ValueError, match="model_preset name 'default' is reserved"):
        Config.model_validate({
            "modelPresets": {
                "default": {"model": "custom-model"},
            },
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


def test_match_provider_routes_forced_novita_model_api_models() -> None:
    config = Config.model_validate({
        "providers": {
            "novita": {"apiKey": "sk-test"},
        },
        "agents": {
            "defaults": {
                "model": "deepseek-v4-pro",
                "provider": "novita",
            }
        },
    })

    assert config.get_provider_name() == "novita"
    assert config.get_api_base() == "https://api.novita.ai/openai"


def test_transcription_only_provider_is_not_chat_fallback() -> None:
    config = Config.model_validate({
        "providers": {
            "assemblyai": {"apiKey": "aai-test"},
        },
        "agents": {
            "defaults": {
                "model": "assemblyai/universal-3-pro",
            }
        },
    })

    assert config.get_provider_name() is None


def test_spawn_presets_validator_rejects_unknown_entry() -> None:
    import pytest

    with pytest.raises(ValueError, match="spawn_presets entry 'nonexistent' not found"):
        Config.model_validate({
            "modelPresets": {
                "fast": {"model": "openai/gpt-4.1"},
            },
            "agents": {
                "defaults": {
                    "spawnPresets": ["fast", "nonexistent"],
                }
            },
        })


def test_spawn_presets_validator_accepts_valid_entries() -> None:
    config = Config.model_validate({
        "modelPresets": {
            "fast": {"model": "openai/gpt-4.1"},
            "smart": {"model": "anthropic/claude-opus-4-5"},
        },
        "agents": {
            "defaults": {
                "spawnPresets": ["fast", "smart"],
            }
        },
    })
    assert config.agents.defaults.spawn_presets == ["fast", "smart"]
