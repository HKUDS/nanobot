from __future__ import annotations

import json
from types import SimpleNamespace
from urllib.parse import quote, urlencode

import pytest
from websockets.datastructures import Headers
from websockets.http11 import Request

from nanobot.bus.events import INBOUND_META_LOCAL_MEDIA
from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket.runtime import WebSocketConfig
from nanobot.config.paths import get_media_dir
from nanobot.runtime_context import RUNTIME_CONTEXT_HISTORY_META
from nanobot.security.workspace_access import WORKSPACE_SCOPE_METADATA_KEY
from nanobot.session.display_history import HistoryFact, HistoryKind
from nanobot.session.history_visibility import HIDDEN_HISTORY_META
from nanobot.session.manager import SessionManager
from nanobot.session.recovery import RECOVERY_METADATA_KEY
from nanobot.session.session_handles import SessionHandleResolver
from nanobot.session.types import SESSION_TYPE_KEY
from nanobot.session.webui_turns import (
    clear_websocket_turns,
    register_queued_websocket_turn_if_idle,
    websocket_turn_wall_started_at,
)
from nanobot.webui.gateway_services import build_gateway_services
from nanobot.webui.session_identity import channel_session_chat_id
from nanobot.webui.workspaces import write_webui_workspace_state


@pytest.fixture
async def gateway(tmp_path, monkeypatch, request):
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path / "data")
    workspace = tmp_path / "workspace"
    sessions = SessionManager(workspace, sessions_root=tmp_path / "sessions")
    services = build_gateway_services(
        config=WebSocketConfig(), bus=MessageBus(), session_manager=sessions,
        static_dist_path=None, workspace_path=workspace,
        default_restrict_to_workspace=getattr(request, "param", True),
        runtime_model_name=lambda: "test-model", runtime_surface="gateway",
        runtime_capabilities_overrides=None, config_path=tmp_path / "config.json",
    )
    token = services.tokens.issue_api_token(60)
    connection = SimpleNamespace(remote_address=("127.0.0.1", 12345))

    async def get(path, *, etag=None, authenticated=True):
        headers = Headers({"Authorization": f"Bearer {token}"}) if authenticated else Headers()
        if etag is not None:
            headers["If-None-Match"] = etag
        return await services.http.dispatch(connection, Request(path, headers))

    try:
        yield sessions, workspace, get
    finally:
        await sessions.state.aclose()


def _session_path(key: str, suffix: str = "/webui-thread", **query: str | int) -> str:
    path = f"/api/sessions/{quote(key, safe='')}{suffix}"
    return f"{path}?{urlencode(query)}" if query else path


def _conversation(sessions, key, **metadata):
    session = sessions.get_or_create(key)
    session.metadata.update(metadata)
    session.add_message("user", "hello")
    sessions.save(session)
    return session


