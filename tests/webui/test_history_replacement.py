"""A process exit cannot split canonical and display history replacement."""
from __future__ import annotations

import sqlite3
import subprocess
import sys
from contextlib import closing

import pytest

from nanobot.session.display_history import HistoryFact, HistoryKind
from nanobot.session.manager import Session, SessionManager


@pytest.mark.parametrize("committed", [False, True])
def test_process_exit_keeps_both_histories_on_the_same_side_of_commit(tmp_path, committed):
    manager = SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "sessions")
    source = Session(key="websocket:crash-edit")
    source.add_message("user", "old private input", webui_turn_id="old-turn")
    source.add_message("assistant", "old private answer")
    manager.save(source)
    old_facts = [
        HistoryFact(HistoryKind.INPUT, {"text": "old private input"}, "old-turn", created_at_ms=1000),
        HistoryFact(HistoryKind.ANSWER, {"text": "old private answer"}, "old-turn", created_at_ms=1001),
        HistoryFact(HistoryKind.COMPLETION, turn_id="old-turn", created_at_ms=1002),
    ]
    manager.append_history(source.key, old_facts)
    child = r'''
import asyncio, os, sys
from pathlib import Path
from nanobot.bus.events import InboundMessage
from nanobot.session.display_history import HistoryFact, HistoryKind
from nanobot.session.history_edit import HistoryEditAnchor, HistoryEditDisplay, message_digest
from nanobot.session.manager import SessionManager
root = Path(sys.argv[1])
manager = SessionManager(root / "workspace", sessions_root=root / "sessions")
async def main():
    source = await manager.state.read("websocket:crash-edit")
    anchor = HistoryEditAnchor(source.generation, source.revision, 0, message_digest(source.messages[0]))
    message = InboundMessage(channel="websocket", sender_id="webui", chat_id="crash-edit", content="replacement", metadata={"webui_turn_id": "new-edit"})
    fact = HistoryFact(HistoryKind.INPUT, {"text": "replacement"}, "new-edit", created_at_ms=2000)
    if sys.argv[2] == "True":
        # This boundary is reached only after the outer SQLite transaction commits.
        manager.state._publish = lambda *_args: os._exit(23)
    else:
        original = manager._store.replace_history_input
        def before_commit(*args, **kwargs):
            original(*args, **kwargs)
            os._exit(23)
        manager._store.replace_history_input = before_commit
    await manager.state.replace_user_input(source.key, anchor, message, lambda _source, _history: HistoryEditDisplay(0, 0, fact))
asyncio.run(main())
'''
    result = subprocess.run(
        [sys.executable, "-c", child, str(tmp_path), str(committed)],
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 23, result.stderr
    reopened = SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "sessions")
    current = reopened.read_session_snapshot(source.key)
    facts = reopened.project_history(source.key, lambda history: history.all_facts())
    assert current is not None
    assert (current.generation != source.generation) is committed
    if committed:
        assert [message["content"] for message in current.messages] == ["replacement"]
        assert facts == [HistoryFact(HistoryKind.INPUT, {"text": "replacement"}, "new-edit", created_at_ms=2000)]
    else:
        assert current.messages == source.messages
        assert facts == old_facts
    with closing(sqlite3.connect(reopened.sessions_dir / "sessions.sqlite3")) as db:
        head = db.execute("SELECT user_preview, preview, updated_at_ms FROM history_heads WHERE session_key=?", (source.key,)).fetchone()
        turn = db.execute("SELECT record_count, byte_count, user_count, completed FROM history_turns WHERE session_key=?", (source.key,)).fetchone()
        assert head == (("replacement", "", 2000) if committed else ("old private input", "old private answer", 1002))
        assert turn == (len(facts), sum(len(fact.encode().encode("utf-8")) for fact in facts), 1, int(not committed))
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


