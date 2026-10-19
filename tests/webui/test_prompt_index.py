"""Complete, lightweight navigation uses the same IDs and cursors as replay."""

import json
import time

import pytest
from websockets.datastructures import Headers
from websockets.http11 import Request

from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket.runtime import WebSocketConfig
from nanobot.session.manager import SessionManager
from nanobot.webui import transcript
from nanobot.webui.client_contract import webui_contract
from nanobot.webui.gateway_services import build_gateway_services


def test_complete_index_and_bidirectional_pages_without_loading_sqlite(tmp_path, monkeypatch):
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(transcript, "_ACTIVE_TRANSCRIPT_ROTATE_BYTES", 2000)
    monkeypatch.setattr(transcript, "_TARGET_ACTIVE_TRANSCRIPT_BYTES", 1000)
    key = "websocket:navigation"
    for i in range(120):
        transcript.append_transcript_object(key, {"event": "user", "chat_id": "navigation", "text": f"question {i}", "turn_id": f"t{i}"})
        transcript.append_transcript_object(key, {"event": "message", "chat_id": "navigation", "text": "answer " + "x" * 200, "turn_id": f"t{i}"})
        transcript.append_transcript_object(key, {"event": "turn_end", "chat_id": "navigation", "turn_id": f"t{i}"})
    index = transcript.build_prompt_index(key)
    assert len(index) == 120
    assert not (tmp_path / "sessions" / "sessions.sqlite3").exists()
    latest = transcript.build_webui_thread_response(key, limit=3)
    assert len(latest["events"]) < len(index)
    target = index[42]
    stats = transcript.TranscriptReplayStats()
    page = transcript.build_webui_thread_response(key, after=target["cursor"], limit=6, stats=stats)
    assert page["events"][0]["projection_id"] == target["id"]
    assert page["events"][0]["text"] == "question 42"
    assert page["page"]["user_message_offset"] == 42
    assert page["page"]["has_more_before"] and page["page"]["has_more_after"]
    assert stats.parsed_records < 40  # Not the 360-record transcript.
    newer = transcript.build_webui_thread_response(key, after=page["page"]["after_cursor"], limit=6)
    older = transcript.build_webui_thread_response(key, before=newer["page"]["before_cursor"], limit=6)
    assert older["events"] == page["events"]
    # Warm navigation uses file metadata + cached summaries, not replay.
    with monkeypatch.context() as patch:
        patch.setattr(transcript, "_read_transcript_file", lambda _: (_ for _ in ()).throw(AssertionError("replayed history")))
        assert transcript.build_prompt_index(key) == index
    transcript.append_transcript_object(key, {"event": "user", "chat_id": "navigation", "text": "new question"})
    assert len(transcript.build_prompt_index(key)) == 121


def test_oversized_turn_keeps_matching_navigation_identity(tmp_path, monkeypatch):
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(transcript, "_MAX_TRANSCRIPT_PAGE_RECORDS", 6)
    key = "websocket:large-turn"
    transcript.append_transcript_object(key, {"event": "user", "chat_id": "large-turn", "text": "target"})
    for i in range(20):
        transcript.append_transcript_object(key, {"event": "message", "chat_id": "large-turn", "kind": "tool_hint", "text": str(i)})
    transcript.append_transcript_object(key, {"event": "message", "chat_id": "large-turn", "text": "done"})
    transcript.append_transcript_object(key, {"event": "turn_end", "chat_id": "large-turn"})
    target = transcript.build_prompt_index(key)[0]
    page = transcript.build_webui_thread_response(key, after=target["cursor"], limit=40)
    assert page["page"]["truncated_oversized_turn"]
    assert page["events"][0]["projection_id"] == target["id"]
    assert len(target["answerPreview"]) <= 240


