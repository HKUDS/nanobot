from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from nanobot.channels.weixin.connect import WeixinConnectStore
from nanobot.channels.weixin.runtime import WeixinChannel
from nanobot.config.loader import save_config
from nanobot.config.schema import Config


@pytest.mark.asyncio
async def test_weixin_connect_store_saves_confirmed_qr_login(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / "weixin-state"
    config_path = tmp_path / "config.json"
    save_config(
        Config.model_validate({"channels": {"weixin": {"stateDir": str(state_dir)}}}),
        config_path,
    )
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)

    async def fake_fetch_qr_code(self: WeixinChannel) -> tuple[str, str]:
        return "qr-1", "https://qr.example/1"

    async def fake_api_get_with_base(
        self: WeixinChannel,
        *,
        base_url: str,
        endpoint: str,
        params: dict[str, Any],
        auth: bool,
    ) -> dict[str, str]:
        assert base_url == "https://ilinkai.weixin.qq.com"
        assert endpoint == "ilink/bot/get_qrcode_status"
        assert params == {"qrcode": "qr-1"}
        assert auth is False
        return {
            "status": "confirmed",
            "bot_token": "wx-token",
            "baseurl": "https://weixin.example",
            "ilink_user_id": "wx-user",
        }

    monkeypatch.setattr(WeixinChannel, "_fetch_qr_code", fake_fetch_qr_code)
    monkeypatch.setattr(WeixinChannel, "_api_get_with_base", fake_api_get_with_base)

    store = WeixinConnectStore()

    started = await store.start()
    assert started["status"] == "pending"
    assert started["qr_url"] == "https://qr.example/1"

    completed = await store.poll(started["session_id"])
    assert completed["status"] == "succeeded"
    assert completed["account"] == "wx-user"

    saved = json.loads((state_dir / "account.json").read_text())
    assert saved["token"] == "wx-token"
    assert saved["base_url"] == "https://weixin.example"


@pytest.mark.asyncio
async def test_weixin_reconnect_keeps_existing_account_until_scan_succeeds(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / "weixin-state"
    state_dir.mkdir()
    existing = {
        "token": "working-token",
        "base_url": "https://working.weixin.example",
        "context_tokens": {"user-1": "context-1"},
    }
    state_file = state_dir / "account.json"
    state_file.write_text(json.dumps(existing), encoding="utf-8")
    config_path = tmp_path / "config.json"
    save_config(
        Config.model_validate({"channels": {"weixin": {"stateDir": str(state_dir)}}}),
        config_path,
    )
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)

    async def fake_fetch_qr_code(self: WeixinChannel) -> tuple[str, str]:
        return "qr-reconnect", "https://qr.example/reconnect"

    monkeypatch.setattr(WeixinChannel, "_fetch_qr_code", fake_fetch_qr_code)

    store = WeixinConnectStore()
    started = await store.start(force=True)

    assert json.loads(state_file.read_text(encoding="utf-8")) == existing
    cancelled = await store.cancel(started["session_id"])
    assert cancelled["status"] == "cancelled"
    assert json.loads(state_file.read_text(encoding="utf-8")) == existing


@pytest.mark.asyncio
async def test_weixin_cancel_wins_over_inflight_confirmation(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / "weixin-state"
    config_path = tmp_path / "config.json"
    save_config(
        Config.model_validate({"channels": {"weixin": {"stateDir": str(state_dir)}}}),
        config_path,
    )
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)

    poll_started = asyncio.Event()
    release_poll = asyncio.Event()

    async def fake_fetch_qr_code(self: WeixinChannel) -> tuple[str, str]:
        return "qr-cancel", "https://qr.example/cancel"

    async def fake_api_get_with_base(
        self: WeixinChannel,
        **_kwargs: Any,
    ) -> dict[str, str]:
        poll_started.set()
        await release_poll.wait()
        return {
            "status": "confirmed",
            "bot_token": "late-token",
            "ilink_user_id": "late-user",
        }

    monkeypatch.setattr(WeixinChannel, "_fetch_qr_code", fake_fetch_qr_code)
    monkeypatch.setattr(WeixinChannel, "_api_get_with_base", fake_api_get_with_base)

    store = WeixinConnectStore()
    started = await store.handle("start", {})
    query = {"session_id": [started["session_id"]]}
    poll_task = asyncio.create_task(store.handle("poll", query))
    await asyncio.wait_for(poll_started.wait(), timeout=5)

    cancelled = await store.handle("cancel", query)
    release_poll.set()
    completed = await poll_task

    assert cancelled["status"] == "cancelled"
    assert completed["status"] == "cancelled"
    assert not (state_dir / "account.json").exists()