async def test_list_keeps_native_rows_and_exposes_only_public_channel_sessions(gateway, tmp_path):
    sessions, workspace, get = gateway
    legacy_project = tmp_path / "legacy-project"
    legacy_project.mkdir()
    scope = {"project_path": str(legacy_project), "access_mode": "full"}
    recovery = {"status": "awaiting_user", "recovery_id": "recover-1", "reason": "interrupted_stream"}
    native_key = "websocket:browser"
    external_key = "telegram:-1001234:topic:19"
    for key in [native_key, external_key]:
        _conversation(sessions, key, **{
            "title": "Stored title", WORKSPACE_SCOPE_METADATA_KEY: scope, RECOVERY_METADATA_KEY: recovery,
        })
    _conversation(sessions, "cli:tty")
    _conversation(sessions, "dream:did-not-publish")
    _conversation(sessions, "matrix:!private:example.org", **{SESSION_TYPE_KEY: "unregistered-private"})
    await sessions.state.register_transient("telegram:temporary")
    write_webui_workspace_state({"default_access_mode": "full"})

    alias = channel_session_chat_id(external_key)
    assert alias is not None
    assert register_queued_websocket_turn_if_idle(alias, "browser-turn") is not None
    try:
        response = await get("/api/sessions")
        assert response.status_code == 200
        rows = {row["key"]: row for row in json.loads(response.body)["sessions"]}
        assert set(rows) == {native_key, external_key}
        native, external = rows[native_key], rows[external_key]
        assert "chat_id" not in native
        assert native["title"] == "Stored title"
        assert native["recovery_state"]["recovery_id"] == "recover-1"
        assert native["workspace_scope"]["project_path"] == str(legacy_project)
        assert native["workspace_scope"]["access_mode"] == "full"
        assert external["chat_id"] == alias and alias.startswith("channel.")
        assert external["title"] == "Telegram"
        assert external["preview"] == "hello"
        assert external["project_locked"] is True
        assert external["workspace_scope"]["project_path"] == str(workspace)
        assert external["workspace_scope"]["access_mode"] == "restricted"
        assert external["run_started_at"] == websocket_turn_wall_started_at(alias)
        assert "recovery_state" not in external
        handle = await SessionHandleResolver(sessions).aresolve(external["handle"]["name"])
        assert handle is not None and handle.session_key == external_key
    finally:
        clear_websocket_turns(alias)


@pytest.mark.parametrize("key", [
    "matrix:!room:example.org:thread:$id/with+=base64",
    "matrix:@person:example.org",
    "matrix:#room:example.org",
    "telegram:-1001234:topic:42",
])
async def test_thread_reads_the_exact_encoded_channel_address(gateway, key):
    sessions, _, get = gateway
    session = _conversation(sessions, key)
    path = _session_path(key)
    assert (await get(path, authenticated=False)).status_code == 401
    response = await get(path)
    assert response.status_code == 200
    body = json.loads(response.body)
    assert body["sessionKey"] == key
    assert body["projection"] == "events"
    assert body["page"]["history_generation"] == session.generation
    assert body["events"][0]["chat_id"] == channel_session_chat_id(key)
    assert body["events"][0]["text"] == "hello"
    assert "entry_channel" not in body["events"][0]


async def test_external_reads_deny_unknown_private_or_unpersisted_keys(gateway):
    sessions, _, get = gateway
    public_key = "telegram:public"
    _conversation(sessions, public_key)
    _conversation(sessions, "cli:with-history")
    _conversation(sessions, "matrix:!private:example.org", **{SESSION_TYPE_KEY: "private"})
    await sessions.state.register_transient("telegram:temporary")
    for key in ["cli:with-history", "matrix:!private:example.org", "telegram:temporary", "telegram:missing"]:
        for suffix in ["/webui-thread", "/webui-thread/prompts"]:
            response = await get(_session_path(key, suffix), etag="*")
            assert response.status_code == 404
    for suffix in ["/automations", "/subagents", "/file-preview", "/webui-thread/trace-detail"]:
        assert (await get(_session_path(public_key, suffix))).status_code == 404
    assert (await get(_session_path(public_key, "/delete"))).status_code == 405
    assert (await get(_session_path(public_key))).status_code == 200


