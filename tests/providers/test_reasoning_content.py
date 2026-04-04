"""Tests for reasoning_content extraction in OpenAICompatProvider.

Covers non-streaming (_parse) and streaming (_parse_chunks) paths for
providers that return a reasoning_content field (e.g. MiMo, DeepSeek-R1).
"""

from types import SimpleNamespace
from unittest.mock import patch

from janniebot.providers.openai_compat_provider import OpenAICompatProvider

# ── _parse: non-streaming ─────────────────────────────────────────────────


def test_parse_dict_extracts_reasoning_content() -> None:
    """reasoning_content at message level is surfaced in LLMResponse."""
    with patch("janniebot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider()

    response = {
        "choices": [{
            "message": {
                "content": "42",
                "reasoning_content": "Let me think step by step…",
            },
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
    }

    result = provider._parse(response)

    assert result.content == "42"
    assert result.reasoning_content == "Let me think step by step…"


def test_parse_dict_reasoning_content_none_when_absent() -> None:
    """reasoning_content is None when the response doesn't include it."""
    with patch("janniebot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider()

    response = {
        "choices": [{
            "message": {"content": "hello"},
            "finish_reason": "stop",
        }],
    }

    result = provider._parse(response)

    assert result.reasoning_content is None


# ── _parse_chunks: streaming dict branch ─────────────────────────────────


def test_parse_chunks_dict_accumulates_reasoning_content() -> None:
    """reasoning_content deltas in dict chunks are joined into one string."""
    chunks = [
        {
            "choices": [{
                "finish_reason": None,
                "delta": {"content": None, "reasoning_content": "Step 1. "},
            }],
        },
        {
            "choices": [{
                "finish_reason": None,
                "delta": {"content": None, "reasoning_content": "Step 2."},
            }],
        },
        {
            "choices": [{
                "finish_reason": "stop",
                "delta": {"content": "answer"},
            }],
        },
    ]

    result = OpenAICompatProvider._parse_chunks(chunks)

    assert result.content == "answer"
    assert result.reasoning_content == "Step 1. Step 2."


def test_parse_chunks_dict_reasoning_content_none_when_absent() -> None:
    """reasoning_content is None when no chunk contains it."""
    chunks = [
        {"choices": [{"finish_reason": "stop", "delta": {"content": "hi"}}]},
    ]

    result = OpenAICompatProvider._parse_chunks(chunks)

    assert result.content == "hi"
    assert result.reasoning_content is None


# ── _parse_chunks: streaming SDK-object branch ────────────────────────────


def _make_reasoning_chunk(reasoning: str | None, content: str | None, finish: str | None):
    delta = SimpleNamespace(content=content, reasoning_content=reasoning, tool_calls=None)
    choice = SimpleNamespace(finish_reason=finish, delta=delta)
    return SimpleNamespace(choices=[choice], usage=None)


def test_parse_chunks_sdk_accumulates_reasoning_content() -> None:
    """reasoning_content on SDK delta objects is joined across chunks."""
    chunks = [
        _make_reasoning_chunk("Think… ", None, None),
        _make_reasoning_chunk("Done.", None, None),
        _make_reasoning_chunk(None, "result", "stop"),
    ]

    result = OpenAICompatProvider._parse_chunks(chunks)

    assert result.content == "result"
    assert result.reasoning_content == "Think… Done."


def test_parse_chunks_sdk_reasoning_content_none_when_absent() -> None:
    """reasoning_content is None when SDK deltas carry no reasoning_content."""
    chunks = [_make_reasoning_chunk(None, "hello", "stop")]

    result = OpenAICompatProvider._parse_chunks(chunks)

    assert result.reasoning_content is None
