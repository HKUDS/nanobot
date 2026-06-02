"""Tests for L1 SQLite + FTS store (LM2-C)."""

from pathlib import Path

import pytest

from nanobot.agent.layered_memory.l1_dedup import content_hash
from nanobot.agent.layered_memory.l1_store import L1Store


@pytest.fixture
def store(tmp_path: Path) -> L1Store:
    return L1Store(tmp_path)


def test_insert_and_search(store: L1Store) -> None:
    atom_id = store.insert(
        session_key="cli:direct",
        memory_type="preference",
        content="User prefers dark mode in the IDE",
        source_l0_ids=(1, 2),
        source_turn_ids=("cli:direct:1",),
    )
    assert atom_id is not None
    assert store.db_path.exists()
    hits = store.search("dark mode", session_key="cli:direct")
    assert len(hits) == 1
    assert hits[0].atom_id == atom_id
    assert hits[0].memory_type == "preference"


def test_list_recent_returns_newest_first(store: L1Store) -> None:
    for i in range(3):
        store.insert(
            session_key=f"s{i}",
            memory_type="fact",
            content=f"item {i}",
            source_l0_ids=(i,),
            source_turn_ids=(f"t{i}",),
        )
    recent = store.list_recent(2)
    assert len(recent) == 2
    assert "item 2" in recent[0].content
    first = store.insert(
        session_key="cli:direct",
        memory_type="fact",
        content="Project codename is nanobot",
        source_l0_ids=(3,),
        source_turn_ids=("t1",),
    )
    second = store.insert(
        session_key="cli:direct",
        memory_type="fact",
        content="Project codename is nanobot",
        source_l0_ids=(4,),
        source_turn_ids=("t2",),
    )
    assert first is not None
    assert second is None
    assert store.count_session("cli:direct") == 1
    assert store.has_content_hash(content_hash("Project codename is nanobot"))


def test_count_session(store: L1Store) -> None:
    store.insert(
        session_key="sess-a",
        memory_type="event",
        content="Deployed v1 on Monday",
        source_l0_ids=(1,),
        source_turn_ids=("t1",),
    )
    store.insert(
        session_key="sess-b",
        memory_type="rule",
        content="Never commit secrets",
        source_l0_ids=(2,),
        source_turn_ids=("t2",),
    )
    assert store.count_session("sess-a") == 1
    assert store.count_session("sess-b") == 1