@pytest.mark.asyncio
async def test_navigation_public_routes_auth_validation_and_old_reads(tmp_path, monkeypatch):
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    gateway = build_gateway_services(
        config=WebSocketConfig(), bus=MessageBus(), session_manager=None,
        static_dist_path=None, workspace_path=tmp_path, config_path=tmp_path / "config.json",
        default_restrict_to_workspace=False, runtime_model_name=None,
        runtime_surface="browser", runtime_capabilities_overrides=None,
    )
    path = "/api/sessions/websocket%3Atest/webui-thread"
    denied = await gateway.http._dispatch_session_routes(Request(path + "/prompts", Headers()), path + "/prompts")
    assert denied.status_code == 401
    gateway.tokens.api_tokens["test-token"] = time.monotonic() + 60
    headers = Headers([("Authorization", "Bearer test-token")])
    transcript.append_transcript_object("websocket:test", {"event": "user", "chat_id": "test", "text": "hello"})
    response = await gateway.http._dispatch_session_routes(Request(path + "/prompts", headers), path + "/prompts")
    prompt = json.loads(response.body)["prompts"][0]
    revision = json.loads(response.body)["revision"]
    revalidate = Headers([("Authorization", "Bearer test-token"), ("If-None-Match", f'"{revision}"')])
    unchanged = await gateway.http._dispatch_session_routes(Request(path + "/prompts", revalidate), path + "/prompts")
    assert unchanged.status_code == 304 and not unchanged.body
    denied = await gateway.http._dispatch_session_routes(Request(path + "/prompts", Headers([("If-None-Match", f'"{revision}"')])), path + "/prompts")
    assert denied.status_code == 401
    current = await gateway.http._dispatch_session_routes(Request(path + "?after=" + prompt["cursor"], headers), path)
    legacy = await gateway.http._dispatch_session_routes(Request(path + "?direction=latest&limit=40", headers), path)
    assert current.status_code == legacy.status_code == 200
    assert json.loads(current.body)["events"] == json.loads(legacy.body)["events"]
    invalid = await gateway.http._dispatch_session_routes(Request(path + "?after=bad", headers), path)
    assert invalid.status_code == 400
    assert "webui.prompt-navigation.v1" in webui_contract()["capabilities"]


def test_summary_deltas_rebuild_after_append_rewrite_eviction_and_delete(tmp_path, monkeypatch):
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:index-delta"
    for i in range(100):
        transcript.append_transcript_object(key, {"event": "user", "text": f"question {i}", "turn_id": f"t{i}"})
        transcript.append_transcript_object(key, {"event": "turn_end", "turn_id": f"t{i}"})
    initial = transcript.prompt_index_response(key, None)
    assert len(initial["prompts"]) == 100
    transcript.append_transcript_object(key, {"event": "user", "text": "next", "turn_id": "next"})
    appended = transcript.prompt_index_response(key, initial["revision"])
    assert appended["replaceFrom"] == 100
    assert len(appended["prompts"]) == 1
    assert [*initial["prompts"], *appended["prompts"]] == transcript.build_prompt_index(key)
    # A late answer changes the last preview; it must replace that prompt, not append it.
    transcript.append_transcript_object(key, {"event": "message", "text": "answer", "turn_id": "next"})
    changed = transcript.prompt_index_response(key, appended["revision"])
    assert changed["replaceFrom"] == 100
    assert changed["prompts"][0]["answerPreview"] == "answer"
    transcript.delete_webui_transcript(key)
    transcript.append_transcript_object(key, {"event": "user", "text": "replacement"})
    replaced = transcript.prompt_index_response(key, changed["revision"])
    assert replaced["replaceFrom"] == 0
    assert len(replaced["prompts"]) == 1
    transcript._PROMPT_SNAPSHOTS.clear()  # Restart/eviction sends a complete response.
    assert transcript.prompt_index_response(key, replaced["revision"])["replaceFrom"] == 0
    transcript.delete_webui_transcript(key)
    assert transcript.prompt_index_response(key, replaced["revision"])["prompts"] == ()


@pytest.mark.parametrize("input_id", [None, "injected-guidance"])
def test_recovered_prompt_identity_time_and_cursor_survive_pages(tmp_path, monkeypatch, input_id):
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:recovered-navigation"
    messages = [{"role": "system", "content": "context"}]
    for i in range(2):
        user = {"role": "user", "content": "same guidance", "timestamp": f"2026-06-02T10:0{i}:00+00:00"}
        if input_id:
            user["webui_turn_id"] = f"{input_id}-{i}"
        messages.extend([user, {"role": "assistant", "content": f"answer {i}"}])
        transcript.append_transcript_object(key, {"event": "message", "text": f"answer {i}", "turn_id": f"execution-{i}"})
        transcript.append_transcript_object(key, {"event": "turn_end", "turn_id": f"execution-{i}"})
    def loader():
        return messages

    cold_page = transcript.build_webui_thread_response(key, limit=1, session_messages_loader=loader)
    index = transcript.build_prompt_index(key, session_messages_loader=loader)
    assert transcript.build_webui_thread_response(key, limit=1, session_messages_loader=loader) == cold_page
    assert len(index) == 2
    assert index[0]["id"] != index[1]["id"]
    assert [prompt["createdAt"] for prompt in index] == [1780394400000, 1780394460000]
    for position, prompt in enumerate(index):
        page = transcript.build_webui_thread_response(key, after=prompt["cursor"], limit=1, session_messages_loader=loader)
        user = next(event for event in page["events"] if event["event"] == "user_message")
        assert user["projection_id"] == prompt["id"]
        assert user["created_at_ms"] == prompt["createdAt"]
        assert user.get("turn_id") == (f"{input_id}-{position}" if input_id else None)
    assert transcript.build_prompt_index(key, session_messages_loader=loader) == index


