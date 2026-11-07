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
    assert started["retrying"] is False
    assert started["qr_url"].endswith("task_id=task-1&_wv=2")
    assert store.has_pending_work

    polled = await store.poll(started["session_id"])
    assert polled["status"] == "succeeded"
    assert not store.has_pending_work
    assert polled["retrying"] is False
    assert await store.poll(started["session_id"]) == {
        "session_id": started["session_id"],
        "status": "expired",
        "message": "This QQ login has expired. Start again.",
        "retrying": False,
    }

    saved = json.loads(_isolated_config.read_text(encoding="utf-8"))
    qq = saved["channels"]["qq"]
    assert qq["appId"] == "1024"
    assert qq["secret"] == "s3cret"
    assert qq["allowFrom"] == ["42"]


@pytest.mark.asyncio
@pytest.mark.parametrize("stop", ["cancel", "close", "expire"])
async def test_qq_late_portal_result_cannot_save_after_session_ends(
    monkeypatch: pytest.MonkeyPatch, _isolated_config: Path, stop: str,
):
    key = base64.b64encode(b"k" * 32).decode()
    polling = asyncio.Event()
    release = asyncio.Event()

    async def fake_poll(_task_id: str) -> dict[str, Any]:
        polling.set()
        await release.wait()
        return {"status": 2, "bot_appid": "1024", "bot_encrypt_secret": _encrypt("new", key)}

    monkeypatch.setattr(connect, "poll_bind_task", fake_poll)
    store = QQConnectStore()
    session = store._new_session("task", key)
    before = _isolated_config.read_bytes()
    poll = asyncio.create_task(store.poll(session.id))
    try:
        await asyncio.wait_for(polling.wait(), timeout=5)
        if stop == "cancel":
            await store.cancel(session.id)
        elif stop == "close":
            await store.close()
        else:
            session.deadline = 0
        assert not store.has_pending_work
    finally:
        release.set()
    assert (await poll)["status"] == "expired"
    assert _isolated_config.read_bytes() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("stop", ["cancel", "close"])
async def test_qq_cleanup_waits_for_writer_after_poll_request_is_cancelled(
    monkeypatch: pytest.MonkeyPatch, _isolated_config: Path, stop: str,
):
    from nanobot.runtime_admission import RuntimeAdmission, RuntimeBusyError

    key = base64.b64encode(b"k" * 32).decode()
    saving = threading.Event()
    release = threading.Event()
    original_save = connect.save_credentials

    async def fake_poll(_task_id: str) -> dict[str, Any]:
        return {"status": 2, "bot_appid": "1024", "bot_encrypt_secret": _encrypt("new", key)}

    def slow_save(app_id: str, secret: str) -> None:
        saving.set()
        if not release.wait(timeout=5):
            raise TimeoutError("credential writer was not released")
        original_save(app_id, secret)

    monkeypatch.setattr(connect, "poll_bind_task", fake_poll)
    monkeypatch.setattr(connect, "save_credentials", slow_save)
    store = QQConnectStore()
    admission = RuntimeAdmission()
    admission.register_pending_work(lambda: store.has_pending_work)
    session = store._new_session("task", key)
    poll = asyncio.create_task(store.poll(session.id))
    cleanup: asyncio.Task[None | dict[str, Any]] | None = None
    try:
        assert await asyncio.to_thread(saving.wait, 5)
        poll.cancel()
        with pytest.raises(asyncio.CancelledError):
            await poll
        session.deadline = 0
        cleanup = asyncio.create_task(store.close() if stop == "close" else store.cancel(session.id))
        await asyncio.sleep(0)
        assert not cleanup.done()
        assert store.has_pending_work
        with pytest.raises(RuntimeBusyError), admission.pause_if_idle(lambda: False):
            pytest.fail("an active credential writer must block an update")
    finally:
        release.set()
        await asyncio.gather(poll, return_exceptions=True)
        if cleanup is not None:
            await cleanup
        await store.close()
    assert not store.has_pending_work
    with admission.pause_if_idle(lambda: False):
        assert admission.paused
    saved = json.loads(_isolated_config.read_text(encoding="utf-8"))["channels"]["qq"]
    assert (saved["appId"], saved["secret"], saved["allowFrom"]) == ("1024", "new", ["42"])


@pytest.mark.asyncio
async def test_qq_close_during_start_does_not_leave_a_new_session(monkeypatch: pytest.MonkeyPatch):
    creating = asyncio.Event()
    release = asyncio.Event()

    async def fake_create() -> tuple[str, str]:
        creating.set()
        await release.wait()
        return "late-task", base64.b64encode(b"k" * 32).decode()

    monkeypatch.setattr(connect, "create_bind_task", fake_create)
    store = QQConnectStore()
    start = asyncio.create_task(store.start())
    try:
        await asyncio.wait_for(creating.wait(), timeout=5)
        await store.close()
    finally:
        release.set()
    with pytest.raises(connect.ChannelConnectError, match="closed"):
        await start
    assert not store.has_pending_work


@pytest.mark.asyncio
async def test_qq_connect_clears_retrying_after_portal_recovers(monkeypatch: pytest.MonkeyPatch):
    async def fake_create() -> tuple[str, str]:
        return "task-2", base64.b64encode(b"k" * 32).decode()

    poll_count = 0

    async def fake_poll(task_id: str) -> dict[str, Any]:
        nonlocal poll_count
        assert task_id == "task-2"
        poll_count += 1
        if poll_count == 1:
            raise RuntimeError("portal hiccup")
        return {"status": 0}

    monkeypatch.setattr(connect, "create_bind_task", fake_create)
    monkeypatch.setattr(connect, "poll_bind_task", fake_poll)
    store = QQConnectStore()

    started = await store.start()
    assert started["retrying"] is False

    retrying = await store.poll(started["session_id"])
    assert retrying["status"] == "pending"
    assert retrying["retrying"] is True
    assert retrying["qr_url"] == started["qr_url"]

    waiting = await store.poll(started["session_id"])
    assert waiting["status"] == "pending"
    assert waiting["retrying"] is False
    assert waiting["qr_url"] == started["qr_url"]

    cancelled = await store.cancel(started["session_id"])
    assert cancelled["status"] == "cancelled"
    assert cancelled["retrying"] is False


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
        qq_started.set()
        if not settings_saved.wait(timeout=5):
            raise TimeoutError("settings mutation did not finish")
        return config

    def acquire(lock, *args, **kwargs):
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