async def test_projection_filters_internal_history_and_preserves_trusted_attribution(gateway):
    sessions, _, get = gateway
    key = "telegram:with-history"
    session = sessions.get_or_create(key)
    context = {"type": "text", "text": "private runtime context"}
    session.add_message("user", [{"type": "text", "text": "old prompt"}, context], **{
        RUNTIME_CONTEXT_HISTORY_META: {"version": 1, "blocks": [context]},
    })
    session.add_message("assistant", "<think>private reasoning</think>old reply")
    session.add_message("user", "do not show me", **{HIDDEN_HISTORY_META: {"kind": "internal"}})
    session.add_message("user", "[Subagent 'private']\n\nTask: secret\n\nResult: private\nSummarize this naturally")
    session.add_message("user", "/new", _command=True)
    session.add_message("assistant", "internal tool call", tool_calls=[{"id": "call-1"}])
    session.add_message("tool", "unsanitized tool output", tool_call_id="call-1")
    input_id = "input:92cf6446886345f8b115cf6fe9052038"
    session.add_message("user", "hello from Telegram", entry_channel="telegram", input_id=input_id)
    session.add_message("assistant", "telegram reply", response_input_ids=[input_id])
    session.add_message("user", "hello from WebUI", entry_channel="webui", input_id="user:web-1", webui_turn_id="web-1")
    session.add_message("assistant", "web answer", response_input_ids=["user:web-1"])
    sessions.save(session)
    # Old display facts must never mix into the canonical timeline.
    sessions.append_history(key, [HistoryFact(HistoryKind.INPUT, content={"text": "display-only"})])

    response = await get(_session_path(key, include_model_requests=1))
    assert response.status_code == 200
    body = json.loads(response.body)
    old_user, old_reply, telegram, telegram_reply, web, web_reply = body["events"]
    assert [event["text"] for event in body["events"]] == [
        "old prompt", "old reply", "hello from Telegram", "telegram reply", "hello from WebUI", "web answer",
    ]
    assert "entry_channel" not in old_user and "entry_channel" not in old_reply
    assert telegram["entry_channel"] == "Telegram"
    assert telegram_reply["response_input_ids"] == [input_id]
    assert web["entry_channel"] == "WebUI" and web["input_id"] == "user:web-1"
    assert web["turn_id"] == web_reply["turn_id"] == "web-1"
    assert web_reply["entry_channel"] == "WebUI"
    assert body["completed_turn_ids"] == ["web-1"]
    assert body["active_turn_id"] is None


async def test_latest_etag_tracks_active_turn_and_new_canonical_reply(gateway, monkeypatch):
    sessions, _, get = gateway
    key = "telegram:active"
    session = sessions.get_or_create(key)
    session.add_message("user", "waiting", entry_channel="webui", input_id="user:web-turn", webui_turn_id="web-turn")
    sessions.save(session)
    alias = channel_session_chat_id(key)
    assert alias is not None
    path = _session_path(key, direction="latest", limit=2)
    idle = await get(path)
    assert idle.status_code == 200
    etag = idle.headers["ETag"]
    with monkeypatch.context() as patch:
        def no_scan(*_args, **_kwargs):
            pytest.fail("conditional GET must not walk the model history")

        patch.setattr(sessions, "project_session_messages", no_scan)
        assert (await get(path, etag=etag)).status_code == 304
    register_queued_websocket_turn_if_idle(alias, "web-turn")
    try:
        active = await get(path, etag=etag)
        assert active.status_code == 200
        active_data = json.loads(active.body)
        assert active_data["active_turn_id"] == "web-turn"
        assert active_data["has_pending_tool_calls"] is True
        assert active_data["completed_turn_ids"] == []
        draft = await sessions.state.get(key)
        draft.add_message("assistant", "new reply", response_input_ids=["user:web-turn"])
        await sessions.state.finish_turn(draft)
        committed = await get(path, etag=active.headers["ETag"])
        assert committed.status_code == 200
        assert json.loads(committed.body)["completed_turn_ids"] == []
    finally:
        clear_websocket_turns(alias)
    completed = await get(path, etag=committed.headers["ETag"])
    assert completed.status_code == 200
    data = json.loads(completed.body)
    assert data["events"][-1]["text"] == "new reply"
    assert data["events"][0]["projection_id"] == active_data["events"][0]["projection_id"]
    assert data["active_turn_id"] is None
    assert data["has_pending_tool_calls"] is False
    assert data["completed_turn_ids"] == ["web-turn"]


