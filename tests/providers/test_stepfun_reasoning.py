"""Tests for StepFun Plan API reasoning field fallback in OpenAICompatProvider.

StepFun Plan API returns response content in the 'reasoning' field when
the model is in thinking mode and 'content' is empty. This test module
verifies the fallback logic for all code paths.
"""

from unittest.mock import patch

from openai.types.chat import ChatCompletion, ChatCompletionChunk

from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.providers.registry import ProviderSpec

_STEPFUN_SPEC = ProviderSpec(
    name="stepfun",
    keywords=("stepfun", "step"),
    env_key="STEPFUN_API_KEY",
    request_apis=("chat_completions", "responses"),
    display_name="Step Fun",
    backend="openai_compat",
    default_api_base="https://api.stepfun.com/v1",
    reasoning_as_content=True,
)


# ── _parse: dict branch ─────────────────────────────────────────────────────


def test_parse_dict_stepfun_reasoning_fallback() -> None:
    """When content is None and reasoning exists, content falls back to reasoning."""
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider(spec=_STEPFUN_SPEC)

    response = {
        "choices": [{
            "message": {
                "content": None,
                "reasoning": "Let me think... The answer is 42.",
            },
            "finish_reason": "stop",
        }],
    }

    result = provider._parse(response)

    assert result.content == "Let me think... The answer is 42."
    # reasoning_content should also be populated from reasoning
    assert result.reasoning_content == "Let me think... The answer is 42."


def test_parse_dict_stepfun_reasoning_priority() -> None:
    """reasoning_content field takes priority over reasoning when both present."""
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider(spec=_STEPFUN_SPEC)

    response = {
        "choices": [{
            "message": {
                "content": None,
                "reasoning": "informal thinking",
                "reasoning_content": "formal reasoning content",
            },
            "finish_reason": "stop",
        }],
    }

    result = provider._parse(response)

    assert result.content == "informal thinking"
    # reasoning_content uses the dedicated field, not reasoning
    assert result.reasoning_content == "formal reasoning content"


# ── _parse: SDK objects ────────────────────────────────────────────────────


def _make_sdk_response(content, reasoning=None, reasoning_content=None) -> ChatCompletion:
    return ChatCompletion.model_validate({
        "id": "chatcmpl-stepfun",
        "object": "chat.completion",
        "created": 0,
        "model": "step-3.5-flash",
        "choices": [{
            "index": 0,
            "finish_reason": "stop",
            "message": {
                "role": "assistant",
                "content": content,
                "reasoning": reasoning,
                "reasoning_content": reasoning_content,
            },
        }],
    })


def test_parse_sdk_stepfun_reasoning_fallback() -> None:
    """SDK branch: content falls back to msg.reasoning when content is None."""
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider(spec=_STEPFUN_SPEC)

    response = _make_sdk_response(content=None, reasoning="After analysis: result is 4.")

    result = provider._parse(response)

    assert result.content == "After analysis: result is 4."
    assert result.reasoning_content == "After analysis: result is 4."


def test_parse_sdk_stepfun_reasoning_priority() -> None:
    """reasoning_content field takes priority over reasoning in SDK branch."""
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider(spec=_STEPFUN_SPEC)

    response = _make_sdk_response(
        content=None,
        reasoning="thinking process",
        reasoning_content="formal reasoning",
    )

    result = provider._parse(response)

    assert result.content == "thinking process"
    assert result.reasoning_content == "formal reasoning"


# ── _parse_chunks: streaming dict branch ────────────────────────────────────


def test_parse_chunks_dict_stepfun_reasoning_fallback() -> None:
    """Streaming dict: reasoning field used when reasoning_content is absent."""
    chunks = [
        {
            "choices": [{
                "finish_reason": None,
                "delta": {"content": None, "reasoning": "Thinking step 1... "},
            }],
        },
        {
            "choices": [{
                "finish_reason": None,
                "delta": {"content": None, "reasoning": "step 2."},
            }],
        },
        {
            "choices": [{
                "finish_reason": "stop",
                "delta": {"content": "final answer"},
            }],
        },
    ]

    result = OpenAICompatProvider._parse_chunks(chunks)

    assert result.content == "final answer"
    assert result.reasoning_content == "Thinking step 1... step 2."


