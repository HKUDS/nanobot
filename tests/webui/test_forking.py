from __future__ import annotations

from pathlib import Path

from nanobot.agent.memory import Consolidator
from nanobot.session.manager import SessionManager
from nanobot.webui.forking import create_webui_chat_fork


def test_fork_preserves_dream_tail_marker_via_production_entry_point(tmp_path: Path) -> None:
    """create_webui_chat_fork (the real WebUI fork_chat handler's entry point,
    not the lower-level SessionManager.fork_session_before_user_index tested
    elsewhere) must carry the dream-tail marker into the fork. Without the
    explicit extra_index_metadata_keys passed here, correctness would depend
    on nanobot.agent.memory having already been imported somewhere in the
    process for the marker key to be in the registry — this test can't prove
    that dependency doesn't exist (pytest's own collection already imports
    memory.py), only that the explicit path works regardless of it."""
    manager = SessionManager(tmp_path)
    source = manager.get_or_create("websocket:src")
    for i in range(4):
        source.add_message("user", f"msg{i}")
        source.add_message("assistant", f"reply{i}")
    # marker=6 covers indices 0-5 (msg0/reply0/msg1/reply1/msg2/reply2) —
    # beyond the 4-message prefix before_user_index=2 will copy, so a correct
    # fork must clamp it to 4, not carry the stale out-of-range value forward.
    source.metadata[Consolidator.DREAM_TAIL_MARKER_KEY] = 6
    manager.save(source)

    result = create_webui_chat_fork(
        manager,
        source_chat_id="src",
        before_user_index=2,
    )
    assert result is not None
    _chat_id, fork_key = result

    forked = manager.get_or_create(fork_key)
    assert forked.metadata.get(Consolidator.DREAM_TAIL_MARKER_KEY) == 4, (
        "Expected the marker to be clamped to the copied prefix length (4), "
        f"got metadata={forked.metadata!r}"
    )
