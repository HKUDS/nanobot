import pytest
from nanobot.memory.store import NormalMemoryStore


def test_read_long_term_empty(tmp_path):
    store = NormalMemoryStore(tmp_path)
    assert store.read_long_term() == ""


def test_write_and_read_long_term(tmp_path):
    store = NormalMemoryStore(tmp_path)
    store.write_long_term("key fact: Python is great")
    assert store.read_long_term() == "key fact: Python is great"


def test_append_history(tmp_path):
    store = NormalMemoryStore(tmp_path)
    store.append_history("[2026-04-02 10:00] User asked about weather")
    store.append_history("[2026-04-02 10:01] User asked about news")
    history = (tmp_path / "memory" / "HISTORY.md").read_text()
    assert "[2026-04-02 10:00]" in history
    assert "[2026-04-02 10:01]" in history


def test_get_memory_context_with_content(tmp_path):
    store = NormalMemoryStore(tmp_path)
    store.write_long_term("the user likes cats")
    ctx = store.get_memory_context()
    assert "the user likes cats" in ctx
    assert "Long-term Memory" in ctx
