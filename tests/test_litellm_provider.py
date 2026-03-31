from __future__ import annotations

from types import SimpleNamespace

import pytest

from nanobot.providers.litellm_provider import LiteLLMProvider


def test_canonicalize_explicit_prefix() -> None:
    assert (
        LiteLLMProvider._canonicalize_explicit_prefix(
            "github-copilot/gpt-4.1", "github_copilot", "github_copilot"
        )
        == "github_copilot/gpt-4.1"
    )
    assert (
        LiteLLMProvider._canonicalize_explicit_prefix("plain-model", "openai", "openai")
        == "plain-model"
    )


def test_sanitize_messages_and_cache_control_helpers() -> None:
    provider = LiteLLMProvider(api_key=None)
    msgs = [
        {"role": "assistant", "tool_calls": [{"x": 1}], "extra": True},
        {"role": "system", "content": "sys"},
    ]
    sanitized = provider._sanitize_messages(msgs)
    assert sanitized[0]["role"] == "assistant"
    assert "extra" not in sanitized[0]
    assert "content" in sanitized[0]

    cc_msgs, cc_tools = provider._apply_cache_control(
        [{"role": "system", "content": "x"}],
        [{"type": "function", "function": {"name": "f", "parameters": {"type": "object"}}}],
    )
    assert isinstance(cc_msgs[0]["content"], list)
    assert cc_tools is not None
    assert "cache_control" in cc_tools[-1]


def _count_cache_blocks(messages: list[dict], tools: list[dict] | None) -> int:
    """Count total cache_control markers across messages and tools."""
    count = 0
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and "cache_control" in block:
                    count += 1
    if tools:
        for t in tools:
            if "cache_control" in t:
                count += 1
    return count


def _make_system_msg(text: str) -> dict:
    return {"role": "system", "content": text}


def _make_tool() -> dict:
    return {"type": "function", "function": {"name": "f", "parameters": {"type": "object"}}}


def test_cache_control_caps_at_four_blocks() -> None:
    """6 system messages + tools must produce at most 4 cache_control blocks."""
    provider = LiteLLMProvider(api_key=None)
    msgs = [_make_system_msg(f"sys{i}") for i in range(6)]
    msgs.insert(2, {"role": "user", "content": "hi"})  # non-system interspersed
    tools = [_make_tool(), _make_tool()]

    cc_msgs, cc_tools = provider._apply_cache_control(msgs, tools)
    total = _count_cache_blocks(cc_msgs, cc_tools)
    assert total <= 4, f"Expected <= 4 cache_control blocks, got {total}"


def test_cache_control_first_and_last_system_messages() -> None:
    """First system message and last N should be cached; intermediates skipped."""
    provider = LiteLLMProvider(api_key=None)
    msgs = [_make_system_msg(f"sys{i}") for i in range(5)]
    tools = [_make_tool()]

    cc_msgs, cc_tools = provider._apply_cache_control(msgs, tools)

    # First system message should be cached
    assert isinstance(cc_msgs[0]["content"], list)
    assert "cache_control" in cc_msgs[0]["content"][0]

    # Last system message should be cached
    assert isinstance(cc_msgs[4]["content"], list)
    assert "cache_control" in cc_msgs[4]["content"][0]

    # Middle messages (indices 1-2) should NOT be cached (budget: 4 - 1 tool = 3 msgs)
    # With 5 system msgs and budget 3: first + last 2 = indices 0, 3, 4
    assert isinstance(cc_msgs[1]["content"], str), "Intermediate msg should not be cached"
    assert isinstance(cc_msgs[2]["content"], str), "Intermediate msg should not be cached"


def test_cache_control_single_system_message() -> None:
    """Common case: 1 system message + tools = 2 blocks."""
    provider = LiteLLMProvider(api_key=None)
    msgs = [_make_system_msg("prompt")]
    tools = [_make_tool()]

    cc_msgs, cc_tools = provider._apply_cache_control(msgs, tools)
    assert _count_cache_blocks(cc_msgs, cc_tools) == 2
    assert isinstance(cc_msgs[0]["content"], list)
    assert cc_tools is not None
    assert "cache_control" in cc_tools[-1]


