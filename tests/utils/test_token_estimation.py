import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from nanobot.utils import helpers
from nanobot.utils.helpers import estimate_prompt_tokens_chain


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


def test_tokenizer_lookup_waits_for_inflight_warmup(monkeypatch) -> None:
    warmup_entered = Event()
    release_warmup = Event()

    class _FakeEncoding:
        def encode(self, text: str) -> list[int]:
            if text == "warmup":
                warmup_entered.set()
                assert release_warmup.wait(timeout=2)
            return [1]

    fake_encoding = _FakeEncoding()

    monkeypatch.setattr(helpers, "_TOKENIZER_ENCODING", None)
    monkeypatch.setattr(
        helpers.tiktoken,
        "get_encoding",
        lambda _name: fake_encoding,
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        warmup_future = executor.submit(helpers.warmup_tokenizer)
        assert warmup_entered.wait(timeout=2)

        lookup_future = executor.submit(helpers.get_tokenizer_encoding)
        time.sleep(0.05)
        assert not lookup_future.done()

        release_warmup.set()
        assert lookup_future.result(timeout=2) is fake_encoding
        warmup_future.result(timeout=2)


def test_warmup_tokenizer_reuses_cached_encoding(monkeypatch) -> None:
    calls: list[str] = []

    class _FakeEncoding:
        def encode(self, _text: str) -> list[int]:
            return [1]

    monkeypatch.setattr(helpers, "_TOKENIZER_ENCODING", None)

    def fake_get_encoding(name: str) -> _FakeEncoding:
        calls.append(name)
        return _FakeEncoding()

    monkeypatch.setattr(helpers.tiktoken, "get_encoding", fake_get_encoding)

    helpers.warmup_tokenizer()
    helpers.warmup_tokenizer()

    assert calls == ["cl100k_base"]
