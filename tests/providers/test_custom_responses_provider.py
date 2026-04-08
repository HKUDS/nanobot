"""Tests for custom Responses provider (OpenAI SDK Responses API)."""

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.providers.base import LLMResponse
from nanobot.providers.custom_responses_provider import CustomResponsesProvider


def _make_sdk_response(
    content: str = "Hello!",
    *,
    status: str = "completed",
    usage: dict[str, int] | None = None,
    output: list[dict[str, object]] | None = None,
    extra_fields: dict[str, object] | None = None,
) -> MagicMock:
    """Build a minimal SDK-like Response object."""
    resp = MagicMock()
    output_items = output or [
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": content}],
        }
    ]
    payload: dict[str, object] = {
        "output": output_items,
        "status": status,
        "usage": usage or {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
    }
    if extra_fields:
        payload.update(extra_fields)
    resp.model_dump = MagicMock(return_value=payload)
    return resp


def test_init_base_url_with_v1_no_trailing_slash() -> None:
    provider = CustomResponsesProvider(api_key="k", api_base="https://api.example.com/v1")
    assert str(provider._client.base_url).rstrip("/").endswith("/v1")


def test_init_base_url_with_v1_trailing_slash() -> None:
    provider = CustomResponsesProvider(api_key="k", api_base="https://api.example.com/v1/")
    assert str(provider._client.base_url).rstrip("/").endswith("/v1")


def test_init_passes_extra_headers() -> None:
    provider = CustomResponsesProvider(
        api_key="k",
        api_base="https://api.example.com/v1",
        extra_headers={"X-Custom-Header": "demo"},
    )
    assert provider._client.default_headers["X-Custom-Header"] == "demo"
    assert "x-session-affinity" in provider._client.default_headers


@pytest.mark.asyncio
async def test_chat_non_streaming_uses_responses_create_and_maps_request_fields() -> None:
    provider = CustomResponsesProvider(api_key="k", api_base="https://api.example.com/v1")

    responses_create = AsyncMock(return_value=_make_sdk_response("ok"))
    chat_create = AsyncMock()
    with (
        patch.object(provider._client.responses, "create", responses_create),
        patch.object(provider._client.chat.completions, "create", chat_create),
    ):
        result = await provider.chat(
            messages=[
                {"role": "system", "content": "Be concise."},
                {"role": "developer", "content": "Use short bullets."},
                {"role": "user", "content": "Hello"},
            ],
            tools=[{"type": "function", "function": {"name": "echo", "parameters": {}}}],
            max_tokens=128,
            tool_choice="required",
            reasoning_effort="medium",
            parallel_tool_calls=True,
        )

    assert isinstance(result, LLMResponse)
    assert result.content == "ok"

    responses_create.assert_awaited_once()
    chat_create.assert_not_awaited()

    req = cast(dict[str, Any], responses_create.call_args[1])
    assert req["instructions"] == "Be concise.\n\nUse short bullets."
    assert req["input"][0]["role"] == "user"
    assert req["max_output_tokens"] == 128
    assert req["tools"] == [
        {"type": "function", "name": "echo", "description": "", "parameters": {}}
    ]
    assert req["tool_choice"] == "required"
    assert req["parallel_tool_calls"] is True
    assert req["reasoning"] == {"effort": "medium"}
    assert "messages" not in req
    assert "max_tokens" not in req
    assert "temperature" not in req
    for excluded in (
        "previous_response_id",
        "store",
        "include",
        "conversation",
        "background",
        "metadata",
    ):
        assert excluded not in req
    assert result.usage == {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}


@pytest.mark.asyncio
async def test_chat_non_streaming_parses_tool_call_and_incomplete_status() -> None:
    provider = CustomResponsesProvider(api_key="k", api_base="https://api.example.com/v1")

    tool_output: list[dict[str, object]] = [
        {
            "type": "function_call",
            "id": "fc_42",
            "call_id": "call_42",
            "name": "echo",
            "arguments": '{"msg":"hi"}',
        }
    ]
    responses_create = AsyncMock(
        return_value=_make_sdk_response(
            status="incomplete",
            usage={"input_tokens": 8, "output_tokens": 0, "total_tokens": 8},
            output=tool_output,
        )
    )
    with patch.object(provider._client.responses, "create", responses_create):
        result = await provider.chat(
            messages=[{"role": "user", "content": "Call echo"}],
            tools=[{"type": "function", "function": {"name": "echo", "parameters": {}}}],
        )

    assert result.finish_reason == "length"
    assert result.content is None
    assert result.usage == {"prompt_tokens": 8, "completion_tokens": 0, "total_tokens": 8}
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].id == "call_42|fc_42"
    assert result.tool_calls[0].name == "echo"
    assert result.tool_calls[0].arguments == {"msg": "hi"}


