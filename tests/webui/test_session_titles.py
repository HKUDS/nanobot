"""Legacy sidebar titles become durable conversation metadata before removal."""

from __future__ import annotations

import pytest

from nanobot.session.manager import Session, SessionManager
from nanobot.webui.session_titles import migrate_legacy_session_titles
from nanobot.webui.sidebar_state import read_webui_sidebar_state, write_webui_sidebar_state


@pytest.mark.asyncio
async def test_legacy_title_retries_after_session_persistence_fails(tmp_path, monkeypatch):
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    sessions = SessionManager(tmp_path / "workspace")
    sessions.save(Session(key="websocket:chat"))
    write_webui_sidebar_state({"title_overrides": {"websocket:chat": "Chosen title"}})
    original = sessions.state._store.replace_metadata
    failed = False

    def fail_once(key, metadata):
        nonlocal failed
        if not failed:
            failed = True
            raise OSError("storage unavailable")
        return original(key, metadata)

    monkeypatch.setattr(sessions.state._store, "replace_metadata", fail_once)
    with pytest.raises(OSError, match="storage unavailable"):
        await migrate_legacy_session_titles(sessions)
    assert read_webui_sidebar_state()["title_overrides"] == {"websocket:chat": "Chosen title"}
    assert (await sessions.state.read_metadata("websocket:chat"))["metadata"].get("title") is None

    await migrate_legacy_session_titles(sessions)
    assert read_webui_sidebar_state()["title_overrides"] == {}
    restarted = SessionManager(tmp_path / "workspace")
    metadata = (await restarted.state.read_metadata("websocket:chat"))["metadata"]
    assert (metadata["title"], metadata["title_user_edited"]) == ("Chosen title", True)
