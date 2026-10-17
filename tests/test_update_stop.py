"""Cooperative shutdown protocol tests; no installer or real account is touched."""

import asyncio
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
from zipfile import ZipFile

import pytest

import nanobot
from nanobot.config.home import get_selected_home_path, set_home_path
from nanobot.data_access import data_access, profile_data_paths
from nanobot.gateway.runtime import GatewayInstance, GatewayRuntime
from nanobot.installation_lock import file_access, installation_access, installation_state_dir
from nanobot.release_feed import ReleaseTarget
from nanobot.releases import ReleaseArtifact
from nanobot.runtime_admission import RuntimeAdmission
from nanobot.update_backup import BackupSource
from nanobot.update_jobs import _worker_archive
from nanobot.update_plan import InstallationSnapshot, UpdatePlan
from nanobot.update_profiles import ObservedProfile, ProfileLaunch, ProfileReceipt, inspect_profiles
from nanobot.update_stop import (
    settle_uncommitted_handoff,
    stop_reviewed_gateways,
    watch_gateway_stop,
)
from nanobot.update_worker import (
    EnvironmentSnapshot,
    JobStatus,
    Phase,
    StagedWheel,
    WorkerSpec,
    read_record,
    write_record,
)


def prepared_job(profiles, *, stop=None):
    """Synthetic wheel metadata: not an actual nanobot installation fixture."""
    identifier = str(uuid4())
    directory = installation_state_dir() / "jobs" / identifier
    directory.mkdir(parents=True)
    snapshot = InstallationSnapshot(
        environment=str(Path(sys.prefix).resolve()), python=sys.executable,
        installed_version=nanobot.__version__, running_version=nanobot.__version__,
        package_path=nanobot.__file__, running_package=nanobot.__file__, owner="venv", records={},
    )
    version = "99.0.0"
    filename = f"nanobot_ai-{version}-py3-none-win_amd64.whl"
    wheels = directory / "wheels"
    wheels.mkdir()
    wheel = wheels / filename
    with ZipFile(wheel, "w") as archive:
        archive.writestr(f"nanobot_ai-{version}.dist-info/METADATA",
                         f"Metadata-Version: 2.1\nName: nanobot-ai\nVersion: {version}\n")
    size, checksum = wheel.stat().st_size, hashlib.sha256(wheel.read_bytes()).hexdigest()
    plan = UpdatePlan(
        id=identifier, installation=snapshot, channel="stable", profiles=profiles,
        stop_profiles=[item.receipt.id for item in profiles] if stop is None else stop,
        extras=[], created_at=int(time.time()), expires_at=int(time.time()) + 900,
        target=ReleaseTarget(version=version, source="pypi", url=f"https://files.pythonhosted.org/packages/{filename}",
                             artifact=ReleaseArtifact(filename=filename, size=size, sha256=checksum)),
    )
    write_record(directory / "plan.json", plan.model_dump(mode="json"))
    spec = WorkerSpec(
        identifier, hashlib.sha256((directory / "plan.json").read_bytes()).hexdigest(),
        _worker_archive(directory / "worker.pyz"),
        EnvironmentSnapshot(snapshot.environment, sys.executable, sys.executable,
                            "0" * 64, {}, {}, nanobot.__version__, {}), version,
        (StagedWheel(filename, "nanobot-ai", version, size, checksum),),
        (BackupSource(str(directory / "fixture-data")),),
    )
    spec.save(directory)
    JobStatus(identifier, Phase.READY, 0, False, "Fixture: staged, not installed", int(time.time())).save(directory)
    return directory, plan


@pytest.fixture
def private_home(tmp_path, monkeypatch):
    root = tmp_path / "private account"
    root.mkdir()
    monkeypatch.setenv("HOME", str(root))
    monkeypatch.setenv("USERPROFILE", str(root))
    return root


