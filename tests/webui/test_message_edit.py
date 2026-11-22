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
    replace_webui_chat_input,
)
from nanobot.webui.history import fact_from_record

KEY = "websocket:edit-chat"


@pytest.fixture
async def editing(tmp_path):
    display = tmp_path / "display"
    display.mkdir()
    manager = SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "sessions")
    session = Session(key=KEY, metadata={
        "title": "Keep title", "title_user_edited": True, "session_handle": "editable",
        "model_preset": "precise", "workspace_scope": {"project_path": str(tmp_path)},
    })
    manager.save(session)
    for index in range(4):
        # Mix pre-ID history and current WebUI input identities in one topic.
        identity = {"input_id": f"user:old-{index}"} if index else {}
        session.add_message("user", f"question-{index}", webui_turn_id=f"old-{index}", **identity)
        session.add_message("assistant", f"answer-{index}")
        transcript.append_transcript_object(KEY, {"event": "user", "chat_id": "edit-chat", "text": f"question-{index}",
                                                "turn_id": f"old-{index}", **identity}, sessions=manager)
        transcript.append_transcript_object(KEY, {"event": "message", "chat_id": "edit-chat", "text": f"answer-{index}", "turn_id": f"old-{index}"}, sessions=manager)
        transcript.append_transcript_object(KEY, {"event": "turn_end", "chat_id": "edit-chat", "turn_id": f"old-{index}"}, sessions=manager)
    manager.save(session)
    submissions = []

    async def submit(message, anchor, projection, accepted):
        value = await manager.state.replace_user_input(message.session_key, anchor, message, projection)
        if value is not None:
            submissions.append(message)
            await accepted(value)

    gateway = SimpleNamespace(session_manager=manager, replace_user_input=submit,
                              transcripts=transcript.WebUITranscriptRecorder(manager),
                              ingress=SimpleNamespace(validate_text=lambda _: None))
    host = SimpleNamespace(gateway=gateway, announce_webui_history_replacement=AsyncMock())
    clear_websocket_turns("edit-chat")
    yield manager, host, submissions, display
    clear_websocket_turns("edit-chat")
    await manager.state.aclose()


def read_rows(manager, key=KEY):
    return manager.project_history(key, lambda history: transcript.read_transcript_lines(key, history=history))


async def read_source(host, index):
    manager = host.gateway.session_manager
    body = await manager.state.project_history(KEY, lambda history: transcript.build_webui_thread_response(
        KEY, history=history, limit=1, session_version_loader=lambda: manager.read_session_version(KEY),
    ))
    assert body is not None
    # A paged selection uses stable input identity, never a page-local index.
    return {"revision": body["source_revision"], "id": f"user:old-{index}"}


def payload(source, text="replacement", turn_id="new-edit"):
    return {"mode": "replace", "chat_id": "edit-chat", "text": text,
            "turn_id": turn_id, "source": source}


@pytest.mark.parametrize("index", [0, 2, 3])
async def test_edit_keeps_identity_prefix_and_one_new_input(editing, index):
    manager, host, submissions, display = editing
    before = await manager.state.read(KEY)
    stale_draft = await manager.state.get(KEY)
    old_metadata = deepcopy(before.metadata)
    prepared = await read_source(host, index)
    result = await replace_webui_chat_input(host, payload(prepared))
    assert result == {"accepted": True, "turn_id": "new-edit"}
    assert host.announce_webui_history_replacement.await_args.kwargs["retired_turn_ids"] == [
        f"old-{i}" for i in range(index, 4)
    ]
    after = await manager.state.read(KEY)
    assert after.key == before.key and after.created_at == before.created_at
    for name, value in old_metadata.items():
        assert after.metadata[name] == value
    assert after.generation != before.generation
    assert after.messages[:-1] == before.messages[:index * 2]
    assert after.messages[-1]["content"] == "replacement"
    assert after.messages[-1]["input_id"] == "user:new-edit"
    assert after.get_history(include_runtime_context=True)[-1]["_meta"]["input_id"] == "user:new-edit"
    assert after.metadata["pending_user_turn"] is True
    rows = read_rows(manager)
    assert [row["text"] for row in rows if row.get("event") == "user"] == [*[f"question-{i}" for i in range(index)], "replacement"]
    assert len(await manager.state.list_sessions()) == 1
    await replace_webui_chat_input(host, payload(prepared))
    assert len(submissions) == 1
    stale_draft.add_message("assistant", "obsolete suffix")
    with pytest.raises(SessionConflictError):
        await manager.state.finish_turn(stale_draft)
    assert "obsolete suffix" not in str((await manager.state.read(KEY)).messages)
    with pytest.raises(SessionConflictError):
        await manager.state.append_history(KEY, [fact_from_record({"event": "message", "text": "obsolete suffix"})],
                                           expected_generation=before.generation)
    assert read_rows(manager) == rows


