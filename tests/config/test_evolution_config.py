from __future__ import annotations

import pytest
from pydantic import ValidationError

from nanobot.config.schema import EvolutionConfig


def test_evolution_defaults_are_private_and_observe_only() -> None:
    config = EvolutionConfig()

    assert config.enabled is False
    assert config.mode == "observe"
    assert config.capture_content is False
    assert config.auto_apply_max_risk == 0


def test_evolution_storage_must_be_workspace_relative() -> None:
    with pytest.raises(ValidationError, match="workspace-relative"):
        EvolutionConfig(storage_dir="../outside")
    with pytest.raises(ValidationError, match="workspace-relative"):
        EvolutionConfig(storage_dir="/tmp/evolution")


def test_auto_apply_requires_controlled_mode() -> None:
    with pytest.raises(ValidationError, match="controlled mode"):
        EvolutionConfig(mode="propose", auto_apply_max_risk=1)

    assert EvolutionConfig(mode="controlled", auto_apply_max_risk=1).auto_apply_max_risk == 1
