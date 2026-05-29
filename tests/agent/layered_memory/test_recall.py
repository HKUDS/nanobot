"""Tests for turn-before recall (LM2-D)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from nanobot.agent.layered_memory import LayeredMemoryFacade, RecallResult
from nanobot.agent.layered_memory.l1_store import L1Store
from nanobot.agent.layered_memory.recall import perform_recall
from nanobot.config.schema import LayeredMemoryConfig, LayeredMemoryRecallConfig


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path


def _seed_atom(store: L1Store, content: str, *, session_key: str = "cli:direct") -> None:
    store.insert(
        session_key=session_key,
        memory_type="rule",
        content=content,
        source_l0_ids=(1,),
        source_turn_ids=("t1",),
    )


def test_perform_recall_finds_atom_by_keyword(workspace: Path) -> None:
    store = L1Store(workspace)
    _seed_atom(store, '只在用户明确说"提交/commit"时才执行 git commit')
    cfg = LayeredMemoryRecallConfig(enable=True, top_k=5)
    result = perform_recall(
        workspace=workspace,
        config=cfg,
        query="git commit 规则是什么",
        session_key="cli:direct",
        l1_store=store,
    )
    joined = "\n".join(result.prepend_lines)
    assert "[Recalled memories]" in joined
    assert "git commit" in joined


def test_perform_recall_cross_session(workspace: Path) -> None:
    store = L1Store(workspace)
    _seed_atom(store, "User prefers Chinese replies", session_key="other:session")
    cfg = LayeredMemoryRecallConfig(enable=True)
    result = perform_recall(
        workspace=workspace,
        config=cfg,
        query="Chinese language preference",
        session_key="cli:direct",
        l1_store=store,
    )
    assert any("Chinese" in line for line in result.prepend_lines)


def test_perform_recall_includes_user_md_note(workspace: Path) -> None:
    (workspace / "USER.md").write_text(
        "# Profile\n\nCommunicates in Chinese.\n\nMore details here.",
        encoding="utf-8",
    )
    cfg = LayeredMemoryRecallConfig(enable=True)
    result = perform_recall(
        workspace=workspace,
        config=cfg,
        query="",
        session_key="cli:direct",
    )
    joined = "\n".join(result.prepend_lines)
    assert "[User profile note]" in joined
    assert "Communicates in Chinese" in joined


def test_perform_recall_empty_query_no_atoms(workspace: Path) -> None:
    cfg = LayeredMemoryRecallConfig(enable=True)
    result = perform_recall(
        workspace=workspace,
        config=cfg,
        query="",
        session_key="cli:direct",
    )
    assert result.prepend_lines == []


def test_recall_respects_max_prepend_chars(workspace: Path) -> None:
    store = L1Store(workspace)
    for i in range(10):
        _seed_atom(store, f"Memory item number {i} with extra padding text")
    cfg = LayeredMemoryRecallConfig(enable=True, top_k=10, max_prepend_chars=500)
    result = perform_recall(
        workspace=workspace,
        config=cfg,
        query="Memory item",
        session_key="cli:direct",
        l1_store=store,
    )
    assert len("\n".join(result.prepend_lines)) <= 500


@pytest.mark.asyncio
async def test_facade_recall_timeout_returns_empty(workspace: Path) -> None:
    cfg = LayeredMemoryConfig(
        enable=True,
        recall=LayeredMemoryRecallConfig(enable=True, timeout_ms=500),
    )
    facade = LayeredMemoryFacade(workspace, cfg)

    def slow_recall(**kwargs) -> RecallResult:
        import time

        time.sleep(0.5)
        return RecallResult(prepend_lines=["should not appear"])

    with patch(
        "nanobot.agent.layered_memory.facade.perform_recall",
        side_effect=slow_recall,
    ):
        result = await facade.recall("query", "cli:direct")
    assert result == RecallResult()


@pytest.mark.asyncio
async def test_facade_recall_with_seeded_atom(workspace: Path) -> None:
    store = L1Store(workspace)
    _seed_atom(store, "Never auto git commit without explicit user request")
    cfg = LayeredMemoryConfig(
        enable=True,
        recall=LayeredMemoryRecallConfig(enable=True),
    )
    facade = LayeredMemoryFacade(workspace, cfg)
    facade._l1_store = store
    result = await facade.recall("git commit policy", "cli:direct")
    joined = "\n".join(result.prepend_lines)
    assert "git commit" in joined.lower()
