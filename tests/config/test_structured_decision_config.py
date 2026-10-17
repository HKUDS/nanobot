from __future__ import annotations

import pytest

from nanobot.config.schema import Config, StructuredDecisionConfig


def test_structured_decision_config_defaults() -> None:
    settings = StructuredDecisionConfig()

    assert settings.enabled is False
    assert settings.provider == "openrouter"
    assert settings.protocol == "system_one"
    assert settings.model == "typesafe/jev-1.13"
    assert settings.timeout_s == 15.0


def test_structured_decision_config_accepts_and_serializes_camel_case() -> None:
    config = Config.model_validate({"structuredDecision": {"timeoutS": 30}})
    serialized = config.model_dump(by_alias=True)

    assert config.structured_decision.timeout_s == 30
    assert serialized["structuredDecision"]["timeoutS"] == 30


def test_structured_decision_config_rejects_invalid_model_and_timeout() -> None:
    with pytest.raises(ValueError):
        StructuredDecisionConfig.model_validate({"model": "  "})

    with pytest.raises(ValueError):
        StructuredDecisionConfig.model_validate({"timeoutS": 0})

    with pytest.raises(ValueError):
        StructuredDecisionConfig.model_validate({"timeoutS": 121})

    assert StructuredDecisionConfig.model_validate({"timeoutS": 120}).timeout_s == 120

    with pytest.raises(ValueError):
        StructuredDecisionConfig.model_validate({"protocol": "other"})

    for field in ("baseUrl", "base_url", "apiKey", "confidenceThreshold"):
        with pytest.raises(ValueError):
            StructuredDecisionConfig.model_validate({field: "not-allowed"})


def test_structured_decision_config_accepts_only_registered_providers() -> None:
    with pytest.raises(ValueError, match="Unsupported structuredDecision.provider"):
        Config.model_validate({"structuredDecision": {"provider": "not-configured"}})

    with pytest.raises(ValueError, match="Unsupported structuredDecision.provider"):
        Config.model_validate(
            {
                "structuredDecision": {"provider": "local_decider"},
                "providers": {"local_decider": {"apiBase": "https://chat.example/v1"}},
            }
        )

    assert Config().structured_decision.provider == "openrouter"


def test_root_config_does_not_expose_jev_or_endpoint_overrides() -> None:
    assert "jev" not in Config.model_fields
    assert not hasattr(Config(), "jev")
    assert "base_url" not in StructuredDecisionConfig.model_fields
