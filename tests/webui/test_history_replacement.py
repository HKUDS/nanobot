"""Interrupted display replacement follows the SQLite commit decision."""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

from nanobot.session.manager import Session, SessionManager
from nanobot.webui import transcript
from nanobot.webui.history_replacement import transcript_access


@pytest.mark.parametrize("committed", [False, True])
def test_process_exit_during_replacement_recovers_by_generation(tmp_path, monkeypatch, committed):
    display = tmp_path / "display"
    display.mkdir()
    monkeypatch.setattr(transcript, "get_webui_dir", lambda: display)
    manager = SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "sessions")
    key = "websocket:crash-edit"
    manager.save(Session(key=key))
    old = {"event": "user", "chat_id": "crash-edit", "text": "old"}
    transcript.append_transcript_object(key, old)
    old_rows = transcript.read_transcript_lines(key)
    database = manager.sessions_dir / "sessions.sqlite3"
    child = r'''
import os, sqlite3, sys
from pathlib import Path
from nanobot.webui import transcript
from nanobot.webui.history_replacement import replace_transcript
root, database, committed = sys.argv[1:]
transcript.get_webui_dir = lambda: Path(root)
with replace_transcript("websocket:crash-edit", [{"event":"user", "text":"new"}], database=Path(database), generation="new-generation"):
    if committed == "True":
        with sqlite3.connect(database) as db:
            db.execute("UPDATE sessions SET generation=? WHERE key=?", ("new-generation", "websocket:crash-edit"))
    os._exit(23)
'''
    result = subprocess.run(
        [sys.executable, "-c", child, str(display), str(database), str(committed)],
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
