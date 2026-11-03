from __future__ import annotations

import pytest
from openai.types.chat import ChatCompletion, ChatCompletionChunk

from nanobot.providers.openai_compat_provider import OpenAICompatProvider


class FakeUsage:
    """Attribute-based fixture for the Anthropic response tests."""
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


def _provider() -> OpenAICompatProvider:
    return OpenAICompatProvider(api_key="test-key")


_DICT_CHOICE = {"message": {"content": "Hello"}}


def _sdk_response(usage) -> ChatCompletion:
    return ChatCompletion.model_validate({
        "id": "chatcmpl-usage",
        "object": "chat.completion",
        "created": 0,
        "model": "test-model",
        "choices": [{
            "index": 0,
            "finish_reason": "stop",
            "message": {"role": "assistant", "content": "Hello"},
        }],
        "usage": usage,
    })


def test_extract_usage_openai_cached_tokens_dict():
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


@pytest.mark.parametrize("cache_read, cache_write", [(1200, None), (0, 0)])
def test_extract_usage_openai_cached_tokens_obj(cache_read, cache_write):
    p = _provider()
    response = _sdk_response({
        "prompt_tokens": 2000,
        "completion_tokens": 300,
        "total_tokens": 2300,
        "prompt_tokens_details": {
            "cached_tokens": cache_read,
            "cache_write_tokens": cache_write,
        },
    })
    result = p._parse(response)
    assert result.usage is not None
    assert result.usage.cache_read_tokens == cache_read
    assert result.usage.cache_write_tokens == cache_write


def test_extract_usage_preserves_reported_total_and_cache_write_obj():
    response = _sdk_response({
        "prompt_tokens": 15,
        "completion_tokens": 18,
        "total_tokens": 175,
        "prompt_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 7},
    })

    result = _provider()._parse(response)

    assert result.usage is not None
    assert result.usage.total_tokens == 175
    assert result.usage.reported_tokens == 175
    assert result.usage.cache_read_tokens == 0
    assert result.usage.cache_write_tokens == 7


def test_extract_usage_deepseek_cached_tokens_obj():
    p = _provider()
    response = _sdk_response({
        "prompt_tokens": 1500,
        "completion_tokens": 200,
        "total_tokens": 1700,
        "prompt_cache_hit_tokens": 1200,
    })
    result = p._parse(response)
    assert result.usage is not None
    assert result.usage.cache_read_tokens == 1200


def test_extract_usage_stepfun_top_level_cached_tokens_dict():
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
    p = _provider()
    response = _sdk_response({
        "prompt_tokens": 591,
        "completion_tokens": 120,
        "total_tokens": 711,
        "cached_tokens": 512,
    })
    result = p._parse(response)
    assert result.usage is not None
    assert result.usage.cache_read_tokens == 512


def test_extract_usage_priority_nested_over_top_level_dict():
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


@pytest.mark.parametrize("as_sdk", [False, True], ids=["dict", "sdk"])
def test_parse_chunks_preserves_usage_only_chunk(as_sdk: bool) -> None:
    chunks = [
        {"choices": [{"index": 0, "delta": {"content": "Hello"}, "finish_reason": "stop"}]},
        {
            "choices": [],
            "usage": {
                "prompt_tokens": 15,
                "completion_tokens": 18,
                "total_tokens": 175,
                "prompt_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
            },
        },
    ]
    if as_sdk:
        chunks = [ChatCompletionChunk.model_validate({
            "id": "chatcmpl-usage",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": "test-model",
            **chunk,
        }) for chunk in chunks]

    result = OpenAICompatProvider._parse_chunks(chunks)

    assert result.content == "Hello"
    assert result.finish_reason == "stop"
    assert result.usage is not None
    assert result.usage.input_tokens == 15
    assert result.usage.output_tokens == 18
    assert result.usage.total_tokens == 175
    assert result.usage.reported_tokens == 175
    assert result.usage.cache_read_tokens == 0
    assert result.usage.cache_write_tokens == 0


def test_anthropic_adds_native_cache_fields_to_logical_input():
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
