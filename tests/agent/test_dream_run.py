import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nanobot.agent.dream import run_dream
from nanobot.agent.memory import MemoryStore
from nanobot.bus.events import OutboundMessage


def response(reason="completed"):
    return OutboundMessage(
        channel="cli", chat_id="dream", content="done", metadata={"_stop_reason": reason},
    )


def loop_for(store, process):
    return SimpleNamespace(
        context=SimpleNamespace(memory=store),
        sessions=SimpleNamespace(state=SimpleNamespace(prune_dream_sessions=AsyncMock())),
        dream_runtime=lambda: None,
        process_direct=process,
    )


@pytest.mark.asyncio
async def test_drains_snapshot_with_full_tails_and_defers_new_history(tmp_path):
    store = MemoryStore(tmp_path)
    tail = "[correction] The current deployment is region-west."
    # Beyond the old 1,000-character clip, but fits with 19 short records even
    # when the tokenizer is not ready and batching uses the byte estimate.
    checkpoint = "[durable] Existing project knowledge.\n" * 60 + tail
    store.append_history(checkpoint)
    for index in range(24):
        store.append_history(f"queued record {index}")
    prompts, keys = [], []

    async def process(prompt, **kwargs):
        prompts.append(prompt)
        keys.append(kwargs["session_key"])
        if len(prompts) == 1:
            store.append_history("Arrived while Dream was running")
        return response()

    loop = loop_for(store, process)
    first = await run_dream(loop, commit_prefix="dream: periodic memory consolidation")

    assert first.error is None
    assert first.completed_batches == 2
    assert checkpoint in prompts[0]
    assert tail in prompts[0]
    assert "queued record 23" in prompts[-1]
    assert all("Arrived while Dream" not in prompt for prompt in prompts)
    assert store.get_last_dream_cursor() == 25
    assert len(set(keys)) == len(keys)
    second = await run_dream(loop, commit_prefix="dream: manual run")
    assert second.completed_batches == 1
    assert "Arrived while Dream" in prompts[-1]
    assert store.get_last_dream_cursor() == 26


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["length", "exception"])
async def test_failed_batch_remains_pending_after_restart(tmp_path, failure):
    store = MemoryStore(tmp_path)
    for index in range(25):
        store.append_history(f"record-{index:02d}")
    calls = 0

    async def process(prompt, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            if failure == "exception":
                raise RuntimeError("Provider unavailable")
            return response(failure)
        return response()

    result = await run_dream(loop_for(store, process), commit_prefix="dream: manual run")
    assert result.error
    assert result.completed_batches == 1
    assert store.get_last_dream_cursor() == 20

    restarted = MemoryStore(tmp_path)
    resumed = []

    async def finish(prompt, **kwargs):
        resumed.append(prompt)
        return response()

    result = await run_dream(loop_for(restarted, finish), commit_prefix="dream: manual run")
    assert result.error is None
    assert result.completed_batches == 1
    assert restarted.get_last_dream_cursor() == 25
    assert "record-20" in resumed[0] and "record-24" in resumed[0]
    assert "record-00" not in resumed[0]


@pytest.mark.asyncio
async def test_overlapping_manual_and_periodic_runs_do_not_repeat_history(tmp_path):
    store = MemoryStore(tmp_path)
    store.append_history("One pending record")
    entered, release, second_started = asyncio.Event(), asyncio.Event(), asyncio.Event()
    calls = []

    async def process(prompt, **kwargs):
        calls.append(prompt)
        entered.set()
        await release.wait()
        return response()

    loop = loop_for(store, process)
    first = asyncio.create_task(run_dream(loop, commit_prefix="dream: periodic memory consolidation"))
    await entered.wait()

    async def manual():
        second_started.set()
        return await run_dream(loop, commit_prefix="dream: manual run")

    second = asyncio.create_task(manual())
    try:
        await second_started.wait()
        assert len(calls) == 1
    finally:
        release.set()
        outcomes = await asyncio.gather(first, second)
    assert len(calls) == 1
    assert [outcome.completed_batches for outcome in outcomes] == [1, 0]
    assert not outcomes[1].had_input
    assert store.get_last_dream_cursor() == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("edit", [False, True])
async def test_versions_only_real_content_changes(tmp_path, edit):
    store = MemoryStore(tmp_path)
    store.write_memory("# Memory")
    store.git.init()
    before = store.git.log()
    store.append_history("Research notes")

    async def process(prompt, **kwargs):
        if edit:
            store.write_memory("# Memory\n- Research notes")
        return response()

    result = await run_dream(
        loop_for(store, process), commit_prefix="dream: periodic memory consolidation",
    )
    assert result.error is None
    assert result.changed is edit
    assert store.get_last_dream_cursor() == 1
    if edit:
        assert result.commit_sha
        commit = store.git.log()[0]
        assert commit.message.startswith("dream: periodic memory consolidation\n\n")
        assert "Research notes" in commit.message
    else:
        assert result.commit_sha is None
        assert store.git.log() == before
