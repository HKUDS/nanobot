"""Run native packaged upgrade/recovery journeys in a disposable account.

The healthy target is the exact supplied wheel, not a patched application. The
default baseline is explicitly a version-only fixture with a local feed transport
and bounded fault injection. It does not stand for an older published release.
Use --baseline-wheel to exercise an actual earlier updater-enabled package too.
No public feed, user installation, model, credentials or OS service is used.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import csv
import hashlib
import importlib.util
import io
import json
import os
import platform
import re
import secrets
import signal
import socket
import sqlite3
import subprocess
import sys
import time
from contextlib import ExitStack, closing, contextmanager
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch
from urllib.parse import quote
from zipfile import ZIP_DEFLATED, ZipFile

if TYPE_CHECKING:
    from nanobot.agent.tools._windows_job import WindowsJob

SCENARIOS = ("upgrade", "upgrade-again", "skipped-preview", "import-failure", "restart-failure",
             "backup-failure", "worker-exit", "metadata-loss", "restore-interruption")
TWO_JOURNEY_SCENARIOS = {"upgrade-again", "import-failure", "restart-failure", "backup-failure",
                         "metadata-loss", "restore-interruption"}
# Each lane retains the existing per-command deadlines and cleanup. This outer
# bound also covers a stuck controller; it is not permission to leave it running.
LANE_TIMEOUT = 30 * 60


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class Timings:
    """Separate, incrementally persisted evidence; never include commands or logs."""

    def __init__(self, output: Path):
        self.output = output
        self.records: list[dict] = []

    @contextmanager
    def measure(self, phase: str, *, scenario: str | None = None, journey: int | None = None):
        started = time.perf_counter()
        succeeded = False
        try:
            yield
            succeeded = True
        finally:
            record = {"phase": phase, "scenario": scenario, "journey": journey,
                      "seconds": time.perf_counter() - started,
                      "status": "succeeded" if succeeded else "failed"}
            self.records.append(record)
            self.checkpoint()
            label = "/".join(str(value) for value in (scenario, journey, phase) if value is not None)
            print(f"TIMING {label}: {record['seconds']:.3f}s ({record['status']})", flush=True)

    def checkpoint(self) -> None:
        # Each controller owns its file. The parent imports only settled lane
        # checkpoints, never raw logs or concurrent writes to a shared report.
        temporary = self.output.with_suffix(".tmp")
        write(temporary, {"schema_version": 1, "clock": "perf_counter", "timings": self.records})
        temporary.replace(self.output)

    def merge(self, source: Path, worker: int) -> None:
        keys = ("phase", "scenario", "journey", "seconds", "status")
        self.records.extend({**{key: row[key] for key in keys}, "worker": worker}
                            for row in read(source)["timings"])
        self.checkpoint()


def replace_once(source: bytes, old: bytes, new: bytes) -> bytes:
    if source.count(old) != 1:
        raise ValueError("The fault-injection seam changed; review the acceptance fixture")
    return source.replace(old, new, 1)


def fixture_wheel(source: Path, output: Path, version: str, *, feed: Path | None = None,
                  scenario: str = "upgrade") -> Path:
    """Private instrumentation only; never overwrite or relabel the supplied target."""
    from packaging.utils import parse_wheel_filename

    _, previous, _, _ = parse_wheel_filename(source.name)
    prefix, replacement = f"nanobot_ai-{previous}.dist-info/", f"nanobot_ai-{version}.dist-info/"
    with ZipFile(source) as archive:
        entries = [(item, archive.read(item)) for item in archive.infolist() if not item.filename.endswith("/RECORD")]
    files = {item.filename.replace(prefix, replacement): data for item, data in entries}
    metadata = replacement + "METADATA"
    files[metadata] = replace_once(files[metadata], f"Version: {previous}\n".encode(), f"Version: {version}\n".encode())
    if feed is not None:
        # This existing injectable transport runs in both planner and preflight
        # processes. It cannot reach external hosts. These private packages are
        # not approved public releases: signature admission is exercised by the
        # separate trust tests, not this installation/recovery fixture.
        files["nanobot/_acceptance_feed.py"] = f'''import json
from pathlib import Path
import httpx
def transport():
    def respond(request):
        record = json.loads(Path({str(feed)!r}).read_text(encoding="utf-8"))
        if request.method != "GET" or str(request.url) not in record:
            raise ValueError("Unexpected acceptance feed request: " + str(request.url))
        item = record[str(request.url)]
        return httpx.Response(200, content=Path(item["file"]).read_bytes() if "file" in item else json.dumps(item["json"]).encode())
    return httpx.MockTransport(respond)
'''.encode()
        files["nanobot/release_feed.py"] = replace_once(
            files["nanobot/release_feed.py"], b"transport=transport or PinnedDNSAsyncTransport(),",
            b'transport=transport or __import__("nanobot._acceptance_feed", fromlist=["transport"]).transport(),')
        if b"await self._authorize(target)" in files["nanobot/release_feed.py"]:
            files["nanobot/release_feed.py"] = replace_once(
                files["nanobot/release_feed.py"], b"await self._authorize(target)",
                b"pass  # Private unsigned acceptance fixture, never a distributable wheel.")
        # Windows source archives can contain CRLF. Normalize only the private
        # instrumentation copy; the final target's bytes remain untouched.
        worker = files["nanobot/update_worker.py"].replace(b"\r\n", b"\n")
        # Inject into the first job in this disposable account. The recovered
        # updater must subsequently install a release without re-injecting it.
        fault = f"__import__('pathlib').Path({str(feed.parent / 'injected-fault')!r})"
        if scenario == "worker-exit":
            needle = b'            env = {key: value for key, value in os.environ.items() if not key.upper().startswith("PIP_")}\n'
            worker = replace_once(worker, needle, f'''            if not {fault}.exists():
                {fault}.touch()
                (directory / 'fault-fired').write_text('worker exit')
                os._exit(91)
'''.encode() + needle)
        elif scenario == "metadata-loss":
            needle = b"\n            _verify(spec, directory)\n"
            worker = replace_once(worker, needle, f'''
            if not {fault}.exists():
                {fault}.touch()
                (directory / 'fault-fired').write_text('metadata loss')
                next(Path(spec.baseline.environment).rglob('nanobot_ai-' + spec.version + '.dist-info/METADATA')).unlink()
                os._exit(92)
'''.encode() + needle)
        elif scenario == "backup-failure":
            needle = b"                ensure_backup(directory, spec.backup_sources,\n"
            worker = replace_once(worker, needle, f'''                if not {fault}.exists():
                    {fault}.write_text(str(directory))
                if {fault}.read_text() == str(directory):
                    raise OSError('Injected backup write failure')
'''.encode() + needle)
        files["nanobot/update_worker.py"] = worker
        if scenario == "restore-interruption":
            needle = b"    os.rename(original, environment)\n"
            files["nanobot/update_fallback.py"] = replace_once(files["nanobot/update_fallback.py"].replace(b"\r\n", b"\n"), needle, b'''    if not (directory / 'restore-fault-fired').exists():
        (directory / 'restore-fault-fired').write_text('interrupted between renames')
        raise OSError('Injected rename interruption')
''' + needle)
    elif scenario in {"import-failure", "restore-interruption"}:
        files["nanobot/__init__.py"] = b"raise RuntimeError('Injected candidate import failure')\n"
    elif scenario == "restart-failure":
        files["nanobot/update_restart.py"] = b"raise RuntimeError('Injected candidate startup failure')\n"
    record = replacement + "RECORD"
    rows = io.StringIO()
    writer = csv.writer(rows, lineterminator="\n")
    for name, content in files.items():
        writer.writerow((name, "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode(), len(content)))
    writer.writerow((record, "", ""))
    files[record] = rows.getvalue().encode()
    output.mkdir(parents=True, exist_ok=True)
    result = output / source.name.replace(f"-{previous}-", f"-{version}-", 1)
    info = {item.filename.replace(prefix, replacement): item for item, _ in entries}
    with ZipFile(result, "x", compression=ZIP_DEFLATED) as archive:
        for name, content in files.items():
            if name in info:
                item = info[name]
                item.filename = name  # Retain native executable permissions.
                archive.writestr(item, content)
            else:
                archive.writestr(name, content)
    return result


def feed_records(wheel: Path, commit: str, *, generation: int = 1) -> dict:
    from packaging.utils import parse_wheel_filename
    from packaging.version import Version

    from nanobot.release_feed import CATALOGUE_URL
    from nanobot.releases import (
        ReleaseArtifact,
        ReleaseCatalogue,
        ReleaseManifest,
        ReleasePointer,
        release_filenames,
    )

    version = str(parse_wheel_filename(wheel.name)[1])
    artifacts = [ReleaseArtifact(filename=name, size=wheel.stat().st_size if name == wheel.name else 1,
                                sha256=digest(wheel) if name == wheel.name else "a" * 64)
                 for name in sorted(release_filenames(version))]
    if not Version(version).is_prerelease:
        base = "https://files.pythonhosted.org/packages/"
        metadata = {"info": {"name": "nanobot-ai", "version": version, "requires_python": ">=3.11"},
                    "urls": [{"filename": item.filename, "size": item.size, "url": base + item.filename,
                              "digests": {"sha256": item.sha256}, "yanked": False}
                             for item in artifacts if item.filename.endswith((".whl", ".tar.gz"))]}
        return {base + wheel.name: {"file": str(wheel)},
                "https://pypi.org/pypi/nanobot-ai/json": {"json": metadata},
                f"https://pypi.org/pypi/nanobot-ai/{version}/json": {"json": metadata}}
    manifest = ReleaseManifest(version=version, source_commit=commit, candidate_commit=commit,
                               requires_python=">=3.11", artifacts=artifacts)
    data = manifest.model_dump(mode="json")
    pointer = ReleasePointer(version=version, candidate_commit=commit,
                             manifest_sha256=hashlib.sha256(json.dumps(data).encode()).hexdigest())
    catalogue = ReleaseCatalogue(generation=generation, preview=pointer)
    base = f"https://github.com/HKUDS/nanobot/releases/download/v{version}/"
    return {CATALOGUE_URL: {"json": catalogue.model_dump(mode="json")},
            base + "release-manifest.json": {"json": data}, base + wheel.name: {"file": str(wheel)}}


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def gateway(root: Path, *arguments: str) -> None:
    subprocess.run([sys.executable, "-I", "-m", "nanobot", "gateway", *arguments,
                    "--config", str(root / "account/.nanobot/config.json")], check=True, timeout=60)


def _dock_supported(root: Path) -> bool:
    return bool(read(root / "case.json").get("dock")
                and importlib.util.find_spec("nanobot.cli.dock") is not None)


def _desktop_webui(root: Path) -> None:
    # The real managed receipt must select automatic detachment, not a test flag.
    subprocess.run([sys.executable, "-I", "-m", "nanobot", "webui", "--yes", "--no-open",
                    "--config", str(root / "account/.nanobot/config.json")], check=True, timeout=60)


def _dock_socket(root: Path) -> Path:
    from nanobot.cli.dock import _directory
    from nanobot.cli.webui_support import _webui_browser_url
    from nanobot.config.loader import load_config
    from nanobot.gateway.runtime import GatewayInstance

    config = root / "account/.nanobot/config.json"
    instance = GatewayInstance.resolve(config_path=config)
    return _directory(instance.paths.state_path, _webui_browser_url(load_config(config))) / "s"


def _wait_dock(address: Path, *, present: bool) -> None:
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        processes = subprocess.run(["/usr/bin/pgrep", "-f", str(address)], capture_output=True,
                                   text=True, check=False)
        count = len(processes.stdout.split())
        if count == (1 if present else 0):
            return
        time.sleep(0.1)
    raise AssertionError(f"Expected {'one live' if present else 'no'} Dock helper")


def request(root: Path, path: str):
    import httpx

    config = read(root / "account/.nanobot/config.json")
    web = config["channels"]["websocket"]
    base = f'http://127.0.0.1:{web["port"]}'
    with httpx.Client(timeout=10, trust_env=False) as client:
        bootstrap = client.get(base + "/webui/bootstrap", headers={"X-Nanobot-Auth": web["tokenIssueSecret"]})
        bootstrap.raise_for_status()
        if path == "/webui/bootstrap":
            return bootstrap.json()
        headers = ({"X-Nanobot-Auth": web["tokenIssueSecret"]} if path == "/webui/terminal"
                   else {"Authorization": "Bearer " + bootstrap.json()["api_token"]})
        response = client.get(base + path, headers=headers)
        response.raise_for_status()
        return response.json()


def history(root: Path, key: str):
    rows = request(root, "/api/sessions")["sessions"]
    assert key in {row["key"] for row in rows}, rows
    response = request(root, "/api/sessions/" + quote(key, safe="") + "/webui-thread")
    # Revision/ETag and gateway identity must change after restart. Compare the
    # persisted transcript, not that intentionally volatile response envelope.
    return {name: response[name] for name in ("events", "completed_turn_ids")}


def assert_history_preserved(before: dict, after: dict) -> None:
    """Allow only known additive defaults in the older transcript projection."""
    assert after["completed_turn_ids"] == before["completed_turn_ids"]
    assert len(after["events"]) == len(before["events"])
    for previous, current in zip(before["events"], after["events"], strict=True):
        current = dict(current)
        # SQLite represents an unknown legacy timestamp as zero. New projection
        # also exposes the already-persisted inactive goal on a completed turn.
        # Do not ignore these fields when the old API supplied an actual value.
        if "created_at_ms" not in previous and current.get("created_at_ms") == 0:
            del current["created_at_ms"]
        if (previous["event"] == "turn_end" and "goal_state" not in previous
                and current.get("goal_state") == {"active": False}):
            del current["goal_state"]
        assert current == previous, (current, previous)


def canonical_records(path: Path, tables: tuple[str, ...] = ("sessions", "messages", "checkpoints", "pending_inputs")) -> dict:
    """Compare logical records, not SQLite's transient WAL/checkpoint layout."""
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        return {table: [list(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY 1, 2")]
                for table in tables}


def assert_canonical_preserved(before: dict, after: dict) -> None:
    """Schema v2 may add a display-only owner, never model context or lost rows."""
    key = "websocket:display-only"
    existing = {row[0] for row in before["sessions"]}
    added = [row for row in after["sessions"] if row[0] == key and key not in existing]
    for row in added:
        # A newly imported display transcript owns an empty Session. Only its
        # identity/timestamps and the public handle allocated by /api/sessions
        # are new; it must not manufacture agent context or other metadata.
        metadata = json.loads(row[3])
        if metadata:
            assert set(metadata) == {"session_handle"}, row
            handle = metadata["session_handle"]
            assert isinstance(handle, str) and re.fullmatch("[a-z]{4,16}", handle), row
        revision = 2 if metadata else 1
        assert row[4:7] == [None, 0, revision] and row[8:] == ["", "", None], row
    comparable = {**after, "sessions": [row for row in after["sessions"] if row not in added]}
    assert comparable == before, (comparable, before)


def canonical_context(root: Path) -> dict:
    context = request(root, "/api/sessions/websocket%3Acanonical-only/context")
    # Tokenizer availability can alter estimates; stored message content is
    # checked separately against every canonical SQLite record.
    return {key: value for key, value in context.items() if not key.startswith("estimated_")}


async def chat(root: Path, chat_id: str | None = None) -> str:
    import websockets

    bootstrap = request(root, "/webui/bootstrap")
    async def receive(ws, event):
        async with asyncio.timeout(30):
            while True:
                value = json.loads(await ws.recv())
                if value.get("event") == event:
                    return value
    async with websockets.connect(bootstrap["ws_url"] + "?token=" + bootstrap["token"] + "&client_id=package-acceptance") as ws:
        await receive(ws, "ready")
        await ws.send(json.dumps({"type": "attach", "chat_id": chat_id} if chat_id else {"type": "new_chat"}))
        attached = await receive(ws, "attached")
        chat_id = attached["chat_id"]
        await ws.send(json.dumps({"type": "message", "chat_id": chat_id, "content": "/model", "webui": True,
                                  "turn_id": "acceptance-" + secrets.token_hex(8)}))
        answer = await receive(ws, "message")
        assert "acceptance-no-model" in answer["text"], answer
        await receive(ws, "turn_end")
    return chat_id


def ready(root: Path, version: str):
    from nanobot.gateway.runtime import GatewayRuntime
    from nanobot.update_profiles import inspect_profiles

    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        profiles = inspect_profiles(str(Path(sys.prefix).resolve()))
        if len(profiles) == 1:
            receipt = profiles[0].receipt
            if GatewayRuntime().verify_ready(receipt.health_identity, maintenance=False):
                assert receipt.version == version, (receipt.version, version)
                assert request(root, "/webui/terminal")["webui"]["version"] == version
                return receipt
        time.sleep(0.2)
    raise RuntimeError("The actual installed gateway did not become ready")


def seed(root: Path) -> None:
    import nanobot
    from nanobot.config.loader import load_config, save_config, set_config_path
    from nanobot.config.paths import get_webui_dir

    assert Path(nanobot.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
    config_path = root / "account/.nanobot/config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    set_config_path(config_path)
    config = load_config(config_path)
    config.agents.defaults.workspace = str(root / "workspace")
    config.agents.defaults.provider = "custom"
    config.agents.defaults.model = "acceptance-no-model"
    config.agents.defaults.dream.enabled = False
    config.agents.defaults.session_ttl_minutes = 0
    config.providers.custom.api_key = "fixture-not-a-secret"
    config.providers.custom.api_base = "http://127.0.0.1:1/v1"
    config.gateway.host, config.gateway.port = "127.0.0.1", free_port()
    config.gateway.heartbeat.enabled = False
    config.channels.websocket = {"enabled": True, "host": "127.0.0.1", "port": free_port(),
                                 "tokenIssueSecret": secrets.token_urlsafe(32), "websocketRequiresToken": True}
    save_config(config, config_path)
    # Real historical canonical files are imported by the installed SQLite owner,
    # not generated by a new-store round trip. Existing source bytes stay readable.
    if importlib.util.find_spec("nanobot.session.location") is not None:
        from nanobot.session.location import SessionLocation
        location = SessionLocation(root / "workspace")
    else:
        # The retained pre-SQLite package owns the same namespace here. This is
        # acceptance-fixture compatibility, not a fallback in the application.
        from nanobot.session.manager import JsonlSessionStore
        location = JsonlSessionStore(root / "workspace")
    sessions = location.sessions_dir
    key = "websocket:legacy-acceptance"
    legacy = sessions / (location.storage_key(key) + ".jsonl")
    legacy.write_text(json.dumps({"_type": "metadata", "key": key, "metadata": {"title": "升级前的聊天"},
                                 "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00"}) + "\n" +
                      json.dumps({"role": "user", "content": "配置和聊天不能丢失"}, ensure_ascii=False) + "\n", encoding="utf-8")
    canonical_only = sessions / (location.storage_key("websocket:canonical-only") + ".jsonl")
    canonical_only.write_bytes(legacy.read_bytes().replace(key.encode(), b"websocket:canonical-only"))
    webui_dir = get_webui_dir()
    webui_dir.mkdir(parents=True, exist_ok=True)
    for chat_id in ("legacy-acceptance", "display-only"):
        events = [{"event": "user", "chat_id": chat_id, "text": "配置和聊天不能丢失"},
                  {"event": "message", "chat_id": chat_id, "text": "独立验收数据"},
                  {"event": "turn_end", "chat_id": chat_id}]
        (webui_dir / f"websocket_{chat_id}.jsonl").write_text(
            "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events), encoding="utf-8")
    if _dock_supported(root):
        _desktop_webui(root)
        _wait_dock(_dock_socket(root), present=True)
    else:
        gateway(root, "--background")


def snapshot(root: Path) -> None:
    from nanobot.config.loader import set_config_path
    from nanobot.config.paths import get_webui_dir

    case = read(root / "case.json")
    config_path = root / "account/.nanobot/config.json"
    set_config_path(config_path)
    delivery = config_path.parent / "delivery/outbox.sqlite3"
    if not delivery.exists() and importlib.util.find_spec("nanobot.channels.outbox") is not None:
        from nanobot.bus.delivery import DeliveryRequest
        from nanobot.bus.events import OutboundMessage
        from nanobot.channels.outbox import DeliveryOutbox

        # Keep a real durable result pending through the private journey without
        # attempting an external send. Older retained code has no outbox owner.
        with patch("nanobot.channels.outbox.time.time", return_value=time.time() + 3600):
            DeliveryOutbox(delivery).record(OutboundMessage(
                "whatsapp", "acceptance-offline", "Retain this scheduled result",
                delivery=DeliveryRequest("acceptance-run", "websocket:legacy-acceptance", None),
            ))
    if importlib.util.find_spec("nanobot.session.location") is not None:
        from nanobot.session.location import SessionLocation
        location = SessionLocation(root / "workspace")
    else:
        from nanobot.session.manager import JsonlSessionStore
        location = JsonlSessionStore(root / "workspace")
    sessions, webui_dir = location.sessions_dir, get_webui_dir()
    key = "websocket:legacy-acceptance"
    legacy = sessions / (location.storage_key(key) + ".jsonl")
    canonical_only = sessions / (location.storage_key("websocket:canonical-only") + ".jsonl")
    receipt = ready(root, case["baseline_version"])
    chat_id = (read(root / "before.json")["chat_id"] if (root / "before.json").exists()
               else asyncio.run(chat(root)))
    before = history(root, "websocket:" + chat_id)
    legacy_before = history(root, key)
    display_before = history(root, "websocket:display-only")
    context_before = canonical_context(root)
    assert context_before["total_messages"] == 1
    assert "配置和聊天不能丢失" in json.dumps(legacy_before, ensure_ascii=False)
    # Immutable files plus public logical records: SQLite/WAL checkpoint bytes
    # may legitimately change across a clean shutdown without changing a record.
    preserved = {str(path): digest(path) for path in (legacy, canonical_only,
                 webui_dir / "websocket_legacy-acceptance.jsonl", webui_dir / "websocket_display-only.jsonl")}
    preserved[str(config_path)] = digest(config_path)
    write(root / "before.json", {"chat_id": chat_id, "history": before, "legacy": legacy_before,
                                "display_only": display_before, "canonical_only": context_before,
                                "files": preserved, "run_id": receipt.run_id,
                                "database": str(sessions / "sessions.sqlite3"),
                                "delivery": (canonical_records(delivery, ("deliveries",)) if delivery.exists() else None),
                                "canonical": (canonical_records(sessions / "sessions.sqlite3")
                                              if (sessions / "sessions.sqlite3").exists() else None)})


def prepare(root: Path) -> None:
    from packaging.version import Version

    from nanobot.installation_lock import installation_state_dir
    from nanobot.release_feed import ReleaseFeed
    from nanobot.update_channel import UpdateChannelRequest, read_update_channel
    from nanobot.update_jobs import prepare_job, start_handoff
    from nanobot.update_plan import preview_release_update
    from nanobot.update_service import UpdateJobService

    if not (root / "before.json").exists():
        seed(root)
    snapshot(root)
    case = read(root / "case.json")

    async def plan_update():
        state = installation_state_dir()
        channel = "preview" if Version(case["target_version"]).is_prerelease else "stable"
        UpdateJobService().change_channel(UpdateChannelRequest(channel=channel, revision=read_update_channel().revision))
        plan = await preview_release_update(restart_running=True)
        assert plan.stop_profiles and plan.restart_profiles
        async with ReleaseFeed(state / "feed") as feed:
            return await prepare_job(plan, feed)
    directory = asyncio.run(plan_update())
    # Capture the production launch, then let the outer, stdlib-only controller
    # execute it after this process exits. Otherwise Windows DLL locks from the
    # *test controller* prevent restoring the live venv directory.
    with patch("nanobot.update_jobs.subprocess.Popen") as spawn:
        start_handoff(directory, once=True)
        command = spawn.call_args.args[0]
    write(root / "launch.json", {"command": command, "directory": str(directory)})


def verify(root: Path) -> dict:
    import nanobot
    from nanobot.build_info import COMMIT
    from nanobot.config.loader import set_config_path
    from nanobot.update_worker import JobStatus, Phase

    set_config_path(root / "account/.nanobot/config.json")
    case, before, launch = read(root / "case.json"), read(root / "before.json"), read(root / "launch.json")
    directory = Path(launch["directory"])
    restored = case["scenario"] not in {"upgrade", "upgrade-again", "skipped-preview", "worker-exit"}
    status = JobStatus.read(directory)
    assert status.phase == (Phase.RESTORED if restored else Phase.SUCCEEDED), status
    expected = case["baseline_version"] if restored else case["target_version"]
    receipt = ready(root, expected)
    assert receipt.run_id != before["run_id"], "Update did not restart the gateway"
    assert nanobot.__version__ == expected
    if not restored:
        assert COMMIT == case["commit"]
        assert digest(Path(case["target_wheel"])) == case["target_sha256"]
    sqlite_expected = verify_data(root, expected)
    if case["scenario"] in {"worker-exit", "metadata-loss"}:
        assert (directory / "fault-fired").exists()
    if case["scenario"] in {"worker-exit", "metadata-loss", "backup-failure"}:
        assert (root / "injected-fault").exists()
    if case["scenario"] == "restore-interruption":
        assert (directory / "restore-fault-fired").exists()
    return {**case, "phase": status.phase.value, "running_version": receipt.version,
            "restarted": True, "config_and_legacy_bytes_preserved": True,
            "authenticated_history_preserved": True, "sqlite_records_preserved": True if sqlite_expected else None,
            "scheduled_delivery_preserved": True if before.get("delivery") is not None else None,
            "continued_write_and_second_start": True,
            "dock_socket": str(_dock_socket(root)) if _dock_supported(root) else None,
            "dock_restart_verified": True if _dock_supported(root) else None}


def verify_data(root: Path, expected: str) -> bool:
    """Public reads and subsequent writes, shared by inline and owner-driven updates."""
    from nanobot.config.loader import set_config_path

    set_config_path(root / "account/.nanobot/config.json")
    before = read(root / "before.json")
    receipt = ready(root, expected)
    assert receipt.run_id != before["run_id"], "Update did not restart the gateway"
    if _dock_supported(root):
        from nanobot.gateway.runtime import GatewayInstance

        instance = GatewayInstance.resolve(config_path=root / "account/.nanobot/config.json")
        # A historical package without this feature cannot record desktop intent.
        # After that first upgrade, exercise the real new launcher, then restart.
        if not instance.paths.state_path.with_suffix(".dock").exists():
            _desktop_webui(root)
        _wait_dock(_dock_socket(root), present=True)
    assert {name: digest(Path(name)) for name in before["files"]} == before["files"]
    key = "websocket:" + before["chat_id"]
    assert_history_preserved(before["history"], history(root, key))
    assert_history_preserved(before["legacy"], history(root, "websocket:legacy-acceptance"))
    assert_history_preserved(before["display_only"], history(root, "websocket:display-only"))
    assert canonical_context(root) == before["canonical_only"], (canonical_context(root), before["canonical_only"])
    database = Path(before["database"])
    sqlite_expected = importlib.util.find_spec("nanobot.session.location") is not None
    canonical = canonical_records(database) if sqlite_expected else None
    if before["canonical"] is not None:
        assert_canonical_preserved(before["canonical"], canonical)
    delivery = root / "account/.nanobot/delivery/outbox.sqlite3"
    if before.get("delivery") is not None:
        assert canonical_records(delivery, ("deliveries",)) == before["delivery"]
    if canonical is not None:
        # Display transcripts are not canonical agent context. Check the actual
        # imported message bodies too when the baseline predates SQLite.
        assert not any(row[0] == "websocket:display-only" for row in canonical["messages"])
        for session_key in ("websocket:legacy-acceptance", "websocket:canonical-only"):
            messages = [json.loads(row[2]) for row in canonical["messages"] if row[0] == session_key]
            assert [(message["role"], message["content"]) for message in messages] == [
                ("user", "配置和聊天不能丢失")]
    asyncio.run(chat(root, before["chat_id"]))
    continued = history(root, key)
    canonical = canonical_records(database) if sqlite_expected else None
    assert len(continued["events"]) > len(before["history"]["events"])
    gateway(root, "stop")
    if _dock_supported(root):
        _wait_dock(_dock_socket(root), present=False)
    gateway(root, "--background")
    ready(root, expected)
    if _dock_supported(root):
        _wait_dock(_dock_socket(root), present=True)
    assert history(root, key) == continued
    assert_history_preserved(before["legacy"], history(root, "websocket:legacy-acceptance"))
    assert_history_preserved(before["display_only"], history(root, "websocket:display-only"))
    assert canonical_context(root) == before["canonical_only"]
    if sqlite_expected:
        assert canonical_records(database) == canonical
    if before.get("delivery") is not None:
        assert canonical_records(delivery, ("deliveries",)) == before["delivery"]
    assert {name: digest(Path(name)) for name in before["files"]} == before["files"]
    return sqlite_expected


def isolated_environment(root: Path) -> dict[str, str]:
    from scripts.verify_installed_release import host_environment

    system = host_environment(dict(os.environ))
    system.update(HOME=str(root), USERPROFILE=str(root), APPDATA=str(root / "config"),
                  LOCALAPPDATA=str(root / "data"), XDG_CONFIG_HOME=str(root / "config"),
                  XDG_CACHE_HOME=str(root / "cache"), XDG_DATA_HOME=str(root / "data"),
                  TMPDIR=str(root), TMP=str(root), TEMP=str(root),
                  PIP_CONFIG_FILE=os.devnull, PIP_NO_INPUT="1", PIP_DISABLE_PIP_VERSION_CHECK="1", PYTHONUTF8="1",
                  NANOBOT_TUI_NO_DOWNLOAD="1", NO_COLOR="1", PATH=os.defpath)
    if os.name == "nt":
        system["PATH"] = str(Path(system["SYSTEMROOT"]) / "System32")
    return system


def scenario_groups(scenarios: list[str], workers: int) -> list[list[str]]:
    groups: list[list[str]] = [[] for _ in range(min(workers, len(scenarios)))]
    loads = [0] * len(groups)
    for scenario in scenarios:
        lane = min(range(len(groups)), key=loads.__getitem__)
        groups[lane].append(scenario)
        loads[lane] += 1 + (scenario in TWO_JOURNEY_SCENARIOS)
    return groups


def check_coverage(results: list[dict], scenarios: list[str]) -> None:
    if [result["scenario"] for result in results] != scenarios:
        raise ValueError("Lane report does not cover its assigned scenarios in order")
    for result in results:
        if ("subsequent_update" in result) != (result["scenario"] in TWO_JOURNEY_SCENARIOS):
            raise ValueError("Lane report does not cover every required upgrade journey")


def stop_controller(process: subprocess.Popen, owner: WindowsJob | None) -> None:
    # Tree ownership outlives the controller: an exited supervisor can leave an
    # installer running. Clear that tree before stopping its detached gateways.
    if owner is not None:
        owner.terminate()
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait(timeout=15)


def cleanup_lane(output: Path, scenarios: list[str]) -> None:
    """After abnormal controller exit, stop only its explicitly configured gateways."""
    from scripts.verify_installed_release import _wait_for_closed_listeners

    # Use the controller's installed package, not the potentially interrupted
    # managed venv. Gateway stop validates the recorded process identity itself.
    failed = False
    with (output.parent / "cleanup.log").open("w", encoding="utf-8") as log:
        for scenario in scenarios:
            case_root = output / scenario
            config_file = case_root / "account/.nanobot/config.json"
            if not config_file.exists():
                continue
            try:
                env = isolated_environment(case_root / "account")
                env.update(TMPDIR=str(case_root), TMP=str(case_root), TEMP=str(case_root))
                subprocess.run([sys.executable, "-I", "-B", "-m", "nanobot", "gateway", "stop", "--config",
                                str(config_file)], env=env, cwd=case_root, stdout=log, stderr=log,
                               timeout=60, check=True)
                config = read(config_file)
                _wait_for_closed_listeners((config["gateway"]["port"], config["channels"]["websocket"]["port"]))
            except Exception:
                failed = True
    if failed:
        raise RuntimeError("A lane gateway did not finish bounded cleanup")


def run_parallel(args, root: Path, target: Path, version: str, original_hash: str,
                 scenarios: list[str], timings: Timings) -> list[dict]:
    groups = scenario_groups(scenarios, args.workers)
    jobs = []
    failed = False
    with timings.measure("parallel_total"), ExitStack() as stack:
        try:
            deadline = time.monotonic() + LANE_TIMEOUT
            for worker, selected in enumerate(groups, 1):
                lane = root / f"lane-{worker}"
                lane.mkdir(mode=0o700)
                output = lane / "run"  # The child exclusively creates this root.
                env = isolated_environment(lane)
                # Controller dependencies are shared read-only; do not write
                # bytecode into their environment from either lane.
                command = [sys.executable, "-I", "-B", str(Path(__file__).resolve()), "--wheel", str(target),
                           "--commit", args.commit, "--output", str(output), "--workers", "1"]
                if args.baseline_wheel:
                    command.extend(("--baseline-wheel", str(args.baseline_wheel.resolve(strict=True))))
                if args.dock:
                    command.append("--dock")
                for scenario in selected:
                    command.extend(("--scenario", scenario))
                # No child stdout/stderr is replayed. It can contain credentials,
                # including assertion messages and dynamically issued API tokens.
                log = stack.enter_context((lane / "controller.log").open("w", encoding="utf-8"))
                owner = None
                flags = 0
                if os.name == "nt":
                    from nanobot.agent.tools._windows_job import WindowsJob

                    owner = stack.enter_context(closing(WindowsJob.create()))
                    flags = subprocess.CREATE_NEW_PROCESS_GROUP | owner.creation_flags
                process = subprocess.Popen(command, env=env, cwd=lane, stdout=log, stderr=log,
                                           start_new_session=os.name != "nt", creationflags=flags)
                if owner is not None:
                    try:
                        owner.assign_and_resume(process.pid)
                    except BaseException:
                        if process.poll() is None:
                            process.kill()
                        process.wait(timeout=15)
                        raise
                jobs.append((worker, selected, output, process, owner))
            for worker, _, _, process, _ in jobs:
                try:
                    status = process.wait(timeout=max(0, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    failed = True
                    print(f"FAIL lane-{worker}: controller deadline exceeded", flush=True)
                    break
                if status:
                    failed = True
                    print(f"FAIL lane-{worker}: controller exited with status {status}", flush=True)
        finally:
            cleanup_failed = False
            # Finish or terminate every owned controller before importing JSON.
            # An ordinary failing lane does not interrupt another lane's cleanup.
            for _, selected, output, process, owner in jobs:
                try:
                    stop_controller(process, owner)
                    if process.returncode:
                        cleanup_lane(output, selected)
                except Exception:
                    cleanup_failed = True
            for worker, _, output, _, _ in jobs:
                checkpoint = output / "packaged-update-timings.json"
                if checkpoint.exists():
                    timings.merge(checkpoint, worker)
            if cleanup_failed:
                raise RuntimeError("A lane did not finish bounded cleanup")
        if failed:
            raise RuntimeError("Packaged update lane failed; raw logs remain private")
        results = {}
        for _, selected, output, _, _ in jobs:
            report = read(output / "packaged-update-report.json")
            if (report["target_sha256"] != original_hash or report["candidate_commit"] != args.commit
                    or report["version"] != version):
                raise ValueError("Lane did not verify the original candidate wheel")
            check_coverage(report["scenarios"], selected)
            results.update((result["scenario"], result) for result in report["scenarios"])
        return [results[scenario] for scenario in scenarios]


def run_serial(args, root: Path, target: Path, version: str, original_hash: str,
               scenarios: list[str], timings: Timings) -> list[dict]:
    from packaging.utils import parse_wheel_filename
    from packaging.version import Version

    from scripts.verify_installed_release import _wait_for_closed_listeners

    environment = root / "managed"
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    baseline_source = args.baseline_wheel.resolve(strict=True) if args.baseline_wheel else target
    if args.baseline_wheel:
        baseline_version = str(parse_wheel_filename(baseline_source.name)[1])
    else:
        # A version-only fixture, not a claim about a published predecessor.
        # Minor/major releases have a zero patch component (e.g. 0.4.0).
        base = list(Version(version).release)
        for index in reversed(range(len(base))):
            if base[index]:
                base[index] -= 1
                break
        baseline_version = ".".join(map(str, base))
    if Version(baseline_version) >= Version(version):
        raise ValueError("Baseline must precede the target; select an earlier baseline wheel")
    results = []
    system = isolated_environment(root)
    # Install once per lane, without inherited user pip settings; every case
    # resets only nanobot. No mutable venv or dependency snapshot crosses lanes.
    with timings.measure("venv"):
        subprocess.run([sys.executable, "-I", "-B", "-m", "venv", str(environment)], check=True, env=system, timeout=90)
    with timings.measure("initial_dependency_install"):
        subprocess.run([str(python), "-I", "-m", "pip", "install", "--only-binary=:all:", str(target)],
                       check=True, env=system, timeout=600, stdout=subprocess.DEVNULL)
    write(environment / "nanobot-install.json", {"schema_version": 1, "owner": "nanobot-installer",
                                               "environment": str(environment), "extras": []})
    for scenario in scenarios:
        with timings.measure("scenario_total", scenario=scenario):
            with timings.measure("fixture", scenario=scenario, journey=1):
                case_root = root / scenario
                case_root.mkdir()
                account = case_root / "account"
                account.mkdir()
                env = dict(system, HOME=str(account), USERPROFILE=str(account), APPDATA=str(account / "config"),
                           LOCALAPPDATA=str(account / "data"), XDG_CONFIG_HOME=str(account / "config"),
                           XDG_CACHE_HOME=str(root / "cache"), XDG_DATA_HOME=str(account / "data"),
                           TMPDIR=str(case_root), TMP=str(case_root), TEMP=str(case_root))
                selected = target
                feed = case_root / "feed.json"
                if scenario in {"upgrade-again", "import-failure", "restart-failure", "restore-interruption"}:
                    intermediate = Version(version).base_version + ".dev0"
                    if not Version(baseline_version) < Version(intermediate) < Version(version):
                        raise ValueError("Consecutive updates require baseline < target.dev0 < target")
                    # Faults and the instrumented intermediate get a distinct version:
                    # never overwrite a previously observed version with healthy bytes.
                    selected = fixture_wheel(target, case_root / "intermediate", intermediate,
                                             feed=feed if scenario == "upgrade-again" else None, scenario=scenario)
                write(feed, feed_records(selected, args.commit))
                earlier = baseline_version
                if scenario == "skipped-preview" and not args.baseline_wheel:
                    earlier = Version(version).base_version + ".dev0"
                    if Version(earlier) >= Version(version):
                        raise ValueError("Skipped Preview requires a target newer than dev0")
                baseline = fixture_wheel(baseline_source, case_root / "baseline", earlier, feed=feed, scenario=scenario)
                case = {"scenario": scenario, "baseline_version": earlier, "dock": args.dock,
                        "target_version": str(parse_wheel_filename(selected.name)[1]),
                        "baseline_kind": "instrumented historical wheel" if args.baseline_wheel else "instrumented version fixture",
                        "baseline_source_sha256": digest(baseline_source), "baseline_fixture_sha256": digest(baseline),
                        "target_wheel": str(selected), "target_sha256": digest(selected), "commit": args.commit,
                        "target_unmodified": selected == target}
                write(case_root / "case.json", case)
            with timings.measure("baseline_install", scenario=scenario, journey=1):
                subprocess.run([str(python), "-I", "-m", "pip", "install", "--no-deps", "--force-reinstall", str(baseline)],
                               check=True, env=env, timeout=120, stdout=subprocess.DEVNULL)
            child = [str(python), "-I", str(Path(__file__).resolve())]
            # Raw logs stay private to this local evidence root, including on success.
            with (case_root / "acceptance.log").open("w", encoding="utf-8") as log:
                def journey(number):
                    with timings.measure("prepare", scenario=scenario, journey=number):
                        subprocess.run([*child, "--phase", "prepare", "--output", str(case_root)],
                                       check=True, env=env, cwd=case_root, stdout=log, stderr=log, timeout=180)
                        launch = read(case_root / "launch.json")
                    with timings.measure("worker", scenario=scenario, journey=number):
                        subprocess.run(launch["command"], check=True, env=env, cwd=launch["directory"],
                                       stdout=log, stderr=log, timeout=420)
                    with timings.measure("verify", scenario=scenario, journey=number):
                        subprocess.run([*child, "--phase", "verify", "--output", str(case_root)],
                                       check=True, env=env, cwd=case_root, stdout=log, stderr=log, timeout=180)
                        return read(case_root / "result.json")

                try:
                    result = journey(1)
                    if result["phase"] == "restored" or scenario == "upgrade-again":
                        with timings.measure("fixture", scenario=scenario, journey=2):
                            previous_job = read(case_root / "launch.json")["directory"]
                            write(feed, feed_records(target, args.commit, generation=2))
                            write(case_root / "case.json", {
                                **case, "scenario": "upgrade", "baseline_version": result["running_version"],
                                "baseline_kind": "previous journey's running installation",
                                "baseline_source_sha256": (case["baseline_source_sha256"] if result["phase"] == "restored"
                                                           else case["target_sha256"]),
                                "baseline_fixture_sha256": (case["baseline_fixture_sha256"] if result["phase"] == "restored"
                                                            else case["target_sha256"]),
                                "target_version": version, "target_wheel": str(target),
                                "target_sha256": original_hash, "target_unmodified": True,
                            })
                        result["subsequent_update"] = journey(2)
                        assert read(case_root / "launch.json")["directory"] != previous_job
                        assert result["subsequent_update"]["phase"] == "succeeded"
                        write(case_root / "result.json", result)
                    results.append(result)
                finally:
                    with timings.measure("cleanup", scenario=scenario):
                        subprocess.run([str(python), "-I", "-m", "nanobot", "gateway", "stop", "--config",
                                        str(account / ".nanobot/config.json")], env=env, cwd=case_root,
                                       stdout=log, stderr=log, timeout=60, check=True)
                        config_file = account / ".nanobot/config.json"
                        if config_file.exists():
                            config = read(config_file)
                            _wait_for_closed_listeners((config["gateway"]["port"], config["channels"]["websocket"]["port"]))
                        # No journey result exists on failure; successful journeys
                        # also retain the existing native Dock shutdown assertion.
                        if results and results[-1]["scenario"] == scenario:
                            results[-1]["gateway_process_stopped"] = True
                            dock_address = results[-1].get("dock_socket")
                            if not dock_address:
                                dock_address = results[-1].get("subsequent_update", {}).get("dock_socket")
                            if dock_address:
                                _wait_dock(Path(dock_address), present=False)
                                results[-1]["dock_stopped"] = True
            print(f"PASS {scenario}: {results[-1]['phase']}", flush=True)
    return results


def run(args) -> dict:
    from packaging.utils import parse_wheel_filename

    # The build environment supplies dependencies for metadata construction only.
    # Product phases run in the separately installed wheel, never this checkout.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts.build_tui_wheels import wheel_files

    target = args.wheel.resolve(strict=True)
    _, parsed_version, _, tags = parse_wheel_filename(target.name)
    version = str(parsed_version)
    if len(tags) != 1 or any(tag.platform == "any" for tag in tags):
        raise ValueError("Acceptance requires the final native wheel, not an intermediate universal wheel")
    files, _, _ = wheel_files(target, version, platform=next(iter(tags)).platform)
    if files["nanobot/_build_commit.txt"].decode().strip() != args.commit:
        raise ValueError("Target wheel does not contain the requested candidate commit")
    original_hash = digest(target)
    scenarios = list(args.scenario or SCENARIOS)
    if len(set(scenarios)) != len(scenarios):
        raise ValueError("Select each scenario only once")
    root = args.output.resolve()
    root.mkdir(mode=0o700)  # Exclusive evidence root. Never use a user's installation.
    timings = Timings(root / "packaged-update-timings.json")
    workers = min(args.workers, len(scenarios))
    runner = run_parallel if workers > 1 else run_serial
    results = runner(args, root, target, version, original_hash, scenarios, timings)
    check_coverage(results, scenarios)
    assert digest(target) == original_hash
    return {"platform": platform.system(), "machine": platform.machine(), "python": platform.python_version(),
            "target_sha256": original_hash, "candidate_commit": args.commit, "version": version,
            "release_transport": "local fixture; no public-download proof", "interactive_ui_e2e": False,
            "release_approval": "private unsigned fixture; not signature acceptance", "workers": workers,
            "scenario_count": len(results), "journey_count": sum(1 + ("subsequent_update" in result) for result in results),
            "scenarios": results}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path)
    parser.add_argument("--baseline-wheel", type=Path)
    parser.add_argument("--commit")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--scenario", action="append", choices=SCENARIOS)
    parser.add_argument("--workers", type=int, default=1,
                        help="Maximum independent lanes, each with its own installation (default: 1)")
    parser.add_argument("--dock", action="store_true", help="Verify native macOS background Dock lifecycle")
    parser.add_argument("--phase", choices=("prepare", "verify"), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    if not sys.flags.isolated:
        parser.error("Run with python -I")
    if args.dock and sys.platform != "darwin":
        parser.error("--dock requires a real macOS desktop session")
    if args.phase:
        if sys.prefix == sys.base_prefix:
            parser.error("Product phases must run in the disposable installation")
        if args.phase == "prepare":
            prepare(args.output)
        else:
            write(args.output / "result.json", verify(args.output))
        return
    if not args.wheel or not args.commit:
        parser.error("--wheel and --commit are required")
    try:
        result = run(args)
        write(args.output / "packaged-update-report.json", result)
    except Exception as error:
        # Exception values/commands can include temporary credentials. Only the
        # structured checkpoints and this safe class name may leave the account.
        raise SystemExit(f"Packaged update verification failed ({type(error).__name__}); raw logs remain private") from None


if __name__ == "__main__":
    main()
