from __future__ import annotations

import asyncio
import base64
import json
from typing import Any

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from nanobot.channels.qq import connect
from nanobot.channels.qq.connect import QQConnectStore, _decrypt_secret
from nanobot.config.loader import save_config
from nanobot.config.schema import Config


def _encrypt(secret: str, key: str) -> str:
    iv = b"\x01" * 12
    raw = iv + AESGCM(base64.b64decode(key)).encrypt(iv, secret.encode(), None)
    return base64.b64encode(raw).decode()


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path, monkeypatch: pytest.MonkeyPatch):
    config_path = tmp_path / "config.json"
    save_config(Config.model_validate({"channels": {"qq": {"allowFrom": ["42"]}}}), config_path)
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)
    monkeypatch.setattr(connect, "POLL_INTERVAL_MS", 0)
    return config_path


@pytest.mark.asyncio
async def test_qq_connect_writes_scanned_credentials_to_config(monkeypatch: pytest.MonkeyPatch, _isolated_config):
    async def fake_create() -> tuple[str, str]:
        return "task-1", base64.b64encode(b"k" * 32).decode()

    async def fake_poll(task_id: str) -> dict[str, Any]:
        assert task_id == "task-1"
        key = base64.b64encode(b"k" * 32).decode()
        return {"status": 2, "bot_appid": "1024", "bot_encrypt_secret": _encrypt("s3cret", key)}

    monkeypatch.setattr(connect, "create_bind_task", fake_create)
    monkeypatch.setattr(connect, "poll_bind_task", fake_poll)
    store = QQConnectStore()

    started = await store.start()
    assert started["status"] == "pending"
    assert started["qr_url"].endswith("task_id=task-1&_wv=2")

    polled = await store.poll(started["session_id"])
    assert polled["status"] == "succeeded"
    assert await store.poll(started["session_id"]) == {
        "session_id": started["session_id"],
        "status": "expired",
        "message": "This QQ login has expired. Start again.",
    }

    saved = json.loads(_isolated_config.read_text(encoding="utf-8"))
    qq = saved["channels"]["qq"]
    assert qq["appId"] == "1024"
    assert qq["secret"] == "s3cret"
    assert qq["allowFrom"] == ["42"]


@pytest.mark.asyncio
async def test_qq_connect_keeps_waiting_on_transient_portal_errors(monkeypatch: pytest.MonkeyPatch):
    async def fake_create() -> tuple[str, str]:
        return "task-2", base64.b64encode(b"k" * 32).decode()

    async def fake_poll(_task_id: str) -> dict[str, Any]:
        raise RuntimeError("portal hiccup")

    monkeypatch.setattr(connect, "create_bind_task", fake_create)
    monkeypatch.setattr(connect, "poll_bind_task", fake_poll)
    store = QQConnectStore()

    started = await store.start()
    assert (await store.poll(started["session_id"]))["status"] == "pending"


@pytest.mark.asyncio
async def test_qq_login_scans_and_persists(monkeypatch: pytest.MonkeyPatch, _isolated_config):
    key = base64.b64encode(b"k" * 32).decode()

    async def fake_create() -> tuple[str, str]:
        return "task-3", key

    async def fake_poll(_task_id: str) -> dict[str, Any]:
        return {"status": 2, "bot_appid": "2048", "bot_encrypt_secret": _encrypt("new", key)}

    monkeypatch.setattr(connect, "create_bind_task", fake_create)
    monkeypatch.setattr(connect, "poll_bind_task", fake_poll)
    monkeypatch.setattr(connect, "_print_qr", lambda _url: None)

    assert await asyncio.wait_for(QQConnectStore().login(), timeout=5) is True
    saved = json.loads(_isolated_config.read_text(encoding="utf-8"))["channels"]["qq"]
    assert (saved["appId"], saved["secret"]) == ("2048", "new")


@pytest.mark.asyncio
async def test_qq_login_skips_scan_when_credentials_configured(monkeypatch: pytest.MonkeyPatch):
    from nanobot.bus.queue import MessageBus
    from nanobot.channels.qq.runtime import QQChannel

    async def fail_scan(*_args, **_kwargs):
        raise AssertionError("scan should not start")

    monkeypatch.setattr(connect, "create_bind_task", fail_scan)
    channel = QQChannel({"appId": "1024", "secret": "s3cret"}, MessageBus())
    assert await channel.login() is True


def test_decrypt_secret_rejects_wrong_key():
    key = base64.b64encode(b"k" * 32).decode()
    encrypted = _encrypt("s3cret", key)
    with pytest.raises(Exception):
        _decrypt_secret(encrypted, base64.b64encode(b"x" * 32).decode())