@pytest.fixture
def protocol(private_home, monkeypatch):
    from nanobot import update_stop

    profiles = []
    for number in range(2):
        root = private_home / f"gateway-{number}"
        receipt = ProfileReceipt(
            id=hashlib.sha256(str(root).encode()).hexdigest(), run_id=uuid4().hex,
            environment=str(Path(sys.prefix).resolve()), python=sys.executable,
            package=nanobot.__file__, version=nanobot.__version__, home=str(root), data_dir=str(root),
            config=str(root / "config.json"), workspace=str(root / "workspace"),
            state_path=str(root / "runtime.json"), log_path=str(root / "runtime.log"), port=18790 + number,
            launch_mode="background", pid=os.getpid() + 10000 + number, process_identity=f"fixture-{number}",
            active=True, stop_protocol=1,
            launch=ProfileLaunch(home=str(root), config_path=None, workspace=None,
                                 working_directory=str(root), verbose=False, lifetime="explicit"),
        )
        profiles.append(ObservedProfile(receipt=receipt, state="running"))
    directory, plan = prepared_job(profiles)
    gates = [RuntimeAdmission(), RuntimeAdmission()]
    stops = [asyncio.Event(), asyncio.Event()]
    # This test exercises mailbox/admission races with controlled process state;
    # a separate subprocess test checks actual gateway exit and lease release.
    monkeypatch.setattr(update_stop, "validate_profiles", lambda expected, environment: None)

    def stopped(expected, environment):
        if not all(event.is_set() for event in stops):
            raise ValueError("still running")

    monkeypatch.setattr(update_stop, "require_stopped_profiles", stopped)
    monkeypatch.setattr(update_stop.GatewayRuntime, "process_is_running", lambda self, pid: False)
    return directory, plan, gates, stops


async def wait_until(predicate, *, timeout=5):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


@pytest.mark.parametrize("failure", [ValueError("Invalid release approval"), TimeoutError("Trust service unavailable")])
async def test_handoff_rejects_approval_before_requesting_gateway_shutdown(protocol, monkeypatch, failure):
    from unittest.mock import AsyncMock

    from nanobot import update_handoff

    directory, _, _, stops = protocol
    state = JobStatus.read(directory)
    state.advance(directory, Phase.CHECKING, "Checking approval", mutation_started=False)
    # Environment inspection is covered by the real installed-process tests;
    # exercise the actual handoff ordering and durable status here.
    monkeypatch.setattr(update_handoff, "current_environment", lambda **_: None)
    monkeypatch.setattr(update_handoff, "check_environment", lambda *_, **__: None)
    monkeypatch.setattr(update_handoff.ReleaseFeed, "revalidate", AsyncMock(side_effect=failure))
    stop = AsyncMock()
    monkeypatch.setattr(update_handoff, "stop_reviewed_gateways", stop)
    with pytest.raises(type(failure), match=str(failure)):
        await update_handoff._prepare(directory)
    stop.assert_not_called()
    assert not any(event.is_set() for event in stops)
    state = JobStatus.read(directory)
    assert state.phase == Phase.HANDOFF_FAILED and not state.mutation_started
    assert "shutdown was not requested" in state.message
    assert not (directory / "handoff-approval.json").exists()