@pytest.mark.asyncio
async def test_chat_stream_first_uses_deltas_when_completed_payload_is_empty() -> None:
    provider = CustomResponsesProvider(api_key="k", api_base="https://api.example.com/v1")

    delta_1 = SimpleNamespace(type="response.output_text.delta", delta="Hello")
    delta_2 = SimpleNamespace(type="response.output_text.delta", delta=" from stream")
    usage_obj = SimpleNamespace(input_tokens=11, output_tokens=3, total_tokens=14)
    completed_response = SimpleNamespace(
        status="completed",
        usage=usage_obj,
        output_text=None,
        output=[],
    )
    completed = SimpleNamespace(type="response.completed", response=completed_response)

    async def mock_stream():
        for event in [delta_1, delta_2, completed]:
            yield event

    responses_create = AsyncMock(return_value=mock_stream())
    with patch.object(provider._client.responses, "create", responses_create):
        result = await provider.chat(messages=[{"role": "user", "content": "Hi"}])

    req = responses_create.call_args[1]
    assert req["stream"] is True
    assert req["input"][0]["role"] == "user"
    assert "messages" not in req
    assert "max_tokens" not in req
    assert "temperature" not in req
    for excluded in (
        "previous_response_id",
        "store",
        "include",
        "conversation",
        "background",
        "metadata",
    ):
        assert excluded not in req

    assert result.finish_reason == "stop"
    assert result.content == "Hello from stream"
    assert result.usage == {"prompt_tokens": 11, "completion_tokens": 3, "total_tokens": 14}


@pytest.mark.asyncio
async def test_chat_stream_first_finalizes_tool_call_arguments_from_stream_events() -> None:
    provider = CustomResponsesProvider(api_key="k", api_base="https://api.example.com/v1")

    item_added = SimpleNamespace(
        type="response.output_item.added",
        item=SimpleNamespace(
            type="function_call",
            id="fc_77",
            call_id="call_77",
            name="weather",
            arguments="",
        ),
    )
    args_delta = SimpleNamespace(
        type="response.function_call_arguments.delta",
        call_id="call_77",
        delta='{"city":"Bei',
    )
    args_done = SimpleNamespace(
        type="response.function_call_arguments.done",
        call_id="call_77",
        arguments='{"city":"Beijing"}',
    )
    item_done = SimpleNamespace(
        type="response.output_item.done",
        item=SimpleNamespace(
            type="function_call",
            id="fc_77",
            call_id="call_77",
            name="weather",
            arguments="{}",
        ),
    )
    completed_response = SimpleNamespace(
        status="completed", usage=None, output_text=None, output=[]
    )
    completed = SimpleNamespace(type="response.completed", response=completed_response)

    async def mock_stream():
        for event in [item_added, args_delta, args_done, item_done, completed]:
            yield event

    responses_create = AsyncMock(return_value=mock_stream())
    with patch.object(provider._client.responses, "create", responses_create):
        result = await provider.chat(
            messages=[{"role": "user", "content": "Call weather"}],
            tools=[{"type": "function", "function": {"name": "weather", "parameters": {}}}],
        )

    assert result.finish_reason == "stop"
    assert result.content is None
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].id == "call_77|fc_77"
    assert result.tool_calls[0].name == "weather"
    assert result.tool_calls[0].arguments == {"city": "Beijing"}


