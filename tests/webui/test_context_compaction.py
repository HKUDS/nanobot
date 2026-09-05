"""WebUI replay behavior for structured context-compaction events."""

import pytest

from nanobot.webui.transcript import replay_transcript_to_ui_messages


@pytest.mark.parametrize("phase", ["succeeded", "cancelled"])
def test_replay_folds_compaction_lifecycle_into_one_stable_message(phase) -> None:
    messages = replay_transcript_to_ui_messages([
        {
            "event": "context_compaction",
            "compaction_id": "compact-1",
            "phase": "started",
            "created_at_ms": 1_700_000_000_000,
        },
        {
            "event": "context_compaction",
            "compaction_id": "compact-1",
            "phase": phase,
            "created_at_ms": 1_700_000_001_000,
        },
    ])

    assert messages == [{
        "id": "compaction-compact-1",
        "role": "assistant",
        "content": "",
        "kind": "compaction",
        "createdAt": 1_700_000_000_000,
        "turnPhase": "activity",
        "compaction": {
            "id": "compact-1",
            "phase": phase,
        },
    }]


def test_replay_keeps_distinct_compactions_in_one_turn() -> None:
    messages = replay_transcript_to_ui_messages([
        {
            "event": "context_compaction",
            "compaction_id": compaction_id,
            "phase": phase,
        }
        for compaction_id in ("compact-1", "compact-2")
        for phase in ("started", "succeeded")
    ])

    assert [message["id"] for message in messages] == [
        "compaction-compact-1",
        "compaction-compact-2",
    ]
    assert all(message["compaction"]["phase"] == "succeeded" for message in messages)
