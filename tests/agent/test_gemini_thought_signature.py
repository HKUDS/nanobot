"""Tests for Gemini thought_signature round-trip through extra_content.

The Gemini OpenAI-compatibility API returns tool calls with an extra_content
field: ``{"google": {"thought_signature": "..."}}``.  This MUST survive the
parse → serialize round-trip so the model can continue reasoning.
"""

from types import SimpleNamespace
from unittest.mock import patch

from janniebot.providers.base import ToolCallRequest
from janniebot.providers.openai_compat_provider import OpenAICompatProvider

GEMINI_EXTRA = {"google": {"thought_signature": "sig-abc-123"}}


# ── ToolCallRequest serialization ──────────────────────────────────────

def test_tool_call_request_serializes_extra_content() -> None:
    tc = ToolCallRequest(
        id="abc123xyz",
        name="read_file",
        arguments={"path": "todo.md"},
        extra_content=GEMINI_EXTRA,
    )

    payload = tc.to_openai_tool_call()

    assert payload["extra_content"] == GEMINI_EXTRA
    assert payload["function"]["arguments"] == '{"path": "todo.md"}'


def test_tool_call_request_serializes_provider_fields() -> None:
    tc = ToolCallRequest(
        id="abc123xyz",
        name="read_file",
        arguments={"path": "todo.md"},
        provider_specific_fields={"custom_key": "custom_val"},
        function_provider_specific_fields={"inner": "value"},
    )

    payload = tc.to_openai_tool_call()

    assert payload["provider_specific_fields"] == {"custom_key": "custom_val"}
    assert payload["function"]["provider_specific_fields"] == {"inner": "value"}


def test_tool_call_request_omits_absent_extras() -> None:
    tc = ToolCallRequest(id="x", name="fn", arguments={})
    payload = tc.to_openai_tool_call()

    assert "extra_content" not in payload
    assert "provider_specific_fields" not in payload
    assert "provider_specific_fields" not in payload["function"]


# ── _parse: SDK-object branch ──────────────────────────────────────────

def _make_sdk_response_with_extra_content():
    """Simulate a Gemini response via the OpenAI SDK (SimpleNamespace)."""
    fn = SimpleNamespace(name="get_weather", arguments='{"city":"Tokyo"}')
    tc = SimpleNamespace(
        id="call_1",
        index=0,
        type="function",
        function=fn,
        extra_content=GEMINI_EXTRA,
    )
    msg = SimpleNamespace(
        content=None,
        tool_calls=[tc],
        reasoning_content=None,
    )
    choice = SimpleNamespace(message=msg, finish_reason="tool_calls")
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    return SimpleNamespace(choices=[choice], usage=usage)


def test_parse_sdk_object_preserves_extra_content() -> None:
    with patch("janniebot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider()

    result = provider._parse(_make_sdk_response_with_extra_content())

    assert len(result.tool_calls) == 1
    tc = result.tool_calls[0]
    assert tc.name == "get_weather"
    assert tc.extra_content == GEMINI_EXTRA

    payload = tc.to_openai_tool_call()
    assert payload["extra_content"] == GEMINI_EXTRA


# ── _parse: dict/mapping branch ───────────────────────────────────────

def test_parse_dict_preserves_extra_content() -> None:
    with patch("janniebot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider()

    response_dict = {
        "choices": [{
            "message": {
                "content": None,
                "tool_calls": [{
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "get_weather", "arguments": '{"city":"Tokyo"}'},
                    "extra_content": GEMINI_EXTRA,
                }],
            },
            "finish_reason": "tool_calls",
        }],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }

    result = provider._parse(response_dict)

    assert len(result.tool_calls) == 1
    tc = result.tool_calls[0]
    assert tc.name == "get_weather"
    assert tc.extra_content == GEMINI_EXTRA

    payload = tc.to_openai_tool_call()
    assert payload["extra_content"] == GEMINI_EXTRA


# ── _parse_chunks: streaming round-trip ───────────────────────────────

def test_parse_chunks_sdk_preserves_extra_content() -> None:
    fn_delta = SimpleNamespace(name="get_weather", arguments='{"city":"Tokyo"}')
    tc_delta = SimpleNamespace(
        id="call_1",
        index=0,
        function=fn_delta,
        extra_content=GEMINI_EXTRA,
    )
    delta = SimpleNamespace(content=None, tool_calls=[tc_delta])
    choice = SimpleNamespace(finish_reason="tool_calls", delta=delta)
    chunk = SimpleNamespace(choices=[choice], usage=None)

    result = OpenAICompatProvider._parse_chunks([chunk])

    assert len(result.tool_calls) == 1
    tc = result.tool_calls[0]
    assert tc.extra_content == GEMINI_EXTRA

    payload = tc.to_openai_tool_call()
    assert payload["extra_content"] == GEMINI_EXTRA


def test_parse_chunks_dict_preserves_extra_content() -> None:
    chunk = {
        "choices": [{
            "finish_reason": "tool_calls",
            "delta": {
                "content": None,
                "tool_calls": [{
                    "index": 0,
                    "id": "call_1",
                    "function": {"name": "get_weather", "arguments": '{"city":"Tokyo"}'},
                    "extra_content": GEMINI_EXTRA,
                }],
            },
        }],
    }

    result = OpenAICompatProvider._parse_chunks([chunk])

    assert len(result.tool_calls) == 1
    tc = result.tool_calls[0]
    assert tc.extra_content == GEMINI_EXTRA

    payload = tc.to_openai_tool_call()
    assert payload["extra_content"] == GEMINI_EXTRA


# ── Model switching: stale extras shouldn't break other providers ─────

def test_stale_extra_content_in_tool_calls_survives_sanitize() -> None:
    """When switching from Gemini to OpenAI, extra_content inside tool_calls
    should survive message sanitization (it lives inside the tool_call dict,
    not at message level, so it bypasses _ALLOWED_MSG_KEYS filtering)."""
    with patch("janniebot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider()

    messages = [{
        "role": "assistant",
        "content": None,
        "tool_calls": [{
            "id": "call_1",
            "type": "function",
            "function": {"name": "fn", "arguments": "{}"},
            "extra_content": GEMINI_EXTRA,
        }],
    }]

    sanitized = provider._sanitize_messages(messages)

    assert sanitized[0]["tool_calls"][0]["extra_content"] == GEMINI_EXTRA