async def test_replay_uses_one_snapshot_and_rejects_an_edit_from_before_concurrent_append(editing, tmp_path, monkeypatch):
    import json
    from concurrent.futures import ThreadPoolExecutor

    from websockets.datastructures import Headers
    from websockets.http11 import Request

    from nanobot.bus.queue import MessageBus
    from nanobot.channels.websocket.runtime import WebSocketConfig
    from nanobot.webui import ws_http
    from nanobot.webui.gateway_services import build_gateway_services

    manager, host, submissions, _ = editing
    gateway = build_gateway_services(
        config=WebSocketConfig(), bus=MessageBus(), session_manager=manager,
        static_dist_path=None, workspace_path=tmp_path, config_path=tmp_path / "config.json",
        default_restrict_to_workspace=False, runtime_model_name=None,
        runtime_surface="browser", runtime_capabilities_overrides=None,
    )
    auth = ("Authorization", "Bearer " + gateway.tokens.issue_api_token(300))
    path = "/api/sessions/websocket%3Aedit-chat/webui-thread"

    async def read(*headers):
        return await gateway.http._dispatch_session_routes(Request(path, Headers([auth, *headers])), path)

    before = await read()
    build = ws_http.build_webui_thread_response
    writer = SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "sessions")
    fact = fact_from_record({"event": "user", "turn_id": "later", "text": "later question"})
    with ThreadPoolExecutor(max_workers=1) as pool, monkeypatch.context() as patch:
        def concurrent_build(*args, **kwargs):
            pool.submit(writer.append_history, KEY, [fact]).result(timeout=5)
            return build(*args, **kwargs)

        patch.setattr(ws_http, "build_webui_thread_response", concurrent_build)
        overlapping = await read()
    assert overlapping.status_code == before.status_code == 200
    assert overlapping.headers["ETag"] == before.headers["ETag"]
    assert overlapping.body == before.body
    old = json.loads(overlapping.body)
    changed = await read(("If-None-Match", overlapping.headers["ETag"]))
    assert changed.status_code == 200
    assert changed.headers["ETag"] != overlapping.headers["ETag"]
    current = json.loads(changed.body)
    assert current["source_revision"] != old["source_revision"]
    assert current["events"][-1]["text"] == "later question"
    user = next(event for event in old["events"] if event["event"] == "user_message")
    with pytest.raises(HistoryEditError, match="edit_source_changed"):
        await replace_webui_chat_input(host, payload({
            "revision": old["source_revision"], "id": f"user:{user['turn_id']}",
        }))
    assert not submissions


async def test_other_chat_revision_cannot_authorize_replacement(editing):
    manager, host, submissions, _ = editing
    before = await manager.state.read(KEY)
    rows = read_rows(manager)
    prepared = await read_source(host, 1)
    other = await manager.state.get("websocket:other-chat")
    other.add_message("user", "other question", webui_turn_id="old-1")
    await manager.state.finish_turn(other)
    with pytest.raises(HistoryEditError, match="edit_source_changed"):
        await replace_webui_chat_input(host, {**payload(prepared), "chat_id": "other-chat"})
    assert (await manager.state.read(other.key)).messages == other.messages
    assert (await manager.state.read(KEY)).messages == before.messages
    assert read_rows(manager) == rows
    assert not submissions