async def test_handoff_rejects_observed_catalogue_rollback_before_gateway_shutdown(protocol, monkeypatch):
    from dataclasses import replace
    from unittest.mock import AsyncMock

    import httpx
    from packaging.tags import Tag

    from nanobot import update_handoff
    from nanobot.release_feed import CATALOGUE_URL, ReleaseFeed, ReleaseFeedError
    from nanobot.releases import (
        ReleaseCatalogue,
        ReleaseManifest,
        ReleasePointer,
        release_filenames,
    )

    directory, plan, _, _ = protocol
    artifact = plan.target.artifact
    manifest = ReleaseManifest(
        version=plan.target.version, source_commit="a" * 40, candidate_commit="b" * 40,
        requires_python=">=3.11", artifacts=[
            artifact if name == artifact.filename else ReleaseArtifact(filename=name, size=1, sha256="c" * 64)
            for name in sorted(release_filenames(plan.target.version))
        ],
    )
    payload = manifest.model_dump_json().encode()
    pointer = ReleasePointer(version=manifest.version, candidate_commit=manifest.candidate_commit,
                             manifest_sha256=hashlib.sha256(payload).hexdigest())
    original = ReleaseCatalogue(generation=1, stable=pointer)
    observed = original.model_copy(update={"generation": 2, "withdrawn": {manifest.version: "Startup regression"}})
    selected = original

    def respond(request):
        if str(request.url) == CATALOGUE_URL:
            return httpx.Response(200, content=selected.model_dump_json())
        if str(request.url) == pointer.manifest_url:
            return httpx.Response(200, content=payload)
        assert request.url.path == f"/pypi/nanobot-ai/{manifest.version}/json"
        return httpx.Response(200, json={
            "info": {"name": "nanobot-ai", "version": manifest.version, "requires_python": ">=3.11"},
            "urls": [{"filename": item.filename, "size": item.size, "yanked": False,
                      "url": f"https://files.pythonhosted.org/packages/{item.filename}",
                      "digests": {"sha256": item.sha256}}
                     for item in manifest.artifacts if item.filename.endswith((".whl", ".tar.gz"))],
        })

    class CachedFeed(ReleaseFeed):
        def __init__(self, cache_dir):
            super().__init__(cache_dir, transport=httpx.MockTransport(respond),
                             supported_tags=[Tag("py3", "none", "win_amd64")])

    # Publication authority is independent of catalogue freshness. These fixture
    # bytes stand for a previously approved release that has since been withdrawn.
    monkeypatch.setattr(ReleaseFeed, "_authorize", AsyncMock())
    root = installation_state_dir(plan.installation.environment)
    spec = WorkerSpec.read(directory)
    async with CachedFeed(root / "releases") as feed:
        target = await feed.latest("preview")
        plan = plan.model_copy(update={"channel": "preview", "target": target})
        write_record(directory / "plan.json", plan.model_dump(mode="json"))
        selected = observed
        assert await feed.catalogue() == observed
    replace(spec, plan_sha256=hashlib.sha256((directory / "plan.json").read_bytes()).hexdigest()).save(directory)
    JobStatus.read(directory).advance(directory, Phase.CHECKING, "Checking the exact release", mutation_started=False)
    monkeypatch.setattr(update_handoff, "current_environment", lambda **_: spec.baseline)
    monkeypatch.setattr(update_handoff, "ReleaseFeed", CachedFeed)
    stop = AsyncMock()
    monkeypatch.setattr(update_handoff, "stop_reviewed_gateways", stop)
    selected = original
    with pytest.raises(ReleaseFeedError, match="generation"):
        await update_handoff._prepare(directory)
    stop.assert_not_called()
    state = JobStatus.read(directory)
    assert state.phase == Phase.HANDOFF_FAILED and not state.mutation_started
    assert "shutdown was not requested" in state.message


@pytest.mark.parametrize("phase", [Phase.READY, Phase.HANDOFF_FAILED])
def test_expired_uncommitted_handoff_can_be_settled_while_gateway_remains_running(protocol, monkeypatch, phase):
    directory, plan, _, stops = protocol
    monkeypatch.setattr(time, "time", lambda: plan.expires_at + 1)
    JobStatus(plan.id, phase, 0, False, "No installation", plan.created_at).save(directory)
    original = {path.name: path.read_bytes() for path in directory.iterdir() if path.is_file() and path.name != "status.json"}
    with installation_access():
        result = settle_uncommitted_handoff(directory)
        assert result.phase == Phase.CANCELLED and not result.mutation_started
        assert settle_uncommitted_handoff(directory) == result
    assert not any(event.is_set() for event in stops)
    assert original == {path.name: path.read_bytes() for path in directory.iterdir() if path.is_file() and path.name != "status.json"}


@pytest.mark.parametrize("lock", ["worker.lock", "handoff-child.lock", "stop.lock"])
def test_settlement_refuses_live_handoff_owners_without_changing_saved_state(protocol, lock):
    directory, plan, _, _ = protocol
    before = (directory / "status.json").read_bytes()
    with file_access(installation_state_dir(plan.installation.environment) / lock, exclusive=True):
        with pytest.raises(BlockingIOError):
            settle_uncommitted_handoff(directory)
    assert (directory / "status.json").read_bytes() == before


