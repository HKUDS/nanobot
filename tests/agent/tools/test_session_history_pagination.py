"""Session tools must not mistake a transcript page for the whole conversation."""

from __future__ import annotations

import json
import weakref

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


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["", "visible"])
async def test_read_releases_raw_pages_while_preserving_global_indexes(tmp_path, monkeypatch, query):
    """Tool results are tiny; do not retain every page's raw trace payloads."""
    class TrackedMessage(dict):
        pass

    manager = SessionManager(tmp_path)
    key = "websocket:history"
    manager.save(manager.get_or_create(key))
    refs = []
    calls = []

    def page(_key, *, before=None, **_kwargs):
        # The immediately previous response can still be live while requesting
        # the next one. Older raw messages must already have been released.
        assert sum(ref() is not None for ref in refs) <= 5
        index = int(before) if before is not None else 0
        calls.append(index)
        start = (9 - index) * 5
        messages = [
            TrackedMessage(role="user", content=f"visible {start}"),
            TrackedMessage(role="tool", content="private tool result"),
            TrackedMessage(role="assistant", content=f"visible {start + 2}"),
            TrackedMessage(role="user", content="hidden", _hidden_history=True),
            TrackedMessage(role="assistant", content=""),
        ]
        refs.extend(weakref.ref(message) for message in messages)
        return {"messages": messages, "page": {
            "has_more_before": index < 9,
            "before_cursor": str(index + 1) if index < 9 else None,
        }}

    monkeypatch.setattr("nanobot.webui.session_access.build_webui_thread_response", page)
    with request_context(RequestContext(
        channel="websocket", chat_id="current", session_key="websocket:current",
    )):
        result = json.loads(await ReadSessionTool(manager).execute(session_key=key, query=query))
    expected = [30, 32, 35, 37, 40, 42, 45, 47]
    assert [item["message_index"] for item in result["messages"]] == expected
    assert [item["content"] for item in result["messages"]] == [f"visible {i}" for i in expected]
    assert calls == list(range(10))
    assert not any(ref() is not None for ref in refs)


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["canonical", "transcript", "mixed"])
async def test_session_tools_preserve_durable_sources_after_index_rebuild_and_restart(
    tmp_path, monkeypatch, state,
):
    webui_dir = tmp_path / "webui"
    monkeypatch.setattr("nanobot.webui.transcript.get_webui_dir", lambda: webui_dir)
    monkeypatch.setattr("nanobot.webui.session_list_index.get_webui_dir", lambda: webui_dir)
    manager = SessionManager(tmp_path)
    key = "websocket:history"
    if state != "transcript":
        session = manager.get_or_create(key)
        session.metadata.update({"title": "Project notes", "title_user_edited": True})
        session.add_message("user", "canonical needle")
        manager.save(session)
    if state != "canonical":
        append_transcript_object(key, {
            "event": "user", "chat_id": "history", "text": "display needle",
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
        # Read-only tools may rebuild derived indexes, not canonical records.
        manager = SessionManager(tmp_path)
        with request_context(RequestContext(
            channel="websocket", chat_id="current", session_key="websocket:current",
        )):
            search = json.loads(await SearchSessionsTool(manager).execute(query="needle"))
            read = await ReadSessionTool(manager).execute(session_key=key, query="needle")
        assert [row["session_key"] for row in search["results"]] == [key]
        if state == "transcript":
            # Existing read/mention validation requires canonical metadata.
            assert "session not found" in str(read)
            assert manager.read_session_metadata(key) is None
        else:
            expected = "canonical needle" if state == "canonical" else "display needle"
            assert [item["content"] for item in json.loads(read)["messages"]] == [expected]
        assert durable_files() == original
        (manager.sessions_dir / ".webui_session_index.json").unlink(missing_ok=True)
