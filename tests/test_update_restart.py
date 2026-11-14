"""Protected post-install startup with the actual gateway, isolated data and ports.

These tests begin at the verified-package handoff, not at a public download or pip
upgrade. The subprocess bootstrap selects this checkout's code while reusing the
test interpreter's dependencies; no user installation is replaced or restarted.
"""

import asyncio
import hashlib
import http.client
import json
import os
import socket
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

import pytest

import nanobot
from nanobot.config.home import get_selected_home_path, set_home_path
from nanobot.data_access import DataStartupGrant, data_access, profile_data_paths
from nanobot.gateway.runtime import GatewayInstance, GatewayRuntime
from nanobot.installation_lock import (
    InstallationBusyError,
    installation_access,
    installation_state_dir,
    pending_update_path,
)
from nanobot.release_feed import ReleaseTarget
from nanobot.releases import ReleaseArtifact
from nanobot.update_backup import BackupSource, unique_sources
from nanobot.update_jobs import _worker_archive
from nanobot.update_plan import InstallationSnapshot, UpdatePlan
from nanobot.update_profiles import inspect_profiles, verify_restarted_profile
from nanobot.update_restart import GatewayStartup, run_restarts
from nanobot.update_worker import (
    EnvironmentSnapshot,
    JobStatus,
    Phase,
    StagedWheel,
    WorkerSpec,
    write_record,
)