async def test_source_revision_is_shared_by_different_history_pages(editing):
    manager, _, _, _ = editing
    async def page(limit=1, before=None):
        return await manager.state.project_history(KEY, lambda history: transcript.build_webui_thread_response(
            KEY, history=history, limit=limit, before=before,
            session_version_loader=lambda: manager.read_session_version(KEY),
        ))
    latest = await page()
    full = await page(1000)
    assert latest is not None and full is not None
    older = await page(before=latest["page"]["before_cursor"])
    assert older is not None
    assert latest["source_revision"] == full["source_revision"] == older["source_revision"]
    assert latest["source_revision"]
    assert latest["events"][0]["text"] != older["events"][0]["text"]


async def test_long_replacement_broadcast_is_a_page_with_a_recoverable_prefix(editing):
    manager, host, _, _ = editing
    session = await manager.state.get(KEY)
    facts = []
    for index in range(4, 32):
        turn_id = f"old-{index}"
        session.add_message("user", f"question-{index}", webui_turn_id=turn_id)
        session.add_message("assistant", f"answer-{index}")
        for event, text in (("user", f"question-{index}"), ("message", f"answer-{index}"), ("turn_end", None)):
            facts.append(fact_from_record({"event": event, "turn_id": turn_id, "text": text}))
    await manager.state.finish_turn(session)
    await manager.state.append_history(KEY, facts, expected_generation=session.generation)
    await replace_webui_chat_input(host, payload(await read_source(host, 27)))

    async def page(before=None):
        return await manager.state.project_history(KEY, lambda history: transcript.build_webui_thread_response(
            KEY, history=history, limit=40, before=before,
        ))

    live = host.announce_webui_history_replacement.await_args.args[1]
    latest = await page()
    assert live["events"] == latest["events"] and live["page"] == latest["page"]
    assert live["page"]["has_more_before"]
    chunks = [live["events"]]
    cursor = live["page"]["before_cursor"]
    while cursor:
        older = await page(cursor)
        chunks.insert(0, older["events"])
        cursor = older["page"]["before_cursor"]
    assert [e["text"] for chunk in chunks for e in chunk if e["event"] == "user_message"] == [
        *(f"question-{i}" for i in range(27)), "replacement",
    ]


async def test_edit_pre_id_history_uses_the_selected_row_not_its_text(editing):
    manager, host, _, _ = editing
    session = await manager.state.get(KEY)
    facts = []
    for answer in ("first answer", "second answer"):
        session.add_message("user", "same question")
        session.add_message("assistant", answer)
        facts.extend(fact_from_record(row) for row in (
            {"event": "user", "text": "same question"}, {"event": "message", "text": answer}, {"event": "turn_end"},
        ))
    await manager.state.finish_turn(session)
    await manager.state.append_history(KEY, facts, expected_generation=session.generation)
    page = await manager.state.project_history(KEY, lambda history: transcript.build_webui_thread_response(
        KEY, history=history, limit=40, session_version_loader=lambda: history.session_version,
    ))
    first, second = [e for e in page["events"] if e.get("text") == "same question"]
    assert first["projection_id"] != second["projection_id"]
    await replace_webui_chat_input(host, payload({"revision": page["source_revision"], "id": second["projection_id"]}))
    after = await manager.state.read(KEY)
    assert [m["content"] for m in after.messages[-3:]] == ["same question", "first answer", "replacement"]


