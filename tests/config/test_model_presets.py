import json
import os
import subprocess
import sys
import textwrap
import warnings

import pytest

from nanobot.agent.model_presets import load_model_preset_catalog
from nanobot.config.errors import ConfigLoadError
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


def test_model_preset_catalog_missing_env_reports_explicit_config_path(
    tmp_path,
    monkeypatch,
) -> None:
    name = "NANOBOT_TEST_CATALOG_MISSING_KEY"
    monkeypatch.delenv(name, raising=False)
    config_path = tmp_path / "custom.json"
    config_path.write_text(
        json.dumps({"providers": {"openrouter": {"apiKey": f"${{{name}}}"}}}),
        encoding="utf-8",
    )

    with pytest.raises(ConfigLoadError) as exc_info:
        load_model_preset_catalog(config_path)

    assert exc_info.value.path == config_path


def test_agent_timezone_rejects_unknown_iana_name() -> None:
    with pytest.raises(ValueError, match="unknown timezone"):
        Config.model_validate({"agents": {"defaults": {"timezone": "Not/AZone"}}})


def test_agent_timezones_use_packaged_data_without_system_database() -> None:
    script = textwrap.dedent(
        """\
        from zoneinfo import TZPATH

        from nanobot.config.schema import Config

        assert not TZPATH
        for name in ("UTC", "Asia/Shanghai"):
            config = Config.model_validate({"agents": {"defaults": {"timezone": name}}})
            serialized = config.model_dump(mode="json", by_alias=True)
            restored = Config.model_validate(serialized)
            assert restored.agents.defaults.timezone == name
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        env=os.environ | {"PYTHONTZPATH": ""},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


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


def test_legacy_model_preset_label_is_ignored() -> None:
    config = Config.model_validate({
        "modelPresets": {
            "gpt-5-6-sol": {
                "label": "Codex",
                "model": "openai-codex/gpt-5.6-luna",
            }
        }
    })

    assert set(config.model_presets) == {"gpt-5-6-sol"}
    assert "label" not in config.model_presets["gpt-5-6-sol"].model_dump()


@pytest.mark.parametrize(
    "model_presets",
    [
        {"Default": {"model": "openai/gpt-4.1"}},
        {
            "Fast": {"model": "openai/gpt-4.1-mini"},
            "fast": {"model": "openai/gpt-4.1"},
        },
        {" fast ": {"model": "openai/gpt-4.1"}},
    ],
)
def test_model_preset_names_accepted_by_earlier_releases_remain_loadable(
    model_presets: dict[str, dict[str, str]],
) -> None:
    config = Config.model_validate({"modelPresets": model_presets})

    assert list(config.model_presets) == list(model_presets)


def test_model_presets_serializes_with_camel_case_root_key() -> None:
    config = Config.model_validate({
        "model_presets": {
            "fast": {
                "model": "openai/gpt-4.1",
                "provider": "openai",
            }
        },
    })

    dumped = config.model_dump(mode="json", by_alias=True)

    assert "modelPresets" in dumped
    assert "model_presets" not in dumped
    assert dumped["modelPresets"]["fast"]["model"] == "openai/gpt-4.1"


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


def test_validator_accepts_dream_model_preset() -> None:
    config = Config.model_validate({
        "modelPresets": {
            "dream": {"model": "anthropic/claude-haiku-4-5", "provider": "anthropic"},
        },
        "agents": {"defaults": {"dream": {"modelOverride": "dream"}}},
    })

    assert config.agents.defaults.dream.model_override == "dream"


def test_validator_rejects_unknown_dream_model_preset() -> None:
    with pytest.raises(ValueError, match="Dream model preset 'unknown' not found"):
        Config.model_validate({
            "agents": {"defaults": {"dream": {"modelOverride": "unknown"}}},
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
