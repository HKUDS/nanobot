from __future__ import annotations

import uuid
from unittest.mock import Mock

import pytest

from nanobot.session.manager import SessionManager
from nanobot.webui.forking import create_webui_chat_fork


def test_fork_failure_removes_session_when_transcript_cleanup_also_fails(
    tmp_path,
    monkeypatch,
) -> None:
    manager = SessionManager(tmp_path)
    source = manager.get_or_create("websocket:source")
    source.add_message("user", "round one")
    source.add_message("assistant", "answer one")
    manager.save(source)

    fork_id = uuid.UUID("00000000-0000-0000-0000-000000000123")
    monkeypatch.setattr("nanobot.webui.forking.uuid.uuid4", lambda: fork_id)
    transcripts = Mock()
    transcripts.fork_before_user_index.side_effect = OSError("primary transcript failure")
    transcripts.delete.side_effect = OSError("cleanup transcript failure")

    with pytest.raises(OSError, match="primary transcript failure"):
        create_webui_chat_fork(
            manager,
            source_chat_id="source",
            before_user_index=1,
            transcripts=transcripts,
        )

    target_key = f"websocket:{fork_id}"
    transcripts.delete.assert_called_once_with(target_key)
    assert not manager._get_session_path(target_key).exists()
    assert manager.read_session_file(target_key) is None
    assert manager.read_session_file("websocket:source") is not None
