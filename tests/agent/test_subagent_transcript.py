"""Tests for the durable subagent transcript store."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path

import pytest

from nanobot.agent.subagent_transcript import (
    SubagentTranscriptStore,
)
from nanobot.runtime_context import RUNTIME_CONTEXT_HISTORY_META
from nanobot.session.history_visibility import HIDDEN_HISTORY_META


def _messages(*records: dict) -> list[dict]:
    return list(records)


def _assistant_with_tool_calls() -> dict:
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {"id": "call_1", "type": "function", "function": {"name": "list_dir", "arguments": "{}"}}
        ],
    }


def _runtime_context_marker_message() -> dict:
    # public_history_message strips the marker and, when the suffix matches the
    # whole content, empties the content.
    return {
        "role": "user",
        "content": "visible instruction",
        RUNTIME_CONTEXT_HISTORY_META: {"version": 1, "suffix": "", "blocks": []},
    }


@pytest.fixture
def store(tmp_path: Path) -> SubagentTranscriptStore:
    return SubagentTranscriptStore(tmp_path)


async def test_write_read_round_trip(store: SubagentTranscriptStore) -> None:
    """Write then read returns the normalized records unchanged."""
    store.write(
        "abc12345",
        _messages(
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ),
    )
    records = store.read("abc12345")
    assert [r["role"] for r in records] == ["system", "user", "assistant"]
    assert [r["content"] for r in records] == ["sys", "hello", "hi"]


async def test_tool_calls_round_trip(store: SubagentTranscriptStore) -> None:
    """A record with tool_calls preserves them."""
    store.write("abc12345", _messages(_assistant_with_tool_calls()))
    records = store.read("abc12345")
    assert records[0]["tool_calls"][0]["id"] == "call_1"
    assert records[0]["tool_calls"][0]["function"]["name"] == "list_dir"


async def test_strips_runtime_context_and_hidden_rows(store: SubagentTranscriptStore) -> None:
    """Runtime-context markers are stripped and hidden rows excluded."""
    store.write(
        "abc12345",
        _messages(
            _runtime_context_marker_message(),
            {"role": "user", "content": "hidden", HIDDEN_HISTORY_META: True},
            {"role": "user", "content": "kept"},
        ),
    )
    records = store.read("abc12345")
    assert [r["content"] for r in records] == ["visible instruction", "kept"]
    assert all(RUNTIME_CONTEXT_HISTORY_META not in r for r in records)
    assert all(HIDDEN_HISTORY_META not in r for r in records)


async def test_every_record_carries_timestamp(store: SubagentTranscriptStore) -> None:
    """Every stored record is stamped with an ISO 8601 timestamp."""
    store.write(
        "abc12345",
        _messages(
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "b"},
        ),
    )
    for record in store.read("abc12345"):
        assert "timestamp" in record
        datetime.fromisoformat(record["timestamp"])


async def test_thinking_keys_are_dropped(store: SubagentTranscriptStore) -> None:
    """Reasoning/thinking content is not persisted."""
    store.write(
        "abc12345",
        _messages(
            {"role": "assistant", "content": "final", "reasoning_content": "hidden thought",
             "thinking_blocks": [{"type": "thinking", "thinking": "x"}]},
        ),
    )
    records = store.read("abc12345")
    assert "reasoning_content" not in records[0]
    assert "thinking_blocks" not in records[0]


async def test_over_cap_write_emits_truncation_marker(
    store: SubagentTranscriptStore, monkeypatch
) -> None:
    """An over-cap write stops appending, marks truncation, stays valid JSONL."""
    monkeypatch.setattr("nanobot.agent.subagent_transcript.TRANSCRIPT_MAX_BYTES", 128)
    records = _messages(
        {"role": "user", "content": "x" * 512},
        {"role": "assistant", "content": "y" * 512},
    )
    store.write("abc12345", records)
    path = store.path_for("abc12345")
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    parsed = [json.loads(line) for line in lines]
    # First record always fits (never truncate a line); later records drop and
    # a terminal marker is appended.
    assert parsed[0]["content"].startswith("x")
    assert parsed[-1]["role"] == "system"
    assert "truncated" in parsed[-1]["content"]
    for line in lines:
        json.loads(line)  # every line is valid JSON


async def test_atomic_write_preserves_previous_file(store: SubagentTranscriptStore, monkeypatch) -> None:
    """A mid-write failure leaves the previous file intact."""
    store.write("abc12345", _messages({"role": "user", "content": "before"}))
    original = store.path_for("abc12345").read_text(encoding="utf-8")

    import nanobot.agent.subagent_transcript as module

    def _explode(_target: Path, _lines: list[str]) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(module.SubagentTranscriptStore, "_write_atomic", staticmethod(_explode))
    with pytest.raises(OSError):
        store.write("abc12345", _messages({"role": "user", "content": "after"}))

    assert store.path_for("abc12345").read_text(encoding="utf-8") == original
    # No stray temp files remain.
    assert list(store.root.glob("*.tmp")) == []


async def test_prune_keeps_newest_by_mtime(store: SubagentTranscriptStore) -> None:
    """Writing a 51st transcript prunes the oldest by modification time."""
    from nanobot.agent.subagent_transcript import TRANSCRIPT_RETENTION_COUNT

    # Synthetic mtimes strictly increase with i and sit well in the past, so
    # the just-written file (real mtime = now) is always the newest at prune.
    base = time.time() - 1000
    for i in range(TRANSCRIPT_RETENTION_COUNT + 1):
        task_id = f"t{i:08x}"
        store.write(task_id, _messages({"role": "user", "content": f"msg {i}"}))
        ts = base + i
        os.utime(store.path_for(task_id), (ts, ts))

    remaining = store.list()
    assert len(remaining) == TRANSCRIPT_RETENTION_COUNT
    assert "t00000000" not in remaining
    assert f"t{TRANSCRIPT_RETENTION_COUNT:08x}" in remaining


async def test_empty_message_list_writes_valid_empty_file(
    store: SubagentTranscriptStore,
) -> None:
    """An empty message list writes a valid file without error."""
    store.write("abc12345", [])
    assert store.read("abc12345") == []
    assert store.path_for("abc12345").exists()


async def test_size_cap_counts_utf8_bytes(store: SubagentTranscriptStore, monkeypatch) -> None:
    """The cap is measured in UTF-8 bytes, not characters."""
    monkeypatch.setattr("nanobot.agent.subagent_transcript.TRANSCRIPT_MAX_BYTES", 40)
    # Each CJK char is 3 UTF-8 bytes: record 0 (8 chars) fits, record 1 (12
    # chars) pushes the total past the cap, so truncation must fire.
    store.write(
        "abc12345",
        _messages(
            {"role": "user", "content": "你" * 8},
            {"role": "assistant", "content": "你" * 12},
        ),
    )
    lines = [
        line
        for line in store.path_for("abc12345").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    parsed = [json.loads(line) for line in lines]
    assert parsed[-1]["role"] == "system"
    assert "truncated" in parsed[-1]["content"]


async def test_read_skips_one_malformed_line(store: SubagentTranscriptStore) -> None:
    """A single corrupt line is skipped, not fatal to the whole transcript."""
    store.write("abc12345", _messages({"role": "user", "content": "ok"}))
    path = store.path_for("abc12345")
    path.write_text(
        json.dumps({"role": "user", "content": "ok"}) + "\n{not-json}\n" + json.dumps({"role": "assistant", "content": "later"}),
        encoding="utf-8",
    )
    records = store.read("abc12345")
    assert [r["content"] for r in records] == ["ok", "later"]


async def test_write_refuses_symlinked_transcript_dir(
    store: SubagentTranscriptStore, monkeypatch
) -> None:
    """A planted symlink at the transcript directory is refused (containment)."""
    outside = store.root.parent.parent / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("sentinel", encoding="utf-8")
    # Replace the real transcript dir with a symlink to the outside dir.
    import shutil

    if store.root.exists():
        shutil.rmtree(store.root)
    store.root.parent.mkdir(parents=True, exist_ok=True)
    store.root.symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        store.write("abc12345", _messages({"role": "user", "content": "hi"}))
    assert not (outside / "abc12345.jsonl").exists()


async def test_write_refuses_planted_tmp_symlink(
    store: SubagentTranscriptStore, monkeypatch
) -> None:
    """A planted symlink at the .tmp name cannot be followed for overwrite."""
    # First write creates the transcript dir.
    store.write("abc12345", _messages({"role": "user", "content": "x"}))
    victim = store.root.parent / "victim.txt"
    victim.write_text("original", encoding="utf-8")
    # Plant a symlink where the temp file will be created.
    (store.root / "abc12345.jsonl").unlink()
    (store.root / "abc12345.jsonl.tmp").symlink_to(victim)

    store.write("abc12345", _messages({"role": "user", "content": "y"}))
    # O_EXCL refuses the planted name; the retry suffix is used and the victim
    # is never written through the symlink.
    assert victim.read_text(encoding="utf-8") == "original"
    assert (store.root / "abc12345.jsonl").exists()


async def test_list_and_missing_read(store: SubagentTranscriptStore) -> None:
    """list() enumerates task ids; read() on a missing id returns []."""
    store.write("abc12345", _messages({"role": "user", "content": "hi"}))
    assert store.list() == ["abc12345"]
    assert store.read("doesnotexist") == []


async def test_write_without_o_nofollow_attribute(
    store: SubagentTranscriptStore, monkeypatch
) -> None:
    """Platforms lacking os.O_NOFOLLOW (e.g. Windows) still write successfully."""
    import nanobot.agent.subagent_transcript as module

    monkeypatch.delattr(module.os, "O_NOFOLLOW", raising=False)
    store.write("abc12345", _messages({"role": "user", "content": "hi"}))
    assert store.path_for("abc12345").exists()
    assert store.read("abc12345")[0]["content"] == "hi"
