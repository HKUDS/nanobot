"""Tests for Anthropic provider thinking / reasoning_effort modes."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from nanobot.providers.anthropic_provider import AnthropicProvider


def _make_provider(model: str = "claude-sonnet-4-6") -> AnthropicProvider:
    with patch("anthropic.AsyncAnthropic"):
        return AnthropicProvider(api_key="sk-test", default_model=model)


def _build(provider: AnthropicProvider, reasoning_effort: str | None, **overrides):
    defaults = dict(
        messages=[{"role": "user", "content": "hello"}],
        tools=None,
        model=None,
        max_tokens=4096,
        temperature=0.7,
        reasoning_effort=reasoning_effort,
        tool_choice=None,
        supports_caching=False,
    )
    defaults.update(overrides)
    return provider._build_kwargs(**defaults)


def test_adaptive_sets_type_adaptive() -> None:
    kw = _build(_make_provider(), "adaptive")
    assert kw["thinking"] == {"type": "adaptive"}


def test_adaptive_forces_temperature_one() -> None:
    kw = _build(_make_provider(), "adaptive")
    assert kw["temperature"] == 1.0


def test_adaptive_does_not_inflate_max_tokens() -> None:
    kw = _build(_make_provider(), "adaptive", max_tokens=2048)
    assert kw["max_tokens"] == 2048


def test_adaptive_no_budget_tokens() -> None:
    kw = _build(_make_provider(), "adaptive")
    assert "budget_tokens" not in kw["thinking"]


def test_high_uses_enabled_with_budget() -> None:
    kw = _build(_make_provider(), "high", max_tokens=4096)
    assert kw["thinking"]["type"] == "enabled"
    assert kw["thinking"]["budget_tokens"] == max(8192, 4096)
    assert kw["max_tokens"] >= kw["thinking"]["budget_tokens"] + 4096


def test_low_uses_small_budget() -> None:
    kw = _build(_make_provider(), "low")
    assert kw["thinking"] == {"type": "enabled", "budget_tokens": 1024}


def test_none_does_not_enable_thinking() -> None:
    kw = _build(_make_provider(), None)
    assert "thinking" not in kw
    assert kw["temperature"] == 0.7


def test_empty_effort_does_not_enable_thinking() -> None:
    kw = _build(_make_provider(), "")
    assert "thinking" not in kw
    assert kw["temperature"] == 0.7


def test_opus_4_7_omits_temperature_adaptive() -> None:
    kw = _build(_make_provider("claude-opus-4-7"), "adaptive")
    assert "temperature" not in kw
    assert kw["thinking"] == {"type": "adaptive"}


def test_opus_4_7_high_uses_adaptive_effort() -> None:
    kw = _build(_make_provider("claude-opus-4-7"), "high", max_tokens=4096)
    assert "temperature" not in kw
    assert kw["thinking"] == {"type": "adaptive"}
    assert kw["output_config"] == {"effort": "high"}
    assert kw["max_tokens"] == 4096


def test_opus_4_7_omits_temperature_none() -> None:
    """Without thinking, opus-4-7 must still omit temperature (API rejects it)."""
    kw = _build(_make_provider("claude-opus-4-7"), None)
    assert "temperature" not in kw
    assert "thinking" not in kw


def test_opus_4_8_omits_temperature_adaptive() -> None:
    kw = _build(_make_provider("claude-opus-4-8"), "adaptive")
    assert "temperature" not in kw


def test_opus_4_8_high_uses_adaptive_effort() -> None:
    kw = _build(_make_provider("claude-opus-4-8"), "high", max_tokens=4096)
    assert "temperature" not in kw
    assert kw["thinking"] == {"type": "adaptive"}
    assert kw["output_config"] == {"effort": "high"}


def test_opus_4_8_omits_temperature_none() -> None:
    kw = _build(_make_provider("claude-opus-4-8"), None)
    assert "temperature" not in kw


def test_fable_omits_temperature_adaptive() -> None:
    kw = _build(_make_provider("claude-fable-5"), "adaptive")
    assert "temperature" not in kw


def test_fable_high_uses_adaptive_effort() -> None:
    kw = _build(_make_provider("claude-fable-5"), "high", max_tokens=4096)
    assert "temperature" not in kw
    assert kw["thinking"] == {"type": "adaptive"}
    assert kw["output_config"] == {"effort": "high"}


def test_fable_omits_temperature_none() -> None:
    kw = _build(_make_provider("claude-fable-5"), None)
    assert "temperature" not in kw


def test_sonnet_5_omits_temperature_adaptive() -> None:
    kw = _build(_make_provider("claude-sonnet-5"), "adaptive")
    assert "temperature" not in kw
    assert kw["thinking"] == {"type": "adaptive"}


def test_sonnet_5_high_uses_adaptive_effort() -> None:
    kw = _build(_make_provider("claude-sonnet-5"), "high", max_tokens=4096)
    assert "temperature" not in kw
    assert kw["thinking"] == {"type": "adaptive"}
    assert kw["output_config"] == {"effort": "high"}


def test_sonnet_5_omits_temperature_none() -> None:
    kw = _build(_make_provider("anthropic/claude-sonnet-5"), "none")
    assert "temperature" not in kw
    assert kw["thinking"] == {"type": "disabled"}
    assert "output_config" not in kw


def test_mythos_preview_omits_temperature_but_keeps_manual_budget() -> None:
    kw = _build(_make_provider("claude-mythos-preview"), "high", max_tokens=4096)
    assert "temperature" not in kw
    assert kw["thinking"] == {"type": "enabled", "budget_tokens": 8192}
    assert "output_config" not in kw


@pytest.mark.parametrize(
    "reasoning_effort", [None, "none", "adaptive", "low", "medium", "high", "xhigh", "max"]
)
def test_opus_5_omits_temperature(reasoning_effort: str | None) -> None:
    kw = _build(_make_provider("claude-opus-5"), reasoning_effort)
    assert "temperature" not in kw


def test_opus_5_none_disables_default_thinking() -> None:
    kw = _build(_make_provider("claude-opus-5"), "none")
    assert kw["thinking"] == {"type": "disabled"}
    assert "output_config" not in kw


def test_opus_5_unset_preserves_provider_default() -> None:
    kw = _build(_make_provider("claude-opus-5"), None)
    assert "thinking" not in kw
    assert "output_config" not in kw


@pytest.mark.parametrize("reasoning_effort", ["low", "medium", "high", "xhigh", "max"])
def test_opus_5_uses_adaptive_thinking_with_effort(reasoning_effort: str) -> None:
    kw = _build(_make_provider("claude-opus-5"), reasoning_effort, max_tokens=4096)
    assert kw["thinking"] == {"type": "adaptive"}
    assert kw["output_config"] == {"effort": reasoning_effort}
    assert kw["max_tokens"] == 4096


def test_dated_opus_5_model_uses_family_capabilities() -> None:
    kw = _build(_make_provider("claude-opus-5-20260724"), "medium")
    assert "temperature" not in kw
    assert kw["thinking"] == {"type": "adaptive"}
    assert kw["output_config"] == {"effort": "medium"}


def test_dated_opus_4_model_does_not_treat_date_as_minor_version() -> None:
    kw = _build(_make_provider("claude-opus-4-20250514"), "high")
    assert kw["temperature"] == 1.0
    assert kw["thinking"] == {"type": "enabled", "budget_tokens": 8192}
    assert "output_config" not in kw


def test_ordinary_model_sends_temperature() -> None:
    kw = _build(_make_provider("claude-sonnet-4-6"), None)
    assert kw["temperature"] == 0.7


def test_reasoning_effort_string_none_does_not_enable_thinking() -> None:
    """reasoning_effort='none' must not enable thinking — treated same as disabled."""
    kw = _build(_make_provider(), "none")
    assert "thinking" not in kw
    assert kw["temperature"] == 0.7
