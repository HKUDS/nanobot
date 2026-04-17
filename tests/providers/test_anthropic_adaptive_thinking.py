from __future__ import annotations

import pytest

from nanobot.providers.anthropic_provider import AnthropicProvider


def _build(model: str, reasoning_effort: str | None = None) -> dict:
    provider = AnthropicProvider(api_key="sk-ant-api03-fake")
    return provider._build_kwargs(
        messages=[{"role": "user", "content": "hello"}],
        tools=None,
        model=model,
        max_tokens=4096,
        temperature=0.7,
        reasoning_effort=reasoning_effort,
        tool_choice=None,
        supports_caching=False,
    )


@pytest.mark.parametrize(
    "model",
    [
        "claude-opus-4-6-20251010",
        "claude-opus-4.7",
        "claude-opus-4.7-20251010",
        "claude-sonnet-4-6-20250514",
        "claude-sonnet-4.7",
        "claude-sonnet-4.7-20251101",
    ],
)
def test_adaptive_thinking_auto_enabled_for_4x(model: str) -> None:
    """Claude 4.x models should auto-enable adaptive thinking when no reasoning_effort is given."""
    kwargs = _build(model, reasoning_effort=None)
    assert kwargs.get("thinking") == {"type": "adaptive"}
    assert "output_config" in kwargs
    assert kwargs["output_config"]["effort"] == "medium"
    assert "temperature" not in kwargs


def test_non_adaptive_model_uses_budget_thinking() -> None:
    """Older models (e.g. 3.7 Sonnet) should use budget-based thinking."""
    kwargs = _build("claude-3-7-sonnet-20250219", reasoning_effort="high")
    assert kwargs.get("thinking") == {"type": "enabled", "budget_tokens": 8192}
    assert "output_config" not in kwargs
    assert kwargs["temperature"] == 1.0


def test_opus_accepts_max_effort() -> None:
    """Opus 4.x should allow 'max' effort."""
    kwargs = _build("claude-opus-4.7", reasoning_effort="max")
    assert kwargs["output_config"]["effort"] == "max"


def test_opus_accepts_xhigh_effort() -> None:
    """Opus 4.x should allow 'xhigh' effort."""
    kwargs = _build("claude-opus-4.7", reasoning_effort="xhigh")
    assert kwargs["output_config"]["effort"] == "xhigh"


@pytest.mark.parametrize(
    "model",
    [
        "claude-sonnet-4.7",
        "claude-sonnet-4-7-20251101",
    ],
)
def test_sonnet_downgrades_max_to_high(model: str) -> None:
    """Non-Opus 4.x should downgrade 'max' to 'high'."""
    kwargs = _build(model, reasoning_effort="max")
    assert kwargs["output_config"]["effort"] == "high"


@pytest.mark.parametrize(
    "model",
    [
        "claude-sonnet-4.7",
        "claude-sonnet-4-7-20251101",
    ],
)
def test_sonnet_keeps_xhigh(model: str) -> None:
    """Non-Opus 4.x keeps 'xhigh' as-is (SDK will validate)."""
    kwargs = _build(model, reasoning_effort="xhigh")
    assert kwargs["output_config"]["effort"] == "xhigh"


def test_no_thinking_when_reasoning_disabled() -> None:
    """When reasoning_effort is None and model is not adaptive, thinking is disabled."""
    kwargs = _build("claude-3-5-sonnet-20240620", reasoning_effort=None)
    assert "thinking" not in kwargs
    assert kwargs["temperature"] == 0.7
