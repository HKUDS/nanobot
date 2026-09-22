import json
import socket
from concurrent.futures import ThreadPoolExecutor

import pytest
from loguru import logger

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
def isolate_token_caches():
    token_encoding._load_encoding.cache_clear()
    helpers._TOOLS_TOKEN_CACHE.clear()
    yield
    token_encoding._load_encoding.cache_clear()
    helpers._TOOLS_TOKEN_CACHE.clear()


def test_token_estimation_is_offline_with_empty_external_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", str(tmp_path / "empty"))
    attempted = []

    def forbidden(*args, **kwargs):
        attempted.append(args)
        raise AssertionError("token estimation must not use the network or tokenizer registry")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(token_encoding.tiktoken, "get_encoding", forbidden)
    samples = [
        ("hello world", [15339, 1917]),
        ("你好，世界🙂", [57668, 53901, 3922, 3574, 244, 98220, 9468, 19044]),
        ("print(123)\n", [1374, 7, 4513, 340]),
        ("<|endoftext|>", [27, 91, 8862, 728, 428, 91, 29]),
    ]
    for text, expected in samples:
        encoding = helpers._get_token_encoding()
        assert encoding is not None
        assert encoding.encode(text) == expected
        tokens, source = estimate_prompt_tokens_chain(
            _NoCounterProvider(), "custom-model", [{"role": "user", "content": text}],
        )
        assert (tokens, source) == (len(expected) + 4, "tiktoken")
        assert estimate_message_tokens({"role": "user", "content": text}) == tokens
        assert len(encoding.encode(truncate_text_to_tokens(text * 100, 40))) <= 40
    assert attempted == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("corrupt", [False, True], ids=["missing", "corrupt"])
def test_unavailable_vocabulary_falls_back_once_across_threads(tmp_path, monkeypatch, corrupt):
    if corrupt:
        (tmp_path / "cl100k_base.tiktoken.gz").write_bytes(b"broken gzip")
    loads = []

    def resources(package):
        loads.append(package)
        return tmp_path

    monkeypatch.setattr(token_encoding, "files", resources)
    warnings = []
    sink = logger.add(lambda message: warnings.append(str(message)), level="WARNING")
    content = "🙂你" * 100
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(
                lambda _: estimate_message_tokens({"role": "user", "content": content}),
                range(37),
            ))
        tokens, source = estimate_prompt_tokens_chain(
            _NoCounterProvider(), "test-model", [{"role": "user", "content": content}],
        )
        truncated = truncate_text_to_tokens(content, 40)
    finally:
        logger.remove(sink)
    assert results == [len(content.encode("utf-8")) + 4] * 37
    assert (tokens, source) == (results[0], "heuristic")
    assert len(truncated.encode("utf-8")) <= 40
    assert loads == ["nanobot.utils"]
    assert len(warnings) == 1
    assert "until restart" in warnings[0]


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

        def encode(self, text: str) -> list[int]:
            self.encoded.append(text)
            return list(range(max(1, len(text) // 4)))

    fake_encoding = FakeEncoding()
    get_encoding_calls = 0

    def fake_get_encoding(name: str, **kwargs) -> FakeEncoding:
        nonlocal get_encoding_calls
        assert name == "nanobot_cl100k_base"
        get_encoding_calls += 1
        return fake_encoding

    monkeypatch.setattr(token_encoding.tiktoken, "Encoding", fake_get_encoding)
    tools = [{"type": "function", "function": {"name": "demo", "description": "cached"}}]
    messages = [{"role": "user", "content": "hello"}]

    first = estimate_prompt_tokens(messages, tools)
    second = estimate_prompt_tokens(messages, tools)

    assert first == second
    assert get_encoding_calls == 1
    rendered_tools = "\n" + json.dumps(tools, ensure_ascii=False)
    assert fake_encoding.encoded.count(rendered_tools) == 1


def test_estimate_prompt_tokens_recomputes_when_tool_items_change(monkeypatch) -> None:
    class FakeEncoding:
        def __init__(self) -> None:
            self.encoded: list[str] = []

        def encode(self, text: str) -> list[int]:
            self.encoded.append(text)
            return list(range(max(1, len(text) // 4)))

    fake_encoding = FakeEncoding()
    monkeypatch.setattr(token_encoding.tiktoken, "Encoding", lambda **kwargs: fake_encoding)

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
