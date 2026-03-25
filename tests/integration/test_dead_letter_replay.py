"""IT-16: Dead letter file roundtrip.

Verifies that OutboundMessage data written as JSON lines to the dead letter
file can be read back with contents intact.

Does not require LLM API key.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from nanobot.bus.events import OutboundMessage

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers — mirror the ChannelManager._write_dead_letter format
# ---------------------------------------------------------------------------


def _write_dead_letter(path: Path, msg: OutboundMessage, error: str) -> None:
    """Write a dead letter entry in the same format as ChannelManager."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "channel": msg.channel,
        "chat_id": msg.chat_id,
        "content": msg.content,
        "media": list(msg.media or []),
        "metadata": dict(msg.metadata or {}),
        "error": error,
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload) + "\n")


def _read_dead_letters(path: Path) -> list[dict]:
    """Read all dead letter entries from a JSONL file."""
    entries: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDeadLetterRoundtrip:
    def test_single_message_roundtrip(self, tmp_path: Path) -> None:
        """A single dead letter entry can be written and read back."""
        dl_path = tmp_path / "outbound_failed.jsonl"
        msg = OutboundMessage(
            channel="telegram",
            chat_id="chat-42",
            content="Hello from the dead letter test",
        )

        _write_dead_letter(dl_path, msg, "connection timeout")

        entries = _read_dead_letters(dl_path)
        assert len(entries) == 1
        assert entries[0]["channel"] == "telegram"
        assert entries[0]["chat_id"] == "chat-42"
        assert entries[0]["content"] == "Hello from the dead letter test"
        assert entries[0]["error"] == "connection timeout"
        assert "timestamp" in entries[0]

    def test_multiple_messages_roundtrip(self, tmp_path: Path) -> None:
        """Multiple dead letters are stored as separate JSON lines."""
        dl_path = tmp_path / "outbound_failed.jsonl"

        for i in range(5):
            msg = OutboundMessage(
                channel="slack",
                chat_id=f"chat-{i}",
                content=f"message-{i}",
                metadata={"attempt": i},
            )
            _write_dead_letter(dl_path, msg, f"error-{i}")

        entries = _read_dead_letters(dl_path)
        assert len(entries) == 5
        for i, entry in enumerate(entries):
            assert entry["chat_id"] == f"chat-{i}"
            assert entry["content"] == f"message-{i}"
            assert entry["metadata"]["attempt"] == i
            assert entry["error"] == f"error-{i}"

    def test_media_and_metadata_preserved(self, tmp_path: Path) -> None:
        """Media URLs and metadata survive the roundtrip."""
        dl_path = tmp_path / "outbound_failed.jsonl"
        msg = OutboundMessage(
            channel="discord",
            chat_id="guild-1",
            content="image message",
            media=["https://example.com/img.png"],
            metadata={"thread_id": "t-99", "priority": "high"},
        )

        _write_dead_letter(dl_path, msg, "rate limited")

        entries = _read_dead_letters(dl_path)
        assert len(entries) == 1
        assert entries[0]["media"] == ["https://example.com/img.png"]
        assert entries[0]["metadata"]["thread_id"] == "t-99"
        assert entries[0]["metadata"]["priority"] == "high"

    def test_empty_file_returns_empty_list(self, tmp_path: Path) -> None:
        """Reading an empty dead letter file returns no entries."""
        dl_path = tmp_path / "outbound_failed.jsonl"
        dl_path.write_text("")

        entries = _read_dead_letters(dl_path)
        assert entries == []
