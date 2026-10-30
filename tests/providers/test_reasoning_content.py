from unittest.mock import patch

from openai.types.chat import ChatCompletion, ChatCompletionChunk

from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.utils.helpers import build_assistant_message


def test_parse_dict_extracts_reasoning_content() -> None:
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
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
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider()

    response = {
        "choices": [{
            "message": {"content": "hello"},
            "finish_reason": "stop",
        }],
    }

    result = provider._parse(response)

    assert result.reasoning_content is None


def test_parse_dict_reasoning_content_empty_string_preserved() -> None:
    """reasoning_content=\"\" is preserved, not coerced to None.

    Some providers (e.g. DeepSeek) require the reasoning_content key to
    be present in subsequent requests even when empty.  Coercing \"\" to
    None drops the key downstream and causes API errors.
    """
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider()

    response = {
        "choices": [{
            "message": {
                "content": "answer",
                "reasoning_content": "",
            },
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
    }

    result = provider._parse(response)

    assert result.reasoning_content == ""


def test_parse_sdk_reasoning_content_empty_string_preserved() -> None:
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider()

    response = ChatCompletion.model_validate({
        "id": "chatcmpl-reasoning",
        "object": "chat.completion",
        "created": 0,
        "model": "test-model",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": "answer", "reasoning_content": ""},
            "finish_reason": "stop",
        }],
    })

    result = provider._parse(response)

    assert result.content == "answer"
    assert result.reasoning_content == ""


def test_tool_call_history_preserves_empty_reasoning_content_after_sanitize() -> None:
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider()

    response = {
        "choices": [{
            "message": {
                "content": "",
                "reasoning_content": "",
                "tool_calls": [{
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "lookup", "arguments": "{}"},
                }],
            },
            "finish_reason": "tool_calls",
        }],
    }

    result = provider._parse(response)
    assistant_message = build_assistant_message(
        result.content or "",
        tool_calls=[tc.to_openai_tool_call() for tc in result.tool_calls],
        reasoning_content=result.reasoning_content,
    )
    sanitized = provider._sanitize_messages([
        {"role": "user", "content": "look something up"},
        assistant_message,
        {"role": "tool", "tool_call_id": "call_1", "content": "done"},
    ])

    assert sanitized[1]["reasoning_content"] == ""


def test_parse_chunks_dict_accumulates_reasoning_content() -> None:
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
    chunks = [
        {"choices": [{"finish_reason": "stop", "delta": {"content": "hi"}}]},
    ]

    result = OpenAICompatProvider._parse_chunks(chunks)

    assert result.content == "hi"
    assert result.reasoning_content is None


def _make_reasoning_chunk(
    reasoning: str | None, content: str | None, finish: str | None,
) -> ChatCompletionChunk:
    return ChatCompletionChunk.model_validate({
        "id": "chatcmpl-reasoning",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": "test-model",
        "choices": [{
            "index": 0,
            "finish_reason": finish,
            "delta": {"content": content, "reasoning_content": reasoning},
        }],
    })


def test_parse_chunks_sdk_accumulates_reasoning_content() -> None:
    chunks = [
        _make_reasoning_chunk("Think… ", None, None),
        _make_reasoning_chunk("Done.", None, None),
        _make_reasoning_chunk(None, "result", "stop"),
    ]

    result = OpenAICompatProvider._parse_chunks(chunks)

    assert result.content == "result"
    assert result.reasoning_content == "Think… Done."


def test_parse_chunks_sdk_reasoning_content_none_when_absent() -> None:
    chunks = [_make_reasoning_chunk(None, "hello", "stop")]

    result = OpenAICompatProvider._parse_chunks(chunks)

    assert result.reasoning_content is None
