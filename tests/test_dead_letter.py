"""Tests for dead-letter replay (Step 16)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

from nanobot.bus.events import OutboundMessage
from nanobot.channels.manager import ChannelManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_dead_letters(path: Path, entries: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def _dead_entry(
    channel: str = "telegram",
    chat_id: str = "123",
    content: str = "hello",
    error: str = "timeout",
) -> dict[str, Any]:
    return {
        "timestamp": "2026-03-05T10:00:00",
        "channel": channel,
        "chat_id": chat_id,
        "content": content,
        "media": [],
        "metadata": {},
        "error": error,
    }


# ---------------------------------------------------------------------------
# ChannelManager._read_dead_letters
# ---------------------------------------------------------------------------


class TestReadDeadLetters:
    def test_no_file(self, tmp_path: Path) -> None:
        mgr = _make_manager(tmp_path)
        assert mgr._read_dead_letters() == []

    def test_reads_entries(self, tmp_path: Path) -> None:
        mgr = _make_manager(tmp_path)
        _write_dead_letters(mgr._dead_letter_file, [_dead_entry(), _dead_entry(content="bye")])
        entries = mgr._read_dead_letters()
        assert len(entries) == 2
        assert entries[0]["content"] == "hello"
        assert entries[1]["content"] == "bye"

    def test_skips_invalid_json(self, tmp_path: Path) -> None:
        mgr = _make_manager(tmp_path)
        mgr._dead_letter_file.parent.mkdir(parents=True, exist_ok=True)
        mgr._dead_letter_file.write_text("not json\n" + json.dumps(_dead_entry()) + "\n")
        entries = mgr._read_dead_letters()
        assert len(entries) == 1


# ---------------------------------------------------------------------------
# ChannelManager.replay_dead_letters
# ---------------------------------------------------------------------------


class TestReplayDeadLetters:
    async def test_empty_file(self, tmp_path: Path) -> None:
        mgr = _make_manager(tmp_path)
        total, ok, fail = await mgr.replay_dead_letters()
        assert total == 0

    async def test_dry_run(self, tmp_path: Path) -> None:
        mgr = _make_manager(tmp_path, channels=["telegram"])
        _write_dead_letters(mgr._dead_letter_file, [_dead_entry()])
        total, ok, fail = await mgr.replay_dead_letters(dry_run=True)
        assert total == 1
        assert ok == 1
        # File should still exist (dry run doesn't modify)
        assert mgr._dead_letter_file.exists()

    async def test_successful_replay(self, tmp_path: Path) -> None:
        mgr = _make_manager(tmp_path, channels=["telegram"])
        _write_dead_letters(
            mgr._dead_letter_file,
            [
                _dead_entry(content="msg1"),
                _dead_entry(content="msg2"),
            ],
        )

        total, ok, fail = await mgr.replay_dead_letters()
        assert total == 2
        assert ok == 2
        assert fail == 0
        # Dead-letter file should be deleted
        assert not mgr._dead_letter_file.exists()
        # Verify send was called
        assert mgr.channels["telegram"].send.call_count == 2

    async def test_partial_failure(self, tmp_path: Path) -> None:
        mgr = _make_manager(tmp_path, channels=["telegram"])
        _write_dead_letters(
            mgr._dead_letter_file,
            [
                _dead_entry(content="ok-msg"),
                _dead_entry(content="fail-msg"),
            ],
        )
        # Make the second send fail
        call_count = 0

        async def _side_effect(msg):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise ConnectionError("still down")

        mgr.channels["telegram"].send = AsyncMock(side_effect=_side_effect)

        total, ok, fail = await mgr.replay_dead_letters()
        assert total == 2
        assert ok == 1
        assert fail == 1
        # File should still exist with just the failed entry
        remaining = mgr._read_dead_letters()
        assert len(remaining) == 1
        assert remaining[0]["content"] == "fail-msg"

    async def test_skips_unavailable_channel(self, tmp_path: Path) -> None:
        mgr = _make_manager(tmp_path, channels=["telegram"])
        _write_dead_letters(
            mgr._dead_letter_file,
            [
                _dead_entry(channel="discord", content="no channel"),
            ],
        )
        total, ok, fail = await mgr.replay_dead_letters()
        assert total == 1
        assert ok == 0
        assert fail == 1


# ---------------------------------------------------------------------------
# ChannelManager._write_dead_letter
# ---------------------------------------------------------------------------


class TestWriteDeadLetter:
    def test_writes_entry(self, tmp_path: Path) -> None:
        mgr = _make_manager(tmp_path)
        msg = OutboundMessage(channel="telegram", chat_id="456", content="test")
        mgr._write_dead_letter(msg, Exception("fail"))
        entries = mgr._read_dead_letters()
        assert len(entries) == 1
        assert entries[0]["channel"] == "telegram"
        assert entries[0]["content"] == "test"
        assert "fail" in entries[0]["error"]


# ---------------------------------------------------------------------------
# Factory helper
# ---------------------------------------------------------------------------


def _make_manager(tmp_path: Path, channels: list[str] | None = None) -> ChannelManager:
    """Create a ChannelManager with mock channels, bypassing real config."""
    mgr = object.__new__(ChannelManager)
    mgr.channels = {}
    mgr._dispatch_task = None
    mgr._dead_letter_file = tmp_path / "outbound_failed.jsonl"

    for name in channels or []:
        mock_channel = AsyncMock()
        mock_channel.send = AsyncMock()
        mgr.channels[name] = mock_channel

    return mgr
