from __future__ import annotations

import pytest

from agent.memory_harness import MemoryLifecycleHarness


@pytest.mark.asyncio
async def test_memory_lifecycle_harness_archives_then_versions_memory(tmp_path):
    harness = MemoryLifecycleHarness(tmp_path)
    session = harness.session()
    harness.add_turn(
        session,
        "Please keep PR summaries short and concrete.",
        "Got it. I will keep PR summaries short and concrete.",
    )

    summary = await harness.archive_session(
        session,
        summary="- User prefers short, concrete PR summaries.",
    )

    entries = harness.store.read_unprocessed_history(since_cursor=0)
    assert summary == "- User prefers short, concrete PR summaries."
    assert session.last_consolidated == 2
    assert [entry["cursor"] for entry in entries] == [1]
    assert entries[0]["content"] == summary

    harness.init_git_snapshot()
    harness.store.write_user("# User\n- Prefers short, concrete PR summaries.\n")
    sha = harness.commit_memory_change(
        "memory: record user PR summary preference\n\n"
        "Source: archived session summary cursor 1"
    )

    assert len(sha) == 8
    assert "short, concrete PR summaries" in harness.store.read_user()
    commits = harness.store.git.log(max_entries=2)
    assert commits[0].sha == sha
    assert commits[0].message.startswith("memory: record user PR summary preference")
    assert "cursor 1" in commits[0].message


@pytest.mark.asyncio
async def test_memory_lifecycle_harness_raw_archives_failed_summary(tmp_path):
    harness = MemoryLifecycleHarness(tmp_path)
    session = harness.session()
    harness.add_turn(session, "Remember that I use pytest.", "Noted.")

    summary = await harness.archive_session(
        session,
        summary=RuntimeError("provider unavailable"),
    )

    entries = harness.store.read_unprocessed_history(since_cursor=0)
    assert summary is None
    assert session.last_consolidated == 2
    assert [entry["cursor"] for entry in entries] == [1]
    assert entries[0]["content"].startswith("[RAW] 2 messages")
    assert "Remember that I use pytest." in entries[0]["content"]
