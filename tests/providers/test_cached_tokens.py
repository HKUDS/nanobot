"""Tests for cached token extraction from OpenAI-compatible providers."""

from __future__ import annotations

from nanobot.providers.openai_compat_provider import OpenAICompatProvider


class FakeUsage:
    """Mimics an OpenAI SDK usage object (has attributes, not dict keys)."""
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class FakePromptDetails:
    """Mimics prompt_tokens_details sub-object."""
    def __init__(self, cached_tokens=0, cache_write_tokens=None):
        self.cached_tokens = cached_tokens
        self.cache_write_tokens = cache_write_tokens


class _FakeSpec:
    supports_prompt_caching = False
    model_id_prefix = None
    strip_model_prefix = False
    max_completion_tokens = False
    reasoning_effort = None


def _provider():
    from unittest.mock import MagicMock
    p = OpenAICompatProvider.__new__(OpenAICompatProvider)
    p.client = MagicMock()
    p.spec = _FakeSpec()
    return p


# Minimal valid choice so _parse reaches _extract_usage.
_DICT_CHOICE = {"message": {"content": "Hello"}}

class _FakeMessage:
    content = "Hello"
    tool_calls = None


class _FakeChoice:
    message = _FakeMessage()
    finish_reason = "stop"


# --- dict-based response (raw JSON / mapping) ---

def test_extract_usage_openai_cached_tokens_dict():
    """prompt_tokens_details.cached_tokens from a dict response."""
    p = _provider()
    response = {
        "choices": [_DICT_CHOICE],
        "usage": {
            "prompt_tokens": 2000,
            "completion_tokens": 300,
            "total_tokens": 2300,
            "prompt_tokens_details": {"cached_tokens": 1200},
        }
    }
    result = p._parse(response)
    assert result.usage is not None
    assert result.usage.cache_read_tokens == 1200
    assert result.usage.input_tokens == 2000


def test_extract_usage_deepseek_cached_tokens_dict():
    """prompt_cache_hit_tokens from a DeepSeek dict response."""
    p = _provider()
    response = {
        "choices": [_DICT_CHOICE],
        "usage": {
            "prompt_tokens": 1500,
            "completion_tokens": 200,
            "total_tokens": 1700,
            "prompt_cache_hit_tokens": 1200,
            "prompt_cache_miss_tokens": 300,
        }
    }
    result = p._parse(response)
    assert result.usage is not None
    assert result.usage.cache_read_tokens == 1200


def test_extract_usage_no_cached_tokens_dict():
    """Response without any cache fields preserves an unreported cache count."""
    p = _provider()
    response = {
        "choices": [_DICT_CHOICE],
        "usage": {
            "prompt_tokens": 1000,
            "completion_tokens": 200,
            "total_tokens": 1200,
        }
    }
    result = p._parse(response)
    assert result.usage is not None
    assert result.usage.cache_read_tokens is None
    assert result.usage.cache_write_tokens is None


def test_extract_usage_openai_cached_zero_dict():
    """cached_tokens=0 remains distinct from an unreported cache count."""
    p = _provider()
    response = {
        "choices": [_DICT_CHOICE],
        "usage": {
            "prompt_tokens": 2000,
            "completion_tokens": 300,
            "total_tokens": 2300,
            "prompt_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
        }
    }
    result = p._parse(response)
    assert result.usage is not None
    assert result.usage.cache_read_tokens == 0
    assert result.usage.cache_write_tokens == 0


def test_extract_usage_preserves_reported_total_and_cache_write_dict():
    response = {
        "choices": [_DICT_CHOICE],
        "usage": {
            "prompt_tokens": 15,
            "completion_tokens": 18,
            "total_tokens": 175,
            "prompt_tokens_details": {
                "cached_tokens": 0,
                "cache_write_tokens": 7,
            },
        },
    }

    result = _provider()._parse(response)

    assert result.usage is not None
    assert result.usage.total_tokens == 175
    assert result.usage.reported_tokens == 175
    assert result.usage.cache_read_tokens == 0
    assert result.usage.cache_write_tokens == 7


def test_extract_usage_missing_is_none():
    result = _provider()._parse({"choices": [_DICT_CHOICE]})

    assert result.usage is None


# --- object-based response (OpenAI SDK Pydantic model) ---

def test_extract_usage_openai_cached_tokens_obj():
    """prompt_tokens_details.cached_tokens from an SDK object response."""
    p = _provider()
    usage_obj = FakeUsage(
        prompt_tokens=2000,
        completion_tokens=300,
        total_tokens=2300,
        prompt_tokens_details=FakePromptDetails(cached_tokens=1200),
    )
    response = FakeUsage(choices=[_FakeChoice()], usage=usage_obj)
    result = p._parse(response)
    assert result.usage is not None
    assert result.usage.cache_read_tokens == 1200


