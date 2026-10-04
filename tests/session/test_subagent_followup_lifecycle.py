"""Focused regression tests for subagent result require_existing_session.

These tests cover the essential contracts:
1. Subagent announcements use require_existing_session=True
2. Deleted parent sessions are not resurrected by late results
3. Persisted-but-uncached parents still accept legitimate results
4. Deletion during loading invalidates the result, even if the key is reused
"""
import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.agent.memory import Consolidator
from nanobot.agent.subagent import SubagentManager
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMResponse
from nanobot.session.manager import Session


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path / "state")


def _loop(tmp_path: Path) -> AgentLoop:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = SimpleNamespace(max_tokens=4096)
    provider.chat_stream_with_retry = AsyncMock(
        return_value=LLMResponse(content="Reviewed", finish_reason="stop")
    )
    return AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
    )


# -- TEST 1: Announcement contract -------------------------------------


@pytest.mark.asyncio
async def test_announcement_uses_require_existing_session(
    tmp_path: Path,
) -> None:
    """Subagent completion messages must set require_existing_session=True.

    Exercises the real SubagentManager._announce_result() path.
    Without the fix, require_existing_session defaults to False.
    """
    bus = MessageBus()
    mgr = SubagentManager(
        workspace=tmp_path,
        bus=bus,
        max_tool_result_chars=16_000,
        consolidator=MagicMock(spec=Consolidator),
    )

    origin = {
        "channel": "telegram",
        "chat_id": "12345",
        "session_key": "telegram:12345",
    }
    await mgr._announce_result(
        task_id="task-1",
        label="test",
        task="do something",
        result="done",
        origin=origin,
        status="ok",
    )

    msg = await bus.consume_inbound()
    assert msg.require_existing_session is True, (
        "Subagent result must set require_existing_session=True "
        "so the AgentLoop guard can reject it for deleted sessions."
    )
    assert msg.session_key == "telegram:12345"


# -- TEST 2: Deleted parent must not be resurrected ---------------------


@pytest.mark.asyncio
async def test_deleted_parent_not_resurrected_by_late_result(
    tmp_path: Path,
) -> None:
    """A late subagent result must not recreate a deleted parent session.

    Uses monkeypatched read_session_metadata with a threading.Event to
    deterministically observe when the guard has processed the deleted
    session lookup — no arbitrary sleep.
    """
    loop = _loop(tmp_path)
    session_key = "telegram:target"

    # Create and persist parent
    session = loop.sessions.get_or_create(session_key)
    session.add_message("user", "hello")
    session.add_message("assistant", "hi")
    loop.sessions.save(session)
    assert loop.sessions.read_session_file(session_key) is not None

    # Delete parent
    assert loop.sessions.delete_session(session_key)
    assert loop.sessions.read_session_file(session_key) is None
    assert loop.sessions.get_cached(session_key) is None

    # Publish subagent result via SubagentManager
    bus = loop.bus
    mgr = SubagentManager(
        workspace=tmp_path,
        bus=bus,
        max_tool_result_chars=16_000,
        consolidator=loop.consolidator,
    )
    origin = {
        "channel": "telegram",
        "chat_id": "target",
        "session_key": session_key,
    }
    await mgr._announce_result(
        task_id="task-1",
        label="test",
        task="do something",
        result="subagent answer",
        origin=origin,
        status="ok",
    )

    # Instrument read_session_metadata to observe the guard's lookup.
    # The guard calls read_session_metadata via asyncio.to_thread, so
    # the instrumented version runs in a thread pool worker.
    guard_observed = threading.Event()
    original_rsm = loop.sessions.read_session_metadata

    def instrumented_rsm(key: str):
        result = original_rsm(key)
        if key == session_key:
            guard_observed.set()
        return result

    loop.sessions.read_session_metadata = instrumented_rsm  # type: ignore[assignment]

    # Process through AgentLoop
    run_task = asyncio.create_task(loop.run())
    try:
        # Wait in a thread so the asyncio event loop stays free to run.
        observed = await asyncio.to_thread(guard_observed.wait, 10)
        assert observed, (
            "Guard never observed — read_session_metadata was not called"
        )
    finally:
        loop.stop()
        await asyncio.wait_for(run_task, timeout=5)
        loop.sessions.read_session_metadata = original_rsm  # type: ignore[assignment]

    # Provider must NOT have been invoked for the deleted session
    loop.provider.chat_stream_with_retry.assert_not_awaited()  # type: ignore[union-attr]

    # Parent must remain deleted
    assert loop.sessions.read_session_file(session_key) is None, (
        "Deleted parent session recreated on disk by late subagent result."
    )
    assert loop.sessions.get_cached(session_key) is None, (
        "Deleted parent session recreated in cache by late subagent result."
    )


# -- TEST 3: Persisted-but-uncached parent still works ------------------