def test_cache_control_no_system_messages() -> None:
    """No system messages: only tools get cache_control."""
    provider = LiteLLMProvider(api_key=None)
    msgs = [{"role": "user", "content": "hi"}]
    tools = [_make_tool()]

    cc_msgs, cc_tools = provider._apply_cache_control(msgs, tools)
    assert _count_cache_blocks(cc_msgs, cc_tools) == 1  # tool only
    assert isinstance(cc_msgs[0]["content"], str)  # user msg untouched


def test_cache_control_with_list_content() -> None:
    """System message with list content gets cache_control on last block."""
    provider = LiteLLMProvider(api_key=None)
    msgs = [
        {
            "role": "system",
            "content": [
                {"type": "text", "text": "part1"},
                {"type": "text", "text": "part2"},
            ],
        }
    ]
    cc_msgs, _ = provider._apply_cache_control(msgs, None)
    blocks = cc_msgs[0]["content"]
    assert "cache_control" not in blocks[0]  # first block unchanged
    assert "cache_control" in blocks[1]  # last block gets marker


def test_cache_control_no_tools() -> None:
    """No tools: full budget of 4 goes to system messages."""
    provider = LiteLLMProvider(api_key=None)
    msgs = [_make_system_msg(f"sys{i}") for i in range(3)]

    cc_msgs, cc_tools = provider._apply_cache_control(msgs, None)
    # All 3 should be cached (budget 4, no tools)
    for i in range(3):
        assert isinstance(cc_msgs[i]["content"], list), f"sys{i} should be cached"
    assert cc_tools is None


def test_resolve_model_with_and_without_gateway(monkeypatch) -> None:
    provider = LiteLLMProvider(api_key=None)

    class _Spec:
        litellm_prefix = "openai"
        name = "openai"
        skip_prefixes = ("openai/",)

    monkeypatch.setattr("nanobot.providers.litellm_provider.find_by_model", lambda model: _Spec())
    assert provider._resolve_model("gpt-4.1") == "openai/gpt-4.1"

    provider._gateway = SimpleNamespace(
        litellm_prefix="openai",
        strip_model_prefix=True,
        supports_prompt_caching=False,
    )
    assert provider._resolve_model("anthropic/claude") == "openai/claude"


def test_parse_response_with_tool_calls_and_usage() -> None:
    provider = LiteLLMProvider(api_key=None)

    tc = SimpleNamespace(
        id="toolcallid-12345",
        function=SimpleNamespace(name="read_file", arguments='{"path":"a"}'),
    )
    message = SimpleNamespace(content="hello", tool_calls=[tc], reasoning_content="think")
    choice = SimpleNamespace(message=message, finish_reason="stop")
    usage = SimpleNamespace(prompt_tokens=1, completion_tokens=2, total_tokens=3)
    resp = SimpleNamespace(choices=[choice], usage=usage)

    parsed = provider._parse_response(resp)
    assert parsed.content == "hello"
    assert parsed.reasoning_content == "think"
    assert parsed.usage["total_tokens"] == 3
    assert parsed.tool_calls and parsed.tool_calls[0].name == "read_file"


def test_supports_cache_control_with_gateway_and_spec(monkeypatch) -> None:
    provider = LiteLLMProvider(api_key=None)
    provider._gateway = SimpleNamespace(supports_prompt_caching=True)
    assert provider._supports_cache_control("any") is True

    provider._gateway = None
    monkeypatch.setattr("nanobot.providers.litellm_provider.find_by_model", lambda model: None)
    assert provider._supports_cache_control("none") is False


