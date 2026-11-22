from __future__ import annotations

import asyncio
import threading
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import GenerationSettings, LLMResponse
from nanobot.runtime_context import public_history_message
from nanobot.session.display_history import HistoryFact, HistoryKind
from nanobot.session.history_edit import (
    HistoryEditError,
    HistoryEditSource,
    HistoryEditTarget,
)
from nanobot.session.manager import SessionManager


@pytest.fixture
async def edited_loop(tmp_path):
    provider = MagicMock(aclose=AsyncMock())
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings()
    provider.chat_stream_with_retry = AsyncMock(return_value=LLMResponse(content="new answer", usage=None))
    workspace = tmp_path / "workspace"
    manager = SessionManager(workspace, sessions_root=tmp_path / "sessions")
    loop = AgentLoop(bus=MessageBus(), provider=provider, workspace=workspace, model="test-model", cron_service=MagicMock(), session_manager=manager)
    value = await loop.sessions.state.get("websocket:editing")
    for index in range(3):
        value.add_message("user", f"question-{index}", webui_turn_id=f"old-{index}")
        value.add_message("assistant", f"answer-{index}")
    await loop.sessions.state.prepare_input(value)
    facts = [fact for index in range(3) for fact in (
        HistoryFact(HistoryKind.INPUT, {"text": f"question-{index}"}, turn_id=f"old-{index}"),
        HistoryFact(HistoryKind.ANSWER, {"text": f"answer-{index}"}, turn_id=f"old-{index}"),
        HistoryFact(HistoryKind.COMPLETION, turn_id=f"old-{index}"),
    )]
    await manager.state.append_history(value.key, facts, expected_generation=value.generation)
    yield loop
    await loop.aclose()


async def edit(loop):
    value = await loop.sessions.state.read("websocket:editing")
    anchor = HistoryEditSource(str(value.revision), "user:old-1")
    msg = InboundMessage(channel="websocket", sender_id="webui", chat_id="editing", content="modified question",
                         metadata={"webui": True, "webui_turn_id": "edit-turn", "_wants_stream": True})
    return msg, anchor


def display_replacement(_session, _history):
    return HistoryEditTarget(2, 1, 0, HistoryFact(HistoryKind.INPUT, {"text": "modified question"}, turn_id="edit-turn"))


async def drain(loop):
    tasks = [task for group in loop._active_tasks.values() for task in group]
    if tasks:
        await asyncio.wait_for(asyncio.gather(*tasks), 10)


async def test_concurrent_edit_retry_runs_once_with_only_the_retained_context(edited_loop):
    loop = edited_loop
    msg, anchor = await edit(loop)
    retry, _ = await edit(loop)
    accepted = AsyncMock()
    await asyncio.gather(
        loop.replace_user_input(msg, anchor, display_replacement, accepted),
        loop.replace_user_input(retry, anchor, display_replacement, accepted),
    )
    await drain(loop)
    accepted.assert_awaited_once()
    loop.provider.chat_stream_with_retry.assert_awaited_once()
    prompt = loop.provider.chat_stream_with_retry.await_args.kwargs["messages"]
    assert "question-0" in str(prompt) and "answer-0" in str(prompt)
    assert "question-1" not in str(prompt) and "answer-2" not in str(prompt)
    assert sum("modified question" in str(message.get("content")) for message in prompt) == 1
    source = await loop.sessions.state.read(msg.session_key)
    assert [public_history_message(message)["content"] for message in source.messages] == [
        "question-0", "answer-0", "modified question", "new answer",
    ]
    assert "pending_user_turn" not in source.metadata


async def test_execution_lane_busy_is_checked_at_admission(edited_loop):
    loop = edited_loop
    msg, anchor = await edit(loop)
    async with loop._get_session_lock(msg.session_key):
        with pytest.raises(HistoryEditError, match="edit_session_busy"):
            await loop.replace_user_input(msg, anchor, display_replacement, AsyncMock())
    loop.provider.chat_stream_with_retry.assert_not_awaited()


async def test_cancelling_admission_observer_still_executes_an_accepted_input(edited_loop):
    loop = edited_loop
    msg, anchor = await edit(loop)
    started, release = threading.Event(), threading.Event()

    def blocked_projection(session, history):
        started.set()
        assert release.wait(5)
        return display_replacement(session, history)

    task = asyncio.create_task(loop.replace_user_input(msg, anchor, blocked_projection, AsyncMock()))
    assert await asyncio.to_thread(started.wait, 5)
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    await drain(loop)
    assert loop.provider.chat_stream_with_retry.await_count == 1
    assert (await loop.sessions.state.read(msg.session_key)).messages[-1]["content"] == "new answer"


