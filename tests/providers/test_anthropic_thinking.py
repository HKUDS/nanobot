"""Tests for Anthropic provider thinking / reasoning_effort modes."""

from __future__ import annotations

from unittest.mock import patch

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
