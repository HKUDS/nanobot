import json

from nanobot.utils import helpers
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

    actual_tokens = len(helpers.tiktoken.get_encoding("cl100k_base").encode(content)) + 4
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
    helpers._get_token_encoding.cache_clear()
    helpers._TOOLS_TOKEN_CACHE.clear()

    class FakeEncoding:
        def __init__(self) -> None:
            self.encoded: list[str] = []

        def encode(self, text: str) -> list[int]:
            self.encoded.append(text)
            return list(range(max(1, len(text) // 4)))

    fake_encoding = FakeEncoding()
    get_encoding_calls = 0

    def fake_get_encoding(name: str) -> FakeEncoding:
        nonlocal get_encoding_calls
        assert name == "cl100k_base"
        get_encoding_calls += 1
        return fake_encoding

    monkeypatch.setattr(helpers.tiktoken, "get_encoding", fake_get_encoding)
    tools = [{"type": "function", "function": {"name": "demo", "description": "cached"}}]
    messages = [{"role": "user", "content": "hello"}]

    first = estimate_prompt_tokens(messages, tools)
    second = estimate_prompt_tokens(messages, tools)

    assert first == second
    assert get_encoding_calls == 1
    rendered_tools = "\n" + json.dumps(tools, ensure_ascii=False)
    assert fake_encoding.encoded.count(rendered_tools) == 1


def test_estimate_prompt_tokens_recomputes_when_tool_items_change(monkeypatch) -> None:
    helpers._get_token_encoding.cache_clear()
    helpers._TOOLS_TOKEN_CACHE.clear()

    class FakeEncoding:
        def __init__(self) -> None:
            self.encoded: list[str] = []

        def encode(self, text: str) -> list[int]:
            self.encoded.append(text)
            return list(range(max(1, len(text) // 4)))

    fake_encoding = FakeEncoding()
    monkeypatch.setattr(helpers.tiktoken, "get_encoding", lambda _name: fake_encoding)

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
