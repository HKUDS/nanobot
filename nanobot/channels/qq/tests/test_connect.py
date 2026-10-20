from __future__ import annotations

import asyncio
import base64
import json
import threading
from pathlib import Path
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

    assert await asyncio.wait_for(QQConnectStore().login(), timeout=5) == ("2048", "new")
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


def test_qq_credentials_serialize_with_settings_mutations(monkeypatch: pytest.MonkeyPatch, _isolated_config):
    from filelock import FileLock

    from nanobot.config import loader
    from nanobot.webui import settings_api
    from nanobot.webui.settings_services import WebUISettingsServices

    settings = WebUISettingsServices.create(_isolated_config)
    settings_loaded = threading.Event()
    release_settings = threading.Event()
    settings_saved = threading.Event()
    qq_started = threading.Event()
    errors: list[BaseException] = []
    original_settings_load = settings_api._load_settings_config
    original_load = loader.load_config
    original_acquire = FileLock.acquire

    def settings_load(path: Path | None) -> Config:
        config = original_settings_load(path)
        settings_loaded.set()
        if not release_settings.wait(timeout=5):
            raise TimeoutError("settings mutation was not released")
        return config

    def qq_load(path: Path | None = None) -> Config:
        config = original_load(path)
        # An unlocked QQ read must finish after Settings, exposing a stale write.
        qq_started.set()
        if not settings_saved.wait(timeout=5):
            raise TimeoutError("settings mutation did not finish")
        return config

    def acquire(lock, *args, **kwargs):
        # Observe contention without replacing the real cross-process file lock.
        if threading.current_thread().name == "qq-credentials":
            qq_started.set()
        return original_acquire(lock, *args, **kwargs)

    monkeypatch.setattr(settings_api, "_load_settings_config", settings_load)
    monkeypatch.setattr(loader, "load_config", qq_load)
    monkeypatch.setattr(FileLock, "acquire", acquire)

    def save_settings() -> None:
        try:
            settings.mutate(
                settings_api.update_runtime_config_settings,
                {"tools.restrict_to_workspace": True},
                local_browser=True,
            )
        except BaseException as exc:  # noqa: BLE001 - checked after joining the thread
            errors.append(exc)
        finally:
            settings_saved.set()

    def save_qq() -> None:
        try:
            connect.save_credentials("2048", "new")
        except BaseException as exc:  # noqa: BLE001 - checked after joining the thread
            errors.append(exc)

    settings_thread = threading.Thread(target=save_settings)
    qq_thread = threading.Thread(target=save_qq, name="qq-credentials")
    settings_thread.start()
    try:
        assert settings_loaded.wait(timeout=5)
        qq_thread.start()
        assert qq_started.wait(timeout=5)
    finally:
        release_settings.set()
        settings_thread.join(timeout=5)
        if qq_thread.ident is not None:
            qq_thread.join(timeout=5)

    assert not settings_thread.is_alive()
    assert not qq_thread.is_alive()
    assert not errors
    saved = original_load(_isolated_config)
    assert saved.tools.restrict_to_workspace is True
    assert (saved.channels.qq["appId"], saved.channels.qq["secret"]) == ("2048", "new")
    assert saved.channels.qq["allowFrom"] == ["42"]


def test_qq_onboard_keeps_scanned_credentials_on_final_save(monkeypatch: pytest.MonkeyPatch, _isolated_config):
    from nanobot.channels.qq import runtime
    from nanobot.cli import onboard
    from nanobot.config.loader import load_config

    key = base64.b64encode(b"k" * 32).decode()

    async def fake_create() -> tuple[str, str]:
        return "wizard-task", key

    async def fake_poll(_task_id: str) -> dict[str, Any]:
        return {"status": 2, "bot_appid": "2048", "bot_encrypt_secret": _encrypt("new", key)}

    monkeypatch.setattr(connect, "create_bind_task", fake_create)
    monkeypatch.setattr(connect, "poll_bind_task", fake_poll)
    monkeypatch.setattr(connect, "_print_qr", lambda _url: None)
    monkeypatch.setattr(onboard, "_get_channel_class", lambda _name: runtime.QQChannel)
    monkeypatch.setattr(runtime, "get_media_dir", lambda _name: _isolated_config.parent / "media")
    config = load_config(_isolated_config)
    model = runtime.QQConfig.model_validate(config.channels.qq)

    assert onboard._run_channel_login(config, "qq", model, "QQ") is True
    save_config(config, _isolated_config)

    saved = load_config(_isolated_config).channels.qq
    assert (saved["appId"], saved["secret"]) == ("2048", "new")
    assert saved["enabled"] is True
    assert saved["allowFrom"] == ["42"]


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["connected", "expired", "save_failed"])
async def test_qq_forced_login_commits_model_only_after_saving(
    monkeypatch: pytest.MonkeyPatch, _isolated_config, outcome: str,
):
    from nanobot.bus.queue import MessageBus
    from nanobot.channels.qq import runtime

    key = base64.b64encode(b"k" * 32).decode()

    async def fake_create() -> tuple[str, str]:
        return "replacement-task", key

    async def fake_poll(_task_id: str) -> dict[str, Any]:
        if outcome == "expired":
            return {"status": 3}
        return {"status": 2, "bot_appid": "2048", "bot_encrypt_secret": _encrypt("new", key)}

    def fail_save(_app_id: str, _secret: str) -> None:
        raise OSError("config is not writable")

    monkeypatch.setattr(connect, "create_bind_task", fake_create)
    monkeypatch.setattr(connect, "poll_bind_task", fake_poll)
    monkeypatch.setattr(connect, "_print_qr", lambda _url: None)
    monkeypatch.setattr(runtime, "get_media_dir", lambda _name: _isolated_config.parent / "media")
    channel = runtime.QQChannel({"appId": "1024", "secret": "old"}, MessageBus())

    if outcome == "save_failed":
        monkeypatch.setattr(connect, "save_credentials", fail_save)
        with pytest.raises(OSError, match="config is not writable"):
            await channel.login(force=True)
    else:
        assert await channel.login(force=True) is (outcome == "connected")

    expected = ("2048", "new") if outcome == "connected" else ("1024", "old")
    assert (channel.config.app_id, channel.config.secret) == expected


def test_decrypt_secret_rejects_wrong_key():
    key = base64.b64encode(b"k" * 32).decode()
    encrypted = _encrypt("s3cret", key)
    with pytest.raises(Exception):
        _decrypt_secret(encrypted, base64.b64encode(b"x" * 32).decode())
