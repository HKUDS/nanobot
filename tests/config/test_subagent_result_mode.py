"""Tests for subagent result notification configuration."""

import pytest
from pydantic import ValidationError

from nanobot.config.schema import AgentDefaults, Config


def test_subagent_result_mode_defaults_to_realtime() -> None:
    assert AgentDefaults().subagent_result_mode == "realtime"
    assert Config().agents.defaults.subagent_result_mode == "realtime"


def test_subagent_result_mode_accepts_camel_and_snake_aliases() -> None:
    camel = Config.model_validate({
        "agents": {"defaults": {"subagentResultMode": "aggregated"}}
    })
    snake = Config.model_validate({
        "agents": {"defaults": {"subagent_result_mode": "aggregated"}}
    })

    assert camel.agents.defaults.subagent_result_mode == "aggregated"
    assert snake.agents.defaults.subagent_result_mode == "aggregated"
    assert (
        camel.model_dump(by_alias=True)["agents"]["defaults"]["subagentResultMode"]
        == "aggregated"
    )


def test_subagent_result_mode_rejects_unknown_value() -> None:
    with pytest.raises(ValidationError):
        AgentDefaults(subagent_result_mode="batch")