@pytest.mark.parametrize("boundary", ["commit", "stopped", "approval", "mutation"])
def test_settlement_never_undoes_shutdown_or_installation_authority(protocol, boundary):
    directory, plan, _, _ = protocol
    JobStatus(plan.id, Phase.HANDOFF_FAILED, 0, boundary == "mutation", "Saved failure", plan.created_at).save(directory)
    if boundary in {"commit", "stopped"}:
        write_record(installation_state_dir() / "stop.json", {
            "plan_id": plan.id, "attempt": uuid4().hex, "phase": boundary, "deadline": time.monotonic() + 10,
        })
    elif boundary == "approval":
        write_record(directory / "approval.json", {"plan_id": plan.id})
    before = (directory / "status.json").read_bytes()
    with pytest.raises(ValueError):
        settle_uncommitted_handoff(directory)
    assert (directory / "status.json").read_bytes() == before


async def test_all_selected_runs_hold_admission_through_committed_shutdown(protocol):
    directory, plan, gates, stops = protocol
    outer = [ExitStack(), ExitStack()]
    watchers = [asyncio.create_task(watch_gateway_stop(item.receipt, lambda gate=gate: gate.pause_if_idle(lambda: False),
                                                     stop, stack))
                for item, gate, stop, stack in zip(plan.profiles, gates, stops, outer)]
    try:
        await stop_reviewed_gateways(directory)
        assert all(stop.is_set() for stop in stops)
        for watcher in watchers:
            watcher.cancel()
        await asyncio.gather(*watchers, return_exceptions=True)
        assert all(gate.paused for gate in gates), "Watcher cancellation reopened committed intake"
        assert read_record(installation_state_dir() / "stop.json")["phase"] == "stopped"
        assert JobStatus.read(directory).phase == Phase.READY
        assert not (directory / "approval.json").exists()
        # Retrying completed handoff is a read/exit check, not a fresh stop.
        await stop_reviewed_gateways(directory)
    finally:
        for watcher in watchers:
            watcher.cancel()
        await asyncio.gather(*watchers, return_exceptions=True)
        for stack in outer:
            stack.close()
    assert not any(gate.paused for gate in gates)


@pytest.mark.parametrize("reason", ["busy", "cancel", "timeout"])
async def test_precommit_failure_releases_every_hold_without_shutdown(protocol, reason, expire_stop_deadline):
    directory, plan, gates, stops = protocol
    outer = [ExitStack(), ExitStack()]
    holds = ExitStack()
    if reason == "busy":
        holds.enter_context(gates[1].activity())
    watchers = [asyncio.create_task(watch_gateway_stop(plan.profiles[0].receipt,
                lambda: gates[0].pause_if_idle(lambda: False), stops[0], outer[0]))]
    if reason == "busy":
        watchers.append(asyncio.create_task(watch_gateway_stop(plan.profiles[1].receipt,
                        lambda: gates[1].pause_if_idle(lambda: False), stops[1], outer[1])))
    operation = asyncio.create_task(stop_reviewed_gateways(directory))
    try:
        if reason == "cancel":
            await wait_until(lambda: gates[0].paused)
            operation.cancel()
            with pytest.raises(asyncio.CancelledError):
                await operation
        else:
            if reason == "timeout":
                # Expire only after a participant actually holds admission, so
                # this proves release rather than racing slow filesystem I/O.
                await wait_until(lambda: gates[0].paused)
                expire_stop_deadline()
            with pytest.raises(ValueError if reason == "busy" else TimeoutError,
                               match="busy or refused" if reason == "busy" else "did not prepare"):
                await asyncio.wait_for(operation, timeout=30)
        await wait_until(lambda: not any(gate.paused for gate in gates))
        assert not any(stop.is_set() for stop in stops)
        assert read_record(installation_state_dir() / "stop.json")["phase"] == "abort"
        with gates[0].activity():
            pass
        holds.close()
        if reason != "busy":
            watchers.append(asyncio.create_task(watch_gateway_stop(plan.profiles[1].receipt,
                            lambda: gates[1].pause_if_idle(lambda: False), stops[1], outer[1])))
        await asyncio.wait_for(stop_reviewed_gateways(directory), timeout=30)
        assert all(stop.is_set() for stop in stops), "A refused attempt prevented a later explicit retry"
    finally:
        operation.cancel()
        await asyncio.gather(operation, return_exceptions=True)
        for watcher in watchers:
            watcher.cancel()
        await asyncio.gather(*watchers, return_exceptions=True)
        for stack in outer:
            stack.close()
        holds.close()


