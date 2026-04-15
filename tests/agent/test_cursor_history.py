import json
from pathlib import Path
import pytest
from nanobot.agent.memory import MemoryStore

@pytest.fixture
def store(tmp_path):
    return MemoryStore(workspace=tmp_path)

def test_read_unprocessed_returns_entries_after_cursor(store):
    store.append_history("fact one")
    store.append_history("fact two")
    store.append_history("fact three")
    entries = store.read_unprocessed_history(since_cursor=1)
    assert len(entries) == 2
    assert entries[0]["content"] == "fact two"

def test_incremental_read_after_append(store):
    store.append_history("first")
    store.append_history("second")
    e1 = store.read_unprocessed_history(since_cursor=0)
    assert len(e1) == 2
    store.append_history("third")
    e2 = store.read_unprocessed_history(since_cursor=2)
    assert len(e2) == 1
    assert e2[0]["content"] == "third"

def test_compact_resets_offset(store):
    for i in range(20):
        store.append_history(f"entry {i}")
    store.read_unprocessed_history(since_cursor=0)
    store.max_history_entries = 5
    store.compact_history()
    entries = store.read_unprocessed_history(since_cursor=15)
    assert len(entries) == 5

def test_cold_start_full_scan(store):
    store.append_history("hello")
    # No prior read — should do full scan
    entries = store.read_unprocessed_history(since_cursor=0)
    assert len(entries) == 1

def test_empty_history(store):
    entries = store.read_unprocessed_history(since_cursor=0)
    assert entries == []

def test_buffered_writes_visible_before_flush(store):
    store.append_history("buffered")
    entries = store.read_unprocessed_history(since_cursor=0)
    assert len(entries) == 1
    assert entries[0]["content"] == "buffered"

def test_flush_writes_to_disk(store):
    store.append_history("a")
    store.append_history("b")
    store.flush_history()
    raw = store.history_file.read_text()
    assert "a" in raw and "b" in raw

def test_flush_clears_buffer(store):
    store.append_history("x")
    store.flush_history()
    assert store._pending_entries == []

def test_compact_flushes_first(store):
    store.append_history("a")
    store.append_history("b")
    store.append_history("c")
    store.max_history_entries = 2
    store.compact_history()
    entries = store.read_unprocessed_history(since_cursor=0)
    assert len(entries) == 2
