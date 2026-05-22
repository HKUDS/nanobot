"""Tests for the filesystem inter-bot channel."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.filesystem import FilesystemChannel
from nanobot.config.schema import FilesystemConfig, FilesystemPeerConfig


def _make_channel(tmp_path: Path, archive: bool = False) -> tuple[FilesystemChannel, MessageBus, Path, Path]:
    inbox = tmp_path / "inbox"
    outbox = tmp_path / "outbox"
    archive_dir = tmp_path / "archive" if archive else None
    bus = MessageBus()
    cfg = FilesystemConfig(
        enabled=True,
        poll_interval_ms=50,
        peers=[
            FilesystemPeerConfig(
                peer_id="botB",
                inbox=str(inbox),
                outbox=str(outbox),
                archive=str(archive_dir) if archive_dir else "",
            )
        ],
    )
    channel = FilesystemChannel(cfg, bus)
    return channel, bus, inbox, outbox


async def _drive(channel: FilesystemChannel, predicate, timeout: float = 2.0):
    task = asyncio.create_task(channel.start())
    try:
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            if predicate():
                return
            await asyncio.sleep(0.02)
        raise AssertionError("predicate not satisfied within timeout")
    finally:
        await channel.stop()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_inbound_file_published_to_bus(tmp_path):
    channel, bus, inbox, _ = _make_channel(tmp_path)
    inbox.mkdir(parents=True)
    (inbox / "001.md").write_text("hello from peer", encoding="utf-8")

    await _drive(channel, lambda: bus.inbound_size > 0)

    msg = await bus.consume_inbound()
    assert msg.channel == "fs"
    assert msg.sender_id == "botB"
    assert msg.chat_id == "botB"
    assert msg.content == "hello from peer"


@pytest.mark.asyncio
async def test_processed_file_is_deleted_by_default(tmp_path):
    channel, bus, inbox, _ = _make_channel(tmp_path)
    inbox.mkdir(parents=True)
    target = inbox / "001.md"
    target.write_text("payload", encoding="utf-8")

    await _drive(channel, lambda: not target.exists())
    assert not target.exists()


@pytest.mark.asyncio
async def test_processed_file_moved_to_archive_when_configured(tmp_path):
    channel, bus, inbox, _ = _make_channel(tmp_path, archive=True)
    inbox.mkdir(parents=True)
    (inbox / "001.md").write_text("payload", encoding="utf-8")
    archive = tmp_path / "archive"

    await _drive(channel, lambda: archive.exists() and any(archive.iterdir()))
    assert (archive / "001.md").read_text() == "payload"
    assert not (inbox / "001.md").exists()


@pytest.mark.asyncio
async def test_tmp_and_hidden_files_are_ignored(tmp_path):
    channel, bus, inbox, _ = _make_channel(tmp_path)
    inbox.mkdir(parents=True)
    (inbox / ".hidden").write_text("nope", encoding="utf-8")
    (inbox / "partial.tmp").write_text("nope", encoding="utf-8")
    (inbox / "001.md").write_text("yes", encoding="utf-8")

    await _drive(channel, lambda: bus.inbound_size > 0)
    msg = await bus.consume_inbound()
    assert msg.content == "yes"

    # The skipped files should remain.
    assert (inbox / ".hidden").exists()
    assert (inbox / "partial.tmp").exists()


@pytest.mark.asyncio
async def test_outbound_writes_to_peer_outbox(tmp_path):
    channel, _bus, _inbox, outbox = _make_channel(tmp_path)
    outbox.mkdir(parents=True)

    await channel.send(OutboundMessage(channel="fs", chat_id="botB", content="ping"))

    files = list(outbox.iterdir())
    assert len(files) == 1
    assert files[0].suffix == ".md"
    assert files[0].read_text() == "ping"


@pytest.mark.asyncio
async def test_outbound_unknown_peer_is_dropped(tmp_path):
    channel, _bus, _inbox, outbox = _make_channel(tmp_path)
    outbox.mkdir(parents=True)

    await channel.send(OutboundMessage(channel="fs", chat_id="unknown", content="ping"))

    assert list(outbox.iterdir()) == []


@pytest.mark.asyncio
async def test_round_trip_between_two_channels(tmp_path):
    """Bot A's outbox is Bot B's inbox, and vice versa."""
    a_to_b = tmp_path / "a_to_b"
    b_to_a = tmp_path / "b_to_a"
    a_to_b.mkdir()
    b_to_a.mkdir()

    bus_a = MessageBus()
    bus_b = MessageBus()
    chan_a = FilesystemChannel(
        FilesystemConfig(
            enabled=True,
            poll_interval_ms=50,
            peers=[FilesystemPeerConfig(peer_id="botB", inbox=str(b_to_a), outbox=str(a_to_b))],
        ),
        bus_a,
    )
    chan_b = FilesystemChannel(
        FilesystemConfig(
            enabled=True,
            poll_interval_ms=50,
            peers=[FilesystemPeerConfig(peer_id="botA", inbox=str(a_to_b), outbox=str(b_to_a))],
        ),
        bus_b,
    )

    task_a = asyncio.create_task(chan_a.start())
    task_b = asyncio.create_task(chan_b.start())
    try:
        # A -> B
        await chan_a.send(OutboundMessage(channel="fs", chat_id="botB", content="hi B"))
        deadline = asyncio.get_event_loop().time() + 2.0
        while bus_b.inbound_size == 0 and asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.02)
        msg_to_b = await bus_b.consume_inbound()
        assert msg_to_b.sender_id == "botA"
        assert msg_to_b.content == "hi B"

        # B -> A
        await chan_b.send(OutboundMessage(channel="fs", chat_id="botA", content="hi A"))
        deadline = asyncio.get_event_loop().time() + 2.0
        while bus_a.inbound_size == 0 and asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.02)
        msg_to_a = await bus_a.consume_inbound()
        assert msg_to_a.sender_id == "botB"
        assert msg_to_a.content == "hi A"
    finally:
        await chan_a.stop()
        await chan_b.stop()
        for t in (task_a, task_b):
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass
