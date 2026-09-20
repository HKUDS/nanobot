from __future__ import annotations

import pytest

from nanobot.config.schema import Config, JevConfig


def test_jev_config_defaults() -> None:
    cfg = JevConfig()

    assert cfg.enabled is False
    assert cfg.model == "typesafe/jev-1.13"
    assert cfg.threshold == 0.5
    assert cfg.timeout_s == 15.0


def test_jev_config_accepts_snake_case_and_serializes_camel_case() -> None:
    cfg = JevConfig.model_validate({"timeout_s": 30.0})
    dumped = cfg.model_dump(by_alias=True)

    assert cfg.timeout_s == 30.0
    assert dumped["timeoutS"] == 30.0
    assert "timeout_s" not in dumped


def test_jev_config_rejects_invalid_threshold() -> None:
    with pytest.raises(ValueError):
        JevConfig.model_validate({"threshold": 1.5})

    with pytest.raises(ValueError):
        JevConfig.model_validate({"threshold": -0.1})


def test_jev_config_rejects_invalid_timeout() -> None:
    with pytest.raises(ValueError):
        JevConfig.model_validate({"timeout_s": 0})

    with pytest.raises(ValueError):
        JevConfig.model_validate({"timeout_s": 121})


def test_top_level_jev_config_is_optional_and_independent() -> None:
    cfg = Config.model_validate({"jev": {"enabled": True, "threshold": 0.75}})

    assert cfg.jev.enabled is True
    assert cfg.jev.threshold == 0.75
    assert cfg.jev.model == "typesafe/jev-1.13"
    assert cfg.providers.openrouter.api_key is None
    assert "api_key" not in cfg.jev.model_dump()


def test_jev_config_cannot_store_api_key() -> None:
    with pytest.raises(ValueError):
        JevConfig.model_validate({"api_key": "secret"})
