import pytest
from unittest.mock import MagicMock
from nanobot.agent.memory import MemoryConsolidator
from nanobot.memory.store import NormalMemoryStore


def _make_consolidator(tmp_path):
    store = NormalMemoryStore(tmp_path)
    provider = MagicMock()
    provider.generation = MagicMock()
    provider.generation.max_tokens = 4096
    sessions = MagicMock()
    return MemoryConsolidator(
        store=store,
        provider=provider,
        model="test-model",
        sessions=sessions,
        context_window_tokens=8192,
        build_messages=lambda **kw: [],
        get_tool_definitions=lambda: [],
        max_completion_tokens=4096,
    )


def test_consolidator_accepts_injected_store(tmp_path):
    consolidator = _make_consolidator(tmp_path)
    assert consolidator.store is not None


def test_consolidator_store_reads_long_term(tmp_path):
    consolidator = _make_consolidator(tmp_path)
    assert consolidator.store.read_long_term() == ""
