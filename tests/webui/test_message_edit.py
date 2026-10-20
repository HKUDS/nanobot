"""Same-session edits use the owner commit, not fork creation followed by send."""
from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nanobot.session.history_edit import HistoryEditError
from nanobot.session.manager import Session, SessionManager
from nanobot.session.sqlite_store import SessionConflictError
from nanobot.session.webui_turns import clear_websocket_turns
from nanobot.webui import transcript
from nanobot.webui.forking import (
    create_webui_chat_fork,
    prepare_webui_chat_edit,
    replace_webui_chat_input,
)

KEY = "websocket:edit-chat"


@pytest.fixture
async def editing(tmp_path, monkeypatch):
    display = tmp_path / "display"
    display.mkdir()
    monkeypatch.setattr(transcript, "get_webui_dir", lambda: display)
    manager = SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "sessions")
    session = Session(key=KEY, metadata={
        "title": "Keep title", "title_user_edited": True, "session_handle": "editable",
        "model_preset": "precise", "workspace_scope": {"project_path": str(tmp_path)},
    })
    for index in range(4):
        session.add_message("user", f"question-{index}", webui_turn_id=f"old-{index}")
        session.add_message("assistant", f"answer-{index}")
        transcript.append_transcript_object(KEY, {"event": "user", "chat_id": "edit-chat", "text": f"question-{index}", "turn_id": f"old-{index}"})
        transcript.append_transcript_object(KEY, {"event": "message", "chat_id": "edit-chat", "text": f"answer-{index}", "turn_id": f"old-{index}"})
        transcript.append_transcript_object(KEY, {"event": "turn_end", "chat_id": "edit-chat", "turn_id": f"old-{index}"})
    manager.save(session)
    submissions = []

    async def submit(message, anchor, projection, accepted):
        value = await manager.state.replace_user_input(KEY, anchor, message, projection)
        submissions.append(message)
        await accepted(value)
        return value

    gateway = SimpleNamespace(session_manager=manager, unified_session=False, replace_user_input=submit,
                              transcripts=transcript.WebUITranscriptRecorder(),
                              ingress=SimpleNamespace(validate_text=lambda _: None))
    host = SimpleNamespace(gateway=gateway, announce_webui_history_replacement=AsyncMock())
    clear_websocket_turns("edit-chat")
    yield manager, host, submissions, display
    clear_websocket_turns("edit-chat")
    await manager.state.aclose()


async def prepare(host, index):
    body = transcript.build_webui_thread_response(KEY, limit=1)
    assert body is not None
    # A paged selection may have an unrelated local index; stable turn identity
    # must resolve the actual global canonical and display boundaries.
    return await prepare_webui_chat_edit(host.gateway, {
        "chat_id": "edit-chat", "user_index": 0, "message_id": "live-render-id",
        "turn_id": f"old-{index}", "text": f"question-{index}",
    })


def payload(prepared, text="replacement", turn_id="new-edit"):
    return {"mode": "replace", "chat_id": "edit-chat", "text": text,
            "turn_id": turn_id, "anchor": prepared["anchor"]}


@pytest.mark.parametrize("index", [0, 2, 3])
async def test_edit_keeps_identity_prefix_and_one_new_input(editing, index):
    manager, host, submissions, display = editing
    before = await manager.state.read(KEY)
    stale_draft = await manager.state.get(KEY)
    old_metadata = deepcopy(before.metadata)
    prepared = await prepare(host, index)
    assert prepared["anchor"]["user_index"] == index
    assert prepared["anchor"]["transcript_user_index"] == index
    result = await replace_webui_chat_input(host, payload(prepared))
    assert result == {"accepted": True, "turn_id": "new-edit"}
    after = await manager.state.read(KEY)
    assert after.key == before.key and after.created_at == before.created_at
    for name, value in old_metadata.items():
        assert after.metadata[name] == value
    assert after.generation != before.generation
    assert after.messages[:-1] == before.messages[:index * 2]
    assert after.messages[-1]["content"] == "replacement"
    assert after.metadata["pending_user_turn"] is True
    rows = transcript.read_transcript_lines(KEY)
    assert [row["text"] for row in rows if row.get("event") == "user"] == [*[f"question-{i}" for i in range(index)], "replacement"]
    assert len(await manager.state.list_sessions()) == 1
    assert not list(display.glob(".edit-*")) and not list(display.glob("*.edit.json"))
    await replace_webui_chat_input(host, payload(prepared))
    assert len(submissions) == 1
    stale_draft.add_message("assistant", "obsolete suffix")
    with pytest.raises(SessionConflictError):
        await manager.state.finish_turn(stale_draft)
    assert "obsolete suffix" not in str((await manager.state.read(KEY)).messages)


