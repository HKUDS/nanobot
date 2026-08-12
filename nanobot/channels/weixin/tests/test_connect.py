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

    async def fake_fetch_qr_code(
        self: WeixinChannel, **_kwargs: Any
    ) -> tuple[str, str]:
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

    observed_force: list[bool] = []

    async def fake_fetch_qr_code(
        self: WeixinChannel,
        *,
        force: bool = False,
    ) -> tuple[str, str]:
        observed_force.append(force)
        return f"qr-reconnect-{len(observed_force)}", "https://qr.example/reconnect"

    async def fake_api_get_with_base(
        self: WeixinChannel,
        **_kwargs: Any,
    ) -> dict[str, str]:
        return {"status": "expired"}

    monkeypatch.setattr(WeixinChannel, "_fetch_qr_code", fake_fetch_qr_code)
    monkeypatch.setattr(WeixinChannel, "_api_get_with_base", fake_api_get_with_base)

    store = WeixinConnectStore()
    started = await store.start(force=True)
    refreshed = await store.poll(started["session_id"])

    assert refreshed["status"] == "pending"
    assert observed_force == [True, True]
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

    async def fake_fetch_qr_code(
        self: WeixinChannel, **_kwargs: Any
    ) -> tuple[str, str]:
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


@pytest.mark.asyncio
async def test_weixin_connect_store_handles_verification_code(
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

    async def fake_fetch_qr_code(
        self: WeixinChannel, **_kwargs: Any
    ) -> tuple[str, str]:
        return "qr-verify", "https://qr.example/verify"

    responses = [
        {"status": "need_verifycode"},
        {
            "status": "confirmed",
            "bot_token": "verified-token",
            "ilink_user_id": "wx-user",
        },
    ]

    async def fake_api_get_with_base(
        self: WeixinChannel,
        *,
        params: dict[str, Any],
        **_kwargs: Any,
    ) -> dict[str, str]:
        if len(responses) == 1:
            assert params == {"qrcode": "qr-verify", "verify_code": "1234"}
        return responses.pop(0)

    monkeypatch.setattr(WeixinChannel, "_fetch_qr_code", fake_fetch_qr_code)
    monkeypatch.setattr(WeixinChannel, "_api_get_with_base", fake_api_get_with_base)

    store = WeixinConnectStore()
    started = await store.start()
    challenged = await store.poll(started["session_id"])
    completed = await store.handle(
        "poll",
        {
            "session_id": [started["session_id"]],
            "verify_code": ["1234"],
        },
    )

    assert challenged["status"] == "pending"
    assert challenged["challenge"] == "verify_code"
    assert completed["status"] == "succeeded"


@pytest.mark.asyncio
async def test_weixin_connect_store_rejects_existing_binding_during_forced_login(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / "weixin-state"
    state_dir.mkdir()
    (state_dir / "account.json").write_text(
        json.dumps({"token": "working-token"}),
        encoding="utf-8",
    )
    config_path = tmp_path / "config.json"
    save_config(
        Config.model_validate({"channels": {"weixin": {"stateDir": str(state_dir)}}}),
        config_path,
    )
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)

    async def fake_fetch_qr_code(
        self: WeixinChannel,
        *,
        force: bool = False,
    ) -> tuple[str, str]:
        assert force is True
        return "qr-existing", "https://qr.example/existing"

    async def fake_api_get_with_base(
        self: WeixinChannel,
        **_kwargs: Any,
    ) -> dict[str, str]:
        return {"status": "binded_redirect"}

    monkeypatch.setattr(WeixinChannel, "_fetch_qr_code", fake_fetch_qr_code)
    monkeypatch.setattr(WeixinChannel, "_api_get_with_base", fake_api_get_with_base)

    store = WeixinConnectStore()
    started = await store.start(force=True)
    completed = await store.poll(started["session_id"])

    assert completed["status"] == "failed"
    assert "new WeChat login" in completed["message"]
    assert json.loads((state_dir / "account.json").read_text())["token"] == "working-token"


@pytest.mark.asyncio
async def test_weixin_connect_store_rejects_existing_binding_without_local_credentials(
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

    async def fake_fetch_qr_code(
        self: WeixinChannel, **_kwargs: Any
    ) -> tuple[str, str]:
        return "qr-missing", "https://qr.example/missing"

    async def fake_api_get_with_base(
        self: WeixinChannel,
        **_kwargs: Any,
    ) -> dict[str, str]:
        return {"status": "binded_redirect"}

    monkeypatch.setattr(WeixinChannel, "_fetch_qr_code", fake_fetch_qr_code)
    monkeypatch.setattr(WeixinChannel, "_api_get_with_base", fake_api_get_with_base)

    store = WeixinConnectStore()
    started = await store.start(force=False)
    completed = await store.poll(started["session_id"])

    assert completed["status"] == "failed"
    assert "no local credentials" in completed["message"]
