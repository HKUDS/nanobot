"""Tests for Xiaomi MiMo thinking-mode toggle via reasoning_effort.

The hosted Xiaomi MiMo API (api.xiaomimimo.com) accepts
``{"thinking": {"type": "enabled"|"disabled"}}`` in the request body
to toggle reasoning. Source: https://platform.xiaomimimo.com/docs/en-US/api/chat/openai-api

The thinking_type style already exists in _THINKING_STYLE_MAP and
produces exactly this shape, so MiMo just needs to opt in via its
ProviderSpec.thinking_style.

Default thinking behavior per Xiaomi docs:
  - mimo-v2-flash: disabled
  - mimo-v2.5-pro, mimo-v2.5, mimo-v2-pro, mimo-v2-omni: enabled

Without an explicit reasoning_effort, nanobot must not send the
thinking field so the provider default is preserved (issue #3585).
"""

from __future__ import annotations

from typing import Any

from nanobot.config.schema import ProvidersConfig
from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.providers.registry import PROVIDERS


def _mimo_spec():
    """Return the registered xiaomi_mimo ProviderSpec."""
    specs = {s.name: s for s in PROVIDERS}
    return specs["xiaomi_mimo"]


def _openrouter_spec():
    """Return the registered OpenRouter ProviderSpec (no thinking_style)."""
    specs = {s.name: s for s in PROVIDERS}
    return specs["openrouter"]


def _mimo_provider() -> OpenAICompatProvider:
    return OpenAICompatProvider(
        api_key="test-key",
        default_model="mimo-v2.5-pro",
        spec=_mimo_spec(),
    )


def _openrouter_provider(default_model: str) -> OpenAICompatProvider:
    """Provider configured as OpenRouter (gateway, no thinking_style on spec)."""
    return OpenAICompatProvider(
        api_key="sk-or-test",
        default_model=default_model,
        spec=_openrouter_spec(),
    )


def _simple_messages() -> list[dict[str, Any]]:
    return [{"role": "user", "content": "hello"}]


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_xiaomi_mimo_config_field_exists():
    """ProvidersConfig should expose a xiaomi_mimo field."""
    config = ProvidersConfig()
    assert hasattr(config, "xiaomi_mimo")


def test_xiaomi_mimo_uses_thinking_type_style():
    """MiMo hosted API uses {"thinking": {"type": ...}}, the thinking_type style."""
    spec = _mimo_spec()
    assert spec.thinking_style == "thinking_type"
    assert spec.backend == "openai_compat"
    assert spec.default_api_base == "https://api.xiaomimimo.com/v1"


# ---------------------------------------------------------------------------
# _build_kwargs wire-format
# ---------------------------------------------------------------------------


def test_mimo_reasoning_effort_none_disables_thinking():
    """reasoning_effort="none" should send thinking.type="disabled"."""
    provider = _mimo_provider()
    kwargs = provider._build_kwargs(
        messages=_simple_messages(),
        tools=None, model=None, max_tokens=100,
        temperature=0.7, reasoning_effort="none", tool_choice=None,
    )
    # reasoning_effort itself must NOT be sent when value is "none"
    assert "reasoning_effort" not in kwargs
    # The disable signal must be in extra_body
    assert kwargs["extra_body"] == {"thinking": {"type": "disabled"}}


def test_mimo_reasoning_effort_medium_enables_thinking():
    """reasoning_effort="medium" should send thinking.type="enabled"."""
    provider = _mimo_provider()
    kwargs = provider._build_kwargs(
        messages=_simple_messages(),
        tools=None, model=None, max_tokens=100,
        temperature=0.7, reasoning_effort="medium", tool_choice=None,
    )
    assert kwargs.get("reasoning_effort") == "medium"
    assert kwargs["extra_body"] == {"thinking": {"type": "enabled"}}


