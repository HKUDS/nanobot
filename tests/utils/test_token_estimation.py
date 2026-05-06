import tiktoken

from nanobot.utils import helpers
from nanobot.utils.helpers import estimate_prompt_tokens_chain


class _FakeEncoding:
    def encode(self, text: str) -> list[int]:
        return list(range(max(1, len(text) // 4)))


class _NoCounterProvider:
    pass


class _BrokenCounterProvider:
    def estimate_prompt_tokens(self, messages, tools=None, model=None):
        raise RuntimeError("counter unavailable")


def test_estimate_prompt_tokens_chain_falls_back_without_provider_counter(monkeypatch) -> None:
    helpers.get_local_cl100k_encoding.cache_clear()
    monkeypatch.setattr(helpers, "get_local_cl100k_encoding", lambda: _FakeEncoding())
    tokens, source = estimate_prompt_tokens_chain(
        _NoCounterProvider(),
        "test-model",
        [{"role": "user", "content": "hello"}],
    )

    assert tokens > 0
    assert source == "tiktoken"


def test_estimate_prompt_tokens_chain_falls_back_when_provider_counter_fails(monkeypatch) -> None:
    helpers.get_local_cl100k_encoding.cache_clear()
    monkeypatch.setattr(helpers, "get_local_cl100k_encoding", lambda: _FakeEncoding())
    tokens, source = estimate_prompt_tokens_chain(
        _BrokenCounterProvider(),
        "test-model",
        [{"role": "user", "content": "hello"}],
    )

    assert tokens > 0
    assert source == "tiktoken"


def test_estimate_prompt_tokens_chain_uses_char_estimate_without_local_encoder(monkeypatch) -> None:
    tiktoken.registry.ENCODINGS.pop("cl100k_base", None)
    monkeypatch.setattr(helpers, "_get_tiktoken_cache_dir", lambda: None)

    def fail_get_encoding(name: str):
        raise AssertionError(f"unexpected tiktoken load for {name}")

    monkeypatch.setattr(tiktoken, "get_encoding", fail_get_encoding)

    tokens, source = estimate_prompt_tokens_chain(
        _NoCounterProvider(),
        "test-model",
        [{"role": "user", "content": "hello from an offline host"}],
    )

    assert tokens > 0
    assert source == "char_estimate"