async def test_shutdown_joins_committed_edit_before_worker_snapshot(edited_loop, tmp_path):
    loop = edited_loop
    msg, anchor = await edit(loop)
    committed, release = asyncio.Event(), asyncio.Event()

    async def announce(_session):
        committed.set()
        await release.wait()

    loop.preserve_inflight_turns_on_shutdown()
    editing = asyncio.create_task(loop.replace_user_input(msg, anchor, display_replacement, announce))
    async with asyncio.timeout(5):
        await committed.wait()
        closing = asyncio.create_task(loop.aclose())
        try:
            await asyncio.sleep(0)
            assert not closing.done()
        finally:
            release.set()
        await asyncio.gather(editing, closing)
    assert not loop._active_tasks and not loop._pending_queues
    reopened = SessionManager(loop.workspace, sessions_root=tmp_path / "sessions")
    saved = reopened.read_session_snapshot(msg.session_key)
    assert saved is not None
    assert saved.metadata["pending_user_turn"]
    assert saved.messages[-1]["content"] == msg.content


async def test_followup_gets_a_worker_when_the_reserved_edit_is_rejected(edited_loop):
    loop = edited_loop
    msg, anchor = await edit(loop)
    checking, release = threading.Event(), threading.Event()

    def reject_stale_source(_session, _history):
        checking.set()
        assert release.wait(5)
        raise HistoryEditError("edit_source_changed")

    editing = asyncio.create_task(loop.replace_user_input(msg, anchor, reject_stale_source, AsyncMock()))
    followup = InboundMessage(
        channel="websocket", sender_id="webui", chat_id="editing", content="ordinary follow-up",
        metadata={"webui": True, "webui_turn_id": "ordinary-turn", "_wants_stream": True},
    )
    try:
        assert await asyncio.to_thread(checking.wait, 5)
        ordinary = asyncio.create_task(loop._enqueue_session_message(followup))
        await asyncio.sleep(0)  # Let the follow-up reach admission before releasing the edit.
    finally:
        release.set()
    with pytest.raises(HistoryEditError, match="edit_source_changed"):
        await editing
    await asyncio.wait_for(ordinary, 5)
    await drain(loop)
    saved = await loop.sessions.state.read(msg.session_key)
    assert [public_history_message(row)["content"] for row in saved.messages[-2:]] == [
        followup.content, "new answer",
    ]


@pytest.mark.parametrize("arrival", ["during_reply", "after_reply"])
async def test_discarded_turn_child_result_cannot_enter_the_replacement_prompt(edited_loop, arrival):
    from nanobot.agent.tools.context import RequestContext, request_context
    from nanobot.agent.tools.subagent import SubagentTool

    loop = edited_loop
    source = await loop.sessions.state.read("websocket:editing")
    runtime = await loop.runtime_for_session(source)
    child_started, release_child, main_started = asyncio.Event(), asyncio.Event(), asyncio.Event()
    release_main = asyncio.Event()
    child_result = "OLD_CHILD_RESULT_FROM_DISCARDED_SUFFIX"
    main_prompts = []

    async def controlled_model(**kwargs):
        messages = kwargs["messages"]
        if str(messages[-1].get("content", "")).startswith("task from discarded turn"):
            child_started.set()
            await release_child.wait()
            return LLMResponse(content=child_result)
        main_prompts.append(messages)
        main_started.set()
        if arrival == "during_reply":
            await release_main.wait()
        return LLMResponse(content="new answer")

    loop.provider.chat_stream_with_retry.side_effect = controlled_model
    # A background child can outlive the original turn's terminal rendezvous
    # (or its iteration limit). Its result still belongs to that old lifecycle.
    try:
        with request_context(RequestContext(
            channel="websocket", chat_id="editing", session_key=source.key,
            session_generation=source.generation, turn_id="old-2", runtime=runtime,
            can_receive_background_results=True,
        )):
            await SubagentTool(loop.subagents).execute(action="create", task="task from discarded turn")
        await asyncio.wait_for(child_started.wait(), 5)
        msg, anchor = await edit(loop)
        await loop.replace_user_input(msg, anchor, display_replacement, AsyncMock())
        await asyncio.wait_for(main_started.wait(), 5)
        if arrival == "after_reply":
            # The replacement must not join children owned by the discarded turn.
            await drain(loop)
        release_child.set()
        late = await asyncio.wait_for(loop.bus.consume_inbound(), 5)
        assert late.session_generation == source.generation
        assert child_result in late.content
        await loop._enqueue_session_message(late)
        release_main.set()
        await drain(loop)
        assert len(main_prompts) == 1
        assert child_result not in str(main_prompts)
        saved = await loop.sessions.state.read(source.key)
        assert child_result not in str(saved.messages)
    finally:
        release_child.set()
        release_main.set()
