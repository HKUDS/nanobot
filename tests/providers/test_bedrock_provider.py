"""Tests for the native AWS Bedrock Converse provider."""

from __future__ import annotations

from typing import Any

import pytest

from nanobot.config.schema import Config, ProvidersConfig
from nanobot.providers.bedrock_provider import BedrockProvider
from nanobot.providers.registry import find_by_name


class FakeClient:
    def __init__(
        self,
        *,
        response: dict[str, Any] | None = None,
        stream_events: list[dict[str, Any]] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.response = response
        self.stream_events = stream_events or []
        self.error = error
        self.calls: list[dict[str, Any]] = []
        self.stream_calls: list[dict[str, Any]] = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response or {}

    def converse_stream(self, **kwargs):
        self.stream_calls.append(kwargs)
        if self.error:
            raise self.error
        return {"stream": iter(self.stream_events)}


class FakeBedrockError(Exception):
    def __init__(self) -> None:
        super().__init__("too many requests")
        self.response = {
            "ResponseMetadata": {
                "HTTPStatusCode": 429,
                "HTTPHeaders": {"retry-after": "3"},
            },
            "Error": {
                "Code": "ThrottlingException",
                "Message": "Rate exceeded",
            },
        }


def test_bedrock_provider_is_registered_and_matches_without_api_key() -> None:
    spec = find_by_name("bedrock")
    assert spec is not None
    assert spec.backend == "bedrock"
    assert spec.is_direct is True
    assert hasattr(ProvidersConfig(), "bedrock")

    cfg = Config.model_validate({
        "agents": {"defaults": {"model": "bedrock/global.anthropic.claude-opus-4-7"}},
        "providers": {"bedrock": {"region": "us-east-1"}},
    })

    assert cfg.get_provider_name() == "bedrock"
    assert cfg.get_provider().region == "us-east-1"


def test_opus_47_uses_adaptive_thinking_and_omits_temperature() -> None:
    provider = BedrockProvider(region="us-east-1", client=FakeClient())

    kwargs = provider._build_kwargs(
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        model="bedrock/global.anthropic.claude-opus-4-7",
        max_tokens=2048,
        temperature=0.1,
        reasoning_effort="medium",
        tool_choice=None,
    )

    assert kwargs["modelId"] == "global.anthropic.claude-opus-4-7"
    assert kwargs["inferenceConfig"] == {"maxTokens": 2048}
    assert kwargs["additionalModelRequestFields"]["thinking"] == {
        "type": "adaptive",
        "effort": "medium",
    }


def test_generic_bedrock_model_keeps_temperature_and_skips_anthropic_thinking() -> None:
    provider = BedrockProvider(region="us-east-1", client=FakeClient())

    kwargs = provider._build_kwargs(
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        model="bedrock/amazon.nova-lite-v1:0",
        max_tokens=1024,
        temperature=0.3,
        reasoning_effort="medium",
        tool_choice=None,
    )

    assert kwargs["modelId"] == "amazon.nova-lite-v1:0"
    assert kwargs["inferenceConfig"] == {"maxTokens": 1024, "temperature": 0.3}
    assert "additionalModelRequestFields" not in kwargs
    assert "toolConfig" not in kwargs


def test_build_kwargs_converts_messages_tools_and_tool_results() -> None:
    provider = BedrockProvider(region="us-east-1", client=FakeClient())
    tools = [{
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
        },
    }]
    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "read x"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "toolu_1",
                "type": "function",
                "function": {"name": "read_file", "arguments": '{"path": "x"}'},
            }],
        },
        {"role": "tool", "tool_call_id": "toolu_1", "name": "read_file", "content": "ok"},
        {"role": "user", "content": "continue"},
    ]

    kwargs = provider._build_kwargs(
        messages=messages,
        tools=tools,
        model="bedrock/anthropic.claude-opus-4-7",
        max_tokens=1024,
        temperature=0.7,
        reasoning_effort=None,
        tool_choice="required",
    )

    assert kwargs["system"] == [{"text": "You are helpful."}]
    assert kwargs["messages"][1]["content"] == [{
        "toolUse": {
            "toolUseId": "toolu_1",
            "name": "read_file",
            "input": {"path": "x"},
        }
    }]
    assert kwargs["messages"][2]["role"] == "user"
    assert kwargs["messages"][2]["content"][0]["toolResult"]["toolUseId"] == "toolu_1"
    assert kwargs["messages"][2]["content"][1] == {"text": "continue"}
    tool_spec = kwargs["toolConfig"]["tools"][0]["toolSpec"]
    assert tool_spec["name"] == "read_file"
    assert kwargs["toolConfig"]["toolChoice"] == {"any": {}}


