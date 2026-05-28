"""Tests for M2: MEMORY.md is kept whole on disk; only the injected copy is capped.

This replaces the prior behaviour where write_long_term silently truncated the
file to 200 lines, causing facts past the cap to disappear. See
vault/typed-memory-port-from-openclaw.md.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.agent.memory import MemoryStore


@pytest.fixture
def store(tmp_path: Path) -> MemoryStore:
    return MemoryStore(tmp_path)


# ---- on-disk: no silent truncation -------------------------------------------


def test_write_long_term_persists_full_content_past_cap(store: MemoryStore) -> None:
    content = "\n".join(f"fact line {i}" for i in range(500))
    store.write_long_term(content)
    on_disk = store.memory_file.read_text(encoding="utf-8")
    assert on_disk == content, "MEMORY.md must persist full content; no on-disk truncation"
    assert "Truncated" not in on_disk, "Truncation marker must not be written to disk"
    assert on_disk.count("\n") == 499  # 500 lines


def test_write_long_term_short_content_round_trips(store: MemoryStore) -> None:
    content = "a single fact\nand another"
    store.write_long_term(content)
    assert store.read_long_term() == content


def test_read_long_term_returns_full_file(store: MemoryStore) -> None:
    content = "\n".join(f"line {i}" for i in range(300))
    store.write_long_term(content)
    assert store.read_long_term() == content
    assert len(store.read_long_term().splitlines()) == 300


# ---- injected copy: soft cap with marker -------------------------------------


def test_get_memory_context_short_returns_unchanged(store: MemoryStore) -> None:
    store.write_long_term("just a few facts")
    ctx = store.get_memory_context()
    assert ctx.startswith("## Long-term Memory")
    assert "just a few facts" in ctx
    assert "Context-truncated" not in ctx


def test_get_memory_context_truncates_when_oversize(store: MemoryStore) -> None:
    content = "\n".join(f"fact {i}" for i in range(300))
    store.write_long_term(content)
    ctx = store.get_memory_context()

    assert "Context-truncated" in ctx, "marker must signal that more lines exist on disk"
    assert "memory/MEMORY.md" in ctx, "marker should point at the on-disk file"
    assert "read_file" in ctx, "marker should hint at how to read the remainder"
    assert "fact 0" in ctx, "first lines must be present"
    assert "fact 299" not in ctx, "tail lines must NOT be in the injected copy"


def test_get_memory_context_marker_includes_counts(store: MemoryStore) -> None:
    """The agent reads the marker — it should be specific enough to act on."""
    content = "\n".join(f"line {i}" for i in range(258))  # matches Iroh's actual state
    store.write_long_term(content)
    ctx = store.get_memory_context()
    assert "258" in ctx, "total line count should appear"
    assert "200" in ctx, "cap should appear"


def test_get_memory_context_empty_returns_empty(store: MemoryStore) -> None:
    assert store.get_memory_context() == ""


# ---- regression: previous behaviour wouldn't have caught this ----------------


def test_writing_300_lines_does_not_lose_data_on_next_read(store: MemoryStore) -> None:
    """The Peewee/Iroh failure mode: a write of >200 lines silently dropped
    everything past line 200. After M2 the next read must see all 300."""
    content = "\n".join(
        ["# Header"] + [f"- Safety fact #{i}" for i in range(299)]
    )
    store.write_long_term(content)
    # Simulate the next consolidation reading current state to build on it.
    reread = store.read_long_term()
    assert reread.count("Safety fact") == 299, "no safety facts may be lost across write/read"
    assert "Safety fact #298" in reread
