"""Durable subagent detail replay tests."""

from nanobot.session.manager import SessionManager
from nanobot.session.subagent_state import (
    SubagentDetailRecord,
    SubagentDetailStore,
    SubagentTaskRecord,
    SubagentTaskStore,
)


def _record(status: str = "running") -> SubagentTaskRecord:
    return SubagentTaskRecord(
        task_id="task-1",
        label="任务",
        task_description="执行任务",
        status=status,
        channel="websocket",
        chat_id="chat-1",
        session_key="websocket:chat-1",
        turn_id="turn-1",
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )


def test_task_store_persists_and_reloads_records(tmp_path):
    sessions = SessionManager(tmp_path)
    store = SubagentTaskStore(sessions)
    stored = store.upsert(_record("queued"))

    assert stored.revision == 0
    assert store.snapshot("websocket:chat-1")[0].status == "queued"


def test_snapshot_marks_lost_active_task_interrupted(tmp_path):
    sessions = SessionManager(tmp_path)
    store = SubagentTaskStore(sessions)
    store.upsert(_record("running"))

    snapshot = store.snapshot("websocket:chat-1", active_task_ids=set())

    assert snapshot[0].status == "interrupted"
    assert snapshot[0].stop_reason == "gateway_restart_or_runtime_loss"


def test_detail_store_keeps_replayable_snapshot(tmp_path):
    sessions = SessionManager(tmp_path)
    store = SubagentDetailStore(sessions)
    store.upsert(
        "websocket:chat-1",
        SubagentDetailRecord(
            task_id="task-1",
            label="任务",
            turn_id="turn-1",
            status="completed",
            revision=2,
            seq=3,
            input="执行任务",
            steps=[{"kind": "tool_start", "name": "read_file"}],
            output="完成",
        ),
    )

    snapshot = store.snapshot("websocket:chat-1")

    assert snapshot[0]["task_id"] == "task-1"
    assert snapshot[0]["steps"][0]["name"] == "read_file"