@pytest.mark.asyncio
async def test_recovered_public_index_and_page_validators_include_canonical_timestamp(tmp_path, monkeypatch):
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:canonical-revision"
    manager = SessionManager(tmp_path)
    session = manager.get_or_create(key)
    session.messages = [
        {"role": "user", "content": "guidance", "webui_turn_id": "input", "timestamp": "2026-06-02T10:00:00+00:00"},
        {"role": "assistant", "content": "answer"},
    ]
    manager.save(session)
    for event in ({"event": "message", "text": "answer"}, {"event": "turn_end"}):
        transcript.append_transcript_object(key, event)
    gateway = build_gateway_services(
        config=WebSocketConfig(), bus=MessageBus(), session_manager=manager,
        static_dist_path=None, workspace_path=tmp_path, config_path=tmp_path / "config.json",
        default_restrict_to_workspace=False, runtime_model_name=None,
        runtime_surface="browser", runtime_capabilities_overrides=None,
    )
    gateway.tokens.api_tokens["test-token"] = time.monotonic() + 60
    auth = [("Authorization", "Bearer test-token")]
    base = "/api/sessions/websocket%3Acanonical-revision/webui-thread"
    initial = {}
    for path in (base, base + "/prompts"):
        response = await gateway.http._dispatch_session_routes(Request(path, Headers(auth)), path)
        assert response.status_code == 200
        initial[path] = response
        unchanged = await gateway.http._dispatch_session_routes(
            Request(path, Headers([*auth, ("If-None-Match", response.headers["ETag"])])), path,
        )
        assert unchanged.status_code == 304
    # A canonical-only update must invalidate the recovered display even when
    # transcript artifacts and the session's updated_at are unchanged.
    session.messages[0]["timestamp"] = "2026-06-02T10:01:00+00:00"
    manager.save(session)
    changed = {}
    for path, previous in initial.items():
        request_path = path + "?since=" + json.loads(previous.body)["revision"]
        response = await gateway.http._dispatch_session_routes(
            Request(request_path, Headers([*auth, ("If-None-Match", previous.headers["ETag"])])), path,
        )
        assert response.status_code == 200
        assert response.headers["ETag"] != previous.headers["ETag"]
        changed[path] = json.loads(response.body)
    user = next(event for event in changed[base]["events"] if event["event"] == "user_message")
    prompt = changed[base + "/prompts"]["prompts"][0]
    assert user["created_at_ms"] == prompt["createdAt"] == 1780394460000
    assert user["projection_id"] == prompt["id"]
    assert prompt["id"] == json.loads(initial[base + "/prompts"].body)["prompts"][0]["id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("missing_user", [False, True])
async def test_cached_history_routes_skip_replay_and_canonical_reads(tmp_path, monkeypatch, missing_user):
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:cached-history"
    manager = SessionManager(tmp_path)
    session = manager.get_or_create(key)
    for i in range(3):
        session.messages.extend([
            {"role": "user", "content": f"question {i}", "webui_turn_id": f"input-{i}"},
            {"role": "assistant", "content": f"answer {i}"},
        ])
        if not missing_user or i < 2:
            transcript.append_transcript_object(key, {"event": "user", "text": f"question {i}", "turn_id": f"input-{i}"})
        transcript.append_transcript_object(key, {"event": "message", "text": f"answer {i}"})
        transcript.append_transcript_object(key, {"event": "turn_end"})
    manager.save(session)
    gateway = build_gateway_services(
        config=WebSocketConfig(), bus=MessageBus(), session_manager=manager,
        static_dist_path=None, workspace_path=tmp_path, config_path=tmp_path / "config.json",
        default_restrict_to_workspace=False, runtime_model_name=None,
        runtime_surface="browser", runtime_capabilities_overrides=None,
    )
    gateway.tokens.api_tokens["test-token"] = time.monotonic() + 60
    auth = [("Authorization", "Bearer test-token")]
    base = "/api/sessions/websocket%3Acached-history/webui-thread"
    initial = {}
    for path in (base + "?direction=latest&limit=2", base + "/prompts"):
        response = await gateway.http._dispatch_session_routes(Request(path, Headers(auth)), path.split("?")[0])
        assert response.status_code == 200
        initial[path] = response
    prompts = json.loads(initial[base + "/prompts"].body)
    assert len(prompts["prompts"]) == 3

    def unexpected_work(*args, **kwargs):
        pytest.fail("unchanged history was rebuilt")

    monkeypatch.setattr(transcript, "_build_prompt_view", unexpected_work)
    monkeypatch.setattr(transcript, "_read_transcript_file", unexpected_work)
    monkeypatch.setattr(manager, "read_session_file", unexpected_work)
    monkeypatch.setattr("nanobot.webui.ws_http.build_webui_thread_response", unexpected_work)
    for path, previous in initial.items():
        conditional = path + ("&" if "?" in path else "?") + "since=" + json.loads(previous.body)["revision"]
        response = await gateway.http._dispatch_session_routes(
            Request(conditional, Headers([*auth, ("If-None-Match", previous.headers["ETag"])])), path.split("?")[0],
        )
        assert response.status_code == 304 and not response.body
    # An ordinary directory read also reuses the view, with or without `since`.
    for suffix in ("", "?since=" + prompts["revision"]):
        response = await gateway.http._dispatch_session_routes(Request(base + "/prompts" + suffix, Headers(auth)), base + "/prompts")
        assert response.status_code == 200
        data = json.loads(response.body)
        assert data["prompts"] == ([] if suffix else prompts["prompts"])
        assert data["replaceFrom"] == (3 if suffix else 0)
    # Eviction must not turn a valid conditional request into a replay either.
    transcript._PROMPT_SNAPSHOTS.clear()
    for path, previous in initial.items():
        response = await gateway.http._dispatch_session_routes(
            Request(path, Headers([*auth, ("If-None-Match", previous.headers["ETag"])])), path.split("?")[0],
        )
        assert response.status_code == 304 and not response.body


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["", "/prompts"])
async def test_canonical_change_during_recovery_is_not_cached(tmp_path, monkeypatch, endpoint):
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:racing-history"
    manager = SessionManager(tmp_path)
    session = manager.get_or_create(key)
    session.messages = [
        {"role": "user", "content": "question", "timestamp": "2026-06-02T10:00:00+00:00"},
        {"role": "assistant", "content": "answer"},
    ]
    manager.save(session)
    for event in ({"event": "message", "text": "answer"}, {"event": "turn_end"}):
        transcript.append_transcript_object(key, event)
    gateway = build_gateway_services(
        config=WebSocketConfig(), bus=MessageBus(), session_manager=manager,
        static_dist_path=None, workspace_path=tmp_path, config_path=tmp_path / "config.json",
        default_restrict_to_workspace=False, runtime_model_name=None,
        runtime_surface="browser", runtime_capabilities_overrides=None,
    )
    gateway.tokens.api_tokens["test-token"] = time.monotonic() + 60
    auth = Headers([("Authorization", "Bearer test-token")])
    original_read = manager.read_session_file
    changed = False

    def read_and_commit(key):
        nonlocal changed
        data = original_read(key)
        if not changed:
            changed = True
            session.messages[0]["timestamp"] = "2026-06-02T10:01:00+00:00"
            manager.save(session)
        return data

    monkeypatch.setattr(manager, "read_session_file", read_and_commit)
    path = "/api/sessions/websocket%3Aracing-history/webui-thread" + endpoint
    mixed = await gateway.http._dispatch_session_routes(Request(path, auth), path)
    assert changed and mixed.status_code == 200
    assert "ETag" not in mixed.headers and "revision" not in json.loads(mixed.body)
    current = await gateway.http._dispatch_session_routes(Request(path, auth), path)
    assert current.status_code == 200 and current.headers["ETag"]
    data = json.loads(current.body)
    if endpoint:
        assert data["prompts"][0]["createdAt"] == 1780394460000
    else:
        user = next(event for event in data["events"] if event["event"] == "user_message")
        assert user["created_at_ms"] == 1780394460000


