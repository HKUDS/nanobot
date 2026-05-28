"""Tests for L1 deduplication (LM2-C)."""

from nanobot.agent.layered_memory.l1_dedup import is_duplicate, text_similarity


def test_text_similarity_overlap() -> None:
    assert text_similarity("user prefers dark mode", "prefers dark mode theme") > 0.5
    assert text_similarity("hello world", "goodbye moon") == 0.0


def test_is_duplicate_exact_hash(tmp_path) -> None:
    from nanobot.agent.layered_memory.l1_store import L1Store

    store = L1Store(tmp_path)
    store.insert(
        session_key="cli:direct",
        memory_type="fact",
        content="User timezone is Asia/Shanghai",
        source_l0_ids=(1,),
        source_turn_ids=("t1",),
    )
    assert is_duplicate(
        "User timezone is Asia/Shanghai",
        store,
        session_key="cli:direct",
        enable_dedup=True,
    )
    assert not is_duplicate(
        "User speaks Mandarin",
        store,
        session_key="cli:direct",
        enable_dedup=True,
    )


def test_is_duplicate_near_match_with_fts(tmp_path) -> None:
    from nanobot.agent.layered_memory.l1_store import L1Store

    store = L1Store(tmp_path)
    store.insert(
        session_key="cli:direct",
        memory_type="preference",
        content="User prefers responses in Chinese",
        source_l0_ids=(1,),
        source_turn_ids=("t1",),
    )
    assert is_duplicate(
        "User prefers Chinese responses",
        store,
        session_key="cli:direct",
        enable_dedup=True,
    )
