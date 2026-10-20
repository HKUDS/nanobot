"""Interrupted display replacement follows the SQLite commit decision."""
from __future__ import annotations

import json
import subprocess
import sys
from urllib.parse import quote

import pytest
from websockets.datastructures import Headers
from websockets.http11 import Request

from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket.runtime import WebSocketConfig
from nanobot.session.manager import Session, SessionManager
from nanobot.webui import transcript
from nanobot.webui.gateway_services import build_gateway_services
from nanobot.webui.history_replacement import transcript_access
from nanobot.webui.recovery import RecoveryCoordinator
from nanobot.webui.session_list_index import list_webui_sessions


@pytest.mark.parametrize("committed", [False, True])
def test_process_exit_during_replacement_recovers_by_generation(tmp_path, monkeypatch, committed):
    display = tmp_path / "display"
    display.mkdir()
    monkeypatch.setattr(transcript, "get_webui_dir", lambda: display)
    manager = SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "sessions")
    key = "websocket:crash-edit"
    source = Session(key=key)
    manager.save(source)
    old = {"event": "user", "chat_id": "crash-edit", "text": "old"}
    transcript.append_transcript_object(key, old)
    old_rows = transcript.read_transcript_lines(key)
    database = manager.sessions_dir / "sessions.sqlite3"
    child = r'''
import os, sqlite3, sys
from pathlib import Path
from nanobot.webui import transcript
from nanobot.webui.history_replacement import replace_transcript
root, database, committed, previous_generation = sys.argv[1:]
transcript.get_webui_dir = lambda: Path(root)
with replace_transcript("websocket:crash-edit", [{"event":"user", "text":"new"}], database=Path(database), generation="new-generation", previous_generation=previous_generation):
    if committed == "True":
        with sqlite3.connect(database) as db:
            db.execute("UPDATE sessions SET generation=? WHERE key=?", ("new-generation", "websocket:crash-edit"))
    os._exit(23)
'''
    result = subprocess.run(
        [sys.executable, "-c", child, str(display), str(database), str(committed), source.generation],
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 23, result.stderr
    assert list(display.glob("*.edit.json"))
    with transcript_access(key):
        rows = transcript.read_transcript_lines(key)
    assert rows == ([{"event": "user", "text": "new"}] if committed else old_rows)
    assert not list(display.glob("*.edit.json"))
    assert not list(display.glob(".edit-*"))
    assert json.loads(transcript.webui_transcript_path(key).read_text(encoding="utf-8"))["text"] == ("new" if committed else "old")


@pytest.fixture
async def committed_edit(tmp_path, monkeypatch):
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    manager = SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "sessions")
    key = "websocket:crash-edit"
    original = Session(key=key)
    original.add_message("user", "old private input", webui_turn_id="old-turn")
    original.add_message("assistant", "old private answer")
    manager.save(original)
    for row in (
        {"event": "user", "text": "old private input"},
        {"event": "message", "text": "old private answer"},
        {"event": "turn_end"},
    ):
        transcript.append_transcript_object(key, {**row, "chat_id": "crash-edit", "turn_id": "old-turn"})
    child = r'''
import asyncio, os, sys
from pathlib import Path
from nanobot.bus.events import InboundMessage
from nanobot.session.history_edit import HistoryEditAnchor, message_digest
from nanobot.session.manager import SessionManager
from nanobot.webui import history_replacement, transcript
root = Path(sys.argv[1])
transcript.get_webui_dir = lambda: root / "webui"
manager = SessionManager(root / "workspace", sessions_root=root / "sessions")
history_replacement._finish = lambda *_args: os._exit(23)
async def main():
    source = await manager.state.read("websocket:crash-edit")
    anchor = HistoryEditAnchor(source.generation, source.revision, 0, message_digest(source.messages[0]))
    message = InboundMessage(channel="websocket", sender_id="webui", chat_id="crash-edit", content="replacement", metadata={"webui_turn_id": "new-edit"})
    def projection(session):
        return history_replacement.replace_transcript(source.key, [{"event": "user", "chat_id": "crash-edit", "text": "replacement", "turn_id": "new-edit"}], database=manager.sessions_dir / "sessions.sqlite3", generation=session.generation, previous_generation=source.generation)
    await manager.state.replace_user_input(source.key, anchor, message, projection)
asyncio.run(main())
'''
    result = subprocess.run(
        [sys.executable, "-c", child, str(tmp_path)],
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 23, result.stderr
    session = manager.read_session_snapshot(key)
    assert session is not None and session.generation != original.generation
    assert session.messages[-1]["content"] == "replacement"
    display = transcript.get_webui_dir()
    assert len(list(display.glob("*.edit.json"))) == 1
    gateway = build_gateway_services(
        config=WebSocketConfig(enabled=True, allow_from=["*"]), bus=MessageBus(),
        session_manager=manager, static_dist_path=None, workspace_path=tmp_path / "workspace",
        default_restrict_to_workspace=False, config_path=tmp_path / "config.json",
        runtime_model_name=None, runtime_surface="tui", runtime_capabilities_overrides=None,
    )
    try:
        yield manager, key, display, gateway
    finally:
        await manager.state.aclose()


async def test_delete_before_first_replay_discards_interrupted_edit(committed_edit):
    manager, key, display, gateway = committed_edit
    await RecoveryCoordinator(sessions=manager, bus=MessageBus()).scan()
    encoded = quote(key, safe="")
    headers = Headers([("Authorization", f"Bearer {gateway.tokens.issue_api_token(60)}")])
    deleted = await gateway.http._handle_session_delete(Request(f"/api/sessions/{encoded}", headers), encoded)
    assert deleted.status_code == 200 and json.loads(deleted.body) == {"deleted": True}
    assert manager.read_session_snapshot(key) is None
    assert not list(display.glob("*.edit.json"))
    assert not list(display.glob(".edit-*"))
    response = gateway.http._handle_webui_thread_get(Request(f"/api/sessions/{encoded}/webui-thread", headers), encoded)
    assert response.status_code == 404
    assert transcript.read_transcript_lines(key) == []
    assert not transcript.webui_transcript_path(key).exists()
    assert all(row["key"] != key for row in list_webui_sessions(manager))


@pytest.mark.parametrize("recreate", [False, True])
async def test_replay_never_restores_a_deleted_edit_lifecycle(committed_edit, recreate):
    manager, key, display, _ = committed_edit
    # A gateway can exit after canonical deletion but before display cleanup.
    assert await manager.state.delete(key)
    replacement = await manager.state.get(key) if recreate else None
    assert transcript.read_transcript_lines(key) == []
    assert transcript.build_webui_thread_response(key) is None
    assert not list(display.glob("*.edit.json"))
    assert not list(display.glob(".edit-*"))
    current = manager.read_session_snapshot(key)
    if replacement is None:
        assert current is None
    else:
        assert current is not None and current.generation == replacement.generation
        assert current.messages == []
