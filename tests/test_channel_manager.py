from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.channels.manager import ChannelManager


def _manager() -> ChannelManager:
    mgr = object.__new__(ChannelManager)
    mgr.channels = {}
    mgr._dispatch_task = None
    mgr._dead_letter_file = pytest.importorskip("pathlib").Path("/tmp/nonexistent-dead.jsonl")
    mgr.config = SimpleNamespace(channels=SimpleNamespace(send_tool_hints=True, send_progress=True))
    mgr.bus = SimpleNamespace()
    return mgr


def _manager_with_dead_file(path: Path) -> ChannelManager:
    mgr = _manager()
    mgr._dead_letter_file = path
    return mgr


@pytest.mark.asyncio
async def test_start_channel_error_and_start_all_no_channels() -> None:
    mgr = _manager()
    bad_channel = SimpleNamespace(start=AsyncMock(side_effect=RuntimeError("boom")))
    await mgr._start_channel("x", bad_channel)
    await mgr.start_all()


@pytest.mark.asyncio
async def test_stop_all_stops_dispatch_and_channels() -> None:
    mgr = _manager()

    async def _forever() -> None:
        await asyncio.sleep(10)

    mgr._dispatch_task = asyncio.create_task(_forever())
    good = SimpleNamespace(stop=AsyncMock())
    bad = SimpleNamespace(stop=AsyncMock(side_effect=RuntimeError("stop-fail")))
    mgr.channels = {"good": good, "bad": bad}

    await mgr.stop_all()
    assert good.stop.await_count == 1
    assert bad.stop.await_count == 1


@pytest.mark.asyncio
async def test_dispatch_outbound_unknown_channel_and_timeout() -> None:
    mgr = _manager()
    mgr.channels = {}

    calls = {"n": 0}

    async def _consume() -> OutboundMessage:
        calls["n"] += 1
        if calls["n"] == 1:
            return OutboundMessage(channel="missing", chat_id="c", content="hello")
        raise asyncio.CancelledError()

    mgr.bus = SimpleNamespace(consume_outbound=_consume)

    await mgr._dispatch_outbound()


def test_getters_and_status() -> None:
    mgr = _manager()
    ch = SimpleNamespace(is_running=True)
    mgr.channels = {"telegram": ch}
    assert mgr.get_channel("telegram") is ch
    status = mgr.get_status()
    assert status["telegram"]["enabled"] is True
    assert mgr.enabled_channels == ["telegram"]


def test_write_and_read_dead_letters(tmp_path: Path) -> None:
    dead = tmp_path / "outbound_failed.jsonl"
    mgr = _manager_with_dead_file(dead)
    msg = OutboundMessage(channel="telegram", chat_id="c1", content="hello")
    mgr._write_dead_letter(msg, RuntimeError("boom"))
    dead.write_text(dead.read_text(encoding="utf-8") + "not-json\n", encoding="utf-8")

    entries = mgr._read_dead_letters()
    assert len(entries) == 1
    assert entries[0]["channel"] == "telegram"


@pytest.mark.asyncio
async def test_replay_dead_letters_dry_run_and_rewrite(tmp_path: Path) -> None:
    dead = tmp_path / "outbound_failed.jsonl"
    entries = [
        {
            "channel": "ok",
            "chat_id": "a",
            "content": "x",
            "media": [],
            "metadata": {},
        },
        {
            "channel": "fail",
            "chat_id": "b",
            "content": "y",
            "media": [],
            "metadata": {},
        },
        {
            "channel": "missing",
            "chat_id": "c",
            "content": "z",
            "media": [],
            "metadata": {},
        },
    ]
    dead.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")

    mgr = _manager_with_dead_file(dead)
    mgr.channels = {
        "ok": SimpleNamespace(send=AsyncMock(return_value=None)),
        "fail": SimpleNamespace(send=AsyncMock(side_effect=RuntimeError("nope"))),
    }

    total, ok, fail = await mgr.replay_dead_letters(dry_run=True)
    assert (total, ok, fail) == (3, 2, 1)

    total, ok, fail = await mgr.replay_dead_letters(dry_run=False)
    assert (total, ok, fail) == (3, 1, 2)
    persisted = [json.loads(line) for line in dead.read_text(encoding="utf-8").splitlines() if line]
    assert len(persisted) == 2


@pytest.mark.asyncio
async def test_dispatch_outbound_filters_and_retries(tmp_path: Path) -> None:
    mgr = _manager_with_dead_file(tmp_path / "outbound_failed.jsonl")
    mgr.config = SimpleNamespace(channels=SimpleNamespace(send_tool_hints=False, send_progress=False))

    sent = {"count": 0}

    async def _send(_msg: OutboundMessage) -> None:
        sent["count"] += 1
        if sent["count"] < 3:
            raise RuntimeError("try again")

    mgr.channels = {"telegram": SimpleNamespace(send=_send)}

    msgs = [
        OutboundMessage(
            channel="telegram",
            chat_id="c1",
            content="hint",
            metadata={"_progress": True, "_tool_hint": True},
        ),
        OutboundMessage(
            channel="telegram",
            chat_id="c1",
            content="progress",
            metadata={"_progress": True},
        ),
        OutboundMessage(channel="telegram", chat_id="c1", content="normal"),
    ]

    async def _consume() -> OutboundMessage:
        if msgs:
            return msgs.pop(0)
        raise asyncio.CancelledError()

    mgr.bus = SimpleNamespace(consume_outbound=_consume)

    await mgr._dispatch_outbound()
    assert sent["count"] == 3
