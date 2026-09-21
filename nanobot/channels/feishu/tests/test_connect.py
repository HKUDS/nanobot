from __future__ import annotations

import asyncio
import threading
from typing import Any

import pytest

from nanobot.channels.feishu import runtime as feishu
from nanobot.channels.feishu.connect import FeishuConnectStore


@pytest.mark.asyncio
async def test_feishu_cancel_wins_over_inflight_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    poll_started = threading.Event()
    release_poll = threading.Event()
    saved_results: list[dict[str, Any]] = []

    monkeypatch.setattr(feishu, "_init_registration", lambda _domain: None)
    monkeypatch.setattr(
        feishu,
        "_begin_registration",
        lambda _domain: {
            "device_code": "device-cancel",
            "qr_url": "https://qr.example/cancel",
            "expire_in": 600,
            "interval": 2,
        },
    )

    def fake_poll_registration_once(**_kwargs: Any) -> dict[str, str]:
        poll_started.set()
        assert release_poll.wait(timeout=5)
        return {
            "status": "succeeded",
            "domain": "feishu",
            "app_id": "late-app",
            "app_secret": "late-secret",
        }

    def fake_save_registration_result(
        result: dict[str, Any],
        **_kwargs: Any,
    ) -> str:
        saved_results.append(result)
        return "default"

    monkeypatch.setattr(feishu, "poll_registration_once", fake_poll_registration_once)
    monkeypatch.setattr(feishu, "save_registration_result", fake_save_registration_result)

    store = FeishuConnectStore()
    started = await store.handle("start", {})
    query = {"session_id": [started["session_id"]]}
    poll_task = asyncio.create_task(store.handle("poll", query))
    assert await asyncio.to_thread(poll_started.wait, 5)

    cancelled = await store.handle("cancel", query)
    release_poll.set()
    completed = await poll_task

    assert cancelled["status"] == "cancelled"
    assert completed["status"] == "cancelled"
    assert saved_results == []


@pytest.mark.asyncio
async def test_feishu_cancel_does_not_interleave_with_registration_save(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save_started = threading.Event()
    release_save = threading.Event()

    monkeypatch.setattr(feishu, "_init_registration", lambda _domain: None)
    monkeypatch.setattr(
        feishu,
        "_begin_registration",
        lambda _domain: {
            "device_code": "device-lock",
            "qr_url": "https://qr.example/lock",
            "expire_in": 600,
            "interval": 2,
        },
    )
    monkeypatch.setattr(
        feishu,
        "poll_registration_once",
        lambda **_kwargs: {
            "status": "succeeded",
            "domain": "feishu",
            "app_id": "saved-app",
            "app_secret": "saved-secret",
        },
    )

    def fake_save_registration_result(
        _result: dict[str, Any],
        **_kwargs: Any,
    ) -> str:
        save_started.set()
        assert release_save.wait(timeout=5)
        return "default"

    monkeypatch.setattr(feishu, "save_registration_result", fake_save_registration_result)

    store = FeishuConnectStore()
    started = await store.handle("start", {})
    query = {"session_id": [started["session_id"]]}
    poll_task = asyncio.create_task(store.handle("poll", query))
    assert await asyncio.to_thread(save_started.wait, 5)

    cancel_task = asyncio.create_task(store.handle("cancel", query))
    await asyncio.sleep(0)
    assert not cancel_task.done()

    release_save.set()
    completed = await poll_task
    cancelled = await cancel_task

    assert completed["status"] == "succeeded"
    assert cancelled["status"] == "cancelled"