@pytest.mark.asyncio
async def test_chat_non_streaming_failed_status_with_error_shape_maps_to_error() -> None:
    provider = CustomResponsesProvider(api_key="k", api_base="https://api.example.com/v1")

    responses_create = AsyncMock(
        return_value=_make_sdk_response(
            content="",
            status="failed",
            output=[],
            usage={"input_tokens": 1, "output_tokens": 0, "total_tokens": 1},
            extra_fields={
                "error": {"code": "server_error", "message": "boom"},
                "incomplete_details": {"reason": "max_output_tokens"},
            },
        )
    )

    with patch.object(provider._client.responses, "create", responses_create):
        result = await provider.chat(messages=[{"role": "user", "content": "Hi"}])

    assert result.finish_reason == "error"
    assert result.content is None
    assert result.usage == {"prompt_tokens": 1, "completion_tokens": 0, "total_tokens": 1}


@pytest.mark.asyncio
async def test_chat_stream_uses_responses_create_and_emits_deltas() -> None:
    provider = CustomResponsesProvider(api_key="k", api_base="https://api.example.com/v1")

    ev1 = MagicMock(type="response.output_text.delta", delta="Hello")
    ev2 = MagicMock(type="response.output_text.delta", delta=" world")
    resp_obj = MagicMock(status="completed", usage=None, output=[])
    ev3 = MagicMock(type="response.completed", response=resp_obj)

    async def mock_stream():
        for event in [ev1, ev2, ev3]:
            yield event

    responses_create = AsyncMock(return_value=mock_stream())
    chat_create = AsyncMock()

    deltas: list[str] = []

    async def on_delta(text: str) -> None:
        deltas.append(text)

    with (
        patch.object(provider._client.responses, "create", responses_create),
        patch.object(provider._client.chat.completions, "create", chat_create),
    ):
        result = await provider.chat_stream(
            [{"role": "user", "content": "Hi"}],
            on_content_delta=on_delta,
        )

    assert result.content == "Hello world"
    assert result.finish_reason == "stop"
    assert deltas == ["Hello", " world"]
    responses_create.assert_awaited_once()
    chat_create.assert_not_awaited()


@pytest.mark.asyncio
async def test_chat_stream_parses_tool_calls_usage_reasoning_and_incomplete_status() -> None:
    provider = CustomResponsesProvider(api_key="k", api_base="https://api.example.com/v1")

    item_added = SimpleNamespace(
        type="response.output_item.added",
        item=SimpleNamespace(
            type="function_call", id="fc_9", call_id="call_9", name="echo", arguments=""
        ),
    )
    args_delta = MagicMock(
        type="response.function_call_arguments.delta",
        call_id="call_9",
        delta='{"msg":"partial"}',
    )
    args_done = MagicMock(
        type="response.function_call_arguments.done",
        call_id="call_9",
        arguments='{"msg":"done"}',
    )
    item_done = SimpleNamespace(
        type="response.output_item.done",
        item=SimpleNamespace(
            type="function_call", id="fc_9", call_id="call_9", name="echo", arguments=""
        ),
    )
    reasoning_summary = SimpleNamespace(type="summary_text", text="Reasoning summary")
    reasoning_item = SimpleNamespace(type="reasoning", summary=[reasoning_summary])
    usage_obj = SimpleNamespace(input_tokens=10, output_tokens=4, total_tokens=14)
    completed_response = SimpleNamespace(
        status="incomplete", usage=usage_obj, output=[reasoning_item]
    )
    completed = SimpleNamespace(type="response.completed", response=completed_response)

    async def mock_stream():
        for event in [item_added, args_delta, args_done, item_done, completed]:
            yield event

    responses_create = AsyncMock(return_value=mock_stream())
    with patch.object(provider._client.responses, "create", responses_create):
        result = await provider.chat_stream([{"role": "user", "content": "Hi"}])

    assert result.finish_reason == "length"
    assert result.usage == {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14}
    assert result.reasoning_content == "Reasoning summary"
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].id == "call_9|fc_9"
    assert result.tool_calls[0].name == "echo"
    assert result.tool_calls[0].arguments == {"msg": "done"}


