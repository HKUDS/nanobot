import asyncio
import sqlite3
import threading

import pytest

from nanobot.bus.events import InboundMessage
from nanobot.session.manager import SessionManager
from nanobot.session.sqlite_store import SessionConflictError


async def test_append_does_not_resubmit_committed_rows(tmp_path):
    manager = SessionManager(tmp_path)
    state = manager.state
    draft = await state.import_messages("chat:a", [
        {"role": "user", "content": str(i)} for i in range(100)
    ])
    with sqlite3.connect(manager._store.path) as db:
        db.execute("""CREATE TRIGGER reject_prefix BEFORE INSERT ON messages
                      WHEN NEW.position < 100 BEGIN SELECT RAISE(ABORT, 'prefix'); END""")
    draft.add_message("user", "new input")
    await state.prepare_input(draft)
    draft.add_message("assistant", "new answer")
    await state.finish_turn(draft)
    stored = manager.read_session_snapshot(draft.key)
    assert [m["content"] for m in stored.messages] == [str(i) for i in range(100)] + ["new input", "new answer"]
    await state.aclose()


async def test_metadata_checkpoint_and_followups_do_not_read_history(tmp_path):
    manager = SessionManager(tmp_path)
    state = manager.state
    draft = await state.import_messages("websocket:a", [
        {"role": "user", "content": str(i)} for i in range(100)
    ])

    def deny_history(action, table, *_args):
        return sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_READ and table == "messages" else sqlite3.SQLITE_OK

    def protect():
        with manager._store.transaction() as db:
            db.set_authorizer(deny_history)

    await state._execute(draft.key, protect)
    await state.update_metadata(draft.key, {"title": "new"})
    await state.checkpoint_view(draft, {"step": 1})
    before_followup = manager.read_session_snapshot(draft.key).updated_at
    identifier = await state.queue_followup(draft.key, InboundMessage(
        channel="websocket", sender_id="u", chat_id="a", content="follow-up",
    ))
    assert identifier
    assert manager.read_session_snapshot(draft.key).updated_at > before_followup
    await state.acknowledge_followups(draft.key, [identifier])
    await state.aclose()
    stored = manager.read_session_snapshot(draft.key)
    assert len(stored.messages) == 100
    assert stored.metadata["title"] == "new"
    assert stored.metadata["runtime_checkpoint"] == {"step": 1}
    assert not stored.metadata.get("pending_user_followups")


@pytest.mark.parametrize("transient", [False, True])
async def test_nested_draft_edits_and_failed_commits_remain_private(tmp_path, transient):
    manager = SessionManager(tmp_path)
    state = manager.state
    draft = (
        await state.register_transient("chat:a")
        if transient
        else await state.get("chat:a")
    )
    draft.messages.append({"role": "user", "content": [{"type": "text", "text": "original"}]})
    await state.prepare_input(draft)
    peer = await state.get(draft.key)
    draft.messages[0]["content"][0]["text"] = "edited"
    assert state.peek(draft.key).messages[0]["content"][0]["text"] == "original"
    await state.finish_turn(draft)
    assert peer.messages[0]["content"][0]["text"] == "original"
    peer.add_message("assistant", "stale append")
    with pytest.raises(SessionConflictError):
        await state.finish_turn(peer)
    draft.messages[0]["content"][0]["text"] = "unsaved after commit"
    assert (await state.get(draft.key)).messages[0]["content"][0]["text"] == "edited"
    await state.aclose()


async def test_import_and_fork_returns_do_not_alias_committed_records(tmp_path):
    state = SessionManager(tmp_path).state
    source = await state.import_messages("chat:a", [
        {"role": "user", "content": [{"type": "text", "text": "original"}]},
        {"role": "user", "content": "next"},
    ])
    fork = await state.fork(source.key, "chat:b", 1)
    source.messages[0]["content"][0]["text"] = "import edit"
    fork.messages[0]["content"][0]["text"] = "fork edit"
    for key in (source.key, fork.key):
        assert (await state.get(key)).messages[0]["content"][0]["text"] == "original"
    await state.aclose()


async def test_external_append_merges_and_external_edit_conflicts(tmp_path):
    manager = SessionManager(tmp_path)
    state = manager.state
    draft = await state.import_messages("chat:a", [{"role": "user", "content": "first"}])
    other = SessionManager(tmp_path)
    external = other.get_or_create(draft.key)
    external.add_message("assistant", "external")
    other.save(external)
    draft.add_message("assistant", "local")
    await state.finish_turn(draft)
    assert [m["content"] for m in draft.messages] == ["first", "external", "local"]
    external = other.get_or_create(draft.key)
    external.messages[0]["content"] = "replaced"
    other.save(external)
    await state.update_metadata(draft.key, {"title": "new"})
    draft.add_message("assistant", "stale")
    with pytest.raises(SessionConflictError):
        await state.finish_turn(draft)
    assert (await state.get(draft.key)).messages[0]["content"] == "replaced"
    await state.aclose()


async def test_rejected_write_does_not_change_cached_snapshot(tmp_path):
    manager = SessionManager(tmp_path)
    state = manager.state
    draft = await state.import_messages("chat:a", [{"role": "user", "content": "first"}])
    with sqlite3.connect(manager._store.path) as db:
        db.execute("""CREATE TRIGGER reject_append BEFORE INSERT ON messages
                      WHEN NEW.position > 0 BEGIN SELECT RAISE(ABORT, 'injected'); END""")
    draft.add_message("assistant", "rejected")
    draft.metadata["title"] = "rejected"
    with pytest.raises(sqlite3.IntegrityError, match="injected"):
        await state.finish_turn(draft)
    cached = state.peek(draft.key)
    assert len(cached.messages) == 1
    assert "title" not in cached.metadata
    assert manager.read_session_snapshot(draft.key).messages == cached.messages
    await state.aclose()