def test_mimo_reasoning_effort_low_enables_thinking():
    """Any non-none/minimal effort enables thinking."""
    provider = _mimo_provider()
    kwargs = provider._build_kwargs(
        messages=_simple_messages(),
        tools=None, model=None, max_tokens=100,
        temperature=0.7, reasoning_effort="low", tool_choice=None,
    )
    assert kwargs["extra_body"] == {"thinking": {"type": "enabled"}}


def test_mimo_reasoning_effort_unset_preserves_provider_default():
    """When reasoning_effort is None, no thinking field is sent.

    This preserves the provider default (varies by model per Xiaomi docs).
    Required so that omitting the config field behaves the same as before
    this fix — no behavior change for users who never set reasoning_effort.
    """
    provider = _mimo_provider()
    kwargs = provider._build_kwargs(
        messages=_simple_messages(),
        tools=None, model=None, max_tokens=100,
        temperature=0.7, reasoning_effort=None, tool_choice=None,
    )
    assert "reasoning_effort" not in kwargs
    assert "extra_body" not in kwargs


# ---------------------------------------------------------------------------
# Gateway path: MiMo routed through OpenRouter (no spec.thinking_style)
# ---------------------------------------------------------------------------


def test_mimo_via_openrouter_reasoning_effort_none_disables_thinking():
    """OpenRouter routes MiMo as "xiaomi/mimo-v2.5-pro"; the openrouter spec
    has no thinking_style, so the disable signal must come from the
    model-name path (#3845)."""
    provider = _openrouter_provider("xiaomi/mimo-v2.5-pro")
    kwargs = provider._build_kwargs(
        messages=_simple_messages(),
        tools=None, model=None, max_tokens=100,
        temperature=0.7, reasoning_effort="none", tool_choice=None,
    )
    assert "reasoning_effort" not in kwargs
    assert kwargs["extra_body"] == {"thinking": {"type": "disabled"}}


def test_mimo_via_openrouter_reasoning_effort_medium_enables_thinking():
    """Same as the direct path: any non-none/minimal effort enables thinking."""
    provider = _openrouter_provider("xiaomi/mimo-v2.5-pro")
    kwargs = provider._build_kwargs(
        messages=_simple_messages(),
        tools=None, model=None, max_tokens=100,
        temperature=0.7, reasoning_effort="medium", tool_choice=None,
    )
    assert kwargs.get("reasoning_effort") == "medium"
    assert kwargs["extra_body"] == {"thinking": {"type": "enabled"}}


def test_mimo_via_openrouter_bare_slug_also_matches():
    """Bare "mimo-v2.5-pro" (no publisher prefix) must also match the
    allowlist, since gateways sometimes accept either form."""
    provider = _openrouter_provider("mimo-v2.5-pro")
    kwargs = provider._build_kwargs(
        messages=_simple_messages(),
        tools=None, model=None, max_tokens=100,
        temperature=0.7, reasoning_effort="none", tool_choice=None,
    )
    assert kwargs["extra_body"] == {"thinking": {"type": "disabled"}}


def test_mimo_flash_via_openrouter_does_not_inject_thinking():
    """mimo-v2-flash has no thinking mode per Xiaomi docs; the allowlist
    excludes it, so no thinking field should be injected on the gateway path."""
    provider = _openrouter_provider("xiaomi/mimo-v2-flash")
    kwargs = provider._build_kwargs(
        messages=_simple_messages(),
        tools=None, model=None, max_tokens=100,
        temperature=0.7, reasoning_effort="none", tool_choice=None,
    )
    assert "extra_body" not in kwargs


def test_non_mimo_model_via_openrouter_unaffected():
    """Sanity: a non-MiMo, non-Kimi model through OpenRouter is untouched."""
    provider = _openrouter_provider("openai/gpt-4o")
    kwargs = provider._build_kwargs(
        messages=_simple_messages(),
        tools=None, model=None, max_tokens=100,
        temperature=0.7, reasoning_effort="none", tool_choice=None,
    )
    assert "extra_body" not in kwargs