def test_extract_usage_preserves_reported_total_and_cache_write_obj():
    usage_obj = FakeUsage(
        prompt_tokens=15,
        completion_tokens=18,
        total_tokens=175,
        prompt_tokens_details=FakePromptDetails(
            cached_tokens=0,
            cache_write_tokens=7,
        ),
    )
    response = FakeUsage(choices=[_FakeChoice()], usage=usage_obj)

    result = _provider()._parse(response)

    assert result.usage is not None
    assert result.usage.total_tokens == 175
    assert result.usage.reported_tokens == 175
    assert result.usage.cache_read_tokens == 0
    assert result.usage.cache_write_tokens == 7


def test_extract_usage_deepseek_cached_tokens_obj():
    """prompt_cache_hit_tokens from a DeepSeek SDK object response."""
    p = _provider()
    usage_obj = FakeUsage(
        prompt_tokens=1500,
        completion_tokens=200,
        total_tokens=1700,
        prompt_cache_hit_tokens=1200,
    )
    response = FakeUsage(choices=[_FakeChoice()], usage=usage_obj)
    result = p._parse(response)
    assert result.usage is not None
    assert result.usage.cache_read_tokens == 1200


def test_extract_usage_stepfun_top_level_cached_tokens_dict():
    """StepFun/Moonshot: usage.cached_tokens at top level (not nested)."""
    p = _provider()
    response = {
        "choices": [_DICT_CHOICE],
        "usage": {
            "prompt_tokens": 591,
            "completion_tokens": 120,
            "total_tokens": 711,
            "cached_tokens": 512,
        }
    }
    result = p._parse(response)
    assert result.usage is not None
    assert result.usage.cache_read_tokens == 512


def test_extract_usage_stepfun_top_level_cached_tokens_obj():
    """StepFun/Moonshot: usage.cached_tokens as SDK object attribute."""
    p = _provider()
    usage_obj = FakeUsage(
        prompt_tokens=591,
        completion_tokens=120,
        total_tokens=711,
        cached_tokens=512,
    )
    response = FakeUsage(choices=[_FakeChoice()], usage=usage_obj)
    result = p._parse(response)
    assert result.usage is not None
    assert result.usage.cache_read_tokens == 512


def test_extract_usage_priority_nested_over_top_level_dict():
    """When both nested and top-level cached_tokens exist, nested wins."""
    p = _provider()
    response = {
        "choices": [_DICT_CHOICE],
        "usage": {
            "prompt_tokens": 2000,
            "completion_tokens": 300,
            "total_tokens": 2300,
            "prompt_tokens_details": {"cached_tokens": 100},
            "cached_tokens": 500,
        }
    }
    result = p._parse(response)
    assert result.usage is not None
    assert result.usage.cache_read_tokens == 100


def test_anthropic_adds_native_cache_fields_to_logical_input():
    """Anthropic excludes cache reads/writes from its native input_tokens."""
    from nanobot.providers.anthropic_provider import AnthropicProvider

    usage_obj = FakeUsage(
        input_tokens=800,
        output_tokens=200,
        cache_creation_input_tokens=300,
        cache_read_input_tokens=1200,
    )
    content_block = FakeUsage(type="text", text="hello")
    response = FakeUsage(
        id="msg_1",
        type="message",
        stop_reason="end_turn",
        content=[content_block],
        usage=usage_obj,
    )
    result = AnthropicProvider._parse_response(response)
    assert result.usage is not None
    assert result.usage.cache_read_tokens == 1200
    assert result.usage.cache_write_tokens == 300
    assert result.usage.input_tokens == 2300
    assert result.usage.total_tokens == 2500


def test_anthropic_no_cache_fields():
    """Anthropic response without cache fields preserves unreported counts."""
    from nanobot.providers.anthropic_provider import AnthropicProvider

    usage_obj = FakeUsage(input_tokens=800, output_tokens=200)
    content_block = FakeUsage(type="text", text="hello")
    response = FakeUsage(
        id="msg_1",
        type="message",
        stop_reason="end_turn",
        content=[content_block],
        usage=usage_obj,
    )
    result = AnthropicProvider._parse_response(response)
    assert result.usage is not None
    assert result.usage.input_tokens == 800
    assert result.usage.cache_read_tokens is None
    assert result.usage.cache_write_tokens is None
