from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nanobot.channels.mochat import (
    MAX_SEEN_MESSAGE_IDS,
    MochatBufferedEntry,
    MochatChannel,
)


def _cfg() -> SimpleNamespace:
    return SimpleNamespace(
        agent_user_id="agent-1",
        groups={},
        mention=SimpleNamespace(require_in_groups=True),
        reply_delay_mode="non-mention",
        reply_delay_ms=1,
        base_url="https://example.invalid",
        claw_token="token",
        allow_from=[],
    )


def _channel(tmp_path: Path) -> MochatChannel:
    ch = object.__new__(MochatChannel)
    ch.config = _cfg()
    ch._state_dir = tmp_path
    ch._cursor_path = tmp_path / "session_cursors.json"
    ch._session_cursor = {}
    ch._cursor_save_task = None
    ch._session_by_converse = {"conv-1": "sess-1"}
    ch._seen_set = {}
    ch._seen_queue = {}
    ch._delay_states = {}
    ch._panel_set = set()
    ch._ws_ready = False
    ch._cold_sessions = set()
    ch._http = None
    ch._handle_message = AsyncMock()
    ch._refresh_sessions_directory = AsyncMock(return_value=None)
    return ch


@pytest.mark.asyncio
async def test_process_inbound_event_delay_and_mention_flush(tmp_path: Path) -> None:
    ch = _channel(tmp_path)
    ch._enqueue_delayed_entry = AsyncMock()  # type: ignore[method-assign]
    ch._flush_delayed_entries = AsyncMock()  # type: ignore[method-assign]

    payload = {
        "author": "user-1",
        "messageId": "m1",
        "content": "hello <@agent-1>",
        "groupId": "g1",
        "authorInfo": {"nickname": "u"},
        "meta": {},
    }
    await ch._process_inbound_event("panel-1", {"payload": payload, "timestamp": "2026-01-01T00:00:00Z"}, "panel")
    assert ch._flush_delayed_entries.await_count == 1

    payload2 = dict(payload)
    payload2["messageId"] = "m2"
    payload2["content"] = "no mention"
    await ch._process_inbound_event("panel-1", {"payload": payload2}, "panel")
    assert ch._enqueue_delayed_entry.await_count == 1

    await ch._process_inbound_event("panel-1", {"payload": payload2}, "panel")
    assert ch._enqueue_delayed_entry.await_count == 1


def test_remember_message_id_rolls_window(tmp_path: Path) -> None:
    ch = _channel(tmp_path)
    key = "panel:x"
    for i in range(MAX_SEEN_MESSAGE_IDS + 3):
        assert ch._remember_message_id(key, f"m{i}") is False
    assert ch._remember_message_id(key, f"m{MAX_SEEN_MESSAGE_IDS + 2}") is True


@pytest.mark.asyncio
async def test_dispatch_flush_enqueue_and_cancel_timers(tmp_path: Path) -> None:
    ch = _channel(tmp_path)
    entry = MochatBufferedEntry(raw_body="hi", author="u1", group_id="")

    await ch._dispatch_entries("sess-1", "session", [entry], was_mentioned=False)
    assert ch._handle_message.await_count == 1

    await ch._enqueue_delayed_entry("k", "sess-1", "session", entry)
    assert "k" in ch._delay_states

    await ch._flush_delayed_entries("k", "sess-1", "session", "timer", None)

    await ch._cancel_delay_timers()
    assert ch._delay_states == {}


@pytest.mark.asyncio
async def test_notify_handlers_and_inbox_append(tmp_path: Path) -> None:
    ch = _channel(tmp_path)
    ch._process_inbound_event = AsyncMock()  # type: ignore[method-assign]

    await ch._handle_notify_chat_message({"groupId": "g1", "converseId": "p1", "content": "x", "author": "u", "meta": {}})
    assert ch._process_inbound_event.await_count == 1

    await ch._handle_notify_chat_message({"groupId": "", "converseId": "p1"})
    assert ch._process_inbound_event.await_count == 1

    payload = {
        "type": "message",
        "createdAt": "2026-01-01T00:00:00Z",
        "payload": {
            "converseId": "conv-1",
            "messageId": "mid-1",
            "messageAuthor": "u",
            "messagePlainContent": "hello",
        },
    }
    await ch._handle_notify_inbox_append(payload)
    assert ch._process_inbound_event.await_count == 2


@pytest.mark.asyncio
async def test_cursor_load_save_and_mark(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ch = _channel(tmp_path)

    ch._cursor_path.write_text(json.dumps({"cursors": {"sess-1": 10, "bad": -1}}), encoding="utf-8")
    await ch._load_session_cursors()
    assert ch._session_cursor["sess-1"] == 10

    ch._session_cursor["sess-2"] = 20
    await ch._save_session_cursors()
    assert ch._cursor_path.exists()

    ch._save_session_cursors = AsyncMock()  # type: ignore[method-assign]

    async def _fast_sleep(_s: float) -> None:
        return None

    monkeypatch.setattr("asyncio.sleep", _fast_sleep)
    ch._mark_session_cursor("sess-3", 30)
    assert ch._cursor_save_task is not None
    await ch._cursor_save_task
    assert ch._save_session_cursors.await_count == 1


@pytest.mark.asyncio
async def test_http_helpers_api_send_and_group_id(tmp_path: Path) -> None:
    ch = _channel(tmp_path)

    class _Response:
        def __init__(self, *, ok: bool, status: int = 200, data: object = None, text: str = ""):
            self.is_success = ok
            self.status_code = status
            self._data = data
            self.text = text

        def json(self):
            if isinstance(self._data, Exception):
                raise self._data
            return self._data

    class _Http:
        def __init__(self, responses):
            self._responses = responses

        async def post(self, *_a, **_k):
            return self._responses.pop(0)

    with pytest.raises(RuntimeError):
        await ch._post_json("/x", {})

    ch._http = _Http([_Response(ok=False, status=500, text="boom")])
    with pytest.raises(RuntimeError):
        await ch._post_json("/x", {})

    ch._http = _Http([_Response(ok=True, data={"code": 500, "message": "bad"})])
    with pytest.raises(RuntimeError):
        await ch._post_json("/x", {})

    ch._http = _Http([_Response(ok=True, data={"code": 200, "data": {"ok": True}})])
    parsed = await ch._post_json("/x", {"a": 1})
    assert parsed["ok"] is True

    ch._post_json = AsyncMock(return_value={"sent": 1})  # type: ignore[method-assign]
    out = await ch._api_send("/send", "sessionId", "s1", "hello", "r1", "g1")
    assert out == {"sent": 1}

    assert ch._read_group_id({"groupId": " g1 "}) == "g1"
    assert ch._read_group_id({}) is None
