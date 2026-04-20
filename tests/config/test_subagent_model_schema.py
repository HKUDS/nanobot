"""Test subagent model override fields on AgentDefaults.

Verifies that subagent_model / subagent_reasoning_effort / subagent_max_tokens
are optional (default None) and survive a snake_case + camelCase round-trip.
"""

from nanobot.config.schema import AgentDefaults


def test_defaults_are_none():
    d = AgentDefaults()
    assert d.subagent_model is None
    assert d.subagent_reasoning_effort is None
    assert d.subagent_max_tokens is None


def test_subagent_fields_from_snake_case():
    d = AgentDefaults.model_validate({
        "subagent_model": "anthropic/claude-haiku-4-5",
        "subagent_reasoning_effort": "low",
        "subagent_max_tokens": 4096,
    })
    assert d.subagent_model == "anthropic/claude-haiku-4-5"
    assert d.subagent_reasoning_effort == "low"
    assert d.subagent_max_tokens == 4096


def test_subagent_fields_from_camel_case():
    d = AgentDefaults.model_validate({
        "subagentModel": "anthropic/claude-haiku-4-5",
        "subagentReasoningEffort": "low",
        "subagentMaxTokens": 4096,
    })
    assert d.subagent_model == "anthropic/claude-haiku-4-5"
    assert d.subagent_reasoning_effort == "low"
    assert d.subagent_max_tokens == 4096
