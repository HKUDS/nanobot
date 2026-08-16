from pathlib import Path

import pytest
import tiktoken

from nanobot.utils import helpers
from nanobot.utils.helpers import (
    _write_text_atomic,
    content_with_media_breadcrumbs,
    split_message,
    truncate_text_to_tokens,
)


def test_split_message_no_code_blocks_unchanged():
    content = "alpha beta gamma delta"

    assert split_message(content, max_len=12) == ["alpha beta", "gamma delta"]


def test_split_message_nonpositive_maxlen_returns_unsplit():
    content = "alpha beta gamma delta"

    assert split_message(content, max_len=0) == [content]
    assert split_message(content, max_len=-1) == [content]


def test_truncate_text_to_tokens_keeps_text_within_budget():
    text = "hello world " * 100

    result = truncate_text_to_tokens(text, 10_000)

    assert result == text


def test_truncate_text_to_tokens_truncates_over_budget():
    enc = tiktoken.get_encoding("cl100k_base")
    text = "word " * 1_000

    result = truncate_text_to_tokens(text, 50)

    assert result.endswith("\n... (truncated)")
    assert len(enc.encode(result)) <= 50


def test_truncate_text_to_tokens_non_positive_budget_returns_text():
    text = "anything"

    assert truncate_text_to_tokens(text, 0) == text


def test_content_with_media_breadcrumbs_preserves_valid_paths():
    assert content_with_media_breadcrumbs(
        "user",
        "review these",
        ["/media/report.pdf", "/media/clip.mp4"],
    ) == (
        "review these\n"
        "[image: /media/report.pdf]\n"
        "[image: /media/clip.mp4]"
    )


def test_content_with_media_breadcrumbs_only_rewrites_plain_user_content():
    structured = [{"type": "text", "text": "hello"}]

    assert content_with_media_breadcrumbs(
        "assistant",
        "done",
        ["/media/output.png"],
    ) == "done"
    assert content_with_media_breadcrumbs(
        "user",
        structured,
        ["/media/input.png"],
    ) is structured


def test_write_text_atomic_fsyncs_file_and_parent_directory(
    tmp_path: Path, monkeypatch
) -> None:
    target = tmp_path / "pairing.json"
    fsync_calls: list[int] = []
    closed_fds: list[int] = []

    def fake_fsync(fd: int) -> None:
        fsync_calls.append(fd)

    monkeypatch.setattr(helpers.os, "fsync", fake_fsync)
    monkeypatch.setattr(helpers.os, "open", lambda path, flags: 12345)
    monkeypatch.setattr(helpers.os, "close", lambda fd: closed_fds.append(fd))

    _write_text_atomic(target, '{"approved": {}}')

    assert target.read_text(encoding="utf-8") == '{"approved": {}}'
    assert len(fsync_calls) == 2
    assert fsync_calls[0] != 12345
    assert fsync_calls[1] == 12345
    assert closed_fds == [12345]


def test_write_text_atomic_keeps_file_when_directory_fsync_is_unsupported(
    tmp_path: Path, monkeypatch
) -> None:
    target = tmp_path / "pairing.json"
    fsync_calls: list[int] = []

    def fake_open(path, flags):
        raise OSError("directory fsync unsupported")

    monkeypatch.setattr(helpers.os, "fsync", lambda fd: fsync_calls.append(fd))
    monkeypatch.setattr(helpers.os, "open", fake_open)

    _write_text_atomic(target, '{"pending": {}}')

    assert target.read_text(encoding="utf-8") == '{"pending": {}}'
    assert len(fsync_calls) == 1


# ── token estimation: model-aware encoding, framing overhead, usage floor ──


@pytest.fixture(autouse=True)
def _clear_token_encoding_cache():
    """The module-level lru_cache can retain fake encodings across tests."""
    yield
    clear = getattr(helpers._get_token_encoding, "cache_clear", None)
    if clear is not None:
        clear()


class _FakeEncoding:
    """Deterministic local stand-in so tests never hit the tiktoken download."""

    def __init__(self, name: str) -> None:
        self.name = name

    def encode(self, text: str) -> list[str]:
        # ~3 chars per token, same rule as the byte heuristic's intent.
        return ["t"] * max(1, len(text) // 3)


def test_get_token_encoding_selects_o200k_for_modern_models(monkeypatch) -> None:
    seen: list[str] = []

    def fake_get_encoding(name: str) -> _FakeEncoding:
        seen.append(name)
        return _FakeEncoding(name)

    monkeypatch.setattr(helpers.tiktoken, "get_encoding", fake_get_encoding)

    assert helpers._get_token_encoding("gpt-5.6").name == "o200k_base"
    assert helpers._get_token_encoding("gpt-4o-mini").name == "o200k_base"
    assert helpers._get_token_encoding("qwen3.8").name == "o200k_base"  # fallback
    assert helpers._get_token_encoding("gpt-4").name == "cl100k_base"
    assert helpers._get_token_encoding(None).name == "cl100k_base"  # legacy default kept


def test_estimate_prompt_tokens_counts_framing_overhead(monkeypatch) -> None:
    monkeypatch.setattr(helpers, "_get_token_encoding", lambda model=None: _FakeEncoding("o200k_base"))
    monkeypatch.setattr(helpers, "_estimate_tools_tokens", lambda enc, tools, **kw: 0)

    est, source = helpers._estimate_prompt_tokens_with_source(
        [{"role": "user", "content": "hello world"}],
        model="gpt-5.6",
    )
    # content tokens (~11 chars / 3) + 1 msg * 4 framing + 3 request prefix
    assert est > 0
    assert source == "tiktoken"


def test_estimate_prompt_tokens_falls_back_without_network(monkeypatch) -> None:
    def offline(model=None):
        raise OSError("no network")

    monkeypatch.setattr(helpers, "_get_token_encoding", offline)

    est, source = helpers._estimate_prompt_tokens_with_source(
        [{"role": "user", "content": "你好世界"}],
        model="qwen3.8",
    )
    assert est > 0
    assert source == "heuristic"


def test_estimate_chain_uses_known_usage_as_floor(monkeypatch) -> None:
    monkeypatch.setattr(helpers, "_get_token_encoding", lambda model=None: _FakeEncoding("o200k_base"))
    monkeypatch.setattr(helpers, "_estimate_tools_tokens", lambda enc, tools, **kw: 0)

    provider = object()  # no estimate_prompt_tokens attribute
    est, source = helpers.estimate_prompt_tokens_chain(
        provider,
        "gpt-5.6",
        [{"role": "user", "content": "short"}],
        known_usage=5000,
    )
    assert est == 5000
    assert source.endswith("+usage")


def test_estimate_chain_keeps_estimate_when_usage_is_lower(monkeypatch) -> None:
    monkeypatch.setattr(helpers, "_get_token_encoding", lambda model=None: _FakeEncoding("o200k_base"))
    monkeypatch.setattr(helpers, "_estimate_tools_tokens", lambda enc, tools, **kw: 0)

    provider = object()
    est, source = helpers.estimate_prompt_tokens_chain(
        provider,
        "gpt-5.6",
        [{"role": "user", "content": "hello world " * 500}],
        known_usage=10,
    )
    assert est > 10
    assert "usage" not in source