def _port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def _http(port, path, *, method="GET"):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=0.4)
    try:
        connection.request(method, path)
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def _wait(predicate, message, *, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if result := predicate():
                return result
        except (OSError, http.client.HTTPException):
            pass
        time.sleep(0.05)
    pytest.fail(message)


@pytest.fixture
def private_home(tmp_path, monkeypatch):
    root = tmp_path / "private account"
    root.mkdir()
    monkeypatch.setenv("HOME", str(root))
    monkeypatch.setenv("USERPROFILE", str(root))
    return root


def _job(previous, *, legacy_scope=False):
    """Materialize the immutable record supplied by verified package installation."""
    identifier = str(uuid4())
    directory = installation_state_dir() / "jobs" / identifier
    directory.mkdir(parents=True)
    version = nanobot.__version__
    filename = f"nanobot_ai-{version}-py3-none-win_amd64.whl"
    snapshot = InstallationSnapshot(
        environment=str(Path(sys.prefix).resolve()), python=sys.executable,
        installed_version=version, running_version=version, package_path=nanobot.__file__,
        running_package=nanobot.__file__, owner="venv", records={},
    )
    profiles = inspect_profiles(sys.prefix)
    plan = UpdatePlan(
        id=identifier, installation=snapshot, channel="stable", profiles=profiles,
        restart_profiles=[previous.id], extras=[], created_at=int(time.time()), expires_at=int(time.time()) + 900,
        target=ReleaseTarget(version=version, source="pypi", url=f"https://files.pythonhosted.org/packages/{filename}",
                             artifact=ReleaseArtifact(filename=filename, size=1, sha256="0" * 64)),
    )
    write_record(directory / "plan.json", plan.model_dump(mode="json"))
    paths = profile_data_paths(
        home=Path(previous.home), data_dir=Path(previous.data_dir),
        config=Path(previous.config), workspace=Path(previous.workspace))
    if legacy_scope:
        paths = tuple(path for path in paths if path != Path(previous.data_dir) / "delivery")
    sources = unique_sources([BackupSource(str(path)) for path in paths])
    spec = WorkerSpec(
        identifier, hashlib.sha256((directory / "plan.json").read_bytes()).hexdigest(),
        _worker_archive(directory / "worker.pyz"),
        EnvironmentSnapshot(snapshot.environment, sys.executable, sys.executable,
                            "0" * 64, {}, {}, version, {}), version,
        (StagedWheel(filename, "nanobot-ai", version, 1, "0" * 64),), sources, (previous.id,),
    )
    spec.save(directory)
    JobStatus(identifier, Phase.RESTARTING, 1, True, "Fixture: package verification completed", int(time.time())).save(directory)
    with data_access((item.path for item in sources), updating=True, job_id=identifier) as data:
        data.reserve()
    pending_update_path().parent.mkdir(parents=True, exist_ok=True)
    write_record(pending_update_path(), {"schema_version": 2, "job_id": identifier, "version": version})
    return directory, spec


@pytest.mark.skipif(os.name == "nt", reason="Native Windows lifecycle execution requires a Windows runner")
@pytest.mark.parametrize("legacy_scope", [False, True])
def test_actual_gateway_is_parked_until_exact_runtime_activation(private_home, tmp_path, monkeypatch, legacy_scope):
    from nanobot import update_restart

    profile = tmp_path / "gateway home"
    workspace = tmp_path / "中文 workspace"
    cwd = tmp_path / "original working directory"
    profile.mkdir()
    cwd.mkdir()
    health_port, web_port = _port(), _port()
    config_path = profile / "config.json"
    config_path.write_text(json.dumps({
        "agents": {"defaults": {"workspace": str(workspace), "dream": {"enabled": False},
                                "provider": "custom", "model": "lifecycle-test"}},
        "providers": {"custom": {"apiKey": "fixture-not-a-secret", "apiBase": "http://127.0.0.1:1/v1"}},
        "gateway": {"host": "127.0.0.1", "port": health_port, "heartbeat": {"enabled": False}},
        "channels": {"websocket": {"enabled": True, "host": "127.0.0.1", "port": web_port}},
    }))
    source = Path(__file__).resolve().parents[1]
    marker = tmp_path / "mcp-started"
    bootstrap = (
        f"import sys, runpy; sys.path.insert(0, {str(source)!r})\n"
        "from pathlib import Path\nimport os\n"
        "from nanobot.cli import gateway_runtime\n"
        "from nanobot.agent.tools.mcp import MCPProvider\n"
        "gateway_runtime.warmup_token_encoding = lambda: None\n"
        "async def observe_connect(self):\n"
        "    assert 'NANOBOT_UPDATE_STARTUP_TOKEN' not in os.environ\n"
        f"    Path({str(marker)!r}).touch()\n"
        "MCPProvider.connect = observe_connect\n"
    )
    original_popen = subprocess.Popen
    children = []

    def spawn(command, **kwargs):
        if "--gateway" in command:
            # Run the same frozen entrypoint with checkout imports selected by
            # this test, only after protected site initialization. Keep the
            # production -I -S flags; no application import may bypass them.
            script = (
                "import sys, runpy\nsys.argv = sys.argv[1:]\nsys.path.insert(0, sys.argv[0])\n"
                "from _nanobot_update import update_worker\n"
                "initialize = update_worker.initialize_runtime\n"
                "def initialize_fixture(python, environment):\n"
                "    initialize(python, environment)\n"
                f"    exec({bootstrap!r}, {{}})\n"
                "update_worker.initialize_runtime = initialize_fixture\n"
                "runpy.run_path(sys.argv[0], run_name='__main__')\n"
            )
            assert command[1:3] == ["-I", "-S"]
            command = [command[0], "-I", "-S", "-c", script, *command[3:]]
        elif command[1:3] == ["-m", "nanobot"]:
            script = bootstrap + "from nanobot.cli.entry import main\nmain()\n"
            command = [command[0], "-c", script, *command[3:]]
            kwargs["cwd"] = cwd
        else:
            return original_popen(command, **kwargs)
        child = original_popen(command, **kwargs)
        children.append(child)
        return child

    selected_home = get_selected_home_path()
    set_home_path(profile)
    instance = GatewayInstance.resolve(config_path=config_path)
    runtime = GatewayRuntime(paths=instance.paths, python_executable=sys.executable, popen=spawn)
    release = threading.Event()
    parked = threading.Event()
    executor = ThreadPoolExecutor(max_workers=1)
    future = None
    try:
        assert runtime.start_background(instance.start_options(port=health_port)).ok
        _wait(lambda: runtime.status().ready, "Original isolated gateway did not become ready")
        previous = inspect_profiles(sys.prefix)[0].receipt
        assert previous.launch.working_directory == str(cwd)
        assert runtime.stop(timeout_s=10).ok
        assert children[-1].wait(timeout=10) == 0
        marker.unlink()
        directory, spec = _job(previous, legacy_scope=legacy_scope)
        original_wait = update_restart._wait_verified

        def wait_verified(*args, **kwargs):
            result = original_wait(*args, **kwargs)
            if kwargs["maintenance"] is True:
                parked.set()
                assert release.wait(15), "Test did not release the inspected parked runtime"
            return result

        monkeypatch.setattr(update_restart, "_wait_verified", wait_verified)
        monkeypatch.setattr(update_restart.subprocess, "Popen", spawn)

        def coordinate():
            with installation_access(allow_incomplete=True):
                run_restarts(directory)

        future = executor.submit(coordinate)
        _wait(lambda: parked.is_set() or future.done(), "Restart did not reach protected readiness")
        if future.done():
            future.result()
        assert parked.is_set(), "Coordinator skipped protected readiness"
        status, body = _http(health_port, "/health")
        assert status == 200 and json.loads(body)["maintenance"] is True
        assert not marker.exists(), "MCP started before gateway activation"
        assert not (Path(previous.data_dir) / "delivery/outbox.sqlite3").exists()
        assert _http(web_port, "/webui/bootstrap")[0] == 503
        assert _http(web_port, "/api/uploads", method="POST")[0] == 503
        assert JobStatus.read(directory).phase == Phase.RESTARTING
        with pytest.raises(InstallationBusyError):
            with installation_access():
                pytest.fail("Ordinary installation startup bypassed the pending handoff")
        with pytest.raises(InstallationBusyError):
            with data_access([workspace / "sessions"]):
                pytest.fail("Ordinary data access bypassed the pending handoff")
        release.set()
        future.result(timeout=25)
        assert JobStatus.read(directory).phase == Phase.SUCCEEDED
        assert not pending_update_path().exists()
        current = verify_restarted_profile(previous, version=spec.version, job_id=spec.plan_id, maintenance=False)
        assert current.run_id != previous.run_id
        _wait(marker.exists, "MCP did not start after activation")
        assert _http(web_port, "/webui/bootstrap")[0] == 200
        with installation_access(), data_access([workspace / "sessions"]):
            pass
        JobStatus(spec.plan_id, Phase.FINALIZING, 1, True, "Verified; cleanup interrupted", int(time.time())).save(directory)
        write_record(pending_update_path(), {"schema_version": 2, "job_id": spec.plan_id, "version": spec.version})
        run_restarts(directory)
        assert JobStatus.read(directory).phase == Phase.SUCCEEDED
        assert not pending_update_path().exists()
        assert runtime.stop(timeout_s=10).ok
        assert children[-1].wait(timeout=10) == 0
        run_restarts(directory)
        assert len(children) == 2, "Completed job restarted a gateway the user had stopped"
    finally:
        release.set()
        if future is not None:
            try:
                future.result(timeout=130)
            except Exception:
                pass
        executor.shutdown(wait=True)
        if runtime.status().running:
            runtime.stop(timeout_s=10)
        for child in children:
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=10)
        set_home_path(selected_home)


async def test_activation_is_bound_to_new_run_not_just_profile(tmp_path):
    from types import SimpleNamespace

    identifier, participant = str(uuid4()), "a" * 64
    directory = tmp_path / identifier
    directory.mkdir()
    startup = GatewayStartup(directory, SimpleNamespace(id=participant), DataStartupGrant(identifier, participant, "b" * 64))
    from nanobot.gateway.runtime import GatewayHealthIdentity

    identity = GatewayHealthIdentity(participant, "c" * 32, "0.3.5")
    JobStatus(identifier, Phase.ACTIVATING, 1, True, "test activation", int(time.time())).save(directory)
    write_record(directory / "activation.json", {"plan_id": identifier, participant: {**asdict(identity), "run_id": "d" * 32}})
    waiting = asyncio.create_task(startup.wait_for_activation(identity))
    try:
        await asyncio.sleep(0.15)
        assert not waiting.done()
        write_record(directory / "activation.json", {"plan_id": identifier, participant: asdict(identity)})
        await asyncio.wait_for(waiting, timeout=1)
    finally:
        waiting.cancel()
        await asyncio.gather(waiting, return_exceptions=True)