def test_build_kwargs_keeps_tool_config_for_historical_tool_blocks_without_tools() -> None:
    provider = BedrockProvider(region="us-east-1", client=FakeClient())
    messages = [
        {"role": "user", "content": "read x"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "toolu_1",
                "type": "function",
                "function": {"name": "read_file", "arguments": '{"path": "x"}'},
            }],
        },
        {"role": "tool", "tool_call_id": "toolu_1", "name": "read_file", "content": "ok"},
        {"role": "user", "content": "continue"},
    ]

    kwargs = provider._build_kwargs(
        messages=messages,
        tools=[],
        model="bedrock/anthropic.claude-opus-4-7",
        max_tokens=1024,
        temperature=0.7,
        reasoning_effort=None,
        tool_choice=None,
    )

    assert any("toolUse" in block for msg in kwargs["messages"] for block in msg["content"])
    assert any("toolResult" in block for msg in kwargs["messages"] for block in msg["content"])
    assert kwargs["toolConfig"]["tools"][0]["toolSpec"]["name"] == "nanobot_noop"
    assert "toolChoice" not in kwargs["toolConfig"]


def test_parse_response_maps_text_tools_reasoning_usage_and_stop_reason() -> None:
    response = {
        "output": {
            "message": {
                "role": "assistant",
                "content": [
                    {"reasoningContent": {"reasoningText": {"text": "think", "signature": "sig"}}},
                    {"text": "hello"},
                    {"toolUse": {"toolUseId": "t1", "name": "search", "input": {"q": "x"}}},
                ],
            }
        },
        "stopReason": "tool_use",
        "usage": {
            "inputTokens": 10,
            "outputTokens": 5,
            "totalTokens": 15,
            "cacheReadInputTokens": 2,
        },
    }

    result = BedrockProvider._parse_response(response)

    assert result.content == "hello"
    assert result.finish_reason == "tool_calls"
    assert result.usage["prompt_tokens"] == 10
    assert result.usage["cached_tokens"] == 2
    assert result.reasoning_content == "think"
    assert result.thinking_blocks == [{"type": "thinking", "thinking": "think", "signature": "sig"}]
    assert result.tool_calls[0].id == "t1"
    assert result.tool_calls[0].arguments == {"q": "x"}


@pytest.mark.asyncio
async def test_chat_stream_aggregates_text_tool_use_and_usage() -> None:
    client = FakeClient(stream_events=[
        {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": "he"}}},
        {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": "llo"}}},
        {
            "contentBlockStart": {
                "contentBlockIndex": 1,
                "start": {"toolUse": {"toolUseId": "t1", "name": "search"}},
            }
        },
        {
            "contentBlockDelta": {
                "contentBlockIndex": 1,
                "delta": {"toolUse": {"input": '{"q":'}},
            }
        },
        {
            "contentBlockDelta": {
                "contentBlockIndex": 1,
                "delta": {"toolUse": {"input": '"x"}'}},
            }
        },
        {"contentBlockStop": {"contentBlockIndex": 1}},
        {"messageStop": {"stopReason": "tool_use"}},
        {"metadata": {"usage": {"inputTokens": 3, "outputTokens": 4, "totalTokens": 7}}},
    ])
    provider = BedrockProvider(region="us-east-1", client=client)
    deltas: list[str] = []

    result = await provider.chat_stream(
        messages=[{"role": "user", "content": "hi"}],
        model="bedrock/anthropic.claude-opus-4-7",
        on_content_delta=lambda text: _append_delta(deltas, text),
    )

    assert deltas == ["he", "llo"]
    assert result.content == "hello"
    assert result.finish_reason == "tool_calls"
    assert result.usage == {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7}
    assert result.tool_calls[0].name == "search"
    assert result.tool_calls[0].arguments == {"q": "x"}


async def _append_delta(deltas: list[str], text: str) -> None:
    deltas.append(text)


@pytest.mark.asyncio
async def test_chat_error_maps_retry_metadata() -> None:
    provider = BedrockProvider(region="us-east-1", client=FakeClient(error=FakeBedrockError()))

    result = await provider.chat(messages=[{"role": "user", "content": "hi"}])

    assert result.finish_reason == "error"
    assert result.error_status_code == 429
    assert result.error_should_retry is True
    assert result.error_code == "throttlingexception"
    assert result.retry_after == 3