async def test_edit_within_a_turn_rebuilds_paging_summaries_and_keeps_its_prefix(tmp_path):
    from nanobot.bus.events import InboundMessage
    from nanobot.session.history_edit import HistoryEditAnchor, HistoryEditDisplay, message_digest

    manager = SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "sessions")
    key = "websocket:steering-edit"
    source = await manager.state.get(key)
    for index in range(4):
        source.add_message("user", f"input-{index}", webui_turn_id=f"old-{index}")
        source.add_message("assistant", f"answer-{index}")
    await manager.state.finish_turn(source)
    facts = [
        HistoryFact(HistoryKind.INPUT, {"text": "input-0"}, "old-0", created_at_ms=1000),
        HistoryFact(HistoryKind.ANSWER, {"text": "answer-0"}, "old-0", created_at_ms=1001),
        HistoryFact(HistoryKind.COMPLETION, turn_id="old-0", created_at_ms=1002),
        HistoryFact(HistoryKind.INPUT, {"text": "input-1"}, "old-1", created_at_ms=2000),
        HistoryFact(HistoryKind.ANSWER_SEGMENT, {"text": "answer-1"}, "old-1", created_at_ms=2001),
        HistoryFact(HistoryKind.INPUT, {"text": "input-2"}, "old-2", created_at_ms=2002),
        HistoryFact(HistoryKind.ANSWER_SEGMENT, {"text": "answer-2"}, "old-2", created_at_ms=2003),
        HistoryFact(HistoryKind.COMPLETION, turn_id="old-1", created_at_ms=2004),
        HistoryFact(HistoryKind.INPUT, {"text": "input-3"}, "old-3", created_at_ms=3000),
        HistoryFact(HistoryKind.ANSWER, {"text": "answer-3"}, "old-3", created_at_ms=3001),
        HistoryFact(HistoryKind.COMPLETION, turn_id="old-3", created_at_ms=3002),
    ]
    await manager.state.append_history(key, facts, expected_generation=source.generation)
    before = await manager.state.project_history(key, lambda history: history.revision)
    replacement = HistoryFact(HistoryKind.INPUT, {"text": "替换输入"}, "new-edit", created_at_ms=4000)
    current = await manager.state.replace_user_input(
        key, HistoryEditAnchor(source.generation, source.revision, 2, message_digest(source.messages[4])),
        InboundMessage(channel="websocket", sender_id="webui", chat_id="steering-edit", content="替换输入",
                       metadata={"webui_turn_id": "new-edit"}),
        lambda _session, _history: HistoryEditDisplay(1, 2, replacement),
    )
    retained = [*facts[:5], replacement]
    assert current.messages[:-1] == source.messages[:4]
    assert await manager.state.project_history(key, lambda history: history.all_facts()) == retained
    with closing(sqlite3.connect(manager.sessions_dir / "sessions.sqlite3")) as db:
        turns = db.execute("SELECT ordinal, record_count, byte_count, user_count, completed FROM history_turns WHERE session_key=? ORDER BY ordinal", (key,)).fetchall()
        assert turns == [
            (0, 3, sum(len(fact.encode().encode("utf-8")) for fact in facts[:3]), 1, 1),
            (1, 3, sum(len(fact.encode().encode("utf-8")) for fact in retained[3:]), 2, 0),
        ]
        assert db.execute("SELECT user_preview, preview, updated_at_ms, revision FROM history_heads WHERE session_key=?", (key,)).fetchone() == ("input-0", "answer-0", 4000, before[1] + 1)
    following = [
        HistoryFact(HistoryKind.ANSWER_SEGMENT, {"text": "新回答"}, "new-edit"),
        HistoryFact(HistoryKind.COMPLETION, turn_id="new-edit"),
        HistoryFact(HistoryKind.INPUT, {"text": "next input"}, "next-turn"),
    ]
    await manager.state.append_history(key, following, expected_generation=current.generation)
    assert await manager.state.project_history(key, lambda history: history.read_turn(1)) == [*retained[3:], *following[:2]]
    assert await manager.state.project_history(key, lambda history: history.user_count_before(2)) == 3
    assert await manager.state.project_history(key, lambda history: history.read_turn(2)) == following[2:]
    await manager.state.aclose()
