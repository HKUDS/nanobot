import json

import pytest

from nanobot.utils import helpers, token_encoding
from nanobot.utils.helpers import (
    estimate_message_tokens,
    estimate_prompt_tokens,
    estimate_prompt_tokens_chain,
    truncate_text_to_tokens,
)


class _NoCounterProvider:
    pass


class _BrokenCounterProvider:
    def estimate_prompt_tokens(self, messages, tools=None, model=None):
        raise RuntimeError("counter unavailable")


@pytest.fixture(autouse=True)
def isolate_token_caches(monkeypatch, byte_encoding):
    monkeypatch.setattr(token_encoding, "_encoding", byte_encoding)
    helpers._TOOLS_TOKEN_CACHE.clear()
    yield
    helpers._TOOLS_TOKEN_CACHE.clear()


@pytest.mark.parametrize("text", ["hello world", "你好，世界🙂", "print(123)\n", "<|endoftext|>"])
def test_token_estimation_treats_prompt_text_as_ordinary(text, byte_encoding):
    expected = len(byte_encoding.encode_ordinary(text)) + 4
    assert estimate_prompt_tokens_chain(
        _NoCounterProvider(), "custom-model", [{"role": "user", "content": text}],
    ) == (expected, "tiktoken")
    assert estimate_message_tokens({"role": "user", "content": text}) == expected
    assert len(byte_encoding.encode_ordinary(truncate_text_to_tokens(text * 100, 40))) <= 40


def test_provider_counter_does_not_initialize_fallback(monkeypatch):
    def forbidden():
        raise AssertionError("provider counter must take precedence")

    class Provider:
        def estimate_prompt_tokens(self, messages, tools=None, model=None):
            assert model == "provider-specific-model"
            return 1234, "provider-local"

    monkeypatch.setattr(helpers, "_get_token_encoding", forbidden)
    assert estimate_prompt_tokens_chain(
        Provider(), "provider-specific-model", [{"role": "user", "content": "hi"}],
    ) == (1234, "provider-local")


def test_estimate_prompt_tokens_chain_falls_back_without_provider_counter() -> None:
    tokens, source = estimate_prompt_tokens_chain(
        _NoCounterProvider(),
        "test-model",
        [{"role": "user", "content": "hello"}],
    )

    assert tokens > 0
    assert source == "tiktoken"


def test_estimate_prompt_tokens_chain_falls_back_when_provider_counter_fails() -> None:
    tokens, source = estimate_prompt_tokens_chain(
        _BrokenCounterProvider(),
        "test-model",
        [{"role": "user", "content": "hello"}],
    )

    assert tokens > 0
    assert source == "tiktoken"


def test_estimate_prompt_tokens_uses_conservative_fallback_when_tiktoken_fails(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        helpers,
        "_get_token_encoding",
        lambda: (_ for _ in ()).throw(RuntimeError("encoding unavailable")),
    )

    content = "你" * 1_000
    messages = [{"role": "user", "content": content}]
    tokens = estimate_prompt_tokens(messages)
    chain_tokens, source = estimate_prompt_tokens_chain(
        _NoCounterProvider(),
        "test-model",
        messages,
    )

    encoding = token_encoding.get_token_encoding()
    assert encoding is not None
    actual_tokens = len(encoding.encode(content)) + 4
    assert tokens == len(content.encode("utf-8")) + 4
    assert tokens >= actual_tokens
    assert chain_tokens == tokens
    assert source == "heuristic"


def test_estimate_message_tokens_uses_utf8_byte_fallback(monkeypatch) -> None:
    monkeypatch.setattr(
        helpers,
        "_get_token_encoding",
        lambda: (_ for _ in ()).throw(RuntimeError("encoding unavailable")),
    )
    content = "🙂你" * 100

    assert estimate_message_tokens({"role": "user", "content": content}) == (
        len(content.encode("utf-8")) + 4
    )


def test_truncate_text_to_tokens_uses_utf8_byte_budget_fallback(monkeypatch) -> None:
    monkeypatch.setattr(
        helpers,
        "_get_token_encoding",
        lambda: (_ for _ in ()).throw(RuntimeError("encoding unavailable")),
    )

    result = truncate_text_to_tokens("🙂你" * 100, 40)

    assert result.endswith("\n... (truncated)")
    assert len(result.encode("utf-8")) <= 40


def test_estimate_prompt_tokens_caches_tools_encoding(monkeypatch) -> None:
    class FakeEncoding:
        def __init__(self) -> None:
            self.encoded: list[str] = []

        def encode_ordinary(self, text: str) -> list[int]:
            self.encoded.append(text)
            return list(range(max(1, len(text) // 4)))

    fake_encoding = FakeEncoding()
    monkeypatch.setattr(token_encoding, "_encoding", fake_encoding)
    tools = [{"type": "function", "function": {"name": "demo", "description": "cached"}}]
    messages = [{"role": "user", "content": "hello"}]

    first = estimate_prompt_tokens(messages, tools)
    second = estimate_prompt_tokens(messages, tools)

    assert first == second
    rendered_tools = "\n" + json.dumps(tools, ensure_ascii=False)
    assert fake_encoding.encoded.count(rendered_tools) == 1


def test_estimate_prompt_tokens_recomputes_when_tool_items_change(monkeypatch) -> None:
    class FakeEncoding:
        def __init__(self) -> None:
            self.encoded: list[str] = []

        def encode_ordinary(self, text: str) -> list[int]:
            self.encoded.append(text)
            return list(range(max(1, len(text) // 4)))

    fake_encoding = FakeEncoding()
    monkeypatch.setattr(token_encoding, "_encoding", fake_encoding)

    tools = [{"type": "function", "function": {"name": "before"}}]
    messages = [{"role": "user", "content": "hello"}]
    estimate_prompt_tokens(messages, tools)

    tools[0] = {"type": "function", "function": {"name": "after"}}
    estimate_prompt_tokens(messages, tools)

    before_tools = "\n" + json.dumps(
        [{"type": "function", "function": {"name": "before"}}], ensure_ascii=False
    )
    after_tools = "\n" + json.dumps(tools, ensure_ascii=False)
    assert before_tools in fake_encoding.encoded
    assert after_tools in fake_encoding.encoded
