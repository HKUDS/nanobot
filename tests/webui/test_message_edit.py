"""Same-session edits use the owner commit, not fork creation followed by send."""
from __future__ import annotations

import asyncio
import base64
import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import INBOUND_META_LOCAL_MEDIA, InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket.runtime import WebSocketConfig
from nanobot.providers.base import GenerationSettings, LLMResponse
from nanobot.runtime_context import public_history_message
from nanobot.security.workspace_access import WORKSPACE_SCOPE_METADATA_KEY
from nanobot.session.display_history import HISTORY_GENERATION_METADATA_KEY
from nanobot.session.manager import Session, SessionManager
from nanobot.session.recovery import pending_followups
from nanobot.session.state import ForkError
from nanobot.session.webui_turns import clear_websocket_turns
from nanobot.webui import transcript
from nanobot.webui.forking import create_webui_chat_fork, fork_webui_chat_in_place
from nanobot.webui.gateway_services import build_gateway_services
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
        updated = await manager.state.fork_in_place(message.session_key, anchor, message, projection)
        if updated is not None:
            await accepted(updated)

    gateway = SimpleNamespace(session_manager=manager, fork_in_place=submit,
                              transcripts=transcript.WebUITranscriptRecorder(manager),
                              ingress=SimpleNamespace(validate_text=lambda _: None))
    yield manager, SimpleNamespace(gateway=gateway, announce_webui_history_replacement=AsyncMock())
    clear_websocket_turns("edit-chat")
    await manager.state.aclose()


def page(manager, **paging):
    return manager.project_history(KEY, lambda h: transcript.build_webui_thread_response(
        KEY, history=h, session_version_loader=lambda: h.session_version, **paging,
    ))


def payload(source_id, text="replacement"):
    return {"mode": "replace", "chat_id": "edit-chat", "text": text, "turn_id": "new-edit", "source_id": source_id}


@pytest.mark.parametrize("index", [0, 2, 27], ids=["first", "within-turn", "long-prefix"])
async def test_edit_keeps_the_same_topic_and_prefix_in_both_histories(editing, index):
    manager, host = editing
    before = await manager.state.read(KEY)
    await fork_webui_chat_in_place(host, payload(f"user:old-{index}"))
    after = await manager.state.read(KEY)
    assert len(await manager.state.list_sessions()) == 1
    assert after.key == before.key and after.created_at == before.created_at
    assert before.metadata.items() <= after.metadata.items()
    assert after.messages == before.messages[:index * 2]
    assert [(msg.content, msg.metadata["webui_turn_id"]) for msg in pending_followups(after)] == [("replacement", "new-edit")]

    live = host.announce_webui_history_replacement.await_args.args[1]
    assert live["events"] == page(manager, limit=40)["events"]
    events = live["events"]
    cursor = live["page"]["before_cursor"]
    while cursor:
        older = page(manager, limit=40, before=cursor)
        events = older["events"] + events
        cursor = older["page"]["before_cursor"]
    assert [e["text"] for e in events if e["event"] == "user_message"] == [
        *(f"question-{i}" for i in range(index)), "replacement",
    ]


async def test_fork_at_a_displayed_input_discards_a_later_append(editing, tmp_path, monkeypatch):
    import json
    from concurrent.futures import ThreadPoolExecutor

    from websockets.datastructures import Headers
    from websockets.http11 import Request

    from nanobot.webui import ws_http

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
    def append_later_input():
        session = writer.read_session_snapshot(KEY)
        session.add_message("user", "later question", webui_turn_id="later")
        writer.save(session)
        writer.append_history(KEY, [fact_from_record({"event": "user", "turn_id": "later", "text": "later question"})])

    with ThreadPoolExecutor(max_workers=1) as pool, monkeypatch.context() as patch:
        def concurrent_build(*args, **kwargs):
            pool.submit(append_later_input).result(timeout=5)
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
    assert current["events"][-1]["text"] == "later question"
    user = next(event for event in old["events"] if event["event"] == "user_message")
    await fork_webui_chat_in_place(host, payload(f"user:{user['turn_id']}"))
    assert "later question" not in [m["content"] for m in manager.read_session_snapshot(KEY).messages]
    assert [e["text"] for e in page(manager)["events"] if e["event"] == "user_message"][-1] == "replacement"


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
    await fork_webui_chat_in_place(host, payload(second["projection_id"]))
    after = await manager.state.read(KEY)
    assert [m["content"] for m in after.messages[-2:]] == ["same question", "first answer"]