async def test_abandoned_prepare_releases_intake_when_coordinator_lease_disappears(protocol):
    directory, plan, gates, stops = protocol
    gate = ExitStack()
    watcher = asyncio.create_task(watch_gateway_stop(plan.profiles[0].receipt,
                                 lambda: gates[0].pause_if_idle(lambda: False), stops[0], gate))
    try:
        with file_access(installation_state_dir() / "stop.lock", exclusive=True):
            write_record(installation_state_dir() / "stop.json", {
                "plan_id": plan.id, "attempt": uuid4().hex, "phase": "prepare",
                "deadline": time.monotonic() + 30,
            })
            await wait_until(lambda: gates[0].paused)
        await wait_until(lambda: not gates[0].paused)
        assert not stops[0].is_set()
    finally:
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)
        gate.close()


async def test_changed_run_cannot_accept_old_stop_selection(protocol):
    directory, plan, gates, stops = protocol
    different = plan.profiles[0].receipt.model_copy(update={"run_id": uuid4().hex})
    outer = ExitStack()
    watcher = asyncio.create_task(watch_gateway_stop(different, lambda: gates[0].pause_if_idle(lambda: False),
                                 stops[0], outer))
    try:
        with pytest.raises(ValueError, match="run changed"):
            await stop_reviewed_gateways(directory)
        assert not stops[0].is_set() and not gates[0].paused
    finally:
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)
        outer.close()


async def test_unselected_running_gateway_refuses_before_sending_requests(protocol):
    _, plan, _, stops = protocol
    directory, _ = prepared_job(plan.profiles, stop=[plan.profiles[0].receipt.id])
    with pytest.raises(ValueError, match="Every running gateway"):
        await stop_reviewed_gateways(directory)
    assert not (installation_state_dir() / "stop.json").exists()
    assert not any(stop.is_set() for stop in stops)


async def test_changed_staging_refuses_before_closing_task_intake(protocol):
    directory, plan, gates, stops = protocol
    (directory / "wheels" / plan.target.artifact.filename).write_bytes(b"interrupted download")
    with pytest.raises(ValueError, match="Staged wheel"):
        await stop_reviewed_gateways(directory)
    assert not (installation_state_dir() / "stop.json").exists()
    assert not any(gate.paused for gate in gates)
    assert not any(stop.is_set() for stop in stops)


async def test_written_commit_is_not_aborted_if_acknowledging_the_write_fails(protocol, monkeypatch):
    from nanobot import update_stop

    directory, plan, gates, stops = protocol
    outer = [ExitStack(), ExitStack()]
    watchers = [asyncio.create_task(watch_gateway_stop(item.receipt, lambda gate=gate: gate.pause_if_idle(lambda: False),
                                                     stop, stack))
                for item, gate, stop, stack in zip(plan.profiles, gates, stops, outer)]
    actual_write = update_stop.write_record

    def fail_after_commit(path, data, **kwargs):
        actual_write(path, data, **kwargs)
        if path.name == "stop.json" and data.get("phase") == "commit":
            raise OSError("Commit renamed before directory fsync failed")

    monkeypatch.setattr(update_stop, "write_record", fail_after_commit)
    try:
        with pytest.raises(OSError, match="fsync"):
            await stop_reviewed_gateways(directory)
        await wait_until(lambda: all(stop.is_set() for stop in stops))
        assert read_record(installation_state_dir() / "stop.json")["phase"] == "commit"
        assert all(gate.paused for gate in gates)
        await stop_reviewed_gateways(directory)
        assert read_record(installation_state_dir() / "stop.json")["phase"] == "stopped"
        assert not (directory / "approval.json").exists()
    finally:
        for watcher in watchers:
            watcher.cancel()
        await asyncio.gather(*watchers, return_exceptions=True)
        for stack in outer:
            stack.close()