@pytest.mark.asyncio
async def test_chat_stream_failed_event_returns_error_response() -> None:
    provider = CustomResponsesProvider(api_key="k", api_base="https://api.example.com/v1")

    failed_event = MagicMock(type="response.failed", error={"message": "upstream failed"})

    async def mock_stream():
        yield failed_event

    responses_create = AsyncMock(return_value=mock_stream())
    with patch.object(provider._client.responses, "create", responses_create):
        result = await provider.chat_stream([{"role": "user", "content": "Hi"}])

    assert result.finish_reason == "error"
    assert "Response failed" in (result.content or "")


@pytest.mark.asyncio
async def test_chat_stream_incomplete_without_content_or_tools_maps_to_error() -> None:
    provider = CustomResponsesProvider(api_key="k", api_base="https://api.example.com/v1")

    completed_response = SimpleNamespace(status="incomplete", usage=None, output=[])
    completed = SimpleNamespace(type="response.completed", response=completed_response)

    async def mock_stream():
        yield completed

    responses_create = AsyncMock(return_value=mock_stream())
    with patch.object(provider._client.responses, "create", responses_create):
        result = await provider.chat_stream([{"role": "user", "content": "Hi"}])

    assert result.finish_reason == "error"
    assert "incomplete stream" in (result.content or "")


@pytest.mark.asyncio
async def test_chat_stream_empty_completed_turn_maps_to_explicit_empty() -> None:
    provider = CustomResponsesProvider(api_key="k", api_base="https://api.example.com/v1")

    usage_obj = SimpleNamespace(input_tokens=2, output_tokens=0, total_tokens=2)
    completed_response = SimpleNamespace(status="completed", usage=usage_obj, output=[])
    completed = SimpleNamespace(type="response.completed", response=completed_response)

    async def mock_stream():
        yield completed

    responses_create = AsyncMock(return_value=mock_stream())
    with patch.object(provider._client.responses, "create", responses_create):
        result = await provider.chat_stream([{"role": "user", "content": "Hi"}])

    assert result.finish_reason == "empty"
    assert result.content is None
    assert result.usage == {"prompt_tokens": 2, "completion_tokens": 0, "total_tokens": 2}


@pytest.mark.asyncio
async def test_chat_stream_without_completion_metadata_maps_to_error() -> None:
    provider = CustomResponsesProvider(api_key="k", api_base="https://api.example.com/v1")

    async def mock_stream():
        if False:
            yield None

    responses_create = AsyncMock(return_value=mock_stream())
    with patch.object(provider._client.responses, "create", responses_create):
        result = await provider.chat_stream([{"role": "user", "content": "Hi"}])

    assert result.finish_reason == "error"
    assert "without completion metadata" in (result.content or "")


@pytest.mark.asyncio
async def test_chat_failure_returns_error_response() -> None:
    provider = CustomResponsesProvider(api_key="k", api_base="https://api.example.com/v1")

    responses_create = AsyncMock(side_effect=Exception("Connection failed"))
    chat_create = AsyncMock()
    with (
        patch.object(provider._client.responses, "create", responses_create),
        patch.object(provider._client.chat.completions, "create", chat_create),
    ):
        result = await provider.chat([{"role": "user", "content": "Hi"}])

    assert isinstance(result, LLMResponse)
    assert result.finish_reason == "error"
    assert "Connection failed" in (result.content or "")
    responses_create.assert_awaited_once()
    chat_create.assert_not_awaited()
