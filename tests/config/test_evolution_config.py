"""Tests for EvolutionConfig schema."""

import pytest
from pydantic import ValidationError

from nanobot.config.schema import (
    AgentDefaults,
    EvolutionConfig,
    EvolutionGepaConfig,
    EvolutionPostTaskConfig,
    EvolutionTraceConfig,
)


def test_evolution_trace_config_defaults() -> None:
    cfg = EvolutionTraceConfig()
    assert cfg.retention_days == 30


def test_evolution_post_task_config_defaults() -> None:
    cfg = EvolutionPostTaskConfig()
    assert cfg.min_tool_calls == 3
    assert cfg.cooldown_minutes == 10
    assert cfg.min_confidence == 0.8
    assert cfg.auto_apply is False
    assert cfg.model is None
    assert cfg.llm_timeout_s == 120.0
    assert cfg.proposal_retention_days == 30


def test_evolution_gepa_config_defaults() -> None:
    cfg = EvolutionGepaConfig()
    assert cfg.enable is False
    assert cfg.interval_hours is None
    assert cfg.model is None
    assert cfg.max_budget_usd == 10.0
    assert cfg.min_traces == 3
    assert cfg.max_skills_per_run == 1
    assert cfg.notify_on_complete is False
    assert cfg.notify_channel is None
    assert cfg.notify_chat_id is None


def test_evolution_gepa_build_schedule_manual_only() -> None:
    cfg = EvolutionGepaConfig(enable=True)

    assert cfg.build_schedule("UTC") is None
    assert cfg.describe_schedule() == "manual only"


def test_evolution_gepa_build_schedule_every_hours() -> None:
    cfg = EvolutionGepaConfig(enable=True, interval_hours=168)

    schedule = cfg.build_schedule("Asia/Shanghai")

    assert schedule is not None
    assert schedule.kind == "every"
    assert schedule.every_ms == 168 * 3_600_000
    assert schedule.tz == "Asia/Shanghai"
    assert cfg.describe_schedule() == "every 168h"


def test_evolution_config_defaults() -> None:
    cfg = EvolutionConfig()

    assert cfg.enable is True
    assert cfg.trace.retention_days == 30
    assert cfg.post_task.min_tool_calls == 3
    assert cfg.post_task.cooldown_minutes == 10
    assert cfg.post_task.min_confidence == 0.8
    assert cfg.post_task.llm_timeout_s == 120.0
    assert cfg.post_task.auto_apply is False
    assert cfg.gepa.enable is False
    assert cfg.recording_enabled() is True
    assert cfg.post_task_enabled() is True
    assert cfg.gepa_enabled() is False


def test_evolution_config_accepts_nested_camel_case() -> None:
    cfg = EvolutionConfig.model_validate(
        {
            "enable": True,
            "trace": {"retentionDays": 14},
            "postTask": {
                "minToolCalls": 8,
                "cooldownMinutes": 10,
                "minConfidence": 0.85,
                "autoApply": True,
                "model": "openrouter/mini",
                "proposalRetentionDays": 7,
            },
            "gepa": {
                "enable": True,
                "intervalHours": 168.0,
                "model": "openrouter/sonnet",
                "maxBudgetUsd": 5.0,
                "minTraces": 5,
                "maxSkillsPerRun": 2,
            },
        }
    )

    assert cfg.enable is True
    assert cfg.trace.retention_days == 14
    assert cfg.post_task.min_tool_calls == 8
    assert cfg.post_task.cooldown_minutes == 10
    assert cfg.post_task.min_confidence == 0.85
    assert cfg.post_task.auto_apply is True
    assert cfg.post_task.model == "openrouter/mini"
    assert cfg.post_task.proposal_retention_days == 7
    assert cfg.gepa.enable is True
    assert cfg.gepa.interval_hours == 168.0
    assert cfg.gepa.model == "openrouter/sonnet"
    assert cfg.gepa.max_budget_usd == 5.0
    assert cfg.gepa.min_traces == 5
    assert cfg.gepa.max_skills_per_run == 2
    assert cfg.recording_enabled() is True
    assert cfg.post_task_enabled() is True
    assert cfg.gepa_enabled() is True


def test_evolution_config_serializes_nested_camel_case() -> None:
    cfg = EvolutionConfig(
        enable=True,
        post_task=EvolutionPostTaskConfig(auto_apply=True),
        gepa=EvolutionGepaConfig(enable=True),
    )
    dumped = cfg.model_dump(by_alias=True)

    assert dumped["enable"] is True
    assert dumped["trace"]["retentionDays"] == 30
    assert dumped["postTask"]["autoApply"] is True
    assert dumped["postTask"]["minToolCalls"] == 3
    assert dumped["gepa"]["enable"] is True
    assert dumped["gepa"]["maxBudgetUsd"] == 10.0
    assert dumped["gepa"]["minTraces"] == 3
    assert dumped["gepa"]["maxSkillsPerRun"] == 1


def test_agent_defaults_includes_evolution() -> None:
    defaults = AgentDefaults()

    assert isinstance(defaults.evolution, EvolutionConfig)
    assert defaults.evolution.enable is True


def test_agent_defaults_nested_evolution_from_json() -> None:
    defaults = AgentDefaults.model_validate(
        {
            "evolution": {
                "enable": True,
                "postTask": {
                    "autoApply": False,
                    "minToolCalls": 6,
                },
            }
        }
    )

    assert defaults.evolution.enable is True
    assert defaults.evolution.post_task.auto_apply is False
    assert defaults.evolution.post_task.min_tool_calls == 6


def test_gepa_disabled_when_master_switch_off() -> None:
    cfg = EvolutionConfig(enable=False, gepa=EvolutionGepaConfig(enable=True))
    assert cfg.gepa_enabled() is False


@pytest.mark.parametrize(
    ("model", "field", "value"),
    [
        (EvolutionPostTaskConfig, "min_confidence", 1.5),
        (EvolutionPostTaskConfig, "min_tool_calls", 0),
        (EvolutionTraceConfig, "retention_days", 0),
        (EvolutionGepaConfig, "max_budget_usd", 0),
        (EvolutionGepaConfig, "min_traces", 0),
        (EvolutionGepaConfig, "max_skills_per_run", 0),
        (EvolutionGepaConfig, "interval_hours", -1),
    ],
)
def test_evolution_subconfig_rejects_out_of_range(
    model: type[EvolutionPostTaskConfig | EvolutionTraceConfig | EvolutionGepaConfig],
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValidationError):
        model(**{field: value})
