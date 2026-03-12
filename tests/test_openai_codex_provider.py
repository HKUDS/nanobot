from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from nanobot.providers.base import ToolCallRequest
from nanobot.providers.openai_codex_provider import (
    OpenAICodexProvider,
    _consume_sse,
    _convert_messages,
    _convert_tools,
    _convert_user_message,
    _friendly_error,
    _iter_sse,
    _map_finish_reason,
    _prompt_cache_key,
    _split_tool_call_id,
    _strip_model_prefix,
)


class _FakeResponse:
    def __init__(self, lines: list[str]):
        self._lines = lines

    async def aiter_lines(self):
        for line in self._lines:
            yield line


def test_strip_prefix_and_ids_and_finish_reason() -> None:
    assert _strip_model_prefix("openai-codex/gpt-5.1") == "gpt-5.1"
    assert _strip_model_prefix("openai_codex/gpt-5.1") == "gpt-5.1"
    assert _strip_model_prefix("gpt-5.1") == "gpt-5.1"

    assert _split_tool_call_id("call|id") == ("call", "id")
    assert _split_tool_call_id("call") == ("call", None)
    assert _split_tool_call_id(None) == ("call_0", None)

    assert _map_finish_reason("completed") == "stop"
    assert _map_finish_reason("incomplete") == "length"
    assert _map_finish_reason("failed") == "error"
    assert _map_finish_reason("unknown") == "stop"


def test_convert_tools_and_messages() -> None:
    tools = [
        {"type": "function", "function": {"name": "read_file", "parameters": {"type": "object"}}},
        {"type": "function", "function": {"description": "missing name"}},
    ]
    out_tools = _convert_tools(tools)
    assert len(out_tools) == 1
    assert out_tools[0]["name"] == "read_file"

    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hello"},
        {
            "role": "assistant",
            "content": "done",
            "tool_calls": [{"id": "c1|i1", "function": {"name": "read_file", "arguments": "{}"}}],
        },
        {"role": "tool", "tool_call_id": "c1|i1", "content": {"ok": True}},
    ]
    sys_prompt, items = _convert_messages(messages)
    assert sys_prompt == "sys"
    assert any(item.get("type") == "function_call" for item in items)
    assert any(item.get("type") == "function_call_output" for item in items)


def test_convert_user_message_variants_and_prompt_key() -> None:
    assert _convert_user_message("hello")["content"][0]["type"] == "input_text"

    mixed = _convert_user_message(
        [
            {"type": "text", "text": "question"},
            {"type": "image_url", "image_url": {"url": "https://example.com/x.png"}},
        ]
    )
    assert len(mixed["content"]) == 2
    assert _convert_user_message(123)["content"][0]["text"] == ""

    key1 = _prompt_cache_key([{"role": "user", "content": "a"}])
    key2 = _prompt_cache_key([{"role": "user", "content": "a"}])
    assert key1 == key2


@pytest.mark.asyncio
async def test_iter_sse_and_consume_sse() -> None:
    def _line(payload: dict) -> str:
        return f"data: {json.dumps(payload)}"

    events = [
        _line(
            {
                "type": "response.output_item.added",
                "item": {
                    "type": "function_call",
                    "call_id": "c1",
                    "id": "i1",
                    "name": "read_file",
                    "arguments": "{",
                },
            }
        ),
        "",
        _line(
            {
                "type": "response.function_call_arguments.delta",
                "call_id": "c1",
                "delta": '"path":"a"',
            }
        ),
        "",
        _line(
            {
                "type": "response.function_call_arguments.done",
                "call_id": "c1",
                "arguments": '{"path":"a"}',
            }
        ),
        "",
        _line({"type": "response.output_text.delta", "delta": "hello"}),
        "",
        _line(
            {
                "type": "response.output_item.done",
                "item": {
                    "type": "function_call",
                    "call_id": "c1",
                    "id": "i1",
                    "name": "read_file",
                },
            }
        ),
        "",
        _line({"type": "response.completed", "response": {"status": "completed"}}),
        "",
    ]
    fake = _FakeResponse(events)

    parsed = [event async for event in _iter_sse(fake)]
    assert parsed

    content, tool_calls, finish = await _consume_sse(fake)
    assert content == "hello"
    assert finish == "stop"
    assert tool_calls and isinstance(tool_calls[0], ToolCallRequest)
    assert tool_calls[0].arguments["path"] == "a"


@pytest.mark.asyncio
async def test_chat_ssl_fallback_and_error(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = OpenAICodexProvider(default_model="openai-codex/gpt-5.1")

    token = SimpleNamespace(account_id="acct", access="tok")
    monkeypatch.setattr("nanobot.providers.openai_codex_provider._get_codex_token", lambda: token)

    calls = {"n": 0}

    async def _req(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("CERTIFICATE_VERIFY_FAILED")
        return ("ok", [], "stop")

    monkeypatch.setattr("nanobot.providers.openai_codex_provider._request_codex", _req)

    ok = await provider.chat(messages=[{"role": "user", "content": "hello"}], tools=None)
    assert ok.content == "ok"

    async def _req_fail(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("nanobot.providers.openai_codex_provider._request_codex", _req_fail)
    failed = await provider.chat(messages=[{"role": "user", "content": "hello"}], tools=None)
    assert failed.finish_reason == "error"
    assert "Error calling Codex" in (failed.content or "")


def test_friendly_error() -> None:
    assert "quota" in _friendly_error(429, "x").lower()
    assert _friendly_error(500, "oops").startswith("HTTP 500")