async def test_channel_prompt_navigation_and_older_newer_pages_share_stable_ids(gateway):
    sessions, _, get = gateway
    key = "telegram:pagination"
    session = sessions.get_or_create(key)
    for number in range(4):
        input_id = f"input:{number:032x}"
        session.add_message("user", f"prompt {number}", input_id=input_id, entry_channel="telegram")
        session.add_message("tool", "not a visible event")
        session.add_message("assistant", f"answer {number}", response_input_ids=[input_id])
    sessions.save(session)

    async def page(**query):
        response = await get(_session_path(key, limit=2, **query))
        assert response.status_code == 200
        body = json.loads(response.body)
        assert body["page"]["history_generation"] == session.generation
        return body["events"], body["page"]

    latest, last_page = await page(direction="latest")
    assert [event["text"] for event in latest] == ["prompt 3", "answer 3"]
    assert last_page["has_more_before"] and not last_page["has_more_after"]
    older, older_page = await page(before=last_page["before_cursor"])
    assert [event["text"] for event in older] == ["prompt 2", "answer 2"]
    newer, _ = await page(after=older_page["after_cursor"])
    assert newer == latest

    path = _session_path(key, "/webui-thread/prompts")
    response = await get(path)
    index = json.loads(response.body)
    assert index["replaceFrom"] == 0
    assert [prompt["answerPreview"] for prompt in index["prompts"]] == [f"answer {n}" for n in range(4)]
    assert (await get(path, etag=response.headers["ETag"])).status_code == 304
    anchor = index["prompts"][0]
    first, first_page = await page(after=anchor["cursor"])
    assert [event["text"] for event in first] == ["prompt 0", "answer 0"]
    assert first[0]["projection_id"] == anchor["id"]
    assert not first_page["has_more_before"] and first_page["has_more_after"]
    assert (await get(_session_path(key, after="not-a-cursor"))).status_code == 400


@pytest.mark.parametrize("gateway", [False], indirect=True)
async def test_external_media_signs_allowed_paths_only_and_rechecks_borrowed_scope(gateway, tmp_path):
    sessions, workspace, get = gateway
    key = "telegram:attachments"
    image = workspace / "allowed.png"
    image.write_bytes(b"workspace-image")
    download = get_media_dir("telegram") / "from-telegram.png"
    download.write_bytes(b"channel-image")
    unsafe = tmp_path / "secret.txt"
    unsafe.write_bytes(b"secret")
    symlink = workspace / "escape.txt"
    symlink.symlink_to(unsafe)
    session = sessions.get_or_create(key)
    session.metadata[WORKSPACE_SCOPE_METADATA_KEY] = {"project_path": str(tmp_path), "access_mode": "full"}
    session.add_message("user", f"a picture\n[image: {unsafe}]", media=[str(image), str(download), str(symlink)], **{
        INBOUND_META_LOCAL_MEDIA: [str(image), str(symlink)],
    })
    session.add_message("assistant", "created a picture ![preview](allowed.png)", media=[str(download), str(unsafe)])
    sessions.save(session)
    response = await get(_session_path(key))
    assert response.status_code == 200
    assert str(unsafe).encode() not in response.body
    body = json.loads(response.body)
    assert body["workspace_scope"]["access_mode"] == "full"
    user, assistant = body["events"]
    assert user["text"] == "a picture"
    local, uploaded = user["media_urls"]
    assert [item["name"] for item in [local, uploaded]] == ["allowed.png", "from-telegram.png"]
    assert assistant["media_urls"] == [uploaded]
    assert assistant["text"] == f"created a picture ![preview]({local['url']})"
    assert (await get(local["url"], authenticated=False)).body == b"workspace-image"
    assert (await get(uploaded["url"], authenticated=False)).body == b"channel-image"
    image.unlink()
    image.symlink_to(unsafe)
    assert (await get(local["url"], authenticated=False)).status_code == 403
    await sessions.state.delete(key)
    assert (await get(local["url"], authenticated=False)).status_code == 404