# ── Regression: normal models unaffected ────────────────────────────────────


def test_parse_dict_normal_model_with_reasoning_content_unaffected() -> None:
    """Models that use reasoning_content (e.g. DeepSeek-R1) are not affected."""
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider()

    response = {
        "choices": [{
            "message": {
                "content": "The answer is 42.",
                "reasoning_content": "Let me think step by step...",
            },
            "finish_reason": "stop",
        }],
    }

    result = provider._parse(response)

    assert result.content == "The answer is 42."
    assert result.reasoning_content == "Let me think step by step..."


def test_parse_dict_standard_model_no_reasoning_unaffected() -> None:
    """Standard models (no reasoning fields at all) work exactly as before."""
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider()

    response = {
        "choices": [{
            "message": {"content": "Hello!"},
            "finish_reason": "stop",
        }],
    }

    result = provider._parse(response)

    assert result.content == "Hello!"
    assert result.reasoning_content is None


def test_parse_chunks_dict_reasoning_precedence() -> None:
    """reasoning_content takes precedence over reasoning in dict chunks."""
    chunks = [
        {
            "choices": [{
                "finish_reason": None,
                "delta": {
                    "content": None,
                    "reasoning_content": "formal: ",
                    "reasoning": "informal: ",
                },
            }],
        },
        {
            "choices": [{
                "finish_reason": "stop",
                "delta": {"content": "result"},
            }],
        },
    ]

    result = OpenAICompatProvider._parse_chunks(chunks)

    assert result.reasoning_content == "formal: "


# ── _parse_chunks: streaming SDK objects ───────────────────────────────────


def _make_sdk_chunk(
    reasoning_content=None, reasoning=None, content=None, finish=None,
) -> ChatCompletionChunk:
    return ChatCompletionChunk.model_validate({
        "id": "chatcmpl-stepfun",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": "step-3.5-flash",
        "choices": [{
            "index": 0,
            "finish_reason": finish,
            "delta": {
                "content": content,
                "reasoning_content": reasoning_content,
                "reasoning": reasoning,
            },
        }],
    })


def test_parse_chunks_sdk_stepfun_reasoning_fallback() -> None:
    """SDK streaming: reasoning field used when reasoning_content is None."""
    chunks = [
        _make_sdk_chunk(reasoning="Thinking... ", content=None, finish=None),
        _make_sdk_chunk(reasoning=None, content="answer", finish="stop"),
    ]

    result = OpenAICompatProvider._parse_chunks(chunks)

    assert result.content == "answer"
    assert result.reasoning_content == "Thinking... "


def test_parse_chunks_sdk_reasoning_precedence() -> None:
    """reasoning_content takes precedence over reasoning in SDK chunks."""
    chunks = [
        _make_sdk_chunk(reasoning_content="formal: ", reasoning="informal: ", content=None),
        _make_sdk_chunk(reasoning_content=None, reasoning=None, content="result", finish="stop"),
    ]

    result = OpenAICompatProvider._parse_chunks(chunks)

    assert result.reasoning_content == "formal: "


# ── Regression: non-StepFun providers must NOT promote reasoning to content ─


def test_parse_dict_non_stepfun_no_reasoning_as_content() -> None:
    """Providers without reasoning_as_content flag must not treat reasoning as content."""
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider()

    response = {
        "choices": [{
            "message": {
                "content": None,
                "reasoning": "internal thought process that should NOT be shown to user",
            },
            "finish_reason": "stop",
        }],
    }

    result = provider._parse(response)

    # content stays None — reasoning is NOT promoted
    assert result.content is None
    # reasoning still goes to reasoning_content for display as thinking
    assert result.reasoning_content == "internal thought process that should NOT be shown to user"


def test_parse_sdk_non_stepfun_no_reasoning_as_content() -> None:
    """SDK branch: providers without flag must not treat reasoning as content."""
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider()

    response = _make_sdk_response(content=None, reasoning="internal monologue")

    result = provider._parse(response)

    assert result.content is None
    assert result.reasoning_content == "internal monologue"
