"""Session tools must not mistake a transcript page for the whole conversation."""

from __future__ import annotations

import json

import pytest

from nanobot.agent.tools.context import RequestContext, request_context
from nanobot.agent.tools.sessions import ReadSessionTool, SearchSessionsTool
from nanobot.session.manager import SessionManager
from nanobot.webui.transcript import append_transcript_object, webui_transcript_segments_dir


@pytest.mark.asyncio
@pytest.mark.parametrize("compacted", [False, True])
@pytest.mark.parametrize("tool_name", ["search", "read"])
async def test_session_tools_find_old_matches_beyond_the_latest_page(
    tmp_path, monkeypatch, compacted, tool_name,
):
    webui_dir = tmp_path / "webui"
    monkeypatch.setattr("nanobot.webui.transcript.get_webui_dir", lambda: webui_dir)
    monkeypatch.setattr("nanobot.webui.session_list_index.get_webui_dir", lambda: webui_dir)
    if compacted:
        monkeypatch.setattr("nanobot.webui.transcript._ACTIVE_TRANSCRIPT_ROTATE_BYTES", 8192)
        monkeypatch.setattr("nanobot.webui.transcript._TARGET_ACTIVE_TRANSCRIPT_BYTES", 4096)
    manager = SessionManager(tmp_path)
    key = "websocket:history"
    session = manager.get_or_create(key)
    session.metadata.update({"title": "Project notes", "title_user_edited": True})
    for index in range(180):
        text = f"launch decision {index}" if index < 10 else f"unrelated update {index}"
        session.add_message("user", text)
        session.add_message("assistant", f"acknowledged {index}")
        for record in (
            {"event": "user", "text": text},
            {"event": "message", "text": f"acknowledged {index}"},
            {"event": "turn_end"},
        ):
            append_transcript_object(key, record)
    if compacted:
        session.messages = session.messages[-2:]
        assert any(webui_transcript_segments_dir(key).glob("*.jsonl"))
    manager.save(session)

    with request_context(RequestContext(
        channel="websocket", chat_id="current", session_key="websocket:current",
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