@pytest.mark.parametrize("with_anchor", [False, True])
def test_indexed_backfill_preserves_unique_in_suffix_matching(tmp_path, monkeypatch, with_anchor):
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:repeated-answers"
    answers = ["same answer", "anchor answer", "same answer"] if with_anchor else ["same answer"] * 2
    messages = []
    for position, answer in enumerate(answers):
        user = {"role": "user", "content": f"question {position}", "webui_turn_id": f"input-{position}"}
        messages.extend([user, {"role": "assistant", "content": answer}])
        if position < len(answers) - 1:
            transcript.append_transcript_object(key, {"event": "user", "text": user["content"], "turn_id": user["webui_turn_id"]})
        transcript.append_transcript_object(key, {"event": "message", "text": answer})
        transcript.append_transcript_object(key, {"event": "turn_end"})
    prompts = transcript.build_prompt_index(key, session_messages_loader=lambda: messages)
    # A unique intervening answer advances the alignment past the first duplicate.
    assert len(prompts) == (len(answers) if with_anchor else 1)
    page = transcript.build_webui_thread_response(key, limit=1, session_messages=messages)
    users = [event for event in page["events"] if event["event"] == "user_message"]
    assert [user["text"] for user in users] == (["question 2"] if with_anchor else [])
    if with_anchor:
        assert users[0]["projection_id"] == prompts[-1]["id"]
