"""Same-session edits use the owner commit, not fork creation followed by send."""
from __future__ import annotations

import sqlite3
from contextlib import closing
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nanobot.session.history_edit import HistoryEditError
from nanobot.session.manager import Session, SessionManager
from nanobot.session.webui_turns import clear_websocket_turns
from nanobot.webui import transcript
from nanobot.webui.forking import replace_webui_chat_input
from nanobot.webui.history import fact_from_record

KEY = "websocket:edit-chat"


@pytest.fixture
async def editing(tmp_path):
    manager = SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "sessions")
    session = Session(key=KEY, metadata={"title": "Keep title", "session_handle": "editable", "model_preset": "precise"})
    facts = []
    for i in range(32):  # Enough turns for the replacement to span multiple pages.
        turn = {"turn_id": f"old-{i}"}
        identity = {"input_id": f"user:old-{i}"} if i else {}
        session.add_message("user", f"question-{i}", webui_turn_id=turn["turn_id"], **identity)
        session.add_message("assistant", f"answer-{i}")
        facts.append(fact_from_record({"event": "user", "text": f"question-{i}", **turn, **identity}))
        facts.append(fact_from_record({"event": "message", "text": f"answer-{i}", **turn}))
        if i != 1:  # Input 2 steered the existing turn before it completed.
            facts.append(fact_from_record({"event": "turn_end", **turn}))
    manager.save(session)
    manager.append_history(KEY, facts)

    async def submit(message, anchor, projection, accepted):
        updated = await manager.state.replace_user_input(message.session_key, anchor, message, projection)
        if updated is not None:
            await accepted(updated)

    gateway = SimpleNamespace(session_manager=manager, replace_user_input=submit,
                              transcripts=transcript.WebUITranscriptRecorder(manager),
                              ingress=SimpleNamespace(validate_text=lambda _: None))
    yield manager, SimpleNamespace(gateway=gateway, announce_webui_history_replacement=AsyncMock())
    clear_websocket_turns("edit-chat")
    await manager.state.aclose()


def page(manager, **paging):
    return manager.project_history(KEY, lambda h: transcript.build_webui_thread_response(
        KEY, history=h, session_version_loader=lambda: h.session_version, **paging,
    ))


def payload(source, text="replacement"):
    return {"mode": "replace", "chat_id": "edit-chat", "text": text, "turn_id": "new-edit", "source": source}


def source_for(manager, index):
    return {"revision": page(manager, limit=1)["source_revision"], "id": f"user:old-{index}"}


@pytest.mark.parametrize("index", [0, 2, 27], ids=["first", "within-turn", "long-prefix"])
async def test_edit_keeps_the_same_topic_and_prefix_in_both_histories(editing, index):
    manager, host = editing
    before = await manager.state.read(KEY)
    await replace_webui_chat_input(host, payload(source_for(manager, index)))
    after = await manager.state.read(KEY)
    assert len(await manager.state.list_sessions()) == 1
    assert after.key == before.key and after.created_at == before.created_at
    assert before.metadata.items() <= after.metadata.items()
    assert after.messages[:-1] == before.messages[:index * 2]
    assert (after.messages[-1]["content"], after.messages[-1]["input_id"]) == ("replacement", "user:new-edit")

    live = host.announce_webui_history_replacement.await_args.args[1]
    assert live["events"] == page(manager, limit=40)["events"]
    events = live["events"]
    cursor = live["page"]["before_cursor"]
    while cursor:
        older = page(manager, limit=40, before=cursor)
        assert older["source_revision"] == live["source_revision"]
        events = older["events"] + events
        cursor = older["page"]["before_cursor"]
    assert [e["text"] for e in events if e["event"] == "user_message"] == [
        *(f"question-{i}" for i in range(index)), "replacement",
    ]


async def test_replay_uses_one_snapshot_and_rejects_an_edit_from_before_concurrent_append(editing, tmp_path, monkeypatch):
    import json
    from concurrent.futures import ThreadPoolExecutor

    from websockets.datastructures import Headers
    from websockets.http11 import Request

    from nanobot.bus.queue import MessageBus
    from nanobot.channels.websocket.runtime import WebSocketConfig
    from nanobot.webui import ws_http
    from nanobot.webui.gateway_services import build_gateway_services

    manager, host = editing
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
    assert page(manager)["events"][-1]["text"] == "later question"


