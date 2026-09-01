"""Tests for Gemini thought_signature round-trip through extra_content.

The Gemini OpenAI-compatibility API returns tool calls with an extra_content
field: ``{"google": {"thought_signature": "..."}}``.  This MUST survive the
parse → serialize round-trip so the model can continue reasoning.
"""

from types import SimpleNamespace
from unittest.mock import patch

from nanobot.providers.base import ToolCallRequest
from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.providers.registry import ProviderSpec

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
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
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
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
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


def test_parse_dict_deduplicates_duplicate_tool_call_ids() -> None:
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider()

    response_dict = {
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [{
                        "id": "call_same",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": '{"path":"a.txt"}'},
                    }],
                },
                "finish_reason": "tool_calls",
            },
            {
                "message": {
                    "content": None,
                    "tool_calls": [{
                        "id": "call_same",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": '{"path":"b.txt"}'},
                    }],
                },
                "finish_reason": "tool_calls",
            },
        ],
    }

    result = provider._parse(response_dict)

    ids = [tc.id for tc in result.tool_calls]
    assert len(ids) == 2
    assert ids[0] == "call_same"
    assert ids[1] != "call_same"
    assert len(set(ids)) == 2
    assert [tc.arguments for tc in result.tool_calls] == [{"path": "a.txt"}, {"path": "b.txt"}]


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
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider()

    messages = [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "call_1",
                "type": "function",
                "function": {"name": "fn", "arguments": "{}"},
                "extra_content": GEMINI_EXTRA,
            }],
        },
        {"role": "tool", "content": "ok", "tool_call_id": "call_1"},
        {"role": "user", "content": "thanks"},
    ]

    sanitized = provider._sanitize_messages(messages)

    assert sanitized[1]["tool_calls"][0]["extra_content"] == GEMINI_EXTRA


# ── Replay to Gemini: preserve or backfill thought signatures ─────────

def _gemini_provider() -> OpenAICompatProvider:
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        return OpenAICompatProvider(
            spec=ProviderSpec(
                name="gemini", keywords=("gemini",), env_key="GEMINI_API_KEY"
            )
        )


def _tool_call(tc_id: str, name: str, *, signed: bool = False) -> dict:
    tc: dict = {
        "id": tc_id,
        "type": "function",
        "function": {"name": name, "arguments": "{}"},
    }
    if signed:
        tc["extra_content"] = GEMINI_EXTRA
    return tc


def test_gemini_backfills_unsigned_tool_calls_and_keeps_results() -> None:
    """Cross-provider history stays intact and receives the documented fallback."""
    provider = _gemini_provider()
    messages = [
        {"role": "user", "content": "check the sensor"},
        {
            "role": "assistant",
            "content": "On it.",
            "tool_calls": [_tool_call("default_api:exec", "exec")],
        },
        {"role": "tool", "content": "done", "tool_call_id": "default_api:exec"},
        {"role": "user", "content": "thanks"},
    ]

    sanitized = provider._sanitize_messages(messages)

    assert [m["role"] for m in sanitized] == ["user", "assistant", "tool", "user"]
    call = sanitized[1]["tool_calls"][0]
    assert call["extra_content"]["google"]["thought_signature"] == (
        "skip_thought_signature_validator"
    )
    assert sanitized[2]["tool_call_id"] == call["id"]
    assert sanitized[2]["content"] == "done"


def test_gemini_preserves_parallel_calls_when_only_first_is_signed() -> None:
    """Gemini signs only the first native parallel call; all calls must replay."""
    provider = _gemini_provider()
    messages = [
        {"role": "user", "content": "do both"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                _tool_call("call_signed", "read_file", signed=True),
                _tool_call("default_api:exec", "exec"),
            ],
        },
        {"role": "tool", "content": "file contents", "tool_call_id": "call_signed"},
        {"role": "tool", "content": "done", "tool_call_id": "default_api:exec"},
        {"role": "user", "content": "thanks"},
    ]

    sanitized = provider._sanitize_messages(messages)

    assert [m["role"] for m in sanitized] == [
        "user",
        "assistant",
        "tool",
        "tool",
        "user",
    ]
    calls = sanitized[1]["tool_calls"]
    assert len(calls) == 2
    assert calls[0]["extra_content"] == GEMINI_EXTRA
    assert sanitized[2]["tool_call_id"] == calls[0]["id"]
    assert sanitized[2]["content"] == "file contents"
    assert "extra_content" not in calls[1]
    assert sanitized[3]["tool_call_id"] == calls[1]["id"]
    assert sanitized[3]["content"] == "done"