async def test_read_only_prepare_and_cancel_do_not_change_history(editing):
    manager, host, _, _ = editing
    before = await manager.state.read(KEY)
    rows = transcript.read_transcript_lines(KEY)
    await prepare(host, 2)
    after = await manager.state.read(KEY)
    assert (after.generation, after.revision, after.messages, after.metadata) == (before.generation, before.revision, before.messages, before.metadata)
    assert transcript.read_transcript_lines(KEY) == rows


@pytest.mark.parametrize("failure", ["source", "display", "sql", "install"])
async def test_rejection_preserves_the_effective_history(editing, monkeypatch, failure):
    manager, host, submissions, _ = editing
    prepared = await prepare(host, 2)
    if failure == "source":
        await manager.state.update_metadata(KEY, {"title": "Changed elsewhere"})
    if failure == "display":
        transcript.append_transcript_object(KEY, {"event": "message", "text": "another delivery"})
    before = await manager.state.read(KEY)
    rows = transcript.read_transcript_lines(KEY)
    if failure == "sql":
        monkeypatch.setattr(manager._store, "replace_generation", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")))
    if failure == "install":
        monkeypatch.setattr(transcript, "write_transcript_records_to_path", lambda *_args: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises((HistoryEditError, OSError)):
        await replace_webui_chat_input(host, payload(prepared))
    after = await manager.state.read(KEY)
    assert (after.generation, after.revision, after.messages) == (before.generation, before.revision, before.messages)
    assert transcript.read_transcript_lines(KEY) == rows
    assert submissions == []


async def test_discarded_summary_and_provider_continuation_cannot_survive(editing):
    manager, host, _, _ = editing
    source = await manager.state.get(KEY)
    source.commit_summary_checkpoint("discarded summary", insert_at=6, last_active=source.updated_at)
    from nanobot.providers.base import ProviderConversationState
    source.provider_state = ProviderConversationState(
        kind="openai_responses", provider="openai:test", model="fixture", version=1,
        payload={"response_id": "discarded-suffix"},
    )
    await manager.state.prepare_input(source)
    prepared = await prepare(host, 1)
    await replace_webui_chat_input(host, payload(prepared))
    value = await manager.state.read(KEY)
    assert value.last_archived == 0
    assert "_last_summary" not in value.metadata
    assert value.provider_state is None
    assert "discarded summary" not in str(value.get_history())


@pytest.mark.parametrize(("extra", "code"), [
    ({"media": ["image.png"]}, "edit_attachments_unsupported"),
    ({"cli_apps": [{"name": "app"}]}, "edit_mentions_unsupported"),
    ({"mcp_presets": [{"name": "mcp"}]}, "edit_mentions_unsupported"),
    ({"session_mentions": [{"name": "session"}]}, "edit_mentions_unsupported"),
    ({"_command": True}, "edit_special_message"),
    ({"_runtime_context": {"sources": ["session_mentions"]}}, "edit_mentions_unsupported"),
    ({"_runtime_context": {"sources": ["cli_apps"]}}, "edit_mentions_unsupported"),
    ({"_runtime_context": {"sources": ["session_message"]}}, "edit_special_message"),
])
async def test_unsupported_metadata_is_explicitly_rejected(editing, extra, code):
    manager, host, _, _ = editing
    source = await manager.state.get(KEY)
    source.messages[2].update(extra)
    await manager.state.prepare_input(source)
    with pytest.raises(HistoryEditError, match=code):
        await prepare(host, 1)


@pytest.mark.parametrize("text", ["/new", "! rm anything", "use @editable", "> [!QUOTE]\n> quote\n\nreply"])
async def test_edit_never_dispatches_control_or_context_syntax(editing, text):
    manager, host, submissions, _ = editing
    prepared = await prepare(host, 1)
    before = await manager.state.read(KEY)
    with pytest.raises(HistoryEditError):
        await replace_webui_chat_input(host, payload(prepared, text))
    assert (await manager.state.read(KEY)).messages == before.messages
    assert not submissions


async def test_new_fork_still_creates_distinct_identity_and_preserves_source(editing):
    manager, _, _, _ = editing
    source = await manager.state.read(KEY)
    fork_id, fork_key = await create_webui_chat_fork(manager, source_chat_id="edit-chat", before_user_index=2)
    target = await manager.state.read(fork_key)
    assert fork_id != "edit-chat" and target.key != source.key
    assert target.messages == source.messages[:4]
    assert "session_handle" not in target.metadata and "title" not in target.metadata
    assert (await manager.state.read(KEY)).messages == source.messages
    assert len(await manager.state.list_sessions()) == 2


async def test_tampered_display_position_cannot_truncate_a_different_message(editing):
    manager, host, submissions, _ = editing
    before = await manager.state.read(KEY)
    rows = transcript.read_transcript_lines(KEY)
    prepared = await prepare(host, 1)
    prepared["anchor"]["transcript_user_index"] = 2
    with pytest.raises(HistoryEditError, match="edit_source_changed"):
        await replace_webui_chat_input(host, payload(prepared))
    assert (await manager.state.read(KEY)).messages == before.messages
    assert transcript.read_transcript_lines(KEY) == rows
    assert not submissions


async def test_late_old_generation_stream_completion_cannot_reappend_discarded_suffix(editing):
    from unittest.mock import MagicMock

    from nanobot.bus.queue import MessageBus
    from nanobot.channels.websocket.runtime import WebSocketChannel, WebSocketConfig
    from nanobot.webui.gateway_services import build_gateway_services

    manager, host, _, display = editing
    source = await manager.state.read(KEY)
    prepared = await prepare(host, 1)
    await replace_webui_chat_input(host, payload(prepared))
    config = WebSocketConfig(enabled=True, allow_from=["*"], websocket_requires_token=False)
    bus = MagicMock(spec=MessageBus)
    gateway = build_gateway_services(
        config=config, bus=bus, session_manager=manager, static_dist_path=None,
        workspace_path=display, default_restrict_to_workspace=False,
        runtime_model_name=None, runtime_surface="tui", runtime_capabilities_overrides=None,
    )
    channel = WebSocketChannel(config, bus, gateway=gateway)
    rows = transcript.read_transcript_lines(KEY)
    event = {"event": "stream_end", "text": "discarded late completion"}
    persisted = await channel._persist_turn_stream_event(
        "edit-chat", event, completed_text="discarded late completion", phase="answer",
        metadata={"webui": True, "webui_turn_id": "old-3", "_webui_history_generation": source.generation},
    )
    assert persisted is False
    assert event["history_generation"] == source.generation
    assert transcript.read_transcript_lines(KEY) == rows


async def test_new_fork_and_replace_share_the_source_owner_boundary(editing, monkeypatch):
    import asyncio
    import threading

    from nanobot.webui import forking

    manager, host, _, _ = editing
    source = await manager.state.read(KEY)
    prepared = await prepare(host, 1)
    started, release = threading.Event(), threading.Event()
    original = forking.fork_transcript_before_user_index

    def blocked(*args):
        started.set()
        assert release.wait(5)
        return original(*args)

    monkeypatch.setattr(forking, "fork_transcript_before_user_index", blocked)
    fork_task = asyncio.create_task(create_webui_chat_fork(manager, source_chat_id="edit-chat", before_user_index=2))
    assert await asyncio.to_thread(started.wait, 5)
    edit_task = asyncio.create_task(replace_webui_chat_input(host, payload(prepared)))
    release.set()
    _, fork_key = await fork_task
    await edit_task
    target = await manager.state.read(fork_key)
    assert target.messages == source.messages[:4]
    assert [row["text"] for row in transcript.read_transcript_lines(fork_key) if row.get("event") == "user"] == ["question-0", "question-1"]
    assert (await manager.state.read(KEY)).messages[-1]["content"] == "replacement"


async def test_edit_does_not_schedule_a_new_title_for_an_untitled_session(editing):
    from nanobot.session.webui_turns import maybe_generate_webui_title_after_turn

    manager, host, submissions, _ = editing
    await manager.state.update_metadata(KEY, {}, remove=("title", "title_user_edited"))
    prepared = await prepare(host, 1)
    await replace_webui_chat_input(host, payload(prepared))
    provider = SimpleNamespace(chat_stream_with_retry=AsyncMock())
    generated = await maybe_generate_webui_title_after_turn(
        channel="websocket", chat_id="edit-chat", metadata=submissions[0].metadata,
        sessions=manager, session_key=KEY, provider=provider, model="fixture",
    )
    assert generated is False
    provider.chat_stream_with_retry.assert_not_awaited()
    assert "title" not in (await manager.state.read(KEY)).metadata
