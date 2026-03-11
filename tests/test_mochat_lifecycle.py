from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nanobot.channels import mochat as mochat_mod
from nanobot.channels.mochat import MochatChannel


def _cfg() -> SimpleNamespace:
    return SimpleNamespace(
        sessions=["*"],
        panels=["panel-1"],
        watch_limit=50,
        watch_timeout_ms=100,
        refresh_interval_ms=10,
        retry_delay_ms=5,
        socket_disable_msgpack=True,
        socket_reconnect_delay_ms=50,
        socket_max_reconnect_delay_ms=100,
        max_retry_attempts=1,
        socket_url="https://example.invalid",
        base_url="https://example.invalid",
        socket_path="/socket.io",
        socket_connect_timeout_ms=100,
        claw_token="token",
        reply_delay_mode="none",
        groups={},
        mention=SimpleNamespace(require_in_groups=False),
        allow_from=[],
        agent_user_id="agent-1",
    )


def _channel(tmp_path: Path) -> MochatChannel:
    ch = object.__new__(MochatChannel)
    ch.config = _cfg()
    ch._running = True
    ch._http = None
    ch._socket = None
    ch._ws_connected = False
    ch._ws_ready = False
    ch._state_dir = tmp_path
    ch._cursor_path = tmp_path / "session_cursors.json"
    ch._session_cursor = {}
    ch._cursor_save_task = None
    ch._session_set = set()
    ch._panel_set = {"panel-1"}
    ch._auto_discover_sessions = True
    ch._auto_discover_panels = True
    ch._cold_sessions = set()
    ch._session_by_converse = {}
    ch._seen_set = {}
    ch._seen_queue = {}
    ch._delay_states = {}
    ch._fallback_mode = False
    ch._session_fallback_tasks = {}
    ch._panel_fallback_tasks = {}
    ch._refresh_task = None
    ch._target_locks = {}
    ch._handle_watch_payload = AsyncMock()
    return ch


def test_normalize_id_list_handles_star_and_dedup() -> None:
    ids, auto = MochatChannel._normalize_id_list(["a", "*", "a", " "])
    assert ids == ["a"]
    assert auto is True


@pytest.mark.asyncio
async def test_start_socket_client_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ch = _channel(tmp_path)
    monkeypatch.setattr(mochat_mod, "SOCKETIO_AVAILABLE", False)
    assert await ch._start_socket_client() is False


@pytest.mark.asyncio
async def test_subscribe_all_and_refresh_targets(tmp_path: Path) -> None:
    ch = _channel(tmp_path)
    ch._session_set = {"s1"}
    ch._panel_set = {"p1"}
    ch._auto_discover_sessions = True
    ch._auto_discover_panels = True
    ch._subscribe_sessions = AsyncMock(return_value=True)  # type: ignore[method-assign]
    ch._subscribe_panels = AsyncMock(return_value=True)  # type: ignore[method-assign]
    ch._refresh_targets = AsyncMock(return_value=None)  # type: ignore[method-assign]

    ok = await ch._subscribe_all()
    assert ok is True
    assert ch._refresh_targets.await_count == 1


@pytest.mark.asyncio
async def test_refresh_sessions_and_panels_add_new_ids(tmp_path: Path) -> None:
    ch = _channel(tmp_path)
    ch._ws_ready = True
    ch._fallback_mode = True
    ch._ensure_fallback_workers = AsyncMock(return_value=None)  # type: ignore[method-assign]
    ch._subscribe_sessions = AsyncMock(return_value=True)  # type: ignore[method-assign]
    ch._subscribe_panels = AsyncMock(return_value=True)  # type: ignore[method-assign]

    async def _post_json(path: str, payload: dict):
        if path.endswith("/sessions/list"):
            return {"sessions": [{"sessionId": "s1", "converseId": "c1"}]}
        return {"panels": [{"id": "p2", "type": 0}, {"id": "ignored", "type": 1}]}

    ch._post_json = _post_json  # type: ignore[method-assign]

    await ch._refresh_sessions_directory(subscribe_new=True)
    await ch._refresh_panels(subscribe_new=True)

    assert "s1" in ch._session_set
    assert ch._session_by_converse["c1"] == "s1"
    assert "p2" in ch._panel_set
    assert ch._ensure_fallback_workers.await_count >= 1


@pytest.mark.asyncio
async def test_ensure_and_stop_fallback_workers(tmp_path: Path) -> None:
    ch = _channel(tmp_path)
    ch._session_set = {"s1"}
    ch._panel_set = {"p1"}

    async def _session_worker(_sid: str):
        await asyncio.sleep(0)

    async def _panel_worker(_pid: str):
        await asyncio.sleep(0)

    ch._session_watch_worker = _session_worker  # type: ignore[method-assign]
    ch._panel_poll_worker = _panel_worker  # type: ignore[method-assign]

    await ch._ensure_fallback_workers()
    assert ch._fallback_mode is True
    assert "s1" in ch._session_fallback_tasks
    assert "p1" in ch._panel_fallback_tasks

    await ch._stop_fallback_workers()
    assert ch._fallback_mode is False
    assert ch._session_fallback_tasks == {}
    assert ch._panel_fallback_tasks == {}


@pytest.mark.asyncio
async def test_start_and_stop_lifecycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ch = _channel(tmp_path)
    ch._load_session_cursors = AsyncMock(return_value=None)  # type: ignore[method-assign]
    ch._seed_targets_from_config = lambda: None  # type: ignore[method-assign]
    ch._refresh_targets = AsyncMock(return_value=None)  # type: ignore[method-assign]
    ch._start_socket_client = AsyncMock(return_value=False)  # type: ignore[method-assign]
    ch._ensure_fallback_workers = AsyncMock(return_value=None)  # type: ignore[method-assign]
    ch._refresh_loop = AsyncMock(return_value=None)  # type: ignore[method-assign]

    class _Http:
        def __init__(self, timeout: float = 30.0):
            self.closed = False

        async def aclose(self):
            self.closed = True

    monkeypatch.setattr(mochat_mod.httpx, "AsyncClient", _Http)

    original_sleep = asyncio.sleep

    async def _sleep_once(_seconds: float):
        ch._running = False
        await original_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", _sleep_once)

    await ch.start()
    assert ch._ensure_fallback_workers.await_count == 1

    class _Socket:
        async def disconnect(self):
            return None

    ch._socket = _Socket()
    await ch.stop()
    assert ch._http is None