@pytest.mark.parametrize("failure", ["source", "display", "sql", "install"])
async def test_rejection_preserves_the_effective_history(editing, monkeypatch, failure):
    manager, host, submissions, _ = editing
    prepared = await read_source(host, 2)
    if failure == "source":
        await manager.state.update_metadata(KEY, {"title": "Changed elsewhere"})
    if failure == "display":
        source = await manager.state.read(KEY)
        await manager.state.append_history(KEY, [fact_from_record({"event": "message", "text": "another delivery"})], expected_generation=source.generation)
    before = await manager.state.read(KEY)
    rows = read_rows(manager)
    if failure == "sql":
        monkeypatch.setattr(manager._store, "replace_generation", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")))
    if failure == "install":
        original = manager._store.replace_history_input

        def fail(*args, **kwargs):
            original(*args, **kwargs)
            raise OSError("disk full")

        monkeypatch.setattr(manager._store, "replace_history_input", fail)
    with pytest.raises((HistoryEditError, OSError)):
        await replace_webui_chat_input(host, payload(prepared))
    after = await manager.state.read(KEY)
    assert (after.generation, after.revision, after.messages) == (before.generation, before.revision, before.messages)
    assert read_rows(manager) == rows
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
    prepared = await read_source(host, 1)
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
        await replace_webui_chat_input(host, payload(await read_source(host, 1)))


@pytest.mark.parametrize("text", ["/new", "! rm anything", "use @editable", "> [!QUOTE]\n> quote\n\nreply"])
async def test_edit_never_dispatches_control_or_context_syntax(editing, text):
    manager, host, submissions, _ = editing
    prepared = await read_source(host, 1)
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


async def test_mismatched_display_and_model_input_cannot_truncate_history(editing):
    manager, host, submissions, _ = editing
    # A recovered display row still has its ID but no longer describes the model input.
    session = await manager.state.get(KEY)
    session.messages[2]["content"] = "a different model input"
    await manager.state.prepare_input(session)
    before = await manager.state.read(KEY)
    rows = read_rows(manager)
    prepared = await read_source(host, 1)
    with pytest.raises(HistoryEditError, match="edit_source_changed"):
        await replace_webui_chat_input(host, payload(prepared))
    assert (await manager.state.read(KEY)).messages == before.messages
    assert read_rows(manager) == rows
    assert not submissions


async def test_new_fork_and_replace_share_the_source_owner_boundary(editing, monkeypatch):
    import asyncio
    import threading

    manager, host, _, _ = editing
    source = await manager.state.read(KEY)
    prepared = await read_source(host, 1)
    started, release = threading.Event(), threading.Event()
    original = manager._store.copy_history_prefix

    def blocked(*args):
        started.set()
        assert release.wait(5)
        return original(*args)

    monkeypatch.setattr(manager._store, "copy_history_prefix", blocked)
    fork_task = asyncio.create_task(create_webui_chat_fork(manager, source_chat_id="edit-chat", before_user_index=2))
    assert await asyncio.to_thread(started.wait, 5)
    edit_task = asyncio.create_task(replace_webui_chat_input(host, payload(prepared)))
    release.set()
    _, fork_key = await fork_task
    await edit_task
    target = await manager.state.read(fork_key)
    assert target.messages == source.messages[:4]
    assert [row["text"] for row in read_rows(manager, fork_key) if row.get("event") == "user"] == ["question-0", "question-1"]
    assert (await manager.state.read(KEY)).messages[-1]["content"] == "replacement"


async def test_edit_does_not_schedule_a_new_title_for_an_untitled_session(editing):
    from unittest.mock import Mock

    from nanobot.bus.queue import MessageBus
    from nanobot.bus.runtime_events import RuntimeEventContext, TurnCompleted
    from nanobot.providers.base import GenerationSettings
    from nanobot.session.webui_turns import WebuiTurnCoordinator
    from nanobot.utils.llm_runtime import LLMRuntime

    manager, host, submissions, _ = editing
    await manager.state.update_metadata(KEY, {}, remove=("title", "title_user_edited"))
    prepared = await read_source(host, 1)
    await replace_webui_chat_input(host, payload(prepared))
    bus = MessageBus()
    schedule = Mock()
    runtime = LLMRuntime(Mock(), "fixture", GenerationSettings(), 8192)
    ctx = RuntimeEventContext("websocket", "edit-chat", KEY, submissions[0].metadata)
    with WebuiTurnCoordinator(bus, manager, schedule).connected():
        await bus.publish(TurnCompleted(context=ctx, runtime=runtime))
    schedule.assert_not_called()
    assert "title" not in (await manager.state.read(KEY)).metadata
