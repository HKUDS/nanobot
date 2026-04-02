"""Regression tests for max_completion_tokens selection in OpenAI-compatible providers."""

from unittest.mock import patch

from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.providers.registry import find_by_name


def test_openai_provider_uses_max_completion_tokens_when_supported():
    """OpenAI registry spec should drive max_completion_tokens payload selection."""
    spec = find_by_name("openai")
    assert spec is not None
    assert spec.supports_max_completion_tokens is True

    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider(
            api_key="test-key",
            api_base=None,
            default_model="gpt-4.1",
            spec=spec,
        )

    payload = provider._build_kwargs(
        messages=[{"role": "user", "content": "Hello"}],
        tools=None,
        model="gpt-4.1",
        max_tokens=1234,
        temperature=0.2,
        reasoning_effort=None,
        tool_choice=None,
    )

    assert payload["max_completion_tokens"] == 1234
    assert "max_tokens" not in payload
