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
    HistoryEditAnchor,
    HistoryEditDisplay,
    HistoryEditError,
    message_digest,
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
    tasks = [task for group in loop._active_tasks.values() for task in group]
    if tasks:
        await asyncio.wait_for(asyncio.gather(*tasks), 10)
    await loop.sessions.state.aclose()


async def edit(loop, index=1):
    value = await loop.sessions.state.read("websocket:editing")
    anchor = HistoryEditAnchor(value.generation, value.revision, index, message_digest(value.messages[index * 2]))
    msg = InboundMessage(channel="websocket", sender_id="webui", chat_id="editing", content="modified question",
                         metadata={"webui": True, "webui_turn_id": "edit-turn", "_wants_stream": True})
    return msg, anchor


def display_replacement(_session, _history):
    return HistoryEditDisplay(1, 0, HistoryFact(HistoryKind.INPUT, {"text": "modified question"}, turn_id="edit-turn"))


async def drain(loop):
    tasks = [task for group in loop._active_tasks.values() for task in group]
    if tasks:
        await asyncio.wait_for(asyncio.gather(*tasks), 10)


async def test_replacement_runs_once_with_only_the_retained_model_context(edited_loop):
    loop = edited_loop
    msg, anchor = await edit(loop)
    accepted = AsyncMock()
    await loop.replace_user_input(msg, anchor, display_replacement, accepted)
    await drain(loop)
    assert accepted.await_count == 1
    assert loop.provider.chat_stream_with_retry.await_count == 1
    prompt = loop.provider.chat_stream_with_retry.await_args.kwargs["messages"]
    assert "question-0" in str(prompt) and "answer-0" in str(prompt)
    assert "question-1" not in str(prompt) and "answer-2" not in str(prompt)
    assert sum("modified question" in str(message.get("content")) for message in prompt) == 1
    source = await loop.sessions.state.read(msg.session_key)
    assert [public_history_message(message)["content"] for message in source.messages] == [
        "question-0", "answer-0", "modified question", "new answer",
    ]
    assert "pending_user_turn" not in source.metadata
    assert "interrupted" not in str(source.messages)


async def test_execution_lane_busy_is_checked_at_admission(edited_loop):
    loop = edited_loop
    msg, anchor = await edit(loop)
    async with loop._get_session_lock(msg.session_key):
        with pytest.raises(HistoryEditError, match="edit_session_busy"):
            await loop.replace_user_input(msg, anchor, display_replacement, AsyncMock())
    assert (await loop.sessions.state.read(msg.session_key)).generation == anchor.generation
    assert not loop.provider.chat_stream_with_retry.called


async def test_cancelling_admission_observer_still_executes_an_accepted_input(edited_loop, monkeypatch):
    loop = edited_loop
    msg, anchor = await edit(loop)
    started, release = threading.Event(), threading.Event()
    original = loop.sessions._store.replace_generation

    def blocked(*args, **kwargs):
        started.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(loop.sessions._store, "replace_generation", blocked)
    task = asyncio.create_task(loop.replace_user_input(msg, anchor, display_replacement, AsyncMock()))
    assert await asyncio.to_thread(started.wait, 5)
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    await drain(loop)
    assert loop.provider.chat_stream_with_retry.await_count == 1
    assert (await loop.sessions.state.read(msg.session_key)).messages[-1]["content"] == "new answer"


async def test_simultaneous_confirmations_only_admit_one_replacement(edited_loop):
    loop = edited_loop
    msg, anchor = await edit(loop)
    results = await asyncio.gather(*(
        loop.replace_user_input(msg, anchor, display_replacement, AsyncMock())
        for _ in range(2)
    ), return_exceptions=True)
    assert sum(isinstance(value, HistoryEditError) for value in results) == 1
    await drain(loop)
    assert loop.provider.chat_stream_with_retry.await_count == 1


@pytest.mark.parametrize("arrival", ["during_reply", "after_reply"])
async def test_discarded_turn_child_result_cannot_enter_the_replacement_prompt(edited_loop, arrival):
    from nanobot.agent.tools.context import RequestContext, request_context
    from nanobot.agent.tools.subagent import SubagentTool

    loop = edited_loop
    source = await loop.sessions.state.read("websocket:editing")
    runtime = await loop.runtime_for_session(source)
    child_started, release_child, main_started = asyncio.Event(), asyncio.Event(), asyncio.Event()
    release_main = asyncio.Event()
    main_prompts = []

    async def controlled_model(**kwargs):
        messages = kwargs["messages"]
        if str(messages[-1].get("content", "")).startswith("task from discarded turn"):
            child_started.set()
            await release_child.wait()
            return LLMResponse(content="OLD_CHILD_RESULT_FROM_DISCARDED_SUFFIX")
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
        await loop._enqueue_session_message(late)
        release_main.set()
        await drain(loop)
        assert len(main_prompts) == 1
        assert "OLD_CHILD_RESULT_FROM_DISCARDED_SUFFIX" not in str(main_prompts)
        assert late.session_generation == source.generation
        assert "OLD_CHILD_RESULT_FROM_DISCARDED_SUFFIX" not in str((await loop.sessions.state.read(source.key)).messages)
    finally:
        release_child.set()
        release_main.set()
        await loop.subagents.close()
        tasks = [task for group in loop._active_tasks.values() for task in group]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
