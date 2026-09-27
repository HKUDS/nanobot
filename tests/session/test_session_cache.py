"""Detached views and transient session lifetime."""

import pytest

from nanobot.session.manager import SessionManager
from nanobot.session.sqlite_store import SessionConflictError


async def test_committed_view_cache_is_bounded(tmp_path):
    state = SessionManager(tmp_path).state
    for i in range(140):
        await state.update_metadata(str(i), {"title": str(i)})
    assert len(state._snapshots) <= 128
    assert state.peek("0") is None
    assert (await state.get("0")).metadata["title"] == "0"
    await state.aclose()


async def test_cached_views_are_detached(tmp_path):
    state = SessionManager(tmp_path).state
    await state.update_metadata("chat:a", {"title": "saved"})
    cached = state.peek("chat:a")
    cached.metadata["title"] = "unsaved"
    assert state.peek("chat:a").metadata["title"] == "saved"
    await state.aclose()


async def test_transient_session_never_reaches_storage(tmp_path):
    manager = SessionManager(tmp_path)
    state = manager.state
    draft = state.register_transient("temporary:a", disabled_tools=frozenset({"create_goal"}))
    draft.add_message("user", "private")
    await state.prepare_input(draft)
    draft.add_message("assistant", "answer")
    await state.finish_turn(draft)
    assert len((await state.get(draft.key)).messages) == 2
    assert manager.read_session_snapshot(draft.key) is None
    assert manager.list_sessions() == []
    state.forget_transient(draft.key)
    with pytest.raises(SessionConflictError):
        await state.finish_turn(draft)
    await state.aclose()
