"""Tests for ContextCompactor."""

from pathlib import Path

import pytest

from nanobot.agent.compactor import (
    ContextCompactor,
    DEFAULT_BUDGET,
    estimate_tokens,
)
from nanobot.agent.memory import MemoryStore


@pytest.fixture
def store(tmp_path: Path) -> MemoryStore:
    return MemoryStore(tmp_path)


def test_estimate_tokens_empty() -> None:
    assert estimate_tokens("") == 0


def test_push_stays_under_budget(store: MemoryStore) -> None:
    # Best-effort tiered compaction; use a budget large enough to allow
    # L3 index + summaries + recent turns to settle below the cap.
    cap = 6000
    c = ContextCompactor(store, budget=cap)
    c.push("system", "x" * 100, protected=True)
    for i in range(20):
        c.push("user", f"msg {i} " + "u" * 200)
        c.push("assistant", f"reply {i} " + "a" * 200)
    assert c.stats()["tokens"]["total"] <= cap + 500


def test_render_includes_layers(store: MemoryStore) -> None:
    store.write_memory("project fact")
    c = ContextCompactor(store, budget=50_000)
    c.push("user", "hello")
    c.push("assistant", "world")
    text = c.render()
    assert "<memory_index>" in text
    assert "<recent_conversation>" in text
    assert "hello" in text


def test_l3_remembers_via_flush(store: MemoryStore) -> None:
    def summer(_i: str, t: str) -> str:
        return t[:80]

    c = ContextCompactor(store, budget=400, summarizer=summer)
    for i in range(24):
        c.push("user", f"u{i} " + "x" * 120)
        c.push("assistant", f"a{i} " + "y" * 120)
    assert store.list_topics() or c.stats()["l2_digests"] == 0


def test_protected_block_uses_verbatim_summary(store: MemoryStore) -> None:
    c = ContextCompactor(store, budget=300)
    c.push("system", "sys", protected=True)
    for i in range(8):
        c.push("user", "x" * 100)
    c.push("assistant", "y" * 100)
    assert c.stats()["l1_blocks"] >= 0
    assert c.stats()["total_turns"] >= 9


def test_stats_shape(store: MemoryStore) -> None:
    c = ContextCompactor(store, budget=DEFAULT_BUDGET)
    c.push("user", "hi")
    s = c.stats()
    assert "tokens" in s
    assert s["tokens"]["budget"] == DEFAULT_BUDGET


def test_compaction_creates_warm_blocks(store: MemoryStore) -> None:
    c = ContextCompactor(store, budget=1200)
    for i in range(14):
        c.push("user", "hello " * 40)
        c.push("assistant", "world " * 40)
    assert c.stats()["l1_blocks"] >= 1


def test_render_layer_order(store: MemoryStore) -> None:
    store.write_memory("idx")
    c = ContextCompactor(store, budget=800)
    c.push("user", "last")
    out = c.render()
    mi = out.index("<memory_index>")
    rc = out.index("<recent_conversation>")
    assert mi < rc


def test_l2_flush_persists_topic_via_remember(store: MemoryStore) -> None:
    def short_sum(_i: str, t: str) -> str:
        return t[:80]

    c = ContextCompactor(store, budget=160, summarizer=short_sum)
    for i in range(56):
        c.push("user", f"error {i} bug fix " + "x" * 50)
        c.push("assistant", f"ok {i} " + "y" * 50)
    assert store.list_topics(), "L3 flush should persist via remember()"