@pytest.mark.asyncio
async def test_persisted_uncached_parent_accepts_result(
    tmp_path: Path,
) -> None:
    """A persisted-but-uncached parent must still accept subagent results.

    This proves require_existing_session != require_cached_session.
    The #5483 guard checks persisted existence on disk, not just cache.
    """
    loop = _loop(tmp_path)
    session_key = "telegram:target"

    # Create and persist parent
    session = loop.sessions.get_or_create(session_key)
    session.add_message("user", "hello")
    loop.sessions.save(session)
    assert loop.sessions.read_session_file(session_key) is not None

    # Evict from cache only — durable state remains
    loop.sessions.invalidate(session_key)
    assert loop.sessions.get_cached(session_key) is None
    assert loop.sessions.read_session_file(session_key) is not None, (
        "Durable session must survive cache invalidation"
    )

    # Publish real subagent result
    bus = loop.bus
    mgr = SubagentManager(
        workspace=tmp_path,
        bus=bus,
        max_tool_result_chars=16_000,
        consolidator=loop.consolidator,
    )
    origin = {
        "channel": "telegram",
        "chat_id": "target",
        "session_key": session_key,
    }
    await mgr._announce_result(
        task_id="task-1",
        label="test",
        task="do something",
        result="subagent answer",
        origin=origin,
        status="ok",
    )

    # Process through AgentLoop — should accept the result
    run_task = asyncio.create_task(loop.run())
    try:
        await asyncio.wait_for(loop.bus.consume_outbound(), timeout=10)
    finally:
        loop.stop()
        await asyncio.wait_for(run_task, timeout=5)

    # Provider must have been invoked for the legitimate path
    loop.provider.chat_stream_with_retry.assert_awaited()  # type: ignore[union-attr]

    # Inspect the persisted durable record.
    # _persist_subagent_followup stores injected_event and subagent_task_id
    # as top-level message keys, not inside metadata.
    loop.sessions.invalidate(session_key)
    reloaded = loop.sessions.get_or_create(session_key)

    subagent_msgs = [
        m for m in reloaded.messages
        if m.get("injected_event") == "subagent_result"
    ]
    assert len(subagent_msgs) == 1, (
        f"Expected exactly 1 subagent result message, found {len(subagent_msgs)}. "
        f"Roles: {[m.get('role') for m in reloaded.messages]}"
    )

    sr = subagent_msgs[0]
    assert sr["role"] == "assistant", (
        f"Subagent result role should be 'assistant', got '{sr['role']}'"
    )
    assert sr["injected_event"] == "subagent_result"
    assert sr["subagent_task_id"] == "task-1"
    assert "subagent answer" in sr["content"], (
        f"Subagent result content missing expected text. Got: {sr['content'][:200]}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("recreate", [False, True])
async def test_parent_deleted_during_load_rejects_late_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    recreate: bool,
) -> None:
    loop = _loop(tmp_path)
    key = "websocket:target"
    parent = loop.sessions.get_or_create(key)
    parent.add_message("user", "old parent")
    loop.sessions.save(parent)
    loop.sessions.invalidate(key)

    loaded = threading.Event()
    release = threading.Event()
    original_load = loop.sessions._load

    def blocked_load(session_key: str) -> Session | None:
        session = original_load(session_key)
        if session_key == key:
            assert session is not None
            # The store's file lock is released; cache registration has not run.
            loaded.set()
            if not release.wait(timeout=10):
                raise TimeoutError("test release was never signalled")
        return session

    monkeypatch.setattr(loop.sessions, "_load", blocked_load)
    await loop.subagents._announce_result(
        task_id="task-race",
        label="test",
        task="test",
        result="late result",
        origin={"channel": "websocket", "chat_id": "target", "session_key": key},
        status="ok",
    )
    replacement: Session | None = None
    run_task = asyncio.create_task(loop.run())
    try:
        assert await asyncio.to_thread(loaded.wait, 10)
        assert loop.sessions.delete_session(key)
        assert loop.sessions.get_cached(key) is None
        assert loop.sessions.read_session_file(key) is None
        if recreate:
            # Restore normal loading for the new session while the old load waits.
            monkeypatch.setattr(loop.sessions, "_load", original_load)
            replacement = loop.sessions.get_or_create(key)
            replacement.add_message("user", "new parent")
            loop.sessions.save(replacement)
        release.set()
        response = await asyncio.wait_for(loop.bus.consume_outbound(), timeout=10)

        assert response.content == "Sorry, I encountered an error."
        loop.provider.chat_stream_with_retry.assert_not_awaited()  # type: ignore[union-attr]
        assert loop.sessions.get_cached(key) is replacement
        record = loop.sessions.read_session_file(key)
        if replacement is None:
            assert record is None
        else:
            assert record is not None
            assert record["messages"] == replacement.messages
            assert len(replacement.messages) == 1
            assert replacement.messages[0]["role"] == "user"
            assert replacement.messages[0]["content"] == "new parent"
    finally:
        release.set()
        monkeypatch.setattr(loop.sessions, "_load", original_load)
        loop.stop()
        await asyncio.wait_for(run_task, timeout=5)