def test_apply_model_overrides_match_and_miss(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = LiteLLMProvider(api_key=None)

    class _Spec:
        model_overrides = (("gpt-5", {"temperature": 1.0}),)

    monkeypatch.setattr("nanobot.providers.litellm_provider.find_by_model", lambda model: _Spec())
    kwargs: dict[str, object] = {}
    provider._apply_model_overrides("openai/gpt-5-mini", kwargs)
    assert kwargs["temperature"] == 1.0

    kwargs2: dict[str, object] = {}
    provider._apply_model_overrides("openai/gpt-4.1", kwargs2)
    assert kwargs2 == {}


def test_setup_env_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = LiteLLMProvider(api_key=None)

    class _Spec:
        env_key = "TEST_API_KEY"
        default_api_base = "https://example.invalid"
        env_extras = (("EXTRA_ONE", "{api_key}"), ("EXTRA_TWO", "{api_base}"))

    monkeypatch.delenv("TEST_API_KEY", raising=False)
    monkeypatch.delenv("EXTRA_ONE", raising=False)
    monkeypatch.delenv("EXTRA_TWO", raising=False)
    monkeypatch.setattr("nanobot.providers.litellm_provider.find_by_model", lambda model: _Spec())
    provider._gateway = None

    provider._setup_env("abc", None, "gpt-4.1")
    assert "TEST_API_KEY" in __import__("os").environ
    assert __import__("os").environ["EXTRA_ONE"] == "abc"

    class _NoKeySpec:
        env_key = ""
        default_api_base = ""
        env_extras = ()

    monkeypatch.setattr(
        "nanobot.providers.litellm_provider.find_by_model", lambda model: _NoKeySpec()
    )
    provider._setup_env("abc", None, "gpt-4.1")


async def test_chat_success_and_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = LiteLLMProvider(
        api_key="k", api_base="https://api.example", default_model="openai/gpt-4.1"
    )

    tc = SimpleNamespace(id="id-1", function=SimpleNamespace(name="tool", arguments='{"x":1}'))
    msg = SimpleNamespace(content="hello", tool_calls=[tc], reasoning_content=None)
    choice = SimpleNamespace(message=msg, finish_reason="stop")
    usage = SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2)
    fake_response = SimpleNamespace(choices=[choice], usage=usage)

    async def _ok_completion(**kwargs):
        return fake_response

    monkeypatch.setattr("nanobot.providers.litellm_provider.acompletion", _ok_completion)
    out = await provider.chat(
        messages=[{"role": "user", "content": "hi"}], tools=None, max_tokens=0
    )
    assert out.content == "hello"
    assert out.tool_calls and out.tool_calls[0].name == "tool"

    async def _boom_completion(**kwargs):
        raise RuntimeError("network")

    monkeypatch.setattr("nanobot.providers.litellm_provider.acompletion", _boom_completion)
    err = await provider.chat(messages=[{"role": "user", "content": "hi"}])
    assert err.finish_reason == "error"
    assert "Error calling LLM" in (err.content or "")


