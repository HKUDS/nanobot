"""One SQLite owner for model messages and durable, generation-bound display facts."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from nanobot.session.display_history import HistoryFact, HistoryKind
from nanobot.session.manager import SessionManager
from nanobot.session.sqlite_store import SessionConflictError
from nanobot.webui.forking import create_webui_chat_fork
from nanobot.webui.transcript import WebUITranscriptRecorder, build_webui_thread_response


def _manager(tmp_path: Path) -> SessionManager:
    return SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "sessions")


async def test_display_facts_survive_reopen_without_entering_model_history(tmp_path):
    sessions = _manager(tmp_path)
    session = await sessions.state.get("websocket:durable")
    session.add_message("user", "question")
    session.add_message("assistant", "answer")
    await sessions.state.finish_turn(session)
    facts = [
        HistoryFact(HistoryKind.INPUT, {"text": "question"}, "turn-1", "user", 1, 1000),
        HistoryFact(HistoryKind.REASONING_SEGMENT, {"text": "reasoning"}, "turn-1", "reasoning", 2, 1001),
        HistoryFact(HistoryKind.FILE_ACTIVITY, {"edits": [{"path": "a.py", "diff": "-old\n+new"}]}, "turn-1", "activity", 3, 1002),
        HistoryFact(HistoryKind.ANSWER_SEGMENT, {"text": "answer", "response_sources": [{
            "provider": "test", "model": "actual-fallback", "preset": "default", "fallback": True,
        }]}, "turn-1", "answer", 4, 1003),
        HistoryFact(HistoryKind.COMPLETION, {"usage": {"total_tokens": 30}, "round_usages": [{"total_tokens": 30}],
                    "latency_ms": 40, "outcome": "failed", "failure_message": "model unavailable"},
                    "turn-1", "complete", 5, 1004),
    ]
    await sessions.state.append_history(session.key, facts, expected_generation=session.generation)
    with closing(sqlite3.connect(sessions.sessions_dir / "sessions.sqlite3")) as db:
        stored = db.execute("SELECT record FROM history_entries ORDER BY position").fetchall()
        assert [json.loads(row[0])["kind"] for row in stored] == [fact.kind for fact in facts]
        assert all("chat_id" not in json.loads(row[0]) and "event" not in json.loads(row[0]) for row in stored)
    await sessions.state.aclose()

    reopened = _manager(tmp_path)
    assert reopened.project_history(session.key, lambda history: history.all_facts()) == facts
    model = reopened.read_session_file(session.key)
    assert [message["content"] for message in model["messages"]] == ["question", "answer"]
    payload = reopened.project_history(session.key, lambda history: build_webui_thread_response(session.key, history=history))
    assert payload["completed_turn_ids"] == ["turn-1"]
    terminal = next(event for event in payload["events"] if event["event"] == "turn_end")
    assert terminal["failure_message"] == "model unavailable" and terminal["outcome"] == "failed"
    assert terminal["round_usages"] == [{"total_tokens": 30}]
    assert any(event.get("edits") == facts[2].content["edits"] for event in payload["events"])
    assert next(event for event in payload["events"] if event["event"] == "stream_end")["response_sources"] == facts[3].content["response_sources"]


async def test_unbound_display_append_targets_current_session(tmp_path):
    sessions = _manager(tmp_path)
    key = "websocket:current"
    await sessions.state.get(key)
    await sessions.state.reset(key)
    fact = HistoryFact(HistoryKind.INPUT, {"text": "new message"})

    await sessions.state.append_history(key, [fact], expected_generation=None)

    assert await sessions.state.project_history(key, lambda history: list(history.all_facts())) == [fact]
    await sessions.state.aclose()


async def test_delete_reset_reject_old_display_generation(tmp_path):
    sessions = _manager(tmp_path)
    key = "websocket:generation"
    first = await sessions.state.get(key)
    first.add_message("user", "old")
    await sessions.state.finish_turn(first)
    fact = HistoryFact(HistoryKind.INPUT, {"text": "old"})
    await sessions.state.append_history(key, [fact], expected_generation=first.generation)
    assert await sessions.state.delete(key)
    with pytest.raises(SessionConflictError):
        await sessions.state.append_history(key, [fact], expected_generation=first.generation)
    assert await sessions.state.project_history(key, lambda history: history.revision) is None
    second = await sessions.state.get(key)
    second.add_message("user", "new")
    await sessions.state.finish_turn(second)
    with pytest.raises(SessionConflictError):
        await sessions.state.append_history(key, [fact], expected_generation=first.generation)
    assert await sessions.state.project_history(key, lambda history: history.all_facts()) == []
    await sessions.state.aclose()


async def test_fork_rolls_back_both_histories_if_display_copy_fails(tmp_path, monkeypatch):
    sessions = _manager(tmp_path)
    source = await sessions.state.get("websocket:source")
    source.add_message("user", "question")
    source.add_message("assistant", "answer")
    await sessions.state.finish_turn(source)
    monkeypatch.setattr("nanobot.webui.forking.uuid.uuid4", lambda: "failed-fork")
    original = sessions._store.append_history

    def fail(key, facts, *, expected_generation):
        original(key, facts, expected_generation=expected_generation)
        raise OSError("disk full")

    monkeypatch.setattr(sessions._store, "append_history", fail)
    with pytest.raises(OSError, match="disk full"):
        await create_webui_chat_fork(sessions, source_chat_id="source", before_user_index=1)
    assert await sessions.state.read_metadata("websocket:failed-fork") is None
    assert await sessions.state.project_history("websocket:failed-fork", lambda history: history.all_facts()) == []
    assert (await sessions.state.get(source.key)).messages == source.messages
    await sessions.state.aclose()


async def test_recorder_keeps_completed_segments_not_every_transport_delta(tmp_path):
    sessions = _manager(tmp_path)
    key = "websocket:stream"
    generation, _ = await sessions.state.open_with_metadata(key, {})
    recorder = WebUITranscriptRecorder(sessions)
    metadata = {"_history_generation": generation, "_webui_turn_id": "turn"}
    for _ in range(8):
        assert await recorder.prepare_and_append_stream_event("stream", {"event": "delta", "text": "x"}, completed_text=None, metadata=metadata, phase="answer")
    assert await recorder.prepare_and_append_stream_event("stream", {"event": "stream_end"}, completed_text="x" * 8, metadata=metadata, phase="answer")
    facts = await sessions.state.project_history(key, lambda history: history.all_facts())
    assert [fact.kind for fact in facts] == [HistoryKind.ANSWER_SEGMENT]
    assert facts[0].content["text"] == "x" * 8
    await sessions.state.aclose()


@pytest.mark.parametrize("committed", [False, True])
async def test_real_process_exit_cannot_split_fork_model_and_display_histories(tmp_path, committed):
    import subprocess
    import sys

    sessions = _manager(tmp_path)
    source = await sessions.state.get("websocket:source")
    source.add_message("user", "question")
    source.add_message("assistant", "answer")
    await sessions.state.finish_turn(source)
    await sessions.state.append_history(source.key, [
        HistoryFact(HistoryKind.INPUT, {"text": "question"}),
        HistoryFact(HistoryKind.ANSWER, {"text": "answer"}),
        HistoryFact(HistoryKind.COMPLETION),
    ], expected_generation=source.generation)
    await sessions.state.aclose()
    child = tmp_path / "crash.py"
    child.write_text('''import asyncio, os, sys
from pathlib import Path
from nanobot.session.manager import SessionManager
root = Path(sys.argv[1])
sessions = SessionManager(root / "workspace", sessions_root=root / "sessions")
original = sessions._store.append_history
def append(key, facts, *, expected_generation):
    original(key, facts, expected_generation=expected_generation)
    if sys.argv[2] == "False":
        os._exit(91)
sessions._store.append_history = append
async def run():
    await sessions.state.fork("websocket:source", "websocket:fork", 1)
    os._exit(92)
asyncio.run(run())
''', encoding="utf-8")
    result = subprocess.run([sys.executable, str(child), str(tmp_path), str(committed)], capture_output=True, timeout=15)
    assert result.returncode == (92 if committed else 91), result.stderr.decode("utf-8", errors="replace")
    reopened = _manager(tmp_path)
    fork = reopened.read_session_file("websocket:fork")
    facts = reopened.project_history("websocket:fork", lambda history: history.all_facts())
    if committed:
        assert [message["content"] for message in fork["messages"]] == ["question", "answer"]
        assert [fact.kind for fact in facts] == [HistoryKind.INPUT, HistoryKind.ANSWER, HistoryKind.COMPLETION, HistoryKind.FORK_BOUNDARY]
    else:
        assert fork is None and facts == []
    assert reopened.read_session_file(source.key)["messages"] == source.messages


async def test_large_display_fact_serialization_and_copy_stay_off_runtime_loop(tmp_path, monkeypatch):
    import threading

    import nanobot.session.state as state_module

    sessions = _manager(tmp_path)
    session = await sessions.state.get_header("websocket:large-activity")
    runtime_thread = threading.get_ident()
    encode, copy = HistoryFact.encode, state_module.deepcopy

    def worker_encode(fact):
        assert threading.get_ident() != runtime_thread
        return encode(fact)

    def worker_copy(value, *args, **kwargs):
        if isinstance(value, list) and value and isinstance(value[0], HistoryFact):
            assert threading.get_ident() != runtime_thread
        return copy(value, *args, **kwargs)

    monkeypatch.setattr(HistoryFact, "encode", worker_encode)
    monkeypatch.setattr(state_module, "deepcopy", worker_copy)
    recorder = WebUITranscriptRecorder(sessions)
    assert await recorder.prepare_and_append("large-activity", {
        "event": "message", "kind": "tool_hint", "text": "exec",
        "tool_events": [{"tool": "exec", "result": "x" * 1_000_000}],
    }, metadata={"_history_generation": session.generation})
    facts = await sessions.state.project_history(session.key, lambda history: history.all_facts())
    assert len(facts[0].content["tool_events"][0]["result"]) == 1_000_000
    await sessions.state.aclose()


def test_message_projection_adapter_preserves_reply_and_agent_activity():
    from nanobot.webui.history import fact_from_record, record_from_fact

    record = {
        "event": "message", "chat_id": "activity", "kind": "progress",
        "text": "Inspecting workspace", "reply_to": "message-1", "created_at_ms": 1000,
        "agent_ui": {"version": 1, "status": "working", "label": "Inspecting workspace"},
    }
    fact = HistoryFact.decode(fact_from_record(record).encode())
    assert record_from_fact(fact, "websocket:activity") == record


@pytest.mark.parametrize("stored_display", [False, True])
async def test_new_fork_activity_uses_creation_time_not_inherited_history(tmp_path, stored_display):
    from datetime import datetime

    from nanobot.webui.session_list_index import list_webui_sessions

    sessions = _manager(tmp_path)
    source = await sessions.state.get("websocket:old-source")
    old_time = datetime(2020, 1, 1)
    source.add_message("user", "old question", timestamp=old_time.isoformat())
    source.add_message("assistant", "old answer", timestamp=old_time.isoformat())
    await sessions.state.finish_turn(source)
    if stored_display:
        old_ms = int(old_time.timestamp() * 1000)
        await sessions.state.append_history(source.key, [
            HistoryFact(HistoryKind.INPUT, {"text": "old question"}, created_at_ms=old_ms),
            HistoryFact(HistoryKind.ANSWER, {"text": "old answer"}, created_at_ms=old_ms),
            HistoryFact(HistoryKind.COMPLETION, created_at_ms=old_ms),
        ], expected_generation=source.generation)
    forked = await create_webui_chat_fork(sessions, source_chat_id="old-source", before_user_index=1)
    assert forked is not None
    _, fork_key = forked
    fork = await sessions.state.get(fork_key)
    facts = await sessions.state.project_history(fork_key, lambda history: history.all_facts())
    assert facts[-1].kind is HistoryKind.FORK_BOUNDARY
    assert facts[-1].created_at_ms == int(fork.created_at.timestamp() * 1000)
    rows = list_webui_sessions(sessions, await sessions.state.list_metadata())
    assert rows[0]["key"] == fork_key
    await sessions.state.aclose()