def test_gemini_backfills_only_first_cross_provider_parallel_call() -> None:
    provider = _gemini_provider()
    messages = [
        {"role": "user", "content": "do both"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                _tool_call("call_1", "read_file"),
                _tool_call("call_2", "exec"),
            ],
        },
        {"role": "tool", "content": "file contents", "tool_call_id": "call_1"},
        {"role": "tool", "content": "done", "tool_call_id": "call_2"},
    ]

    sanitized = provider._sanitize_messages(messages)

    calls = sanitized[1]["tool_calls"]
    assert len(calls) == 2
    assert calls[0]["extra_content"]["google"]["thought_signature"] == (
        "skip_thought_signature_validator"
    )
    assert "extra_content" not in calls[1]
    assert [message["content"] for message in sanitized[2:]] == ["file contents", "done"]


def test_gemini_requires_signature_on_first_parallel_call() -> None:
    provider = _gemini_provider()
    messages = [
        {"role": "user", "content": "do both"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                _tool_call("call_1", "read_file"),
                _tool_call("call_2", "exec", signed=True),
            ],
        },
        {"role": "tool", "content": "contents", "tool_call_id": "call_1"},
        {"role": "tool", "content": "done", "tool_call_id": "call_2"},
    ]

    sanitized = provider._sanitize_messages(messages)

    calls = sanitized[1]["tool_calls"]
    assert calls[0]["extra_content"]["google"]["thought_signature"] == (
        "skip_thought_signature_validator"
    )
    assert calls[1]["extra_content"] == GEMINI_EXTRA


def test_gemini_replay_preserves_signed_tool_calls() -> None:
    """A pure Gemini-origin history replays unchanged (signature intact)."""
    provider = _gemini_provider()
    messages = [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [_tool_call("call_1", "get_weather", signed=True)],
        },
        {"role": "tool", "content": "sunny", "tool_call_id": "call_1"},
        {"role": "user", "content": "thanks"},
    ]

    sanitized = provider._sanitize_messages(messages)

    assert [m["role"] for m in sanitized] == ["user", "assistant", "tool", "user"]
    calls = sanitized[1]["tool_calls"]
    assert len(calls) == 1
    assert calls[0]["extra_content"] == GEMINI_EXTRA
    assert sanitized[2]["tool_call_id"] == calls[0]["id"]


def test_non_gemini_provider_keeps_unsigned_tool_calls() -> None:
    """The filter is Gemini-scoped: other providers still replay unsigned calls."""
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider()

    messages = [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [_tool_call("default_api:exec", "exec")],
        },
        {"role": "tool", "content": "done", "tool_call_id": "default_api:exec"},
        {"role": "user", "content": "thanks"},
    ]

    sanitized = provider._sanitize_messages(messages)

    assert len(sanitized[1]["tool_calls"]) == 1
    assert sanitized[2]["role"] == "tool"
    assert sanitized[2]["tool_call_id"] == sanitized[1]["tool_calls"][0]["id"]


def test_gemini_drops_malformed_tool_call_entries_without_crashing() -> None:
    provider = _gemini_provider()
    messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": None, "tool_calls": [None]},
        {"role": "user", "content": "continue"},
    ]

    sanitized = provider._sanitize_messages(messages)

    assert not any(message.get("tool_calls") for message in sanitized)


def test_gemini_matches_duplicate_tool_ids_by_call_instance() -> None:
    provider = _gemini_provider()
    messages = [
        {"role": "user", "content": "old request"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [_tool_call("reused", "old_tool")],
        },
        {"role": "tool", "content": "old result", "tool_call_id": "reused"},
        {"role": "user", "content": "new request"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [_tool_call("reused", "new_tool", signed=True)],
        },
        {"role": "tool", "content": "new result", "tool_call_id": "reused"},
    ]

    sanitized = provider._sanitize_messages(messages)

    assert any(message.get("content") == "old result" for message in sanitized)
    assert any(message.get("content") == "new result" for message in sanitized)
    calls = [
        call
        for message in sanitized
        for call in message.get("tool_calls", [])
    ]
    assert len(calls) == 2
    assert calls[0]["function"]["name"] == "old_tool"
    assert calls[0]["extra_content"]["google"]["thought_signature"] == (
        "skip_thought_signature_validator"
    )
    assert calls[1]["function"]["name"] == "new_tool"


def test_gemini_backfill_does_not_mutate_caller_history() -> None:
    provider = _gemini_provider()
    call = _tool_call("call_1", "read_file")
    messages = [
        {"role": "user", "content": "read it"},
        {"role": "assistant", "content": None, "tool_calls": [call]},
        {"role": "tool", "content": "contents", "tool_call_id": "call_1"},
    ]

    sanitized = provider._sanitize_messages(messages)

    assert "extra_content" not in call
    assert sanitized[1]["tool_calls"][0]["extra_content"]["google"][
        "thought_signature"
    ] == "skip_thought_signature_validator"