async def test_display_write_failure_leaves_both_histories_intact_after_reopen(editing, tmp_path):
    manager, host = editing
    source = "user:old-2"
    before = manager.read_session_snapshot(KEY)
    rows = page(manager)["events"]
    with closing(sqlite3.connect(manager.sessions_dir / "sessions.sqlite3")) as db:
        db.execute("""CREATE TRIGGER reject_replacement BEFORE INSERT ON history_entries
                      BEGIN SELECT RAISE(ABORT, 'display write failed'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="display write failed"):
        await fork_webui_chat_in_place(host, payload(source))
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
    await fork_webui_chat_in_place(host, payload("user:old-1"))
    value = await manager.state.read(KEY)
    assert value.last_archived == 0
    assert "_last_summary" not in value.metadata
    assert value.provider_state is None
    assert "discarded summary" not in str(value.get_history())


@pytest.mark.parametrize(("extra", "code"), [
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
    with pytest.raises(ForkError, match=code):
        await fork_webui_chat_in_place(host, payload("user:old-1"))


@pytest.mark.parametrize("text", ["", "/new", "! rm anything", "use @editable", "> [!QUOTE]\n> quote\n\nreply"])
async def test_edit_never_dispatches_control_or_context_syntax(editing, text):
    manager, host = editing
    prepared = "user:old-1"
    before = await manager.state.read(KEY)
    with pytest.raises(ForkError):
        await fork_webui_chat_in_place(host, payload(prepared, text))
    assert (await manager.state.read(KEY)).messages == before.messages


async def test_mismatched_display_and_model_input_cannot_truncate_history(editing):
    manager, host = editing
    # A recovered display row still has its ID but no longer describes the model input.
    session = await manager.state.get(KEY)
    session.messages[2]["content"] = "a different model input"
    await manager.state.prepare_input(session)
    before = await manager.state.read(KEY)
    rows = page(manager)["events"]
    prepared = "user:old-1"
    with pytest.raises(ForkError, match="edit_source_changed"):
        await fork_webui_chat_in_place(host, payload(prepared))
    assert (await manager.state.read(KEY)).messages == before.messages
    assert page(manager)["events"] == rows


@pytest.fixture
async def media_turn(tmp_path, monkeypatch):
    monkeypatch.setattr("nanobot.config.loader._current_config_path", tmp_path / "config.json")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manager = SessionManager(workspace, sessions_root=tmp_path / "sessions")
    provider = MagicMock(generation=GenerationSettings(), aclose=AsyncMock())
    provider.chat_stream_with_retry = AsyncMock(return_value=LLMResponse(content="answer"))
    loop = AgentLoop(bus=MessageBus(), provider=provider, workspace=workspace, model="test-model", session_manager=manager)
    gateway = build_gateway_services(
        config=WebSocketConfig(), bus=loop.bus, session_manager=manager, fork_in_place=loop.session_inputs.fork_in_place,
        static_dist_path=None, workspace_path=workspace, config_path=tmp_path / "config.json",
        default_restrict_to_workspace=True, runtime_model_name=None,
        runtime_surface="browser", runtime_capabilities_overrides=None,
    )
    store = gateway.uploads.store
    async def upload(mime, data):
        async def chunks():
            yield data
        ref = await store.upload(chunks(), owner="browser", mime=mime, size=len(data))
        return store.commit([ref], owner="browser")[0]

    image = await upload("image/gif", base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"))
    document = await upload("text/plain", b"uploaded notes")
    borrowed = tmp_path / "local.txt"
    borrowed.write_text("borrowed notes")
    paths = [document, str(borrowed), image]
    scope = {"project_path": str(workspace), "access_mode": "full"}
    session = await manager.state.get(KEY)
    session.metadata[WORKSPACE_SCOPE_METADATA_KEY] = scope
    await manager.state.prepare_input(session)
    metadata = {WORKSPACE_SCOPE_METADATA_KEY: scope, INBOUND_META_LOCAL_MEDIA: [str(borrowed)],
                HISTORY_GENERATION_METADATA_KEY: session.generation, "webui_turn_id": "attached", "webui": True}
    # Record the display input before the normal worker preprocesses files and images.
    assert await gateway.transcripts.append_user_message("edit-chat", "", metadata=metadata, media_paths=paths)
    await loop._process_message(InboundMessage(
        channel="websocket", chat_id="edit-chat", sender_id="browser", content="", media=paths, metadata=metadata,
    ))
    host = SimpleNamespace(gateway=gateway, announce_webui_history_replacement=AsyncMock())
    try:
        yield loop, host, paths
    finally:
        clear_websocket_turns("edit-chat")
        await loop.aclose()


async def test_edit_retains_original_files_images_and_local_origin(media_turn):
    loop, host, paths = media_turn
    document, borrowed, image = paths
    source = "user:attached"
    for turn_id, caption in (("captioned", "[Attachment: typed by the user]"), ("uncaptioned", "")):
        await fork_webui_chat_in_place(host, {
            **payload(source, caption), "turn_id": turn_id,
            "media": [{"path": "/untrusted", "url": "/api/media/preview"}], "local_media_paths": ["/untrusted"],
        })
        await asyncio.gather(*(task for group in loop._active_tasks.values() for task in group))
        row = public_history_message((await loop.sessions.state.read(KEY)).messages[0])
        assert row["media"] == [image] and row[INBOUND_META_LOCAL_MEDIA] == [borrowed]
        assert row["content"][0]["type"] == "image_attachment"
        assert row["content"][1]["text"] == (caption + "\n\n" if caption else "") + f"[Attachment: {document}]\n[Attachment: {borrowed}]"
        event = host.announce_webui_history_replacement.await_args.args[1]["events"][-1]
        assert event["text"] == caption
        assert event["media_urls"] == host.gateway.media.augment_transcript_user_media(paths, [borrowed], session_key=KEY)
        # This backend-only fixture has no WebSocket turn_end dispatcher.
        clear_websocket_turns("edit-chat")
        source = f"user:{turn_id}"


@pytest.mark.parametrize("loss", ["deleted-upload", "revoked-local-scope"])
async def test_unavailable_attachment_preserves_both_histories(media_turn, loss):
    loop, host, paths = media_turn
    manager = loop.sessions
    if loss == "deleted-upload":
        Path(paths[0]).unlink()
    else:
        session = await manager.state.get(KEY)
        session.metadata[WORKSPACE_SCOPE_METADATA_KEY]["access_mode"] = "restricted"
        await manager.state.prepare_input(session)
    before = await manager.state.read(KEY)
    events = page(manager)["events"]
    with pytest.raises(ForkError, match="edit_attachments_unavailable"):
        await fork_webui_chat_in_place(host, payload("user:attached"))
    after = await manager.state.read(KEY)
    assert (after.generation, after.messages) == (before.generation, before.messages)
    assert page(manager)["events"] == events


async def test_fork_without_original_display_facts_does_not_drop_a_document(editing):
    manager, host = editing
    model_only = await manager.state.get("websocket:without-display")
    model_only.add_message("user", "review\n\n[Attachment: /original.txt]", webui_turn_id="attached")
    await manager.state.prepare_input(model_only)
    chat_id, key = await create_webui_chat_fork(manager, source_chat_id="without-display", before_user_index=1)
    before = await manager.state.read(key)
    with pytest.raises(ForkError, match="edit_attachments_unavailable"):
        await fork_webui_chat_in_place(host, {**payload("user:attached"), "chat_id": chat_id})
    assert (await manager.state.read(key)).generation == before.generation
