"""Dream execution preserves progress and audit behavior for both triggers."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.dream import run_dream
from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus


@pytest.fixture
def dream_loop(tmp_path):
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation.max_tokens = 4096
    loop = AgentLoop(
        bus=MessageBus(), provider=provider, workspace=tmp_path,
        model="test-model", context_window_tokens=128_000,
    )
    store = loop.context.memory
    store.write_memory("Initial memory.\n")
    store.set_last_dream_cursor(0)
    store.git.init()
    store.git.auto_commit("initial")
    store.append_history("[durable] Research notes.")
    return loop


async def _write_memory(tools):
    await tools.execute("read_file", {"path": "memory/MEMORY.md"})
    result = await tools.execute("write_file", {
        "path": "memory/MEMORY.md", "content": "Research notes.\n",
    })
    assert "Successfully wrote" in result


@pytest.mark.parametrize("kind", ["manual", "scheduled"])
@pytest.mark.parametrize("changed", [False, True])
async def test_dream_commit_policy_and_content_summary(dream_loop, monkeypatch, kind, changed):
    loop = dream_loop

    async def process_direct(_prompt, **kwargs):
        if changed:
            await _write_memory(kwargs["tools"])
        return OutboundMessage(
            channel="cli", chat_id="direct", content="Done.",
            metadata={"_stop_reason": "completed"},
        )

    monkeypatch.setattr(loop, "process_direct", process_direct)
    try:
        result = await run_dream(loop, kind=kind)
        assert result.status == "completed"
        assert result.cursor == loop.context.memory.get_last_dream_cursor() == 1
        assert bool(result.content_diff) == changed
        assert bool(result.commit_sha) == (kind == "manual" or changed)
        if result.commit_sha:
            commit, = loop.context.memory.git.log(max_entries=1)
            prefix = (
                "dream: manual run" if kind == "manual"
                else "dream: periodic memory consolidation"
            )
            assert commit.message.startswith(prefix)
            if changed:
                assert "Research notes" in commit.message
    finally:
        await loop.aclose()


@pytest.mark.parametrize("kind", ["manual", "scheduled"])
@pytest.mark.parametrize("failure", ["error", "cancelled"])
async def test_interrupted_dream_commits_partial_edits_without_consuming_history(
    dream_loop, monkeypatch, kind, failure,
):
    loop = dream_loop
    store = loop.context.memory
    edited = asyncio.Event()

    async def process_direct(_prompt, **kwargs):
        await _write_memory(kwargs["tools"])
        edited.set()
        if failure == "error":
            raise RuntimeError("provider unavailable")
        await asyncio.Event().wait()

    monkeypatch.setattr(loop, "process_direct", process_direct)
    task = asyncio.create_task(run_dream(loop, kind=kind))
    try:
        await asyncio.wait_for(edited.wait(), timeout=5)
        if failure == "cancelled":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            result = await asyncio.wait_for(task, timeout=5)
            assert result.status == "failed"
            assert str(result.error) == "provider unavailable"
        assert store.get_last_dream_cursor() == 0
        assert len(store.read_unprocessed_history(0)) == 1
        assert store.read_memory() == "Research notes.\n"
        assert store.dream_content_diff() == ""
        commit, = store.git.log(max_entries=1)
        assert commit.message.startswith("dream:")
        assert store.dream_lock.locked() is False
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await loop.aclose()


async def test_scheduled_preparation_failure_allows_retry(dream_loop, monkeypatch):
    loop = dream_loop
    process = AsyncMock(return_value=OutboundMessage(
        channel="cli", chat_id="direct", content="Done.",
        metadata={"_stop_reason": "completed"},
    ))
    monkeypatch.setattr(loop, "process_direct", process)
    prepare = AsyncMock(side_effect=RuntimeError("MCP unavailable"))
    try:
        failed = await run_dream(loop, kind="scheduled", before_run=prepare)
        assert failed.status == "failed"
        assert str(failed.error) == "MCP unavailable"
        assert loop.context.memory.get_last_dream_cursor() == 0
        process.assert_not_awaited()
        prepare.side_effect = None
        completed = await asyncio.wait_for(
            run_dream(loop, kind="scheduled", before_run=prepare), timeout=5,
        )
        assert completed.status == "completed"
        assert completed.cursor == 1
        prepare.assert_awaited()
        process.assert_awaited_once()
    finally:
        await loop.aclose()
