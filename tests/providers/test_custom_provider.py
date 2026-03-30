"""Tests for OpenAICompatProvider handling custom/direct endpoints."""

from types import SimpleNamespace
from unittest.mock import patch

from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.providers.registry import ProviderSpec


def test_custom_provider_parse_handles_empty_choices() -> None:
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider()
    response = SimpleNamespace(choices=[])

    result = provider._parse(response)

    assert result.finish_reason == "error"
    assert "empty choices" in result.content


def test_custom_provider_parse_accepts_plain_string_response() -> None:
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider()

    result = provider._parse("hello from backend")

    assert result.finish_reason == "stop"
    assert result.content == "hello from backend"


def test_custom_provider_parse_accepts_dict_response() -> None:
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider()

    result = provider._parse({
        "choices": [{
            "message": {"content": "hello from dict"},
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens": 1,
            "completion_tokens": 2,
            "total_tokens": 3,
        },
    })

    assert result.finish_reason == "stop"
    assert result.content == "hello from dict"
    assert result.usage["total_tokens"] == 3


def test_custom_provider_parse_chunks_accepts_plain_text_chunks() -> None:
    result = OpenAICompatProvider._parse_chunks(["hello ", "world"])

    assert result.finish_reason == "stop"
    assert result.content == "hello world"


# ---------------------------------------------------------------------------
# _build_kwargs: max_tokens / max_completion_tokens mutual exclusion
# ---------------------------------------------------------------------------


def _build(model: str, *, spec: ProviderSpec | None = None) -> dict:
    """Build kwargs via the provider without hitting the network."""
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider()
    provider._spec = spec
    return provider._build_kwargs(
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        model=model,
        max_tokens=1024,
        temperature=0.7,
        reasoning_effort=None,
        tool_choice=None,
    )


def test_model_overrides_injects_max_completion_tokens_removes_max_tokens() -> None:
    """model_overrides adding max_completion_tokens must drop max_tokens."""
    spec = ProviderSpec(
        name="test",
        keywords=(),
        env_key="",
        model_overrides=(("o3", {"max_completion_tokens": 8192}),),
    )
    kwargs = _build("o3-mini", spec=spec)
    assert "max_completion_tokens" in kwargs
    assert "max_tokens" not in kwargs
    assert kwargs["max_completion_tokens"] == 8192


def test_no_overrides_keeps_max_tokens_only() -> None:
    """Without overrides, max_tokens is set and max_completion_tokens absent."""
    kwargs = _build("gpt-4o")
    assert "max_tokens" in kwargs
    assert "max_completion_tokens" not in kwargs


def test_supports_max_completion_tokens_flag() -> None:
    """When spec sets supports_max_completion_tokens, use that param."""
    spec = ProviderSpec(
        name="test",
        keywords=(),
        env_key="",
        supports_max_completion_tokens=True,
    )
    kwargs = _build("any-model", spec=spec)
    assert "max_completion_tokens" in kwargs
    assert "max_tokens" not in kwargs