async def test_edit_pre_id_history_uses_the_selected_row_not_its_text(editing):
    manager, host = editing
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
    latest = page(manager, limit=40)
    first, second = [e for e in latest["events"] if e.get("text") == "same question"]
    assert first["projection_id"] != second["projection_id"]
    await replace_webui_chat_input(host, payload({"revision": latest["source_revision"], "id": second["projection_id"]}))
    after = await manager.state.read(KEY)
    assert [m["content"] for m in after.messages[-3:]] == ["same question", "first answer", "replacement"]


async def test_display_write_failure_leaves_both_histories_intact_after_reopen(editing, tmp_path):
    manager, host = editing
    source = source_for(manager, 2)
    before = manager.read_session_snapshot(KEY)
    rows = page(manager)["events"]
    with closing(sqlite3.connect(manager.sessions_dir / "sessions.sqlite3")) as db:
        db.execute("""CREATE TRIGGER reject_replacement BEFORE INSERT ON history_entries
                      BEGIN SELECT RAISE(ABORT, 'display write failed'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="display write failed"):
        await replace_webui_chat_input(host, payload(source))
    reopened = SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "sessions")
    after = reopened.read_session_snapshot(KEY)
    assert (after.generation, after.messages) == (before.generation, before.messages)
    assert page(reopened)["events"] == rows


async def test_discarded_summary_and_provider_continuation_cannot_survive(editing):
    manager, host = editing
    source = await manager.state.get(KEY)
    source.commit_summary_checkpoint("discarded summary", insert_at=6, last_active=source.updated_at)
    from nanobot.providers.base import ProviderConversationState
    source.provider_state = ProviderConversationState(
        kind="openai_responses", provider="openai:test", model="fixture", version=1,
        payload={"response_id": "discarded-suffix"},
    )
    await manager.state.prepare_input(source)
    prepared = source_for(manager, 1)
    await replace_webui_chat_input(host, payload(prepared))
    value = await manager.state.read(KEY)
    assert value.last_archived == 0
    assert "_last_summary" not in value.metadata
    assert value.provider_state is None
    assert "discarded summary" not in str(value.get_history())


@pytest.mark.parametrize(("extra", "code"), [
    ({"media": ["image.png"]}, "edit_attachments_unsupported"),
    ({"session_mentions": [{"name": "session"}]}, "edit_mentions_unsupported"),
    ({"_command": True}, "edit_special_message"),
    ({"_runtime_context": {"sources": ["session_mentions"]}}, "edit_mentions_unsupported"),
    ({"_runtime_context": {"sources": ["session_message"]}}, "edit_special_message"),
])
async def test_unsupported_metadata_is_explicitly_rejected(editing, extra, code):
    manager, host = editing
    source = await manager.state.get(KEY)
    source.messages[2].update(extra)
    await manager.state.prepare_input(source)
    with pytest.raises(HistoryEditError, match=code):
        await replace_webui_chat_input(host, payload(source_for(manager, 1)))


@pytest.mark.parametrize("text", ["/new", "! rm anything", "use @editable", "> [!QUOTE]\n> quote\n\nreply"])
async def test_edit_never_dispatches_control_or_context_syntax(editing, text):
    manager, host = editing
    prepared = source_for(manager, 1)
    before = await manager.state.read(KEY)
    with pytest.raises(HistoryEditError):
        await replace_webui_chat_input(host, payload(prepared, text))
    assert (await manager.state.read(KEY)).messages == before.messages


async def test_mismatched_display_and_model_input_cannot_truncate_history(editing):
    manager, host = editing
    # A recovered display row still has its ID but no longer describes the model input.
    session = await manager.state.get(KEY)
    session.messages[2]["content"] = "a different model input"
    await manager.state.prepare_input(session)
    before = await manager.state.read(KEY)
    rows = page(manager)["events"]
    prepared = source_for(manager, 1)
    with pytest.raises(HistoryEditError, match="edit_source_changed"):
        await replace_webui_chat_input(host, payload(prepared))
    assert (await manager.state.read(KEY)).messages == before.messages
    assert page(manager)["events"] == rows
