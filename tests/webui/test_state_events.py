"""Fixed WebUI invalidations follow domain facts without polling their payloads."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import Event as ThreadEvent
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from websockets.datastructures import Headers
from websockets.http11 import Request

from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket.runtime import WebSocketChannel, WebSocketConfig
from nanobot.config.loader import save_config
from nanobot.config.schema import Config
from nanobot.cron.service import CronService
from nanobot.llm_usage.models import LLMCallRecord
from nanobot.llm_usage.store import LLMUsageStore
from nanobot.pairing import store as pairing
from nanobot.triggers.local_store import LocalTriggerStore
from nanobot.webui import state_events
from nanobot.webui.gateway_services import build_gateway_services
from nanobot.webui.remote_instances import RemoteInstances
from nanobot.webui.session_automations import all_automations_payload
from nanobot.webui.settings_services import WebUISettingsConfig
from nanobot.webui.state_events import WebUIStateEvents, WebUIStateResource


@pytest.fixture(autouse=True)
def isolate_owners(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: data)
    monkeypatch.setattr(pairing, "_store_path", lambda: data / "pairing.json")
    monkeypatch.setattr("nanobot.llm_usage.service.get_data_dir", lambda: data)


def _settings(tmp_path: Path, timezone_name: str = "UTC") -> WebUISettingsConfig:
    settings = WebUISettingsConfig(tmp_path / "configuration" / "custom.json")
    config = Config()
    config.agents.defaults.timezone_mode = "manual"
    config.agents.defaults.timezone = timezone_name
    save_config(config, settings.path)
    return settings


async def _resource(queue: asyncio.Queue[tuple[WebUIStateResource, ...]], resource: str) -> None:
    async with asyncio.timeout(5):
        while resource not in await queue.get():
            pass


async def _subprocess(code: str, *args: Path | str) -> None:
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-c", code, *(str(arg) for arg in args),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=10)
    assert process.returncode == 0, (stdout.decode(), stderr.decode())


async def test_notifications_coalesce_and_replay_changes_during_delivery(tmp_path: Path) -> None:
    events: list[tuple[WebUIStateResource, ...]] = []
    entered, release, replayed = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def sender(resources: tuple[WebUIStateResource, ...]) -> None:
        events.append(resources)
        if "channels" in resources:
            entered.set()
            await release.wait()
        if "remote_instances" in resources:
            replayed.set()

    notifier = WebUIStateEvents(_settings(tmp_path))
    await notifier.start(sender)
    try:
        await asyncio.to_thread(notifier.notify, "channels", "channels", "pairing")
        await asyncio.wait_for(entered.wait(), timeout=2)
        notifier.notify("remote_instances")
        release.set()
        await asyncio.wait_for(replayed.wait(), timeout=2)
        assert ("pairing", "channels") in events
        assert events[-1] == ("remote_instances",)
    finally:
        await notifier.close()
    previous = list(events)
    notifier.notify("usage")
    await asyncio.sleep(0.1)
    assert events == previous


async def test_cross_process_pairing_delivery_and_real_expiry(tmp_path: Path) -> None:
    notifier = WebUIStateEvents(_settings(tmp_path))
    events: asyncio.Queue[tuple[WebUIStateResource, ...]] = asyncio.Queue()
    await notifier.start(events.put)
    try:
        await _subprocess('''
import sys
from pathlib import Path
from nanobot.config.loader import set_config_path
from nanobot.pairing.store import generate_code, record_delivery
set_config_path(Path(sys.argv[1]) / "config.json")
code = generate_code("telegram", "private-sender", ttl=2)
record_delivery(code, "sent")
''', tmp_path / "data")
        await _resource(events, "pairing")
        pending = pairing.list_pending()
        assert len(pending) == 1
        assert pending[0]["delivery_status"] == "sent"
        expires_at = pending[0]["expires_at"]
        while time.time() <= expires_at:
            await asyncio.sleep(min(0.05, expires_at - time.time() + 0.01))
        await _resource(events, "pairing")
        assert pairing.list_pending() == []
        assert pairing.approve_code(pending[0]["code"]) is None
    finally:
        await notifier.close()


async def test_custom_config_directory_and_persistent_owners_are_watched_separately(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    events: asyncio.Queue[tuple[WebUIStateResource, ...]] = asyncio.Queue()
    notifier = WebUIStateEvents(settings)
    await notifier.start(events.put)
    try:
        # This atomic replacement is outside the pairing/usage data directory.
        await _subprocess('''
import sys
from pathlib import Path
from nanobot.config.loader import load_config, save_config
path = Path(sys.argv[1])
config = load_config(path)
config.agents.defaults.timezone_mode = "manual"
config.agents.defaults.timezone = "America/Los_Angeles"
save_config(config, path)
''', settings.path)
        resources: set[str] = set()
        async with asyncio.timeout(5):
            while not {"channels", "usage"} <= resources:
                resources.update(await events.get())
        assert {"channels", "usage"} <= resources
        await _subprocess('''
import sys, time
from pathlib import Path
from nanobot.llm_usage.models import LLMCallRecord
from nanobot.llm_usage.store import LLMUsageStore
store = LLMUsageStore(Path(sys.argv[1]) / "llm_usage.sqlite3")
store.record(LLMCallRecord(started_at_ms=int(time.time()*1000), duration_ms=10,
    provider="fixture", model="test", source="user", stream=False, finish_reason="stop"))
store.close()
''', tmp_path / "data")
        await _resource(events, "usage")
        reader = LLMUsageStore(tmp_path / "data" / "llm_usage.sqlite3")
        try:
            assert reader.count() == 1
        finally:
            reader.close()
    finally:
        await notifier.close()


async def test_usage_store_repair_invalidates_without_blocking_gateway_start(tmp_path: Path) -> None:
    path = tmp_path / "data" / "llm_usage.sqlite3"
    path.write_bytes(b"broken database")
    notifier = WebUIStateEvents(_settings(tmp_path))
    events: asyncio.Queue[tuple[WebUIStateResource, ...]] = asyncio.Queue()
    await notifier.start(events.put)
    try:
        path.unlink()
        writer = LLMUsageStore(path)
        try:
            writer.record(LLMCallRecord(
                started_at_ms=int(time.time() * 1000), duration_ms=10, provider="fixture", model="test",
                source="user", stream=False, finish_reason="stop",
            ))
            await _resource(events, "usage")
            assert writer.count() == 1
        finally:
            writer.close()
    finally:
        await notifier.close()


async def test_cross_process_automation_actions_queues_and_run_records(tmp_path: Path) -> None:
    cron = CronService(tmp_path / "cron" / "jobs.json")
    triggers = LocalTriggerStore(tmp_path / "workspace")
    events: asyncio.Queue[tuple[WebUIStateResource, ...]] = asyncio.Queue()
    notifier = WebUIStateEvents(_settings(tmp_path), cron_service=cron, local_trigger_store=triggers)
    await notifier.start(events.put)
    try:
        await _subprocess('''
import sys
from pathlib import Path
from nanobot.cron.service import CronService
from nanobot.cron.types import CronSchedule
store = CronService(Path(sys.argv[1]) / "jobs.json")
store.add_job("from-cli", CronSchedule(kind="every", every_ms=60000), "private prompt",
    session_key="websocket:chat", origin_channel="websocket", origin_chat_id="chat")
''', cron.store_path.parent)
        await _resource(events, "automations")
        jobs = all_automations_payload(cron)["jobs"]
        assert len(jobs) == 1 and jobs[0]["name"] == "from-cli"
        await _subprocess('''
import sys
from pathlib import Path
from nanobot.cron.service import CronService
store = CronService(Path(sys.argv[1]) / "jobs.json")
store.write_run_record("external-run", {"status": "running", "response": "private output"})
''', cron.store_path.parent)
        await _resource(events, "automations")
        await _subprocess('''
import sys
from pathlib import Path
from nanobot.triggers.local_store import LocalTriggerStore
store = LocalTriggerStore(Path(sys.argv[1]))
trigger = store.create(name="cli-trigger", channel="websocket", chat_id="chat", session_key="websocket:chat")
store.enqueue(trigger.id, "private trigger payload")
''', triggers.workspace_path)
        await _resource(events, "automations")
        trigger = triggers.list_triggers()[0]
        assert trigger.name == "cli-trigger"
        await _subprocess('''
import sys
from pathlib import Path
from nanobot.triggers.local_store import LocalTriggerStore
store = LocalTriggerStore(Path(sys.argv[1]))
delivery = store.claim_deliveries()[0]
store.record_delivery(delivery.trigger_id, status="ok")
store.write_delivery_run_record(delivery, status="ok", response="private result")
store.complete_delivery(delivery)
''', triggers.workspace_path)
        await _resource(events, "automations")
        assert triggers.get(trigger.id).last_status == "ok"
    finally:
        await notifier.close()


async def test_usage_revision_follows_cross_process_commit_not_uncommitted_wal(tmp_path: Path) -> None:
    store = LLMUsageStore(tmp_path / "data" / "llm_usage.sqlite3")
    store.record(LLMCallRecord(
        started_at_ms=int(time.time() * 1000), duration_ms=10, provider="fixture", model="test",
        source="user", stream=False, finish_reason="stop",
    ))
    events: asyncio.Queue[tuple[WebUIStateResource, ...]] = asyncio.Queue()
    notifier = WebUIStateEvents(_settings(tmp_path))
    await notifier.start(events.put)
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-c", '''
import sqlite3, sys
connection = sqlite3.connect(sys.argv[1], isolation_level=None)
connection.execute("PRAGMA cache_size = 1")
connection.execute("BEGIN IMMEDIATE")
for _ in range(1000):
    connection.execute("INSERT INTO llm_calls (started_at_ms,duration_ms,provider,model,source,stream,finish_reason) "
        "VALUES (1,1,'fixture','test','user',0,'stop')")
print("uncommitted", flush=True)
sys.stdin.readline()
connection.execute("COMMIT")
print("committed", flush=True)
connection.close()
''', str(store.path), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        assert await asyncio.wait_for(process.stdout.readline(), timeout=5) == b"uncommitted\n"
        # Drain startup's optional timezone invalidation before testing the WAL signal.
        await asyncio.sleep(0.2)
        while not events.empty():
            events.get_nowait()
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(events.get(), timeout=0.3)
        process.stdin.write(b"commit\n")
        await process.stdin.drain()
        assert await asyncio.wait_for(process.stdout.readline(), timeout=5) == b"committed\n"
        await _resource(events, "usage")
        assert store.count() == 1001
    finally:
        if process.returncode is None:
            process.kill()
        await process.communicate()
        await notifier.close()
        store.close()


async def test_local_day_rollover_and_idle_sources_do_not_read_domain_payloads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [datetime(2026, 6, 4, 6, 59, 59, tzinfo=timezone.utc).timestamp()]
    monkeypatch.setattr(state_events, "time", SimpleNamespace(time=lambda: now[0]))
    monkeypatch.setattr(state_events, "_CLOCK_RECHECK_INTERVAL_S", 0.02)
    monkeypatch.setattr(state_events, "_CHANNEL_SAMPLE_INTERVAL_S", 0.02)
    status = {"telegram": {"enabled": True, "running": False, "state": "starting"}}
    settings = _settings(tmp_path, "America/Los_Angeles")
    events: asyncio.Queue[tuple[WebUIStateResource, ...]] = asyncio.Queue()
    notifier = WebUIStateEvents(settings, channel_runtime_status=lambda: status)
    await notifier.start(events.put)
    try:
        await asyncio.sleep(0.1)
        while not events.empty():
            events.get_nowait()

        def unexpected_read(*_args, **_kwargs):
            pytest.fail("idle/runtime/deadline sampling must not query persisted domain payloads")

        monkeypatch.setattr(settings, "load", unexpected_read)
        monkeypatch.setattr(state_events, "pending_expirations", unexpected_read)
        monkeypatch.setattr(LLMUsageStore, "usage_payload", unexpected_read)
        monkeypatch.setattr(pairing, "list_pending", unexpected_read)
        monkeypatch.setattr(CronService, "list_jobs", unexpected_read)
        status["telegram"]["running"] = True
        status["telegram"]["state"] = "running"
        await _resource(events, "channels")
        now[0] += 2  # Midnight in the configured zone, not UTC midnight.
        await _resource(events, "usage")
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(events.get(), timeout=0.15)
    finally:
        await notifier.close()


async def test_start_failure_closes_registered_sources_and_can_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    notifier = WebUIStateEvents(_settings(tmp_path))
    real_awatch = state_events.awatch

    async def failed_watch(*_args, **_kwargs):
        raise OSError("watch registration failed")
        yield set()

    monkeypatch.setattr(state_events, "awatch", failed_watch)
    with pytest.raises(OSError, match="registration failed"):
        await notifier.start(AsyncMock())
    assert not [task for task in asyncio.all_tasks() if task.get_name().startswith("webui-state-")]
    monkeypatch.setattr(state_events, "awatch", real_awatch)
    events: asyncio.Queue[tuple[WebUIStateResource, ...]] = asyncio.Queue()
    await notifier.start(events.put)
    try:
        notifier.notify("remote_instances")
        await _resource(events, "remote_instances")
    finally:
        await notifier.close()
        await notifier.close()
    assert not [task for task in asyncio.all_tasks() if task.get_name().startswith("webui-state-")]


async def test_cancelled_start_joins_inflight_source_read_before_releasing_ownership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path)
    entered, release = ThreadEvent(), ThreadEvent()
    original_load = settings.load

    def blocked_load():
        entered.set()
        release.wait(timeout=5)
        return original_load()

    monkeypatch.setattr(settings, "load", blocked_load)
    notifier = WebUIStateEvents(settings)
    starting = asyncio.create_task(notifier.start(AsyncMock()))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        starting.cancel()
        await asyncio.sleep(0.05)
        assert not starting.done()
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await starting
        await notifier.close()
    assert not [task for task in asyncio.all_tasks() if task.get_name().startswith("webui-state-")]


async def test_watch_error_is_re_registered_and_later_changes_are_delivered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    notifier = WebUIStateEvents(_settings(tmp_path))
    real_awatch = state_events.awatch
    interrupted = False

    async def interrupted_watch(*args, **kwargs):
        nonlocal interrupted
        async for changes in real_awatch(*args, **kwargs):
            yield changes
            if Path(args[0]) == tmp_path / "data" and not interrupted:
                interrupted = True
                raise OSError("transient native watch interruption")

    monkeypatch.setattr(state_events, "awatch", interrupted_watch)
    events: asyncio.Queue[tuple[WebUIStateResource, ...]] = asyncio.Queue()
    await notifier.start(events.put)
    try:
        assert interrupted
        code = pairing.generate_code("telegram", "during-watch-recovery", ttl=2)
        await _resource(events, "pairing")
        assert pairing.list_pending()[0]["code"] == code
        await _resource(events, "pairing")
        assert pairing.list_pending() == []
    finally:
        await notifier.close()


class _Connection:
    def __init__(self, peer: str, headers: dict[str, str]) -> None:
        self.remote_address = (peer, 12345)
        self.request = Request("/", Headers(headers))
        self.send = AsyncMock()


def _channel(tmp_path: Path) -> WebSocketChannel:
    config = WebSocketConfig()
    bus = MessageBus()
    gateway = build_gateway_services(
        config=config, bus=bus, session_manager=None, static_dist_path=None,
        workspace_path=tmp_path / "workspace", default_restrict_to_workspace=False,
        config_path=tmp_path / "configuration" / "config.json",
        runtime_model_name=None, runtime_surface="browser", runtime_capabilities_overrides=None,
    )
    return WebSocketChannel(config, bus, gateway=gateway)


async def test_wire_event_has_fixed_invalidation_only_and_trusted_local_audience(tmp_path: Path) -> None:
    channel = _channel(tmp_path)
    local = _Connection("127.0.0.1", {"Host": "localhost", "Origin": "http://localhost"})
    remote = _Connection("192.0.2.10", {"Host": "localhost"})
    forwarded = _Connection("127.0.0.1", {"Host": "localhost", "X-Forwarded-For": "192.0.2.10"})
    foreign_origin = _Connection("127.0.0.1", {"Host": "localhost", "Origin": "https://elsewhere.example"})
    untrusted = _Connection("127.0.0.1", {"Host": "localhost"})
    for connection in (local, remote, forwarded, foreign_origin, untrusted):
        token = channel.gateway.tokens.issue_token(
            60, audience="client" if connection is untrusted else "webui",
        )
        assert channel._authorize_websocket_handshake(connection, {"token": [token]}) is None
        channel._attach(connection, "chat")
    await channel.gateway.state_events.start(channel._commands.broadcast_state_change)
    try:
        channel.gateway.state_events.notify("pairing", "remote_instances", "automations", "usage", "channels")
        async with asyncio.timeout(3):
            while local.send.call_count < 1 or remote.send.call_count < 1:
                await asyncio.sleep(0.01)
        local_events = [json.loads(call.args[0]) for call in local.send.call_args_list]
        local_event = next(event for event in local_events if "remote_instances" in event.get("resources", []))
        assert local_event == {
            "event": "webui_state_changed",
            "resources": ["pairing", "channels", "automations", "usage", "remote_instances"],
        }
        for connection in (remote, forwarded, foreign_origin):
            for call in connection.send.call_args_list:
                assert "remote_instances" not in json.loads(call.args[0])["resources"]
        assert untrusted.send.call_count == 0
    finally:
        await channel.stop()


async def test_channel_listener_start_failure_closes_state_event_lifetime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    channel = _channel(tmp_path)

    async def failed_serve(*_args, **_kwargs):
        raise OSError(98, "already bound")

    monkeypatch.setattr("nanobot.channels.websocket.runtime.serve", failed_serve)
    with pytest.raises(OSError, match="already bound"):
        await channel.start()
    assert not [task for task in asyncio.all_tasks() if task.get_name().startswith("webui-state-")]
    channel.gateway.state_events.notify("pairing")
    await channel.stop()


async def test_remote_atomic_replaces_and_receipts_share_registered_watch(tmp_path: Path) -> None:
    manager = RemoteInstances(tmp_path / "client")
    key = "00000000-0000-4000-8000-000000000001"
    manager.path.parent.mkdir(parents=True)
    manager.path.write_text(json.dumps({key: {"name": "Before", "host": "user@example.com"}}))
    receipt = manager.pairing.root / "fixture-pair" / "receipt"
    receipt.parent.mkdir(parents=True, mode=0o700)
    receipt.write_text("old receipt")
    notifier = WebUIStateEvents(_settings(tmp_path), remote_instances=manager)
    events: asyncio.Queue[tuple[WebUIStateResource, ...]] = asyncio.Queue()
    script = '''
import json, os, pathlib, sys
path = pathlib.Path(sys.argv[1])
stat = path.stat()
data = json.loads(path.read_text())
data[sys.argv[2]]["name"] = sys.argv[3]
pending = path.with_suffix(".pending")
pending.write_text(json.dumps(data))
os.utime(pending, ns=(stat.st_atime_ns, stat.st_mtime_ns))
os.replace(pending, path)
'''
    await notifier.start(events.put)
    try:
        # Native notifications must observe atomic replaces even with unchanged mtime.
        for name in ("First", "Again"):
            await _subprocess(script, manager.path, key, name)
            await _resource(events, "remote_instances")
            assert (await manager.health())["profiles"][0]["name"] == name
        await _subprocess('''
from pathlib import Path
import sys
Path(sys.argv[1]).write_text("new receipt")
''', receipt)
        await _resource(events, "remote_instances")
    finally:
        await notifier.close()
        await manager.close()
    while not events.empty():
        events.get_nowait()
    await _subprocess(script, manager.path, key, "After")
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(events.get(), timeout=0.2)


async def test_pairing_encoding_error_does_not_disable_change_detection(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    path = pairing.pairing_store_path()
    path.write_bytes(b"\xff")
    notifier = WebUIStateEvents(settings)
    events: asyncio.Queue[tuple[WebUIStateResource, ...]] = asyncio.Queue()
    await notifier.start(events.put)
    try:
        for sender in ("first-repair", "second-repair"):
            await _subprocess('''
import json, sys
from pathlib import Path
from nanobot.config.loader import set_config_path
from nanobot.pairing.store import generate_code
root = Path(sys.argv[1])
set_config_path(root / "config.json")
(root / "pairing.json").write_text(json.dumps({"approved": {}, "pending": {}}))
generate_code("telegram", sys.argv[2])
''', tmp_path / "data", sender)
            await _resource(events, "pairing")
            assert pairing.list_pending()[0]["sender_id"] == sender
            if sender == "first-repair":
                path.write_bytes(b"\xff")
                await _resource(events, "pairing")
    finally:
        await notifier.close()