@pytest.fixture
def expire_stop_deadline(monkeypatch):
    from nanobot import update_stop

    # Drive protocol deadlines from an observed state, not filesystem speed.
    # Tests retain real-time watchdogs to catch stalled coordination.
    now = 100.0
    monkeypatch.setattr(update_stop, "time", SimpleNamespace(monotonic=lambda: now))

    def expire():
        nonlocal now
        now += 31  # The production stop deadline is 30 seconds.

    return expire


async def test_stop_acknowledgement_does_not_prove_process_exit(protocol, monkeypatch, expire_stop_deadline):
    from nanobot import update_stop

    directory, plan, gates, stops = protocol
    outer = [ExitStack(), ExitStack()]
    watchers = [asyncio.create_task(watch_gateway_stop(item.receipt, lambda gate=gate: gate.pause_if_idle(lambda: False),
                                                     stop, stack))
                for item, gate, stop, stack in zip(plan.profiles, gates, stops, outer)]
    def still_running(_runtime, _pid):
        expire_stop_deadline()
        return True

    monkeypatch.setattr(update_stop.GatewayRuntime, "process_is_running", still_running)
    monkeypatch.setattr(update_stop.GatewayRuntime, "process_identity_match", lambda self, identity, pid: "match")
    try:
        with pytest.raises(TimeoutError, match="process exit is not confirmed"):
            await asyncio.wait_for(stop_reviewed_gateways(directory), timeout=30)
        assert all(stop.is_set() for stop in stops)
        assert all(gate.paused for gate in gates)
        assert read_record(installation_state_dir() / "stop.json")["phase"] == "commit"
        monkeypatch.setattr(update_stop.GatewayRuntime, "process_is_running", lambda self, pid: False)
        await stop_reviewed_gateways(directory)
    finally:
        for watcher in watchers:
            watcher.cancel()
        await asyncio.gather(*watchers, return_exceptions=True)
        for stack in outer:
            stack.close()


async def test_inactive_unselected_profile_must_also_finish_its_process_exit(protocol, monkeypatch, expire_stop_deadline):
    from nanobot import update_stop

    _, original, gates, stops = protocol
    first, second = original.profiles
    inactive = second.model_copy(update={"state": "stopped", "receipt": second.receipt.model_copy(update={"active": False})})
    directory, _ = prepared_job([first, inactive], stop=[first.receipt.id])

    def require_stopped(_expected, _environment):
        if not stops[0].is_set():
            raise ValueError("First gateway has not stopped")

    monkeypatch.setattr(update_stop, "require_stopped_profiles", require_stopped)
    def still_running(_runtime, pid):
        if pid == second.receipt.pid:
            expire_stop_deadline()
            return True
        return False

    monkeypatch.setattr(update_stop.GatewayRuntime, "process_is_running", still_running)
    monkeypatch.setattr(update_stop.GatewayRuntime, "process_identity_match", lambda self, identity, pid: "match")
    outer = ExitStack()
    watcher = asyncio.create_task(watch_gateway_stop(first.receipt, lambda: gates[0].pause_if_idle(lambda: False),
                                 stops[0], outer))
    try:
        with pytest.raises(TimeoutError, match="process exit is not confirmed"):
            await asyncio.wait_for(stop_reviewed_gateways(directory), timeout=30)
        assert stops[0].is_set() and not stops[1].is_set()
        monkeypatch.setattr(update_stop.GatewayRuntime, "process_is_running", lambda self, pid: False)
        await stop_reviewed_gateways(directory)
    finally:
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)
        outer.close()