async def test_truncation_and_summary_keep_storage_and_cache_in_sync(tmp_path):
    manager = SessionManager(tmp_path)
    state = manager.state
    draft = await state.import_messages("chat:a", [
        {"role": "user", "content": str(i)} for i in range(5)
    ])
    draft.messages = draft.messages[:3]
    await state.finish_turn(draft)
    await state.commit_summary(draft, "summary", archive_end=2)
    current = await state.get(draft.key)
    await state.update_metadata(draft.key, {"title": "after summary"})
    stored = manager.read_session_snapshot(draft.key)
    assert len(stored.messages) == 4
    assert stored.last_archived == current.last_archived == 2
    assert stored.messages == current.messages == state.peek(draft.key).messages
    await state.aclose()


@pytest.mark.parametrize("transient", [False, True])
async def test_metadata_callback_result_is_detached(tmp_path, transient):
    state = SessionManager(tmp_path).state
    if transient:
        await state.register_transient("chat:a")
    else:
        await state.get("chat:a")
    shared = {"nested": ["saved"]}

    def change(metadata):
        metadata["custom"] = shared
        return shared

    result, metadata = await state.mutate_metadata("chat:a", change)
    result["nested"].append("result mutation")
    metadata["custom"]["nested"].append("metadata mutation")
    shared["nested"].append("callback mutation")
    assert state.peek("chat:a").metadata["custom"] == {"nested": ["saved"]}
    assert (await state.get("chat:a")).metadata["custom"] == {"nested": ["saved"]}
    await state.aclose()


async def test_owner_reuses_worker_connections_and_closes_them_after_drain(tmp_path, monkeypatch):
    manager = SessionManager(tmp_path)
    connections = []
    closed = []
    original_connect = sqlite3.connect

    class TrackedConnection(sqlite3.Connection):
        def execute(self, *args, **kwargs):
            assert threading.get_ident() == self.owner_thread
            return super().execute(*args, **kwargs)

        def close(self):
            closed.append((id(self), threading.get_ident()))
            return super().close()

    def connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs, factory=TrackedConnection)
        connection.owner_thread = threading.get_ident()
        connections.append((id(connection), threading.get_ident()))
        return connection

    monkeypatch.setattr(sqlite3, "connect", connect)
    state = manager.state
    await state.get("chat:a")
    await state.update_metadata("chat:a", {"title": "new"})
    await state.get("chat:a")
    assert len(connections) == 2
    assert all(thread_id != threading.get_ident() for _, thread_id in connections)
    assert closed == []
    await asyncio.gather(state.aclose(), state.aclose())
    assert {identifier for identifier, _ in closed} == {identifier for identifier, _ in connections}
    assert len(closed) == len(connections)
    assert all(thread_id != threading.get_ident() for _, thread_id in closed)


async def test_history_replay_ack_is_atomic_and_preserves_newer_deliveries(tmp_path):
    from nanobot.providers.base import ProviderConversationState
    from nanobot.session.manager import project_history_messages

    manager = SessionManager(tmp_path)
    state = manager.state
    draft = await state.import_messages("chat:replay", [{"role": "user", "content": "$25 quote"}])
    consumed = frozenset(batch.id for batch in draft.pending_history_replay)
    draft.provider_state = ProviderConversationState(
        kind="fixture", provider="fixture", model="fixture", version=1, payload={},
        pending_messages=project_history_messages(draft.messages),
    )
    draft.consumed_history_replay_ids = consumed
    draft.add_message("user", "Current price?")
    await state.record_delivery(
        draft.key, "newer notification", {"_channel_delivery": True},
        expected_generation=draft.generation,
    )
    queued = (await state.read(draft.key)).pending_history_replay
    assert len(queued) == 2
    with sqlite3.connect(manager._store.path) as db:
        db.execute("""CREATE TRIGGER reject_replay_input BEFORE INSERT ON messages
                      WHEN NEW.position >= 2 BEGIN SELECT RAISE(ABORT, 'input rejected'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="input rejected"):
        await state.prepare_input(draft)
    unchanged = await state.read(draft.key)
    assert unchanged.pending_history_replay == queued
    assert unchanged.provider_state is None
    assert [message["content"] for message in unchanged.messages] == ["$25 quote", "newer notification"]
    with sqlite3.connect(manager._store.path) as db:
        db.execute("DROP TRIGGER reject_replay_input")
    await state.prepare_input(draft)
    assert [batch.id for batch in draft.pending_history_replay] == [queued[-1].id]
    assert draft.provider_state.pending_messages == [{"role": "user", "content": "$25 quote"}]
    await state.checkpoint_view(draft, {"step": 1})
    draft.add_message("assistant", "$50")
    await state.finish_turn(draft)
    assert draft.pending_history_replay == [queued[-1]]
    await state.aclose()

    restarted = SessionManager(tmp_path).state
    try:
        restored = await restarted.read(draft.key)
        assert restored.pending_history_replay == [queued[-1]]
        forked = await restarted.fork(draft.key, "chat:fork", 1)
        assert forked.pending_history_replay == []
        await restarted.reset(draft.key)
        assert (await restarted.read(draft.key)).pending_history_replay == []
        with pytest.raises(SessionConflictError, match="reset"):
            await restarted.prepare_input(draft)
    finally:
        await restarted.aclose()
