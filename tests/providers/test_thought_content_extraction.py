"""Tests for thought_content extraction in OpenAICompatProvider.

Covers non-streaming (_parse) and streaming (_parse_chunks) paths for
providers that emit <thought>…</thought> blocks (e.g. Gemma 4).
"""

from types import SimpleNamespace
from unittest.mock import patch

from nanobot.providers.openai_compat_provider import OpenAICompatProvider


# ── _parse: non-streaming dict branch (top-level content) ────────────────


def test_parse_dict_top_level_extracts_thought_content() -> None:
    """<thought> blocks in top-level content are extracted."""
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider()

    response = {
        "content": "Answer.<thought>reasoning</thought>",
        "finish_reason": "stop",
        "usage": {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
    }

    result = provider._parse(response)

    assert result.content == "Answer.<thought>reasoning</thought>"
    assert result.thought_content == ["reasoning"]


def test_parse_dict_top_level_no_thought_when_absent() -> None:
    """thought_content is None when content has no <thought> tags."""
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider()

    response = {
        "content": "Just text.",
        "finish_reason": "stop",
    }

    result = provider._parse(response)

    assert result.thought_content is None


# ── _parse: non-streaming dict branch (choices[].message) ────────────────


def test_parse_choices_extracts_thought_content() -> None:
    """<thought> blocks in message content are extracted."""
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider()

    response = {
        "choices": [{
            "message": {
                "content": "Hi<thought>internal</thought>bye",
            },
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 2, "completion_tokens": 5, "total_tokens": 7},
    }

    result = provider._parse(response)

    assert result.content == "Hi<thought>internal</thought>bye"
    assert result.thought_content == ["internal"]


def test_parse_choices_multiple_thought_blocks() -> None:
    """Multiple <thought> blocks are all extracted."""
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider()

    response = {
        "choices": [{
            "message": {
                "content": "<thought>step1</thought>A<thought>step2</thought>",
            },
            "finish_reason": "stop",
        }],
    }

    result = provider._parse(response)

    assert result.thought_content == ["step1", "step2"]


def test_parse_choices_no_thought_when_absent() -> None:
    """thought_content is None when message has no <thought> tags."""
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider()

    response = {
        "choices": [{
            "message": {"content": "hello"},
            "finish_reason": "stop",
        }],
    }

    result = provider._parse(response)

    assert result.thought_content is None


# ── _parse: non-streaming SDK-object branch ──────────────────────────────


def test_parse_sdk_object_extracts_thought_content() -> None:
    """<thought> blocks in SDK message.content are extracted."""
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider()

    msg = SimpleNamespace(content="Reply<thought>hidden</thought>")
    choice = SimpleNamespace(message=msg, finish_reason="stop")
    response = SimpleNamespace(choices=[choice], usage=None)

    result = provider._parse(response)

    assert result.content == "Reply<thought>hidden</thought>"
    assert result.thought_content == ["hidden"]


def test_parse_sdk_object_no_thought_when_absent() -> None:
    """thought_content is None when SDK content has no <thought> tags."""
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider()

    msg = SimpleNamespace(content="plain")
    choice = SimpleNamespace(message=msg, finish_reason="stop")
    response = SimpleNamespace(choices=[choice], usage=None)

    result = provider._parse(response)

    assert result.thought_content is None


# ── _parse_chunks: streaming dict branch ─────────────────────────────────


def test_parse_chunks_dict_extracts_thought_content() -> None:
    """<thought> blocks in streamed dict content are extracted."""
    chunks = [
        {"choices": [{"finish_reason": None, "delta": {"content": "A<thought>r"}}]},
        {"choices": [{"finish_reason": None, "delta": {"content": "easoning</thought>B"}}]},
        {"choices": [{"finish_reason": "stop", "delta": {"content": ""}}]},
    ]

    result = OpenAICompatProvider._parse_chunks(chunks)

    assert result.content == "A<thought>reasoning</thought>B"
    assert result.thought_content == ["reasoning"]


def test_parse_chunks_dict_no_thought_when_absent() -> None:
    """thought_content is None when streamed dict content has no <thought>."""
    chunks = [
        {"choices": [{"finish_reason": "stop", "delta": {"content": "hi"}}]},
    ]

    result = OpenAICompatProvider._parse_chunks(chunks)

    assert result.thought_content is None


# ── _parse_chunks: streaming SDK-object branch ───────────────────────────


def _make_chunk(content: str | None, finish: str | None):
    delta = SimpleNamespace(content=content, reasoning_content=None, tool_calls=None)
    choice = SimpleNamespace(finish_reason=finish, delta=delta)
    return SimpleNamespace(choices=[choice], usage=None)


def test_parse_chunks_sdk_extracts_thought_content() -> None:
    """<thought> blocks in streamed SDK content are extracted."""
    chunks = [
        _make_chunk("Start<thought>mid", None),
        _make_chunk("dle</thought>End", "stop"),
    ]

    result = OpenAICompatProvider._parse_chunks(chunks)

    assert result.content == "Start<thought>middle</thought>End"
    assert result.thought_content == ["middle"]


def test_parse_chunks_sdk_no_thought_when_absent() -> None:
    """thought_content is None when SDK streamed content has no <thought>."""
    chunks = [_make_chunk("hello", "stop")]

    result = OpenAICompatProvider._parse_chunks(chunks)

    assert result.thought_content is None
