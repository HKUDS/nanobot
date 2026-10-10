"""Durable cursor, dedup, and token-rotation contracts for the channel store."""

from __future__ import annotations

import json
from pathlib import Path

from nanobot.channels.whatsapp_agent.state import (
    WhatsAppAgentState,
    local_state_present,
    token_fingerprint,
)


def test_cursor_round_trips_through_disk(tmp_path: Path):
    path = tmp_path / "state.json"
    state = WhatsAppAgentState()
    state.reset_for_token("token-a")
    state.accept_offset(9007199254740993)
    state.note_message("wamid.1")
    state.note_status("wamid.out", "read")
    state.note_creator("user:55")
    state.save(path)

    reloaded = WhatsAppAgentState.load(path)

    # next_offset is a signed 64-bit value replayed unchanged.
    assert reloaded.offset == 9007199254740993
    assert reloaded.initialized is True
    assert reloaded.has_message("wamid.1") is True
    assert reloaded.last_status["wamid.out"] == "read"
    assert reloaded.creator_id == "user:55"


def test_corrupt_or_missing_state_starts_a_fresh_cursor(tmp_path: Path):
    path = tmp_path / "state.json"

    assert WhatsAppAgentState.load(path).initialized is False

    path.write_text("{not json", encoding="utf-8")

    recovered = WhatsAppAgentState.load(path)
    assert recovered.initialized is False
    assert recovered.offset is None


def test_state_file_contains_no_raw_token(tmp_path: Path):
    path = tmp_path / "state.json"
    state = WhatsAppAgentState()
    state.reset_for_token("super-secret-token")
    state.save(path)

    assert "super-secret-token" not in path.read_text(encoding="utf-8")
    assert state.token_fingerprint == token_fingerprint("super-secret-token")


def test_rotating_the_token_discards_a_foreign_cursor():
    state = WhatsAppAgentState()
    state.reset_for_token("token-a")
    state.accept_offset(42)
    state.note_message("wamid.1")

    # next_offset is only meaningful for the agent that issued it.
    assert state.reset_for_token("token-b") is True
    assert state.offset is None
    assert state.initialized is False
    assert state.has_message("wamid.1") is False


def test_restarting_with_the_same_token_keeps_the_cursor():
    state = WhatsAppAgentState()
    state.reset_for_token("token-a")
    state.accept_offset(42)

    assert state.reset_for_token("token-a") is False
    assert state.offset == 42
    assert state.initialized is True


def test_dedup_window_is_bounded_and_drops_the_oldest():
    state = WhatsAppAgentState()
    for index in range(2500):
        state.note_message(f"wamid.{index}")

    assert len(state.seen) == 2000
    assert state.has_message("wamid.2499") is True
    assert state.has_message("wamid.0") is False


def test_persisted_seen_order_survives_a_reload(tmp_path: Path):
    path = tmp_path / "state.json"
    state = WhatsAppAgentState()
    state.note_message("wamid.a")
    state.note_message("wamid.b")
    state.save(path)

    assert list(WhatsAppAgentState.load(path).seen) == ["wamid.a", "wamid.b"]


def test_local_state_present_requires_a_saved_token_fingerprint(tmp_path: Path):
    section = {"stateDir": str(tmp_path)}

    assert local_state_present(section) is False

    state = WhatsAppAgentState()
    state.reset_for_token("token-a")
    state.save(tmp_path / "state.json")

    assert local_state_present(section) is True


def test_unreadable_state_file_reports_no_local_state(tmp_path: Path):
    (tmp_path / "state.json").write_text("[]", encoding="utf-8")

    assert local_state_present({"stateDir": str(tmp_path)}) is False


def test_legacy_state_without_creator_id_loads():
    # A state file written before creator ids were persisted must still load.
    payload = json.dumps({"offset": 5, "initialized": True, "token_fingerprint": "abc"})
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "state.json"
        path.write_text(payload, encoding="utf-8")
        state = WhatsAppAgentState.load(path)

    assert state.offset == 5
    assert state.creator_id == ""
