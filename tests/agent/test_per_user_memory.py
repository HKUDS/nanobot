"""Tests for per-user memory isolation (agents.defaults.per_user_memory)."""

from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from nanobot.agent.memory import MemoryStore
from nanobot.agent.context import ContextBuilder


# ---------------------------------------------------------------------------
# MemoryStore — path isolation
# ---------------------------------------------------------------------------

def test_memory_store_shared_path(tmp_path: Path) -> None:
    """Without user_id, memory lives in workspace/memory/ (backwards compat)."""
    store = MemoryStore(tmp_path)
    assert store.memory_dir == tmp_path / "memory"


def test_memory_store_per_user_path(tmp_path: Path) -> None:
    """With user_id, memory lives in workspace/users/{user_id}/memory/."""
    store = MemoryStore(tmp_path, user_id="593980378058")
    assert store.memory_dir == tmp_path / "users" / "593980378058" / "memory"


def test_memory_store_user_id_sanitized(tmp_path: Path) -> None:
    """Special characters in user_id are replaced with underscores."""
    store = MemoryStore(tmp_path, user_id="user@domain.com")
    assert "@" not in str(store.memory_dir)
    assert store.memory_dir.parent.parent == tmp_path / "users"


def test_memory_store_users_are_isolated(tmp_path: Path) -> None:
    """Two users get separate memory dirs and separate MEMORY.md files."""
    store_a = MemoryStore(tmp_path, user_id="user_a")
    store_b = MemoryStore(tmp_path, user_id="user_b")

    store_a.write_memory("Alice's memory")
    store_b.write_memory("Bob's memory")

    assert store_a.read_memory() == "Alice's memory"
    assert store_b.read_memory() == "Bob's memory"
    assert store_a.memory_dir != store_b.memory_dir


# ---------------------------------------------------------------------------
# ContextBuilder — user_id propagation
# ---------------------------------------------------------------------------

def test_context_builder_shared_memory(tmp_path: Path) -> None:
    """Without user_id, ContextBuilder uses shared memory."""
    ctx = ContextBuilder(tmp_path)
    assert ctx.memory.user_id is None
    assert ctx.memory.memory_dir == tmp_path / "memory"


def test_context_builder_per_user_memory(tmp_path: Path) -> None:
    """With user_id, ContextBuilder uses per-user memory."""
    ctx = ContextBuilder(tmp_path, user_id="593980378058")
    assert ctx.memory.user_id == "593980378058"
    assert "users" in str(ctx.memory.memory_dir)
    assert "593980378058" in str(ctx.memory.memory_dir)


# ---------------------------------------------------------------------------
# Consolidator — store_factory routing
# ---------------------------------------------------------------------------

def test_consolidator_get_store_no_factory(tmp_path: Path) -> None:
    """Without store_factory, _get_store always returns the shared store."""
    from nanobot.agent.memory import Consolidator

    shared_store = MemoryStore(tmp_path)
    consolidator = Consolidator(
        store=shared_store,
        provider=MagicMock(),
        model="test",
        sessions=MagicMock(),
        context_window_tokens=1000,
        build_messages=MagicMock(),
        get_tool_definitions=MagicMock(return_value=[]),
    )
    assert consolidator._get_store("whatsapp:user_a") is shared_store
    assert consolidator._get_store("whatsapp:user_b") is shared_store


def test_consolidator_get_store_with_factory(tmp_path: Path) -> None:
    """With store_factory, _get_store returns the per-user store."""
    from nanobot.agent.memory import Consolidator

    shared_store = MemoryStore(tmp_path)
    user_stores: dict[str, MemoryStore] = {}

    def factory(user_id: str) -> MemoryStore:
        if user_id not in user_stores:
            user_stores[user_id] = MemoryStore(tmp_path, user_id=user_id)
        return user_stores[user_id]

    consolidator = Consolidator(
        store=shared_store,
        provider=MagicMock(),
        model="test",
        sessions=MagicMock(),
        context_window_tokens=1000,
        build_messages=MagicMock(),
        get_tool_definitions=MagicMock(return_value=[]),
        store_factory=factory,
    )

    store_a = consolidator._get_store("whatsapp:user_a")
    store_b = consolidator._get_store("whatsapp:user_b")

    assert store_a is not store_b
    assert store_a.user_id == "user_a"
    assert store_b.user_id == "user_b"
    assert store_a is not shared_store