async def test_stream_chat_success_and_error(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = LiteLLMProvider(api_key=None)

    class _Stream:
        def __init__(self, chunks):
            self._chunks = chunks

        def __aiter__(self):
            self._i = 0
            return self

        async def __anext__(self):
            if self._i >= len(self._chunks):
                raise StopAsyncIteration
            item = self._chunks[self._i]
            self._i += 1
            return item

    delta1 = SimpleNamespace(content="hel", reasoning_content=None, tool_calls=None)
    choice1 = SimpleNamespace(delta=delta1, finish_reason=None)
    chunk1 = SimpleNamespace(choices=[choice1], usage=None)

    tc_delta = SimpleNamespace(
        index=0, id="abc", function=SimpleNamespace(name="read", arguments='{"a":')
    )
    delta2 = SimpleNamespace(content="lo", reasoning_content=None, tool_calls=[tc_delta])
    choice2 = SimpleNamespace(delta=delta2, finish_reason=None)
    chunk2 = SimpleNamespace(choices=[choice2], usage=None)

    tc_delta_final = SimpleNamespace(
        index=0, id="", function=SimpleNamespace(name="", arguments="1}")
    )
    delta3 = SimpleNamespace(content=None, reasoning_content=None, tool_calls=[tc_delta_final])
    usage3 = SimpleNamespace(prompt_tokens=1, completion_tokens=2, total_tokens=3)
    choice3 = SimpleNamespace(delta=delta3, finish_reason="stop")
    chunk3 = SimpleNamespace(choices=[choice3], usage=usage3)

    async def _stream_completion(**kwargs):
        return _Stream([chunk1, chunk2, chunk3])

    monkeypatch.setattr("nanobot.providers.litellm_provider.acompletion", _stream_completion)
    chunks = [
        c
        async for c in provider.stream_chat(messages=[{"role": "user", "content": "x"}], tools=None)
    ]
    assert chunks[-1].done is True
    assert chunks[-1].tool_calls and chunks[-1].tool_calls[0].name == "read"

    async def _stream_boom(**kwargs):
        raise RuntimeError("stream down")

    monkeypatch.setattr("nanobot.providers.litellm_provider.acompletion", _stream_boom)
    err_chunks = [
        c
        async for c in provider.stream_chat(messages=[{"role": "user", "content": "x"}], tools=None)
    ]
    assert err_chunks[-1].done is True
    assert "Error calling LLM" in (err_chunks[-1].content_delta or "")


async def test_aclose_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = LiteLLMProvider(api_key=None)
    await provider.aclose()

    async def _close_ok():
        return None

    monkeypatch.setattr("litellm.close_litellm_async_clients", _close_ok)
    await provider.aclose()

    async def _close_fail():
        raise RuntimeError("x")

    monkeypatch.setattr("litellm.close_litellm_async_clients", _close_fail)
    await provider.aclose()


def test_sanitize_repairs_orphaned_tool_calls() -> None:
    """Tool_calls without matching tool results should be stripped to avoid LLM 400 errors."""
    provider = LiteLLMProvider(api_key=None)
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hello"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "tc_1", "type": "function", "function": {"name": "read_file"}},
                {"id": "tc_2", "type": "function", "function": {"name": "exec"}},
            ],
        },
        # Only tc_1 has a result; tc_2 is orphaned (e.g. crash mid-execution)
        {"role": "tool", "tool_call_id": "tc_1", "content": "file contents"},
    ]
    repaired = provider._sanitize_messages(msgs)
    # Assistant should only have tc_1
    assistant = [m for m in repaired if m.get("role") == "assistant"][0]
    assert len(assistant["tool_calls"]) == 1
    assert assistant["tool_calls"][0]["id"] == "tc_1"


def test_sanitize_drops_all_tool_calls_when_none_have_results() -> None:
    """When all tool_calls are orphaned, drop the tool_calls key entirely."""
    provider = LiteLLMProvider(api_key=None)
    msgs = [
        {"role": "user", "content": "hello"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "tc_orphan", "type": "function", "function": {"name": "x"}},
            ],
        },
        {"role": "user", "content": "retry"},
    ]
    repaired = provider._sanitize_messages(msgs)
    assistant = [m for m in repaired if m.get("role") == "assistant"][0]
    assert "tool_calls" not in assistant


def test_sanitize_keeps_valid_tool_calls_untouched() -> None:
    """When all tool_calls have results, messages should pass through unchanged."""
    provider = LiteLLMProvider(api_key=None)
    msgs = [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "tc_ok", "type": "function", "function": {"name": "f"}},
            ],
        },
        {"role": "tool", "tool_call_id": "tc_ok", "content": "result"},
        {"role": "assistant", "content": "done"},
    ]
    repaired = provider._sanitize_messages(msgs)
    assistant = [m for m in repaired if m.get("tool_calls")][0]
    assert len(assistant["tool_calls"]) == 1
    assert assistant["tool_calls"][0]["id"] == "tc_ok"
