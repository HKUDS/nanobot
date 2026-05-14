"""Tests for WebUI thread JSON persistence."""

from __future__ import annotations

from nanobot.utils.webui_thread_disk import (
    WEBUI_THREAD_SCHEMA_VERSION,
    delete_webui_thread,
    read_webui_thread,
    webui_thread_file_path,
    write_webui_thread_atomic,
)


def test_write_read_webui_thread_roundtrip(tmp_path, monkeypatch) -> None:
    from nanobot.config import paths

    monkeypatch.setattr(paths, "get_data_dir", lambda: tmp_path)

    key = "websocket:test-chat"
    payload = {
        "schemaVersion": WEBUI_THREAD_SCHEMA_VERSION,
        "sessionKey": key,
        "messages": [{"role": "user", "content": "hi", "id": "x", "createdAt": 1}],
    }
    write_webui_thread_atomic(key, payload)
    path = webui_thread_file_path(key)
    assert path.is_file()
    loaded = read_webui_thread(key)
    assert loaded is not None
    assert loaded["sessionKey"] == key
    assert len(loaded["messages"]) == 1


def test_read_missing_returns_none(tmp_path, monkeypatch) -> None:
    from nanobot.config import paths

    monkeypatch.setattr(paths, "get_data_dir", lambda: tmp_path)
    assert read_webui_thread("websocket:nope") is None


def test_delete_webui_thread_removes_file(tmp_path, monkeypatch) -> None:
    from nanobot.config import paths

    monkeypatch.setattr(paths, "get_data_dir", lambda: tmp_path)
    key = "websocket:gone"
    write_webui_thread_atomic(
        key,
        {"schemaVersion": WEBUI_THREAD_SCHEMA_VERSION, "sessionKey": key, "messages": []},
    )
    path = webui_thread_file_path(key)
    assert path.is_file()
    assert delete_webui_thread(key) is True
    assert not path.is_file()
    assert delete_webui_thread(key) is False


def test_read_oversized_file_returns_none(tmp_path, monkeypatch) -> None:
    from nanobot.config import paths
    from nanobot.utils import webui_thread_disk as wtd

    monkeypatch.setattr(paths, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(wtd, "_MAX_THREAD_FILE_BYTES", 8)
    key = "websocket:big"
    path = webui_thread_file_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"a":1,"b":2}', encoding="utf-8")
    assert read_webui_thread(key) is None
