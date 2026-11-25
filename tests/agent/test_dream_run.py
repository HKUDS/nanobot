import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

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
async def test_one_dream_reads_full_pages_and_defers_new_history(tmp_path):
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus
    from nanobot.providers.base import GenerationSettings, LLMResponse, ToolCallRequest

    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.supports_tools = True
    provider.generation = GenerationSettings()
    provider.estimate_prompt_tokens.return_value = (200_000, "test-provider")
    loop = AgentLoop(
        bus=MessageBus(), provider=provider, workspace=tmp_path,
        context_window_tokens=512_000,
    )
    store = loop.context.memory
    markers = ("DREAM_SOUL_MARKER", "DREAM_USER_MARKER", "DREAM_MEMORY_MARKER", "DREAM_AGENTS_MARKER")
    store.write_soul(markers[0])
    store.write_user(markers[1])
    store.write_memory(markers[2])
    (tmp_path / "AGENTS.md").write_text(markers[3], encoding="utf-8")
    store.git.init()
    checkpoints = ["Project knowledge. " * 3000 + f"TAIL-{i}" for i in range(3)]
    for checkpoint in checkpoints:
        store.append_history(checkpoint)
    for index in range(23):
        store.append_history(f"queued record {index}")
    model_calls = 0
    read_records = []

    def call(name, **arguments):
        return LLMResponse(content=None, tool_calls=[ToolCallRequest(
            id=f"call-{model_calls}", name=name, arguments=arguments,
        )], finish_reason="tool_calls")

    def collect_read(messages):
        text = next(message["content"] for message in reversed(messages) if message["role"] == "tool")
        for line in text.splitlines():
            number, separator, encoded = line.partition("| ")
            if separator and number.isdigit():
                read_records.append(json.loads(encoded))

    async def chat(**kwargs):
        nonlocal model_calls
        model_calls += 1
        messages = kwargs["messages"]
        assert store.get_last_dream_cursor() == 0
        if model_calls == 1:
            task = messages[-1]["content"]
            assert str(store.history_file.resolve()) in task
            assert "Read lines 1-26" in task and "0 < cursor <= 26" in task
            request = "\n".join(str(message.get("content", "")) for message in messages)
            for marker in markers:
                assert marker in messages[0]["content"] and request.count(marker) == 1
            assert "TAIL-0" not in request and "queued record 22" not in request
            store.append_history("Arrived while Dream was running")
            return call("read_file", path=str(store.history_file), offset=1, limit=26)
        if model_calls == 2:
            collect_read(messages)
            assert [entry["content"] for entry in read_records] == checkpoints[:2]
            return call("read_file", path=str(store.history_file), offset=3, limit=24)
        if model_calls == 3:
            collect_read(messages)
            assert [entry["cursor"] for entry in read_records] == list(range(1, 27))
            assert read_records[2]["content"] == checkpoints[2]
            assert read_records[-1]["content"] == "queued record 22"
            return call("write_file", path=str(store.wiki_dir / "index.md"), content="# Wiki\nCurrent knowledge")
        return LLMResponse(content="History range consolidated.")

    provider.chat_stream_with_retry = AsyncMock(side_effect=chat)
    try:
        result = await run_dream(loop, commit_prefix="dream: periodic memory consolidation")
        assert result.error is None
        assert model_calls == 4
        assert store.get_last_dream_cursor() == 26
        assert result.commit_sha
        commit, diff = store.git.show_commit_diff(result.commit_sha)
        assert commit.message.startswith("dream: periodic memory consolidation\n\n")
        assert "memory/wiki/index.md" in diff and "Current knowledge" in commit.message
        assert ".dream_cursor" not in commit.message
        assert (store.wiki_dir / "index.md").read_text(encoding="utf-8") == "# Wiki\nCurrent knowledge"
        sessions = await loop.sessions.state.list_sessions()
        assert len(sessions) == 1
        assert loop.sessions.read_session_snapshot(sessions[0]["key"]) is not None
        next_prompt, next_cursor = store.build_dream_prompt()
        assert "Read lines 27-27" in next_prompt
        assert next_cursor == 27

        provider.chat_stream_with_retry = AsyncMock(return_value=LLMResponse(content="", finish_reason="length"))
        retry = await run_dream(loop, commit_prefix="dream: manual run")
        assert retry.error == "stop_reason: empty_final_response"
        assert store.get_last_dream_cursor() == 26
    finally:
        await loop.sessions.state.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["length", "exception"])
async def test_failed_task_keeps_entire_range_pending_after_restart(tmp_path, failure):
    store = MemoryStore(tmp_path, max_history_entries=5)
    store.git.init()
    for index in range(25):
        store.append_history(f"record-{index:02d}")

    async def process(prompt, **kwargs):
        assert "Read lines 1-25" in prompt
        store.write_memory("# Memory\nPartial update")
        if failure == "exception":
            raise RuntimeError("Provider unavailable")
        return response(failure)

    result = await run_dream(loop_for(store, process), commit_prefix="dream: manual run")
    assert result.error
    assert store.get_last_dream_cursor() == 0
    assert len(store.read_unprocessed_history(0)) == 25
    assert result.commit_sha
    assert store.read_memory() == "# Memory\nPartial update"

    restarted = MemoryStore(tmp_path)
    resumed = []

    async def finish(prompt, **kwargs):
        resumed.append(prompt)
        return response()

    result = await run_dream(loop_for(restarted, finish), commit_prefix="dream: manual run")
    assert result.error is None
    assert restarted.get_last_dream_cursor() == 25
    assert len(resumed) == 1
    assert "Read lines 1-25" in resumed[0]


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
    assert all(outcome.error is None for outcome in outcomes)
    assert [outcome.had_input for outcome in outcomes] == [True, False]
    assert store.get_last_dream_cursor() == 1