@pytest.mark.parametrize("change", [{"stop_protocol": None}, {"launch_mode": "foreground"}])
def test_old_or_externally_owned_gateway_cannot_be_selected_for_stop(protocol, change):
    _, plan, _, _ = protocol
    values = plan.model_dump(mode="json")
    values["profiles"][0]["receipt"].update(change)
    with pytest.raises(ValueError, match="cooperative stop support"):
        UpdatePlan.model_validate(values)


async def test_actual_gateway_exits_normally_before_installation_and_data_leases_are_available(private_home, tmp_path):
    """Actual gateway stop, not a public download/install/restart E2E."""
    profile = tmp_path / "gateway home"
    workspace = tmp_path / "中文 workspace"
    profile.mkdir()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    config_path = profile / "config.json"
    config_path.write_text(json.dumps({
        "agents": {"defaults": {"workspace": str(workspace), "dream": {"enabled": False},
                                "provider": "custom", "model": "lifecycle-test"}},
        "providers": {"custom": {"apiKey": "fixture-not-a-secret", "apiBase": "http://127.0.0.1:1/v1"}},
        "gateway": {"host": "127.0.0.1", "port": port, "heartbeat": {"enabled": False}},
        "channels": {"websocket": {"enabled": False}},
    }))
    source = Path(__file__).resolve().parents[1]
    script = (
        f"import sys; sys.path.insert(0, {str(source)!r})\n"
        "from nanobot.cli import gateway_runtime\n"
        "gateway_runtime.warmup_token_encoding = lambda: None\n"
        "from nanobot.cli.entry import main\nmain()\n"
    )
    children = []

    def spawn(command, **kwargs):
        assert command[1:3] == ["-m", "nanobot"]
        child = subprocess.Popen([command[0], "-c", script, *command[3:]], **kwargs)
        children.append(child)
        return child

    selected_home = get_selected_home_path()
    set_home_path(profile)
    instance = GatewayInstance.resolve(config_path=config_path)
    runtime = GatewayRuntime(paths=instance.paths, python_executable=sys.executable, popen=spawn)
    try:
        assert runtime.start_background(instance.start_options(port=port)).ok

        def gateway_ready():
            assert children[0].poll() is None, "Gateway exited before readiness"
            return runtime.status().ready

        try:
            # Importing a real gateway on a shared Windows runner can exceed the
            # 5 s budget for the in-process protocol tests. Match the WebUI smoke
            # test's startup budget without relaxing shutdown or lease assertions.
            await wait_until(gateway_ready, timeout=20)
        except (TimeoutError, AssertionError) as exc:
            logs = instance.paths.log_path.read_text(encoding="utf-8", errors="replace")[-8000:]
            raise AssertionError(f"Gateway did not become ready: {exc}\n{logs}") from exc
        profiles = inspect_profiles(sys.prefix)
        assert len(profiles) == 1 and profiles[0].receipt.stop_protocol == 1
        assert profiles[0].receipt.launch_mode == "background"
        directory, plan = prepared_job(profiles)
        await stop_reviewed_gateways(directory, timeout=10)
        assert children[0].wait(timeout=5) == 0
        assert not runtime.status().running
        assert inspect_profiles(sys.prefix)[0].state == "stopped"
        receipt = plan.profiles[0].receipt
        with installation_access(updating=True), data_access(profile_data_paths(
            home=Path(receipt.home), data_dir=Path(receipt.data_dir),
            config=Path(receipt.config), workspace=Path(receipt.workspace),
        ), updating=True):
            pass
        assert JobStatus.read(directory).phase == Phase.READY
        assert not (directory / "approval.json").exists()
        assert len(children) == 1, "Stop-only handoff launched an unrequested replacement"
    finally:
        for child in children:
            if child.poll() is None:
                if os.name == "nt":
                    # A venv python.exe may be only a redirector. On failure,
                    # clean up its owned tree rather than orphan the gateway.
                    subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"],
                                   capture_output=True, timeout=10)
                else:
                    child.terminate()
            child.wait(timeout=10)
        set_home_path(selected_home)
