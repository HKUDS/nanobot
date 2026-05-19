"""Tests for WebUI on-disk cleanup (legacy JSON + transcript JSONL)."""

from __future__ import annotations

from nanobot.utils.webui_thread_disk import delete_webui_thread, webui_thread_file_path
from nanobot.utils.webui_transcript import append_transcript_object, webui_transcript_path


def test_delete_webui_thread_removes_legacy_json_and_transcript(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    key = "websocket:k1"
    json_path = webui_thread_file_path(key)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text('{"x":1}', encoding="utf-8")
    append_transcript_object(key, {"event": "user", "chat_id": "k1", "text": "hi"})
    assert webui_transcript_path(key).is_file()
    assert delete_webui_thread(key) is True
    assert not json_path.is_file()
    assert not webui_transcript_path(key).is_file()
    assert delete_webui_thread(key) is False
