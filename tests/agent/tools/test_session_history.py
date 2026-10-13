"""Session tools read full canonical history independently of WebUI replay."""

from __future__ import annotations

import json

import pytest

from nanobot.agent.tools.context import RequestContext, request_context
from nanobot.agent.tools.sessions import ReadSessionTool, SearchSessionsTool
from nanobot.session.manager import SessionManager
from nanobot.webui.transcript import append_transcript_object


@pytest.mark.asyncio
@pytest.mark.parametrize("compacted", [False, True])
@pytest.mark.parametrize("tool_name", ["search", "read"])
async def test_session_tools_find_old_matches_in_full_session(
    tmp_path, compacted, tool_name,
):
    manager = SessionManager(tmp_path)
    key = "sdk:history"
    session = manager.get_or_create(key)
    session.metadata.update({"title": "Project notes", "title_user_edited": True})
    for index in range(180):
        text = f"launch decision {index}" if index < 10 else f"unrelated update {index}"
        session.add_message("user", text)
        session.add_message("assistant", f"acknowledged {index}")
    if compacted:
        session.commit_summary_checkpoint("Project updates are complete.")
        assert session.get_history() == []
    manager.save(session)
    manager = SessionManager(tmp_path)

    with request_context(RequestContext(
        channel="sdk", chat_id="current", session_key="sdk:current",
    )):
        if tool_name == "search":
            output = json.loads(await SearchSessionsTool(manager).execute(query="launch decision"))
            assert [item["session_key"] for item in output["results"]] == [key]
            matches = output["results"][0]["excerpts"]
            expected = range(8, 10)
        else:
            output = json.loads(await ReadSessionTool(manager).execute(
                session_key=key, query="launch decision",
            ))
            matches = output["messages"]
            expected = range(2, 10)
            latest = json.loads(await ReadSessionTool(manager).execute(session_key=key))
            assert len(latest["messages"]) == 8
            assert [item["message_index"] for item in latest["messages"]] == list(range(352, 360))
            assert latest["messages"][-1]["content"] == "acknowledged 179"

    assert [item["content"] for item in matches] == [f"launch decision {i}" for i in expected]
    assert [item["message_index"] for item in matches] == [i * 2 for i in expected]


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["canonical", "transcript", "mixed"])
async def test_session_tools_use_canonical_records_after_restart(tmp_path, monkeypatch, state):
    webui_dir = tmp_path / "webui"
    monkeypatch.setattr("nanobot.webui.transcript.get_webui_dir", lambda: webui_dir)
    manager = SessionManager(tmp_path)
    key = "websocket:history"
    if state != "transcript":
        session = manager.get_or_create(key)
        session.metadata.update({"title": "Project notes", "title_user_edited": True})
        session.add_message("user", "canonical needle")
        manager.save(session)
    if state != "canonical":
        append_transcript_object(key, {
            "event": "user", "chat_id": "history", "text": "display-only needle",
        })
        append_transcript_object(key, {"event": "turn_end", "chat_id": "history"})

    def durable_files():
        return {
            path: path.read_bytes()
            for root in (manager.sessions_dir, webui_dir)
            for path in root.rglob("*.jsonl")
        }

    original = durable_files()
    for _ in range(2):
        manager = SessionManager(tmp_path)
        with request_context(RequestContext(
            channel="websocket", chat_id="current", session_key="websocket:current",
        )):
            search = json.loads(await SearchSessionsTool(manager).execute(query="needle"))
            read = await ReadSessionTool(manager).execute(session_key=key, query="needle")
            display_search = json.loads(await SearchSessionsTool(manager).execute(query="display-only"))
        if state == "transcript":
            assert search["results"] == []
            assert read.is_error and "session not found" in str(read)
        else:
            assert [row["session_key"] for row in search["results"]] == [key]
            assert search["results"][0]["excerpts"][0]["content"] == "canonical needle"
            assert [item["content"] for item in json.loads(read)["messages"]] == ["canonical needle"]
        assert display_search["results"] == []
        assert durable_files() == original
