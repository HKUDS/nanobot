"""Tests for OpenAICompatProvider spec-driven behavior.

Validates that:
- OpenRouter (no strip) keeps model names intact.
- AiHubMix (strip_model_prefix=True) strips provider prefixes.
- Standard providers pass model names through as-is.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.providers.registry import find_by_name


def _fake_chat_response(content: str = "ok") -> SimpleNamespace:
    """Build a minimal OpenAI chat completion response."""
    message = SimpleNamespace(
        content=content,
        tool_calls=None,
        reasoning_content=None,
    )
    choice = SimpleNamespace(message=message, finish_reason="stop")
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    return SimpleNamespace(choices=[choice], usage=usage)


def _fake_tool_call_response() -> SimpleNamespace:
    """Build a minimal chat response that includes Gemini-style extra_content."""
    function = SimpleNamespace(
        name="exec",
        arguments='{"cmd":"ls"}',
        provider_specific_fields={"inner": "value"},
    )
    tool_call = SimpleNamespace(
        id="call_123",
        index=0,
        type="function",
        function=function,
        extra_content={"google": {"thought_signature": "signed-token"}},
    )
    message = SimpleNamespace(
        content=None,
        tool_calls=[tool_call],
        reasoning_content=None,
    )
    choice = SimpleNamespace(message=message, finish_reason="tool_calls")
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    return SimpleNamespace(choices=[choice], usage=usage)


def _fake_responses_response(content: str = "ok") -> MagicMock:
    """Build a minimal Responses API response object."""
    resp = MagicMock()
    resp.model_dump.return_value = {
        "output": [{
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": content}],
        }],
        "status": "completed",
        "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
    }
    return resp


def _fake_responses_stream(text: str = "ok"):
    async def _stream():
        yield SimpleNamespace(type="response.output_text.delta", delta=text)
        yield SimpleNamespace(
            type="response.completed",
            response=SimpleNamespace(
                status="completed",
                usage=SimpleNamespace(input_tokens=10, output_tokens=5, total_tokens=15),
                output=[],
            ),
        )

    return _stream()


def _fake_chat_stream(text: str = "ok"):
    async def _stream():
        yield SimpleNamespace(
            choices=[SimpleNamespace(finish_reason=None, delta=SimpleNamespace(content=text, reasoning_content=None, tool_calls=None))],
            usage=None,
        )
        yield SimpleNamespace(
            choices=[SimpleNamespace(finish_reason="stop", delta=SimpleNamespace(content=None, reasoning_content=None, tool_calls=None))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )

    return _stream()


class _FakeResponsesError(Exception):
    def __init__(self, status_code: int, text: str):
        super().__init__(text)
        self.status_code = status_code
        self.response = SimpleNamespace(status_code=status_code, text=text, headers={})


class _StalledStream:
    def __aiter__(self):
        return self

    async def __anext__(self):
        await asyncio.sleep(3600)
        raise StopAsyncIteration


def test_openrouter_spec_is_gateway() -> None:
    spec = find_by_name("openrouter")
    assert spec is not None
    assert spec.is_gateway is True
    assert spec.default_api_base == "https://openrouter.ai/api/v1"


def test_openrouter_sets_default_attribution_headers() -> None:
    spec = find_by_name("openrouter")
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI") as MockClient:
        OpenAICompatProvider(
            api_key="sk-or-test-key",
            api_base="https://openrouter.ai/api/v1",
            default_model="anthropic/claude-sonnet-4-5",
            spec=spec,
        )

    headers = MockClient.call_args.kwargs["default_headers"]
    assert headers["HTTP-Referer"] == "https://github.com/HKUDS/nanobot"
    assert headers["X-OpenRouter-Title"] == "nanobot"
    assert headers["X-OpenRouter-Categories"] == "cli-agent,personal-agent"
    assert "x-session-affinity" in headers


def test_openrouter_user_headers_override_default_attribution() -> None:
    spec = find_by_name("openrouter")
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI") as MockClient:
        OpenAICompatProvider(
            api_key="sk-or-test-key",
            api_base="https://openrouter.ai/api/v1",
            default_model="anthropic/claude-sonnet-4-5",
            extra_headers={
                "HTTP-Referer": "https://nanobot.ai",
                "X-OpenRouter-Title": "Nanobot Pro",
                "X-Custom-App": "enabled",
            },
            spec=spec,
        )

    headers = MockClient.call_args.kwargs["default_headers"]
    assert headers["HTTP-Referer"] == "https://nanobot.ai"
    assert headers["X-OpenRouter-Title"] == "Nanobot Pro"
    assert headers["X-OpenRouter-Categories"] == "cli-agent,personal-agent"
    assert headers["X-Custom-App"] == "enabled"


@pytest.mark.asyncio
async def test_openrouter_keeps_model_name_intact() -> None:
    """OpenRouter gateway keeps the full model name (gateway does its own routing)."""
    mock_create = AsyncMock(return_value=_fake_chat_response())
    spec = find_by_name("openrouter")

    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI") as MockClient:
        client_instance = MockClient.return_value
        client_instance.chat.completions.create = mock_create

        provider = OpenAICompatProvider(
            api_key="sk-or-test-key",
            api_base="https://openrouter.ai/api/v1",
            default_model="anthropic/claude-sonnet-4-5",
            spec=spec,
        )
        await provider.chat(
            messages=[{"role": "user", "content": "hello"}],
            model="anthropic/claude-sonnet-4-5",
        )

    call_kwargs = mock_create.call_args.kwargs
    assert call_kwargs["model"] == "anthropic/claude-sonnet-4-5"


@pytest.mark.asyncio
async def test_aihubmix_strips_model_prefix() -> None:
    """AiHubMix strips the provider prefix (strip_model_prefix=True)."""
    mock_create = AsyncMock(return_value=_fake_chat_response())
    spec = find_by_name("aihubmix")

    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI") as MockClient:
        client_instance = MockClient.return_value
        client_instance.chat.completions.create = mock_create

        provider = OpenAICompatProvider(
            api_key="sk-aihub-test-key",
            api_base="https://aihubmix.com/v1",
            default_model="claude-sonnet-4-5",
            spec=spec,
        )
        await provider.chat(
            messages=[{"role": "user", "content": "hello"}],
            model="anthropic/claude-sonnet-4-5",
        )

    call_kwargs = mock_create.call_args.kwargs
    assert call_kwargs["model"] == "claude-sonnet-4-5"


@pytest.mark.asyncio
async def test_standard_provider_passes_model_through() -> None:
    """Standard provider (e.g. deepseek) passes model name through as-is."""
    mock_create = AsyncMock(return_value=_fake_chat_response())
    spec = find_by_name("deepseek")

    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI") as MockClient:
        client_instance = MockClient.return_value
        client_instance.chat.completions.create = mock_create

        provider = OpenAICompatProvider(
            api_key="sk-deepseek-test-key",
            default_model="deepseek-chat",
            spec=spec,
        )
        await provider.chat(
            messages=[{"role": "user", "content": "hello"}],
            model="deepseek-chat",
        )

    call_kwargs = mock_create.call_args.kwargs
    assert call_kwargs["model"] == "deepseek-chat"


@pytest.mark.asyncio
async def test_openai_compat_preserves_extra_content_on_tool_calls() -> None:
    """Gemini extra_content (thought signatures) must survive parse→serialize round-trip."""
    mock_create = AsyncMock(return_value=_fake_tool_call_response())
    spec = find_by_name("gemini")

    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI") as MockClient:
        client_instance = MockClient.return_value
        client_instance.chat.completions.create = mock_create

        provider = OpenAICompatProvider(
            api_key="test-key",
            api_base="https://generativelanguage.googleapis.com/v1beta/openai/",
            default_model="google/gemini-3.1-pro-preview",
            spec=spec,
        )
        result = await provider.chat(
            messages=[{"role": "user", "content": "run exec"}],
            model="google/gemini-3.1-pro-preview",
        )

    assert len(result.tool_calls) == 1
    tool_call = result.tool_calls[0]
    assert tool_call.extra_content == {"google": {"thought_signature": "signed-token"}}
    assert tool_call.function_provider_specific_fields == {"inner": "value"}

    serialized = tool_call.to_openai_tool_call()
    assert serialized["extra_content"] == {"google": {"thought_signature": "signed-token"}}
    assert serialized["function"]["provider_specific_fields"] == {"inner": "value"}


def test_openai_model_passthrough() -> None:
    """OpenAI models pass through unchanged."""
    spec = find_by_name("openai")
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider(
            api_key="sk-test-key",
            default_model="gpt-4o",
            spec=spec,
        )
    assert provider.get_default_model() == "gpt-4o"


@pytest.mark.asyncio
async def test_direct_openai_gpt5_uses_responses_api() -> None:
    mock_chat = AsyncMock(return_value=_fake_chat_response())
    mock_responses = AsyncMock(return_value=_fake_responses_response("from responses"))
    spec = find_by_name("openai")

    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI") as MockClient:
        client_instance = MockClient.return_value
        client_instance.chat.completions.create = mock_chat
        client_instance.responses.create = mock_responses

        provider = OpenAICompatProvider(
            api_key="sk-test-key",
            default_model="gpt-5-chat",
            spec=spec,
        )
        result = await provider.chat(
            messages=[{"role": "user", "content": "hello"}],
            model="gpt-5-chat",
        )

    assert result.content == "from responses"
    mock_responses.assert_awaited_once()
    mock_chat.assert_not_awaited()
    call_kwargs = mock_responses.call_args.kwargs
    assert call_kwargs["model"] == "gpt-5-chat"
    assert call_kwargs["max_output_tokens"] == 4096
    assert "input" in call_kwargs
    assert "messages" not in call_kwargs


@pytest.mark.asyncio
async def test_direct_openai_reasoning_prefers_responses_api() -> None:
    mock_chat = AsyncMock(return_value=_fake_chat_response())
    mock_responses = AsyncMock(return_value=_fake_responses_response("reasoned"))
    spec = find_by_name("openai")

    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI") as MockClient:
        client_instance = MockClient.return_value
        client_instance.chat.completions.create = mock_chat
        client_instance.responses.create = mock_responses

        provider = OpenAICompatProvider(
            api_key="sk-test-key",
            default_model="gpt-4o",
            spec=spec,
        )
        await provider.chat(
            messages=[{"role": "user", "content": "hello"}],
            model="gpt-4o",
            reasoning_effort="medium",
        )

    mock_responses.assert_awaited_once()
    mock_chat.assert_not_awaited()
    call_kwargs = mock_responses.call_args.kwargs
    assert call_kwargs["reasoning"] == {"effort": "medium"}
    assert call_kwargs["include"] == ["reasoning.encrypted_content"]


@pytest.mark.asyncio
async def test_direct_openai_gpt4o_stays_on_chat_completions() -> None:
    mock_chat = AsyncMock(return_value=_fake_chat_response())
    mock_responses = AsyncMock(return_value=_fake_responses_response())
    spec = find_by_name("openai")

    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI") as MockClient:
        client_instance = MockClient.return_value
        client_instance.chat.completions.create = mock_chat
        client_instance.responses.create = mock_responses

        provider = OpenAICompatProvider(
            api_key="sk-test-key",
            default_model="gpt-4o",
            spec=spec,
        )
        await provider.chat(
            messages=[{"role": "user", "content": "hello"}],
            model="gpt-4o",
        )

    mock_chat.assert_awaited_once()
    mock_responses.assert_not_awaited()


@pytest.mark.asyncio
async def test_openrouter_gpt5_stays_on_chat_completions() -> None:
    mock_chat = AsyncMock(return_value=_fake_chat_response())
    mock_responses = AsyncMock(return_value=_fake_responses_response())
    spec = find_by_name("openrouter")

    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI") as MockClient:
        client_instance = MockClient.return_value
        client_instance.chat.completions.create = mock_chat
        client_instance.responses.create = mock_responses

        provider = OpenAICompatProvider(
            api_key="sk-or-test-key",
            api_base="https://openrouter.ai/api/v1",
            default_model="openai/gpt-5",
            spec=spec,
        )
        await provider.chat(
            messages=[{"role": "user", "content": "hello"}],
            model="openai/gpt-5",
        )

    mock_chat.assert_awaited_once()
    mock_responses.assert_not_awaited()


@pytest.mark.asyncio
async def test_direct_openai_streaming_gpt5_uses_responses_api() -> None:
    mock_chat = AsyncMock(return_value=_StalledStream())
    mock_responses = AsyncMock(return_value=_fake_responses_stream("hi"))
    spec = find_by_name("openai")

    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI") as MockClient:
        client_instance = MockClient.return_value
        client_instance.chat.completions.create = mock_chat
        client_instance.responses.create = mock_responses

        provider = OpenAICompatProvider(
            api_key="sk-test-key",
            default_model="gpt-5-chat",
            spec=spec,
        )
        result = await provider.chat_stream(
            messages=[{"role": "user", "content": "hello"}],
            model="gpt-5-chat",
        )

    assert result.content == "hi"
    assert result.finish_reason == "stop"
    mock_responses.assert_awaited_once()
    mock_chat.assert_not_awaited()


@pytest.mark.asyncio
async def test_direct_openai_responses_404_falls_back_to_chat_completions() -> None:
    mock_chat = AsyncMock(return_value=_fake_chat_response("from chat"))
    mock_responses = AsyncMock(side_effect=_FakeResponsesError(404, "Responses endpoint not supported"))
    spec = find_by_name("openai")

    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI") as MockClient:
        client_instance = MockClient.return_value
        client_instance.chat.completions.create = mock_chat
        client_instance.responses.create = mock_responses

        provider = OpenAICompatProvider(
            api_key="sk-test-key",
            default_model="gpt-5-chat",
            spec=spec,
        )
        result = await provider.chat(
            messages=[{"role": "user", "content": "hello"}],
            model="gpt-5-chat",
        )

    assert result.content == "from chat"
    mock_responses.assert_awaited_once()
    mock_chat.assert_awaited_once()


@pytest.mark.asyncio
async def test_direct_openai_open_circuit_skips_responses_api() -> None:
    mock_chat = AsyncMock(return_value=_fake_chat_response("from chat"))
    mock_responses = AsyncMock(return_value=_fake_responses_response("from responses"))
    spec = find_by_name("openai")

    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI") as MockClient:
        client_instance = MockClient.return_value
        client_instance.chat.completions.create = mock_chat
        client_instance.responses.create = mock_responses

        provider = OpenAICompatProvider(
            api_key="sk-test-key",
            default_model="gpt-5-chat",
            spec=spec,
        )
        for _ in range(3):
            provider._record_responses_failure("gpt-5-chat", None)

        result = await provider.chat(
            messages=[{"role": "user", "content": "hello"}],
            model="gpt-5-chat",
        )

    assert result.content == "from chat"
    mock_responses.assert_not_awaited()
    mock_chat.assert_awaited_once()


@pytest.mark.asyncio
async def test_direct_openai_stream_responses_unsupported_param_falls_back() -> None:
    mock_chat = AsyncMock(return_value=_fake_chat_stream("fallback stream"))
    mock_responses = AsyncMock(
        side_effect=_FakeResponsesError(400, "Unknown parameter: max_output_tokens for Responses API")
    )
    spec = find_by_name("openai")

    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI") as MockClient:
        client_instance = MockClient.return_value
        client_instance.chat.completions.create = mock_chat
        client_instance.responses.create = mock_responses

        provider = OpenAICompatProvider(
            api_key="sk-test-key",
            default_model="gpt-5-chat",
            spec=spec,
        )
        result = await provider.chat_stream(
            messages=[{"role": "user", "content": "hello"}],
            model="gpt-5-chat",
        )

    assert result.content == "fallback stream"
    mock_responses.assert_awaited_once()
    mock_chat.assert_awaited_once()


@pytest.mark.asyncio
async def test_direct_openai_responses_rate_limit_does_not_fallback() -> None:
    mock_chat = AsyncMock(return_value=_fake_chat_response("from chat"))
    mock_responses = AsyncMock(side_effect=_FakeResponsesError(429, "rate limit"))
    spec = find_by_name("openai")

    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI") as MockClient:
        client_instance = MockClient.return_value
        client_instance.chat.completions.create = mock_chat
        client_instance.responses.create = mock_responses

        provider = OpenAICompatProvider(
            api_key="sk-test-key",
            default_model="gpt-5-chat",
            spec=spec,
        )
        result = await provider.chat(
            messages=[{"role": "user", "content": "hello"}],
            model="gpt-5-chat",
        )

    assert result.finish_reason == "error"
    mock_responses.assert_awaited_once()
    mock_chat.assert_not_awaited()


def test_openai_compat_supports_temperature_matches_reasoning_model_rules() -> None:
    assert OpenAICompatProvider._supports_temperature("gpt-4o") is True
    assert OpenAICompatProvider._supports_temperature("gpt-5-chat") is False
    assert OpenAICompatProvider._supports_temperature("o3-mini") is False
    assert OpenAICompatProvider._supports_temperature("gpt-4o", reasoning_effort="medium") is False


def test_openai_compat_build_kwargs_uses_gpt5_safe_parameters() -> None:
    spec = find_by_name("openai")
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider(
            api_key="sk-test-key",
            default_model="gpt-5-chat",
            spec=spec,
        )

    kwargs = provider._build_kwargs(
        messages=[{"role": "user", "content": "hello"}],
        tools=None,
        model="gpt-5-chat",
        max_tokens=4096,
        temperature=0.7,
        reasoning_effort=None,
        tool_choice=None,
    )

    assert kwargs["model"] == "gpt-5-chat"
    assert kwargs["max_completion_tokens"] == 4096
    assert "max_tokens" not in kwargs
    assert "temperature" not in kwargs


def test_openai_compat_preserves_message_level_reasoning_fields() -> None:
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider()

    sanitized = provider._sanitize_messages([
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": "done",
            "reasoning_content": "hidden",
            "extra_content": {"debug": True},
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "fn", "arguments": "{}"},
                    "extra_content": {"google": {"thought_signature": "sig"}},
                }
            ],
        },
        {"role": "user", "content": "thanks"},
    ])

    assert sanitized[1]["content"] is None
    assert sanitized[1]["reasoning_content"] == "hidden"
    assert sanitized[1]["extra_content"] == {"debug": True}
    assert sanitized[1]["tool_calls"][0]["extra_content"] == {"google": {"thought_signature": "sig"}}


def _deepseek_kwargs(messages: list[dict]) -> dict:
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider(
            api_key="sk-test",
            default_model="deepseek-v4-flash",
            spec=find_by_name("deepseek"),
        )

    return provider._build_kwargs(
        messages=messages,
        tools=None,
        model="deepseek-v4-flash",
        max_tokens=1024,
        temperature=0.7,
        reasoning_effort="high",
        tool_choice=None,
    )


def _tool_call(call_id: str) -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": "my", "arguments": "{}"},
    }


def test_deepseek_thinking_drops_tool_history_missing_reasoning_content() -> None:
    kwargs = _deepseek_kwargs([
        {"role": "system", "content": "system"},
        {"role": "user", "content": "can we use wechat?"},
        {"role": "assistant", "content": "", "tool_calls": [_tool_call("call_bad")]},
        {"role": "tool", "tool_call_id": "call_bad", "name": "my", "content": "channels"},
        {"role": "user", "content": "continue"},
    ])

    assert kwargs["messages"] == [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "continue"},
    ]


def test_deepseek_thinking_keeps_tool_history_with_reasoning_content() -> None:
    kwargs = _deepseek_kwargs([
        {"role": "user", "content": "can we use wechat?"},
        {
            "role": "assistant",
            "content": "",
            "reasoning_content": "I should inspect supported channels.",
            "tool_calls": [_tool_call("call_good")],
        },
        {"role": "tool", "tool_call_id": "call_good", "name": "my", "content": "channels"},
        {"role": "user", "content": "continue"},
    ])

    assistant = kwargs["messages"][1]
    assert assistant["role"] == "assistant"
    assert assistant["reasoning_content"] == "I should inspect supported channels."
    assert kwargs["messages"][2]["role"] == "tool"


def test_deepseek_thinking_drops_current_bad_tool_turn_without_followup_user() -> None:
    kwargs = _deepseek_kwargs([
        {"role": "system", "content": "system"},
        {"role": "user", "content": "can we use wechat?"},
        {"role": "assistant", "content": "", "tool_calls": [_tool_call("call_bad")]},
        {"role": "tool", "tool_call_id": "call_bad", "name": "my", "content": "channels"},
    ])

    assert kwargs["messages"] == [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "can we use wechat?"},
    ]


def test_openai_compat_keeps_tool_calls_after_consecutive_assistant_messages() -> None:
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider()

    sanitized = provider._sanitize_messages([
        {"role": "user", "content": "不错"},
        {"role": "assistant", "content": "对，破 4 万指日可待"},
        {
            "role": "assistant",
            "content": "<think>我再查一下</think>",
            "tool_calls": [
                {
                    "id": "call_function_akxp3wqzn7ph_1",
                    "type": "function",
                    "function": {"name": "exec", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_function_akxp3wqzn7ph_1", "name": "exec", "content": "ok"},
        {"role": "user", "content": "多少star了呢"},
    ])

    assert sanitized[1]["role"] == "assistant"
    assert sanitized[1]["content"] is None
    assert sanitized[1]["tool_calls"][0]["id"] == "3ec83c30d"
    assert sanitized[2]["tool_call_id"] == "3ec83c30d"


def test_openai_compat_stringifies_dict_tool_arguments() -> None:
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider()

    sanitized = provider._sanitize_messages([
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "exec", "arguments": {"cmd": "ls -la"}},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "name": "exec", "content": "ok"},
        {"role": "user", "content": "done"},
    ])

    assert sanitized[1]["tool_calls"][0]["function"]["arguments"] == '{"cmd": "ls -la"}'


def test_openai_compat_repairs_non_json_tool_arguments_string() -> None:
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider()

    sanitized = provider._sanitize_messages([
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "exec", "arguments": "{'cmd': 'pwd'}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "name": "exec", "content": "ok"},
        {"role": "user", "content": "done"},
    ])

    assert sanitized[1]["tool_calls"][0]["function"]["arguments"] == '{"cmd": "pwd"}'


def test_openai_compat_defaults_missing_tool_arguments_to_empty_object() -> None:
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider()

    sanitized = provider._sanitize_messages([
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "exec"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "name": "exec", "content": "ok"},
        {"role": "user", "content": "done"},
    ])

    assert sanitized[1]["tool_calls"][0]["function"]["arguments"] == "{}"


@pytest.mark.asyncio
async def test_openai_compat_stream_watchdog_returns_error_on_stall(monkeypatch) -> None:
    monkeypatch.setenv("NANOBOT_STREAM_IDLE_TIMEOUT_S", "0")
    mock_create = AsyncMock(return_value=_StalledStream())
    spec = find_by_name("openai")

    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI") as MockClient:
        client_instance = MockClient.return_value
        client_instance.chat.completions.create = mock_create

        provider = OpenAICompatProvider(
            api_key="sk-test-key",
            default_model="gpt-4o",
            spec=spec,
        )
        result = await provider.chat_stream(
            messages=[{"role": "user", "content": "hello"}],
            model="gpt-4o",
        )

    assert result.finish_reason == "error"
    assert result.content is not None
    assert "stream stalled" in result.content


# ---------------------------------------------------------------------------
# Provider-specific thinking parameters (extra_body)
# ---------------------------------------------------------------------------

def _build_kwargs_for(provider_name: str, model: str, reasoning_effort=None):
    spec = find_by_name(provider_name)
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        p = OpenAICompatProvider(api_key="k", default_model=model, spec=spec)
    return p._build_kwargs(
        messages=[{"role": "user", "content": "hi"}],
        tools=None, model=model, max_tokens=1024, temperature=0.7,
        reasoning_effort=reasoning_effort, tool_choice=None,
    )


def test_dashscope_thinking_enabled_with_reasoning_effort() -> None:
    kw = _build_kwargs_for("dashscope", "qwen3-plus", reasoning_effort="medium")
    assert kw["extra_body"] == {"enable_thinking": True}


def test_dashscope_thinking_disabled_for_minimal() -> None:
    """'minimal' → wire 'minimum' + thinking off on DashScope."""
    kw = _build_kwargs_for("dashscope", "qwen3-plus", reasoning_effort="minimal")
    assert kw["reasoning_effort"] == "minimum"
    assert kw["extra_body"] == {"enable_thinking": False}


def test_dashscope_thinking_disabled_for_minimum_alias() -> None:
    """Native 'minimum' spelling must also disable thinking, not enable it."""
    kw = _build_kwargs_for("dashscope", "qwen3-plus", reasoning_effort="minimum")
    assert kw["reasoning_effort"] == "minimum"
    assert kw["extra_body"] == {"enable_thinking": False}


def test_non_dashscope_minimal_not_retranslated() -> None:
    """DashScope-specific translation must not leak to other providers."""
    kw = _build_kwargs_for("openai", "gpt-5", reasoning_effort="minimal")
    assert kw["reasoning_effort"] == "minimal"


def test_dashscope_no_extra_body_when_reasoning_effort_none() -> None:
    kw = _build_kwargs_for("dashscope", "qwen-turbo", reasoning_effort=None)
    assert "extra_body" not in kw


def test_minimax_reasoning_split_enabled_with_reasoning_effort() -> None:
    kw = _build_kwargs_for("minimax", "MiniMax-M2.7", reasoning_effort="medium")
    assert kw["extra_body"] == {"reasoning_split": True}


def test_minimax_reasoning_split_disabled_for_minimal() -> None:
    kw = _build_kwargs_for("minimax", "MiniMax-M2.7", reasoning_effort="minimal")
    assert kw["extra_body"] == {"reasoning_split": False}


def test_minimax_no_extra_body_when_reasoning_effort_none() -> None:
    kw = _build_kwargs_for("minimax", "MiniMax-M2.7", reasoning_effort=None)
    assert "extra_body" not in kw


def test_volcengine_thinking_enabled() -> None:
    kw = _build_kwargs_for("volcengine", "doubao-seed-2-0-pro", reasoning_effort="high")
    assert kw["extra_body"] == {"thinking": {"type": "enabled"}}


def test_byteplus_thinking_disabled_for_minimal() -> None:
    kw = _build_kwargs_for("byteplus", "doubao-seed-2-0-pro", reasoning_effort="minimal")
    assert kw["extra_body"] == {"thinking": {"type": "disabled"}}


def test_byteplus_no_extra_body_when_reasoning_effort_none() -> None:
    kw = _build_kwargs_for("byteplus", "doubao-seed-2-0-pro", reasoning_effort=None)
    assert "extra_body" not in kw


def test_deepseek_thinking_enabled() -> None:
    """DeepSeek V4 requires extra_body.thinking when reasoning_effort is set."""
    kw = _build_kwargs_for("deepseek", "deepseek-v4-pro", reasoning_effort="high")
    assert kw["extra_body"] == {"thinking": {"type": "enabled"}}


def test_deepseek_thinking_disabled_for_minimal() -> None:
    """reasoning_effort='minimal' must send thinking.type=disabled to DeepSeek."""
    kw = _build_kwargs_for("deepseek", "deepseek-v4-pro", reasoning_effort="minimal")
    assert kw["extra_body"] == {"thinking": {"type": "disabled"}}


def test_deepseek_no_extra_body_when_reasoning_effort_none() -> None:
    """Without reasoning_effort the thinking param must not be injected."""
    kw = _build_kwargs_for("deepseek", "deepseek-chat", reasoning_effort=None)
    assert "extra_body" not in kw


def test_deepseek_backfills_reasoning_content_on_legacy_tool_call_messages() -> None:
    """Session messages from before thinking mode was enabled may have assistant
    messages with tool_calls but no reasoning_content. DeepSeek V4 rejects these
    with 400. _build_kwargs must backfill reasoning_content='' on them."""
    spec = find_by_name("deepseek")
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        p = OpenAICompatProvider(api_key="k", default_model="deepseek-v4-pro", spec=spec)
    messages = [
        {"role": "user", "content": "search for news"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "tc1", "type": "function", "function": {"name": "web_search", "arguments": "{}"}}
        ]},
        {"role": "tool", "tool_call_id": "tc1", "content": "result"},
        {"role": "assistant", "content": "Here are the results."},
        {"role": "user", "content": "hi"},
    ]
    kw = p._build_kwargs(
        messages=messages, tools=None, model="deepseek-v4-pro",
        max_tokens=1024, temperature=0.7,
        reasoning_effort="high", tool_choice=None,
    )
    for msg in kw["messages"]:
        if msg.get("role") == "assistant":
            assert "reasoning_content" in msg, "legacy assistant message missing reasoning_content"
            assert msg["reasoning_content"] == ""


def test_backfill_does_not_touch_messages_when_thinking_off() -> None:
    """When reasoning_effort is None or minimal, legacy messages must NOT be altered."""
    spec = find_by_name("deepseek")
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        p = OpenAICompatProvider(api_key="k", default_model="deepseek-v4-pro", spec=spec)
    messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "tc1", "type": "function", "function": {"name": "web_search", "arguments": "{}"}}
        ]},
        {"role": "tool", "tool_call_id": "tc1", "content": "result"},
        {"role": "user", "content": "thanks"},
    ]
    for effort in (None, "minimal"):
        kw = p._build_kwargs(
            messages=list(messages), tools=None, model="deepseek-v4-pro",
            max_tokens=1024, temperature=0.7,
            reasoning_effort=effort, tool_choice=None,
        )
        for msg in kw["messages"]:
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                assert "reasoning_content" not in msg


def test_openai_no_thinking_extra_body() -> None:
    """Non-thinking providers should never get extra_body for thinking."""
    kw = _build_kwargs_for("openai", "gpt-4o", reasoning_effort="medium")
    assert "extra_body" not in kw


def test_kimi_k25_thinking_enabled() -> None:
    """kimi-k2.5 with reasoning_effort set should opt in to thinking."""
    kw = _build_kwargs_for("moonshot", "kimi-k2.5", reasoning_effort="medium")
    assert kw.get("extra_body") == {"thinking": {"type": "enabled"}}


def test_kimi_k25_thinking_disabled_for_minimal() -> None:
    """reasoning_effort='minimal' maps to thinking disabled for kimi-k2.5."""
    kw = _build_kwargs_for("moonshot", "kimi-k2.5", reasoning_effort="minimal")
    assert kw.get("extra_body") == {"thinking": {"type": "disabled"}}


def test_kimi_k25_no_extra_body_when_reasoning_effort_none() -> None:
    """Without reasoning_effort the thinking param must not be injected."""
    kw = _build_kwargs_for("moonshot", "kimi-k2.5", reasoning_effort=None)
    assert "extra_body" not in kw


def test_kimi_k25_thinking_enabled_with_openrouter_prefix() -> None:
    """OpenRouter-style model names like moonshotai/kimi-k2.5 must trigger thinking."""
    kw = _build_kwargs_for("openrouter", "moonshotai/kimi-k2.5", reasoning_effort="medium")
    assert kw.get("extra_body") == {"thinking": {"type": "enabled"}}


def test_kimi_k26_thinking_enabled() -> None:
    """kimi-k2.6 with reasoning_effort set should opt in to thinking."""
    kw = _build_kwargs_for("moonshot", "kimi-k2.6", reasoning_effort="medium")
    assert kw.get("extra_body") == {"thinking": {"type": "enabled"}}


def test_kimi_k26_thinking_enabled_with_openrouter_prefix() -> None:
    """OpenRouter-style names like moonshotai/kimi-k2.6 must trigger thinking."""
    kw = _build_kwargs_for("openrouter", "moonshotai/kimi-k2.6", reasoning_effort="medium")
    assert kw.get("extra_body") == {"thinking": {"type": "enabled"}}


def test_moonshot_kimi_k26_temperature_override() -> None:
    """Moonshot registry forces temperature 1.0 for kimi-k2.6 (API requirement)."""
    kw = _build_kwargs_for("moonshot", "kimi-k2.6", reasoning_effort=None)
    assert kw["temperature"] == 1.0


def test_kimi_k25_thinking_disabled_with_openrouter_prefix() -> None:
    """OpenRouter names must NOT trigger thinking without reasoning_effort."""
    kw = _build_kwargs_for("openrouter", "moonshotai/kimi-k2.5", reasoning_effort=None)
    assert "extra_body" not in kw


def test_kimi_k26_code_preview_thinking_enabled() -> None:
    """k2.6-code-preview also supports thinking; should behave like k2.5."""
    kw = _build_kwargs_for("moonshot", "k2.6-code-preview", reasoning_effort="high")
    assert kw.get("extra_body") == {"thinking": {"type": "enabled"}}


def test_kimi_k2_series_no_thinking_injection() -> None:
    """kimi-k2 (non-thinking) models must NOT receive extra_body.thinking."""
    kw = _build_kwargs_for("moonshot", "kimi-k2", reasoning_effort="high")
    assert "extra_body" not in kw


def test_kimi_k2_thinking_series_no_thinking_injection() -> None:
    """kimi-k2-thinking series models must NOT receive extra_body.thinking."""
    kw = _build_kwargs_for("moonshot", "kimi-k2-thinking", reasoning_effort="high")
    assert "extra_body" not in kw
