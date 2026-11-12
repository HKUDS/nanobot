import asyncio
import base64
import hashlib
import json
import os
import shlex
import signal
import subprocess
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path, PureWindowsPath
from unittest.mock import AsyncMock
from uuid import uuid4
from zipfile import ZipFile

import httpx
import pytest
from packaging.tags import sys_tags

from nanobot.config.home import get_selected_home_path, set_home_path
from nanobot.data_access import data_access
from nanobot.gateway.runtime import GatewayInstance, GatewayRuntime
from nanobot.installation_lock import (
    InstallationBusyError,
    file_access,
    installation_access,
    installation_state_dir,
    pending_update_path,
)
from nanobot.process_runtime import process_is_running
from nanobot.release_feed import CATALOGUE_URL, ReleaseFeed, ReleaseTarget
from nanobot.releases import (
    PLATFORMS,
    ReleaseArtifact,
    ReleaseCatalogue,
    ReleaseManifest,
    ReleasePointer,
    release_filenames,
)
from nanobot.update_backup import BackupSource
from nanobot.update_channel import UpdateChannelRequest, read_update_channel
from nanobot.update_jobs import (
    _recovery_command,
    prepare_job,
    retry_handoff,
    settle_interrupted_preparation,
    start_handoff,
    start_job,
)
from nanobot.update_plan import InstallationSnapshot, UpdatePlan, UpdatePlans
from nanobot.update_process import PreparationProcess, inspect_python_environment
from nanobot.update_profiles import inspect_profiles, record_gateway_profile
from nanobot.update_service import UpdateJobService
from nanobot.update_worker import (
    ExecutionConfirmation,
    JobStatus,
    Phase,
    WorkerSpec,
    cancel_job,
    inspect_environment,
    read_record,
    write_record,
)

_RESTART_PROBE = """
# Synthetic installed handoff for worker/lease routing, not gateway readiness.
import time
from pathlib import Path
import nanobot
from _nanobot_update.data_access import data_access
from _nanobot_update.installation_lock import InstallationBusyError, installation_access, pending_update_path
from _nanobot_update.update_worker import JobStatus, Phase, WorkerSpec, write_record

def run_gateway(directory, participant):
    raise AssertionError('This routing fixture must not launch a gateway')

def run_restarts(directory):
    spec = WorkerSpec.read(directory)
    status = JobStatus.read(directory)
    assert status.phase in {Phase.RESTARTING, Phase.RESTART_FAILED}
    with installation_access(allow_incomplete=True):
        try:
            with installation_access(updating=True):
                raise AssertionError('Runtime bridge has no shared installation lease')
        except InstallationBusyError:
            pass
        with data_access((item.path for item in spec.backup_sources), job_id=spec.plan_id) as data:
            write_record(directory / 'handoff-probe.json', {
                'version': nanobot.__version__, 'package': str(Path(nanobot.__file__).resolve()),
                'attempt': status.attempt, 'phase': status.phase.value,
            })
            if (directory / 'fail-restart').exists():
                raise RuntimeError('Controlled handoff failure')
            JobStatus(spec.plan_id, Phase.FINALIZING, status.attempt, True,
                      'Synthetic routing complete; not real gateway evidence', int(time.time())).save(directory)
            data.release_reservation()
            pending_update_path().unlink()
            JobStatus(spec.plan_id, Phase.SUCCEEDED, status.attempt, True,
                      'Synthetic routing complete; not real gateway evidence', int(time.time())).save(directory)
"""


_HANDOFF_PROBE = """
# Synthetic old-runtime preflight; release/stop contracts are tested separately.
import time
import traceback
from _nanobot_update.installation_lock import InstallationBusyError, installation_access
from _nanobot_update.update_worker import JobStatus, Phase, WorkerSpec, write_record

def prepare_handoff(directory):
    try:
        _prepare_handoff(directory)
    except Exception:
        # Keep subprocess failures visible in CI without changing the real
        # worker's deliberately sanitized output or capturing user data.
        (directory / 'preflight-error.txt').write_text(traceback.format_exc())
        raise

def _prepare_handoff(directory):
    spec = WorkerSpec.read(directory)
    try:
        with installation_access(updating=True):
            raise AssertionError('Old runtime imported before taking its lease')
    except InstallationBusyError:
        pass
    write_record(directory / 'preflight-entered.json', {'plan_id': spec.plan_id})
    deadline = time.monotonic() + 20
    while (directory / 'pause-preflight').exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    if (directory / 'pause-preflight').exists():
        raise RuntimeError('Timed out waiting for the test to release preflight')
    if (directory / 'refuse-preflight').exists():
        JobStatus(spec.plan_id, Phase.HANDOFF_FAILED, 0, False,
                  'Controlled preflight refusal', int(time.time())).save(directory)
        raise RuntimeError('Controlled preflight refusal')
    JobStatus(spec.plan_id, Phase.STOPPING, 0, False,
              'Synthetic preflight complete', int(time.time())).save(directory)
"""


def wheel(directory, name, version, *, requires=(), platform="any", broken=False, restart=False, handoff=False,
          extras=(), entrypoint=False, restart_contract=b'{"schema_version":1,"handoff_protocols":[1]}'):
    package = name.replace("-", "_")
    dist = f"{package}-{version}.dist-info"
    files = {
        f"{package if name != 'nanobot-ai' else 'nanobot'}/__init__.py": f"__version__ = '{version}'\n".encode(),
        f"{dist}/METADATA": (f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
                             + "".join(f"Provides-Extra: {extra}\n" for extra in extras)
                             + "".join(f"Requires-Dist: {requirement}\n" for requirement in requires)).encode(),
        f"{dist}/WHEEL": f"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-{platform}\n".encode(),
    }
    if name == "nanobot-ai":
        if entrypoint:
            files["nanobot/__init__.py"] += b"def main(): pass\n"
            files[f"{dist}/entry_points.txt"] = b"[console_scripts]\nnanobot = nanobot:main\n"
        if broken:
            files["nanobot/__init__.py"] = b"raise RuntimeError('broken release fixture')\n"
        files["nanobot/web/dist/index.html"] = f"verified UI {version}".encode()
        files["nanobot/tui/bin/fixture"] = b"fixture, not a native execution claim"
        if restart:
            files["nanobot/update_restart.py"] = _RESTART_PROBE.encode()
            if restart_contract is not None:
                files["nanobot/update_contract.json"] = restart_contract
        if handoff:
            files["nanobot/update_handoff.py"] = _HANDOFF_PROBE.encode()
    records = []
    for filename, data in files.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        records.append(f"{filename},sha256={digest},{len(data)}")
    files[f"{dist}/RECORD"] = ("\n".join(records) + f"\n{dist}/RECORD,,\n").encode()
    path = directory / f"{package}-{version}-py3-none-{platform}.whl"
    with ZipFile(path, "w") as archive:
        for filename, data in files.items():
            archive.writestr(filename, data)
    return path


def test_planning_probe_bootstraps_before_target_site(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    result = inspect_python_environment(
        sys.executable, str(Path(sys.prefix).resolve()), "print('protected inspection')",
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "protected inspection"


@pytest.fixture
def installation(tmp_path, monkeypatch, request, create_integration_env):
    # Synthetic local packages are not signed public releases. Approval refusal
    # is covered through the real feed in test_release_trust.py.
    monkeypatch.setattr(ReleaseFeed, "_authorize", AsyncMock())
    state_home = tmp_path / "private home"
    state_home.mkdir()
    monkeypatch.setenv("HOME", str(state_home))
    monkeypatch.setenv("USERPROFILE", str(state_home))
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    environment = tmp_path / "venv with spaces"
    python = str(create_integration_env(environment))
    monkeypatch.setenv("PIP_CONFIG_FILE", os.devnull)
    monkeypatch.setenv("PIP_NO_INDEX", "1")
    monkeypatch.setenv("PIP_FIND_LINKS", str(artifacts))
    for version in ("1.0.0", "2.0.0"):
        wheel(artifacts, "fixture-update-dep", version)
    mode = getattr(request, "param", False)
    versions = ("0.3.4", "0.3.5")
    restart_contract = b'{"schema_version":1,"handoff_protocols":[1]}'
    if isinstance(mode, dict):
        versions = mode.get("versions", versions)
        restart_contract = mode.get("restart_contract", restart_contract)
        mode = "handoff" if "restart_contract" in mode else False
    previous_version, next_version = versions
    previous = wheel(artifacts, "nanobot-ai", previous_version, requires=["fixture-update-dep==1.0.0"],
                     handoff=mode == "handoff")
    subprocess.run([python, "-I", "-m", "pip", "install", "--disable-pip-version-check", str(previous)],
                   check=True, capture_output=True, timeout=60)
    platform = next(tag.platform for tag in sys_tags() if tag.platform in PLATFORMS.values())
    candidate = wheel(artifacts, "nanobot-ai", next_version, requires=["fixture-update-dep>=2.0.0"], platform=platform,
                      broken=mode is True,
                      restart=mode in ("restart", "handoff"),
                      restart_contract=restart_contract)
    baseline = inspect_environment(python)
    site = Path(subprocess.check_output([python, "-I", "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"], text=True).strip())
    snapshot = InstallationSnapshot(
        environment=str(environment.resolve()), python=python, installed_version=previous_version, running_version=previous_version,
        package_path=str(site / "nanobot/__init__.py"), running_package=str(site / "nanobot/__init__.py"),
        owner="venv", records={"pyvenv.cfg": baseline.receipt_sha, **baseline.app_records},
    )
    profile, workspace = tmp_path / "gateway data", tmp_path / "user project"
    (profile / "sessions").mkdir(parents=True)
    workspace.mkdir()
    (profile / "config.json").write_text('{"fixture":"private credential"}')
    (profile / "sessions/chat.jsonl").write_text('{"content":"original conversation"}\n')
    (workspace / "private-project.py").write_text("not nanobot state")
    selected_home = get_selected_home_path()
    try:
        set_home_path(profile)
        instance = GatewayInstance.resolve(config_path=profile / "config.json", workspace=str(workspace))
        runtime = GatewayRuntime(paths=instance.paths)
        # Synthetic package fixture, real runtime receipt lifetime. Full gateway
        # registration is independently tested in test_update_profiles.py.
        with monkeypatch.context() as patch:
            patch.setattr(sys, "prefix", str(environment))
            with runtime.foreground_instance(instance.start_options(port=18790)):
                with record_gateway_profile(instance, runtime, data_dir=profile, workspace=workspace, port=18790):
                    pass
    finally:
        set_home_path(selected_home)
    profiles = inspect_profiles(str(environment))
    restart_profiles = []
    if mode in ("restart", "handoff"):
        # Synthetic process metadata selects the installed routing stub above;
        # test_update_restart.py separately runs the actual background gateway.
        receipt = profiles[0].receipt.model_copy(update={"launch_mode": "background"})
        write_record(installation_state_dir(str(environment)) / "profiles" / f"{receipt.id}.json",
                     receipt.model_dump(mode="json"))
        profiles = inspect_profiles(str(environment))
        restart_profiles = [receipt.id]
    target = ReleaseTarget.model_construct(version=next_version, source="pypi",
                           url=f"https://files.pythonhosted.org/packages/{candidate.name}",
                           artifact=ReleaseArtifact(filename=candidate.name, size=candidate.stat().st_size,
                                                    sha256=hashlib.sha256(candidate.read_bytes()).hexdigest()))
    manifest = None
    catalogue = None
    if ".dev" in next_version:
        manifest = ReleaseManifest(version=next_version, source_commit="a" * 40, candidate_commit="b" * 40,
                                   requires_python=">=3.11",
                                   artifacts=[target.artifact if name == candidate.name else ReleaseArtifact(
                                       filename=name, size=1, sha256="b" * 64,
                                   ) for name in release_filenames(next_version)])
        pointer = ReleasePointer(version=next_version, candidate_commit=manifest.candidate_commit,
                                 manifest_sha256=hashlib.sha256(manifest.model_dump_json().encode()).hexdigest())
        catalogue = ReleaseCatalogue(generation=1, preview=pointer)
        target = target.model_copy(update={"source": "github", "url": manifest.artifact_url(target.artifact).split("#")[0],
                                          "pointer": pointer, "catalogue_generation": 1})
    target = ReleaseTarget.model_validate(target.model_dump())
    now = int(time.time())
    plan = UpdatePlan(id=str(uuid4()), installation=snapshot, target=target, extras=[],
                      channel="preview" if manifest else "stable",
                      profiles=profiles, restart_profiles=restart_profiles,
                      created_at=now, expires_at=now + 900)
    requests = []

    def response(request):
        requests.append(str(request.url))
        if catalogue and request.url.host in {"github.com", "raw.githubusercontent.com"}:
            if str(request.url) == CATALOGUE_URL:
                return httpx.Response(200, json=catalogue.model_dump(mode="json"))
            if request.url.path.endswith("release-manifest.json"):
                return httpx.Response(200, content=manifest.model_dump_json().encode())
            assert request.url.path.endswith(candidate.name)
            return httpx.Response(200, content=candidate.read_bytes())
        if request.url.host == "files.pythonhosted.org":
            return httpx.Response(200, content=candidate.read_bytes())
        assert request.url.path == f"/pypi/nanobot-ai/{next_version}/json", "execution re-resolved latest"
        files = []
        for filename in release_filenames(next_version):
            if filename.endswith((".whl", ".tar.gz")):
                selected = filename == candidate.name
                files.append({"filename": filename, "size": target.artifact.size if selected else 1,
                              "url": f"https://files.pythonhosted.org/packages/{filename}", "yanked": False,
                              "digests": {"sha256": target.artifact.sha256 if selected else "a" * 64}})
        return httpx.Response(200, json={"info": {"name": "nanobot-ai", "version": next_version, "requires_python": ">=3.11"}, "urls": files})

    return plan, candidate, site, requests, httpx.MockTransport(response)


@pytest.fixture
def managed_installation(installation):
    plan, candidate, site, requests, transport = installation
    receipt = Path(plan.installation.environment) / "nanobot-install.json"
    write_record(receipt, {"schema_version": 1, "owner": "nanobot-installer",
                           "environment": plan.installation.environment, "extras": []})
    snapshot = plan.installation.model_copy(update={
        "records": {**plan.installation.records, "nanobot-install.json": hashlib.sha256(receipt.read_bytes()).hexdigest()},
    })
    return plan.model_copy(update={"installation": snapshot}), candidate, site, requests, transport


@pytest.mark.parametrize("cancel_feed_close", [False, True])
async def test_confirmed_service_prepares_exact_offline_pip_job_without_installing(installation, monkeypatch, cancel_feed_close):
    from nanobot import update_service

    plan, _, _, requests, transport = installation
    monkeypatch.setattr(sys, "prefix", plan.installation.environment)
    root = installation_state_dir()
    UpdatePlans(root / "plans").save(plan)
    class PreparedFeed(ReleaseFeed):
        def __init__(self, directory):
            super().__init__(directory, transport=transport)

        async def __aexit__(self, *args):
            await super().__aexit__(*args)
            if cancel_feed_close:
                raise asyncio.CancelledError()

    monkeypatch.setattr(update_service, "ReleaseFeed", PreparedFeed)
    service = UpdateJobService()
    acknowledged = service.prepare(plan.id)
    assert acknowledged.recorded_phase == Phase.PREPARATION_REQUESTED
    await service.close()
    restored = UpdateJobService().prepare(plan.id)
    assert restored.recorded_phase == Phase.READY
    spec = WorkerSpec.read(root / "jobs" / plan.id)
    spec.verify_inputs(root / "jobs" / plan.id)
    assert spec.version == "0.3.5"
    assert inspect_environment(plan.installation.python).app_version == "0.3.4"
    assert requests == ["https://pypi.org/pypi/nanobot-ai/0.3.5/json"] * 2 + [plan.target.url]
    assert not (root / "jobs" / plan.id / "approval.json").exists()
    assert not (root / "stop.json").exists()


async def wait_worker(process):
    code = await asyncio.to_thread(process.wait, 40)
    assert code == 0


async def test_channel_switch_retires_real_staged_job_and_preserves_its_evidence(installation, monkeypatch, tmp_path):
    plan, _, _, _, transport = installation
    monkeypatch.setattr(sys, "prefix", plan.installation.environment)
    async with ReleaseFeed(tmp_path / "feed", transport=transport) as feed:
        directory = await prepare_job(plan, feed)
        spec_bytes = (directory / "request.json").read_bytes()
        with file_access(installation_state_dir() / "worker.lock", exclusive=True):
            with pytest.raises(BlockingIOError):
                UpdateJobService().change_channel(UpdateChannelRequest(channel="preview", revision=0))
        assert read_update_channel().channel == "stable"
        assert JobStatus.read(directory).phase == Phase.READY
        changed = UpdateJobService().change_channel(UpdateChannelRequest(channel="preview", revision=0))
        assert changed.revision == 1
        assert JobStatus.read(directory).phase == Phase.CANCELLED
        assert (directory / "request.json").read_bytes() == spec_bytes
        with pytest.raises(ValueError):
            await start_job(directory, feed)
    assert inspect_environment(plan.installation.python).app_version == plan.installation.installed_version
    assert not (directory / "approval.json").exists()
    assert not pending_update_path().exists()


async def test_old_plan_without_channel_revision_remains_readable_and_byte_identical(installation, tmp_path):
    plan, _, _, _, transport = installation
    directory = installation_state_dir(plan.installation.environment) / "jobs" / plan.id
    directory.mkdir(parents=True)
    old = plan.model_dump(mode="json")
    old.pop("channel_revision")
    write_record(directory / "plan.json", old)
    original = (directory / "plan.json").read_bytes()
    async with ReleaseFeed(tmp_path / "feed", transport=transport) as feed:
        assert await prepare_job(plan, feed) == directory
        assert await prepare_job(plan, feed) == directory
    assert (directory / "plan.json").read_bytes() == original
    WorkerSpec.read(directory).verify_inputs(directory)


@pytest.mark.parametrize("installation", [{"versions": ("0.3.6", "0.3.7.dev42")},
                                        {"versions": ("0.3.7.dev42", "0.3.7.dev43")},
                                        {"versions": ("0.3.7.dev43", "0.3.7")}], indirect=True)
async def test_real_channel_upgrade_installs_verified_bytes_and_keeps_user_data(installation, tmp_path):
    plan, _, site, _, transport = installation
    profile = Path(plan.profiles[0].receipt.home)
    original = {path: path.read_bytes() for path in (profile / "config.json", profile / "sessions/chat.jsonl")}
    async with ReleaseFeed(tmp_path / "feed", transport=transport) as feed:
        directory = await prepare_job(plan, feed)
        assert inspect_environment(plan.installation.python).app_version == plan.installation.installed_version
        await wait_worker(await start_job(directory, feed))
    assert JobStatus.read(directory).phase == Phase.INSTALLED
    assert inspect_environment(plan.installation.python).app_version == plan.target.version
    assert (site / "nanobot/web/dist/index.html").read_text() == f"verified UI {plan.target.version}"
    assert all(path.read_bytes() == value for path, value in original.items())
    assert not pending_update_path(plan.installation.environment).exists()


def test_recovery_command_uses_base_python_and_exact_launcher_without_shell_home(monkeypatch, tmp_path):
    import nanobot.update_jobs as jobs

    python = "/opt/Python tools/user's python/bin/python3"
    monkeypatch.setattr(jobs.sys, "_base_executable", python)
    monkeypatch.setattr(jobs.platform, "system", lambda: "Linux")
    state = tmp_path / "user's private home/.nanobot/updates/installation"
    monkeypatch.setattr(jobs, "installation_state_dir", lambda: state)
    job_id = str(uuid4())
    assert shlex.split(_recovery_command(job_id)) == [
        python, "-I", "-S", str(state.parent / "recover.py"), job_id, "--repair",
    ]


def test_recovery_command_quotes_windows_base_python_for_powershell(monkeypatch):
    import nanobot.update_jobs as jobs

    monkeypatch.setattr(jobs.sys, "_base_executable", r"C:\Python tools\user's Python\python.exe")
    monkeypatch.setattr(jobs.platform, "system", lambda: "Windows")
    monkeypatch.setattr(jobs, "installation_state_dir", lambda: PureWindowsPath(
        r"C:\Users\user's private home\.nanobot\updates\installation"))
    job_id = str(uuid4())
    assert _recovery_command(job_id) == (
        r"& 'C:\Python tools\user''s Python\python.exe' -I -S "
        rf"'C:\Users\user''s private home\.nanobot\updates\recover.py' {job_id} --repair"
    )


@pytest.mark.parametrize("installation", [False, {"versions": ("0.3.6", "0.3.7.dev42")},
                                        {"versions": ("0.3.7.dev42", "0.3.7")}], indirect=True)
async def test_standalone_repair_survives_missing_dependency_and_expired_approval(installation, tmp_path):
    plan, _, site, _, transport = installation
    async with ReleaseFeed(tmp_path / "feed", transport=transport) as feed:
        directory = await prepare_job(plan, feed)
        pip_entry = site / "pip/__main__.py"
        original = pip_entry.read_text()
        pip_entry.write_text(
            f"from pathlib import Path\nPath({str(site / 'fixture_update_dep/__init__.py')!r}).unlink()\n"
            "raise SystemExit(99)\n")
        process = await start_job(directory, feed)
        assert await asyncio.to_thread(process.wait, 40) != 0
        pip_entry.write_text(original)
    status = JobStatus.read(directory)
    assert status.mutation_started and status.attempt == 1
    backup = (directory / "backup/data.zip").read_bytes()
    approval = read_record(directory / "approval.json")
    approval.update(created_at=int(time.time()) - 1800, expires_at=int(time.time()) - 900)
    write_record(directory / "approval.json", approval)
    launcher = directory.parents[2] / "recover.py"
    command = [sys._base_executable, "-I", "-S", str(launcher), plan.id]
    terminal_home = tmp_path / "operator home"
    terminal_home.mkdir()
    terminal_env = dict(os.environ, HOME=str(terminal_home), USERPROFILE=str(terminal_home))
    viewed = await asyncio.to_thread(subprocess.run, command, env=terminal_env,
                                    capture_output=True, text=True, timeout=40)
    assert viewed.returncode == 0, viewed.stderr
    assert "Inspection only" in viewed.stdout
    assert JobStatus.read(directory) == status
    with installation_access(environment=plan.installation.environment, allow_incomplete=True):
        refused = await asyncio.to_thread(subprocess.run, [*command, "--repair", "--yes"],
                                          env=terminal_env, capture_output=True, text=True, timeout=40)
    assert refused.returncode != 0
    assert JobStatus.read(directory) == status
    repaired = await asyncio.to_thread(subprocess.run, [*command, "--repair", "--yes"],
                                      env=terminal_env, capture_output=True, text=True, timeout=40)
    assert repaired.returncode == 0, repaired.stdout + repaired.stderr
    assert JobStatus.read(directory).phase == Phase.INSTALLED
    assert JobStatus.read(directory).attempt == 2
    assert inspect_environment(plan.installation.python).app_version == plan.target.version
    assert (site / "fixture_update_dep/__init__.py").read_text() == "__version__ = '2.0.0'\n"
    assert (directory / "backup/data.zip").read_bytes() == backup
    assert not pending_update_path(plan.installation.environment).exists()
    assert list(terminal_home.iterdir()) == []


async def test_standalone_repair_cannot_turn_preparation_into_installation(installation, tmp_path):
    plan, _, _, _, transport = installation
    async with ReleaseFeed(tmp_path / "feed", transport=transport) as feed:
        directory = await prepare_job(plan, feed)
    result = await asyncio.to_thread(subprocess.run, [
        sys._base_executable, "-I", "-S", str(directory.parents[2] / "recover.py"), plan.id, "--repair", "--yes",
    ], capture_output=True, text=True, timeout=40)
    assert result.returncode != 0
    assert JobStatus.read(directory).phase == Phase.READY
    assert not (directory / "approval.json").exists()
    assert inspect_environment(plan.installation.python).app_version == "0.3.4"


async def wait_for(predicate):
    async with asyncio.timeout(40):
        while not predicate():
            await asyncio.sleep(0.02)


@pytest.mark.parametrize("installation", [
    {"restart_contract": None},
    {"restart_contract": b'{"schema_version":1,"handoff_protocols":[2]}'},
    {"restart_contract": b'{"schema_version":1,"handoff_protocols":[true]}'},
    {"restart_contract": b'{"schema_version":1,"handoff_protocols":['},
], ids=["undeclared", "incompatible", "malformed", "truncated"], indirect=True)
async def test_target_restart_contract_is_checked_before_preparation_commits(installation, tmp_path):
    plan, _, _, _, transport = installation
    async with ReleaseFeed(tmp_path / "feed", transport=transport) as feed:
        with pytest.raises(ValueError, match="external update procedure"):
            await prepare_job(plan, feed)
    root = installation_state_dir(plan.installation.environment)
    directory = root / "jobs" / plan.id
    assert JobStatus.read(directory).phase == Phase.PREPARATION_FAILED
    assert not (directory / "request.json").exists()
    assert not (directory / "approval.json").exists()
    assert not (directory / "preflight-entered.json").exists()
    assert not (root / "stop.json").exists()
    assert inspect_environment(plan.installation.python).app_version == "0.3.4"


@pytest.mark.parametrize("installation", [{"restart_contract": None}], indirect=True)
async def test_previously_staged_target_cannot_bypass_restart_contract(installation, tmp_path, monkeypatch):
    from nanobot import update_jobs

    plan, _, _, _, transport = installation
    with monkeypatch.context() as patch:
        patch.setattr(update_jobs, "verify_target_handoff", lambda archive: None)
        async with ReleaseFeed(tmp_path / "feed", transport=transport) as feed:
            directory = await prepare_job(plan, feed)
    before = JobStatus.read(directory)
    assert before.phase == Phase.READY
    with pytest.raises(ValueError, match="external update procedure"):
        start_handoff(directory, once=True)
    assert ExecutionConfirmation.read(directory) is None
    assert not (directory / "handoff-approval.json").exists()
    assert not (directory / "preflight-entered.json").exists()
    assert JobStatus.read(directory) == before
    assert inspect_environment(plan.installation.python).app_version == "0.3.4"


@pytest.mark.parametrize("installation", [
    "handoff", {"restart_contract": b'{"schema_version":1,"handoff_protocols":[2,1]}'},
], ids=["current-contract", "future-with-current-support"], indirect=True)
@pytest.mark.parametrize("refuse", [False, True])
async def test_confirmed_handoff_is_consumed_once_even_after_failure(installation, tmp_path, refuse):
    plan, _, _, _, transport = installation
    async with ReleaseFeed(tmp_path / "feed", transport=transport) as feed:
        directory = await prepare_job(plan, feed)
    if refuse:
        (directory / "refuse-preflight").touch()
    process = start_handoff(directory, once=True)
    assert process is not None
    code = await asyncio.to_thread(process.wait, 40)
    assert (code != 0) is refuse
    confirmation = ExecutionConfirmation.read(directory)
    assert confirmation is not None
    before = JobStatus.read(directory)
    assert before.phase == (Phase.HANDOFF_FAILED if refuse else Phase.SUCCEEDED)
    assert inspect_environment(plan.installation.python).app_version == ("0.3.4" if refuse else "0.3.5")
    (directory / "refuse-preflight").unlink(missing_ok=True)
    assert start_handoff(directory, once=True) is None
    assert ExecutionConfirmation.read(directory) == confirmation
    spec = WorkerSpec.read(directory)
    replay = subprocess.run([spec.baseline.base_python, "-I", str(directory / "worker.pyz"),
                             "--confirmed-handoff", str(directory), confirmation.id], capture_output=True, timeout=10)
    assert replay.returncode == 0, replay.stderr
    assert JobStatus.read(directory) == before
    assert not (directory / "approval.json").exists() if refuse else before.attempt == 1
    if not refuse:
        with pytest.raises(ValueError, match="unmodified"):
            retry_handoff(directory, confirmation.id)
        assert ExecutionConfirmation.read(directory) == confirmation


@pytest.mark.parametrize("installation", ["handoff"], indirect=True)
async def test_retry_consumes_one_failed_confirmation_and_rechecks_ownership_and_expiry(installation, tmp_path, monkeypatch):
    from nanobot import update_jobs

    plan, _, _, _, transport = installation
    async with ReleaseFeed(tmp_path / "feed", transport=transport) as feed:
        directory = await prepare_job(plan, feed)
    refusal = directory / "refuse-preflight"
    refusal.touch()
    process = start_handoff(directory, once=True)
    assert process is not None
    assert await asyncio.to_thread(process.wait, 40) != 0
    previous = ExecutionConfirmation.read(directory)
    assert previous is not None
    failed = JobStatus.read(directory)
    assert failed.phase == Phase.HANDOFF_FAILED and not failed.mutation_started

    root = installation_state_dir(plan.installation.environment)
    with file_access(root / "worker.lock", exclusive=True):
        with pytest.raises(BlockingIOError):
            retry_handoff(directory, previous.id)
    with monkeypatch.context() as patch:
        patch.setattr(update_jobs.time, "time", lambda: plan.expires_at)
        with pytest.raises(ValueError, match="expired"):
            retry_handoff(directory, previous.id)
    assert ExecutionConfirmation.read(directory) == previous
    assert JobStatus.read(directory) == failed

    refusal.unlink()
    process = retry_handoff(directory, previous.id)
    current = ExecutionConfirmation.read(directory)
    assert current is not None and current.id != previous.id
    assert current.request_sha256 == previous.request_sha256
    assert current.expires_at <= plan.expires_at
    assert retry_handoff(directory, previous.id) is None
    await wait_worker(process)
    completed = JobStatus.read(directory)
    assert completed.phase == Phase.SUCCEEDED and completed.attempt == 1
    assert inspect_environment(plan.installation.python).app_version == "0.3.5"
    spec = WorkerSpec.read(directory)
    late = subprocess.run([spec.baseline.base_python, "-I", str(directory / "worker.pyz"),
                           "--confirmed-handoff", str(directory), previous.id], capture_output=True, timeout=10)
    assert late.returncode != 0
    assert retry_handoff(directory, previous.id) is None
    assert JobStatus.read(directory) == completed


@pytest.mark.parametrize("installation", ["handoff"], indirect=True)
async def test_settled_failed_handoff_rejects_delayed_worker_and_keeps_original_files(installation, tmp_path):
    from nanobot.update_stop import settle_uncommitted_handoff

    plan, _, _, _, transport = installation
    async with ReleaseFeed(tmp_path / "feed", transport=transport) as feed:
        directory = await prepare_job(plan, feed)
    (directory / "refuse-preflight").touch()
    process = start_handoff(directory, once=True)
    assert process is not None and await asyncio.to_thread(process.wait, 40) != 0
    confirmation = ExecutionConfirmation.read(directory)
    assert confirmation is not None
    before = (directory / "request.json").read_bytes()
    settled = settle_uncommitted_handoff(directory)
    assert settled.phase == Phase.CANCELLED and not settled.mutation_started
    assert ExecutionConfirmation.read(directory) == confirmation
    assert (directory / "request.json").read_bytes() == before
    (directory / "refuse-preflight").unlink()
    spec = WorkerSpec.read(directory)
    late = await asyncio.to_thread(subprocess.run,
        [spec.baseline.base_python, "-I", str(directory / "worker.pyz"),
         "--confirmed-handoff", str(directory), confirmation.id], capture_output=True, timeout=10)
    assert late.returncode == 0
    assert JobStatus.read(directory) == settled
    assert not (directory / "approval.json").exists()
    with pytest.raises(ValueError, match="unmodified"):
        retry_handoff(directory, confirmation.id)


@pytest.mark.parametrize("installation", ["handoff"], indirect=True)
async def test_confirmed_launch_failure_is_not_retry_authority(installation, tmp_path, monkeypatch):
    from nanobot import update_jobs

    plan, _, _, _, transport = installation
    async with ReleaseFeed(tmp_path / "feed", transport=transport) as feed:
        directory = await prepare_job(plan, feed)
    launches = []

    def failed_spawn(directory, spec, **kwargs):
        launches.append(kwargs)
        raise OSError("controlled launch failure")

    monkeypatch.setattr(update_jobs, "_spawn_worker", failed_spawn)
    with pytest.raises(OSError, match="controlled launch"):
        start_handoff(directory, once=True)
    confirmation = ExecutionConfirmation.read(directory)
    assert confirmation is not None
    assert JobStatus.read(directory).phase == Phase.HANDOFF_FAILED
    assert start_handoff(directory, once=True) is None
    assert launches == [{"handoff": True, "confirmation_id": confirmation.id}]
    assert not (directory / "confirmation-claimed.json").exists()
    assert not (directory / "approval.json").exists()
    assert inspect_environment(plan.installation.python).app_version == "0.3.4"


@pytest.mark.parametrize("installation", ["handoff"], indirect=True)
async def test_late_launch_failure_cannot_overwrite_new_retry_confirmation(installation, tmp_path, monkeypatch):
    from nanobot import update_jobs

    plan, _, _, _, transport = installation
    async with ReleaseFeed(tmp_path / "feed", transport=transport) as feed:
        directory = await prepare_job(plan, feed)
    launched = []

    def spawn(path, spec, **kwargs):
        launched.append(kwargs["confirmation_id"])
        if len(launched) == 1:
            retry_handoff(path, kwargs["confirmation_id"])
            raise OSError("The superseded launcher failed late")
        return None

    monkeypatch.setattr(update_jobs, "_spawn_worker", spawn)
    with pytest.raises(OSError, match="superseded"):
        start_handoff(directory, once=True)
    assert len(launched) == 2 and launched[0] != launched[1]
    assert ExecutionConfirmation.read(directory).id == launched[1]
    assert JobStatus.read(directory).phase == Phase.CHECKING
    assert retry_handoff(directory, launched[0]) is None
    assert len(launched) == 2


@pytest.mark.parametrize("installation", ["handoff"], indirect=True)
async def test_late_confirmed_children_cannot_use_replaced_approval(installation, tmp_path, monkeypatch):
    from nanobot import update_jobs

    plan, _, _, _, transport = installation
    async with ReleaseFeed(tmp_path / "feed", transport=transport) as feed:
        directory = await prepare_job(plan, feed)
    monkeypatch.setattr(update_jobs, "_spawn_worker", lambda *args, **kwargs: None)
    start_handoff(directory, once=True)
    confirmation = ExecutionConfirmation.read(directory)
    assert confirmation is not None
    spec = WorkerSpec.read(directory)
    replaced = read_record(directory / "handoff-approval.json")
    replaced.pop("confirmation_id")
    write_record(directory / "handoff-approval.json", replaced)
    write_record(directory / "approval.json", replaced)
    before = JobStatus.read(directory)
    for entry in ("--confirmed-handoff", "--prepare-handoff", "--install", "--restart"):
        interpreter = spec.baseline.base_python if entry == "--confirmed-handoff" else spec.baseline.python
        result = subprocess.run([interpreter, "-I", "-S", str(directory / "worker.pyz"),
                                 entry, str(directory), confirmation.id], capture_output=True, timeout=10)
        assert result.returncode != 0, entry
    assert not (directory / "preflight-entered.json").exists()
    assert not (directory / "confirmation-claimed.json").exists()
    assert JobStatus.read(directory) == before
    assert inspect_environment(plan.installation.python).app_version == "0.3.4"


@pytest.mark.parametrize("installation", ["handoff"], indirect=True)
async def test_detached_handoff_outlives_requester_and_installs_after_preflight_exits(installation, tmp_path):
    plan, _, site, _, transport = installation
    async with ReleaseFeed(tmp_path / "feed", transport=transport) as feed:
        directory = await prepare_job(plan, feed)
    pause = directory / "pause-preflight"
    pause.touch()
    launcher = (
        f"import sys; sys.path.insert(0, {str(Path(__file__).resolve().parents[1])!r})\n"
        "from pathlib import Path\nfrom nanobot.update_jobs import start_handoff\n"
        f"start_handoff(Path({str(directory)!r}))\n"
    )
    subprocess.run([sys.executable, "-c", launcher], check=True, timeout=10,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        await wait_for(lambda: (directory / "preflight-entered.json").exists())
        assert JobStatus.read(directory).phase == Phase.CHECKING
        assert not (directory / "approval.json").exists()
        with pytest.raises(InstallationBusyError):
            with installation_access(updating=True, environment=plan.installation.environment):
                pytest.fail("Preflight released its environment before actual exit")
        with pytest.raises(BlockingIOError):
            start_handoff(directory)
        assert inspect_environment(plan.installation.python).app_version == "0.3.4"
    finally:
        pause.unlink(missing_ok=True)
        await wait_for(lambda: JobStatus.read(directory).phase in {
            Phase.SUCCEEDED, Phase.HANDOFF_FAILED, Phase.FAILED, Phase.RESTART_FAILED,
        })
    state = JobStatus.read(directory)
    error = directory / "preflight-error.txt"
    assert state.phase == Phase.SUCCEEDED, (state, error.read_text() if error.exists() else "")
    assert inspect_environment(plan.installation.python).app_version == "0.3.5"
    assert read_record(directory / "handoff-probe.json")["package"] == str((site / "nanobot/__init__.py").resolve())
    assert not (site / "nanobot/update_handoff.py").exists(), "Old preflight source was not replaced"


@pytest.mark.parametrize("installation", ["handoff"], indirect=True)
async def test_refused_handoff_never_approves_install_and_can_retry_exact_plan(installation, tmp_path):
    plan, _, _, _, transport = installation
    async with ReleaseFeed(tmp_path / "feed", transport=transport) as feed:
        directory = await prepare_job(plan, feed)
    refusal = directory / "refuse-preflight"
    refusal.touch()
    process = start_handoff(directory)
    assert await asyncio.to_thread(process.wait, 40) != 0
    state = JobStatus.read(directory)
    assert state.phase == Phase.HANDOFF_FAILED and not state.mutation_started
    assert state.message == "Controlled preflight refusal"
    assert not (directory / "approval.json").exists()
    assert not (directory / "backup").exists()
    assert inspect_environment(plan.installation.python).app_version == "0.3.4"
    refusal.unlink()
    await wait_worker(start_handoff(directory))
    assert JobStatus.read(directory).phase == Phase.SUCCEEDED


@pytest.mark.parametrize("installation", ["handoff"], indirect=True)
async def test_handoff_reports_writer_that_remains_after_preflight(installation, tmp_path):
    plan, _, _, _, transport = installation
    async with ReleaseFeed(tmp_path / "feed", transport=transport) as feed:
        directory = await prepare_job(plan, feed)
    with installation_access(environment=plan.installation.environment):
        process = start_handoff(directory)
        assert await asyncio.to_thread(process.wait, 40) != 0
    state = JobStatus.read(directory)
    assert state.phase == Phase.HANDOFF_FAILED and not state.mutation_started
    assert "exclusive access" in state.message
    assert not (directory / "approval.json").exists()
    assert inspect_environment(plan.installation.python).app_version == "0.3.4"
    await wait_worker(start_handoff(directory))
    assert JobStatus.read(directory).phase == Phase.SUCCEEDED
    spec = WorkerSpec.read(directory)
    replay = subprocess.run([spec.baseline.base_python, "-I", str(directory / "worker.pyz"),
                             "--handoff", str(directory)], capture_output=True, timeout=10)
    assert replay.returncode != 0
    assert JobStatus.read(directory).phase == Phase.SUCCEEDED


@pytest.mark.parametrize("installation", ["handoff"], indirect=True)
async def test_saved_handoff_requires_fresh_consent_before_importing_old_runtime(installation, tmp_path):
    plan, _, _, _, transport = installation
    async with ReleaseFeed(tmp_path / "feed", transport=transport) as feed:
        directory = await prepare_job(plan, feed)
    spec = WorkerSpec.read(directory)
    command = [spec.baseline.python, "-I", "-S", str(directory / "worker.pyz"), "--prepare-handoff", str(directory)]
    for expired in (False, True):
        if expired:
            now = int(time.time())
            write_record(directory / "handoff-approval.json", {
                "plan_id": plan.id, "request_sha256": hashlib.sha256((directory / "request.json").read_bytes()).hexdigest(),
                "created_at": now - 1000, "expires_at": now - 100,
            })
        result = subprocess.run(command, capture_output=True, timeout=10)
        assert result.returncode != 0
        assert not (directory / "preflight-entered.json").exists()
        assert not (directory / "approval.json").exists()
        assert JobStatus.read(directory).phase == Phase.READY
    assert inspect_environment(plan.installation.python).app_version == "0.3.4"


@pytest.mark.parametrize("installation", ["handoff"], indirect=True)
async def test_orphan_preflight_keeps_lease_and_cannot_approve_installation(installation, tmp_path):
    plan, _, _, _, transport = installation
    async with ReleaseFeed(tmp_path / "feed", transport=transport) as feed:
        directory = await prepare_job(plan, feed)
    pause = directory / "pause-preflight"
    pause.touch()
    process = start_handoff(directory, once=True)
    confirmation = ExecutionConfirmation.read(directory)
    assert confirmation is not None
    try:
        await wait_for(lambda: (directory / "preflight-entered.json").exists())
        process.kill()
        await asyncio.to_thread(process.wait, 10)
        with pytest.raises(BlockingIOError):
            retry_handoff(directory, confirmation.id)
        assert ExecutionConfirmation.read(directory) == confirmation
        with pytest.raises(InstallationBusyError):
            with installation_access(updating=True, environment=plan.installation.environment):
                pytest.fail("Lost parent released the surviving child's lease")
        assert not (directory / "approval.json").exists()
    finally:
        pause.unlink(missing_ok=True)
        if process.poll() is None:
            process.kill()
        await asyncio.to_thread(process.wait, 10)

    def child_exited():
        try:
            with installation_access(updating=True, environment=plan.installation.environment):
                return True
        except InstallationBusyError:
            return False

    await wait_for(child_exited)
    assert not (directory / "approval.json").exists()
    assert inspect_environment(plan.installation.python).app_version == "0.3.4"
    await wait_worker(retry_handoff(directory, confirmation.id))
    assert JobStatus.read(directory).phase == Phase.SUCCEEDED


@pytest.mark.parametrize("refuse", [False, True, "unfinished"])
async def test_old_runtime_preflight_revalidates_before_shutdown(installation, tmp_path, monkeypatch, refuse):
    from nanobot import update_handoff

    plan, _, _, requests, transport = installation
    async with ReleaseFeed(tmp_path / "feed", transport=transport) as feed:
        directory = await prepare_job(plan, feed)
    events = []

    class ObservedFeed(ReleaseFeed):
        def __init__(self, cache_dir):
            super().__init__(cache_dir, transport=transport)

        async def revalidate(self, target):
            events.append("revalidate")
            assert target == plan.target
            if refuse is True:
                raise RuntimeError("private credential must not enter status")
            await super().revalidate(target)

        async def __aexit__(self, *_args):
            await super().__aexit__()
            events.append("closed")

    async def stop(path):
        assert path == directory
        assert events == ["revalidate", "closed"]
        assert JobStatus.read(directory).phase == Phase.STOPPING
        assert not (directory / "approval.json").exists()
        events.append("stop")

    monkeypatch.setattr(update_handoff, "ReleaseFeed", ObservedFeed)
    monkeypatch.setattr(update_handoff, "stop_reviewed_gateways", stop)
    # This test exercises release/stop ordering in the test interpreter. Real
    # frozen-child startup and lease ownership have separate native coverage.
    baseline = WorkerSpec.read(directory).baseline
    monkeypatch.setattr(update_handoff, "current_environment", lambda **kwargs: baseline)
    JobStatus(plan.id, Phase.CHECKING, 0, False, "Testing preflight", int(time.time())).save(directory)
    if refuse == "unfinished":
        from nanobot.data_access import data_access

        with data_access([tmp_path / "other-installation-data"], updating=True, job_id=str(uuid4())) as lease:
            lease.reserve()
    if refuse:
        with pytest.raises(RuntimeError):
            await asyncio.to_thread(update_handoff.prepare_handoff, directory)
        assert events == ["revalidate", "closed"]
        assert JobStatus.read(directory).phase == Phase.HANDOFF_FAILED
        assert "private credential" not in (directory / "status.json").read_text()
    else:
        await asyncio.to_thread(update_handoff.prepare_handoff, directory)
        assert events == ["revalidate", "closed", "stop"]
        assert requests[-1].endswith("/pypi/nanobot-ai/0.3.5/json")
    assert not (directory / "approval.json").exists()
    assert inspect_environment(plan.installation.python).app_version == "0.3.4"


@pytest.mark.parametrize("installation", ["restart"], indirect=True)
@pytest.mark.parametrize("standalone", [False, True])
async def test_installed_runtime_failure_repairs_handoff_without_reinstalling(installation, tmp_path, monkeypatch, standalone):
    plan, _, site, requests, transport = installation
    async with ReleaseFeed(tmp_path / "feed", transport=transport) as feed:
        directory = await prepare_job(plan, feed)
        failure = directory / "fail-restart"
        failure.touch()
        process = await start_job(directory, feed)
        assert await asyncio.to_thread(process.wait, 40) != 0
        status = JobStatus.read(directory)
        assert status.phase == Phase.RESTART_FAILED and status.attempt == 1
        assert status.mutation_started
        probe = read_record(directory / "handoff-probe.json")
        assert probe == {"version": "0.3.5", "package": str((site / "nanobot/__init__.py").resolve()),
                         "attempt": 1, "phase": "restarting"}
        assert inspect_environment(plan.installation.python).app_version == "0.3.5"
        backup = (directory / "backup/data.zip").read_bytes()
        record = (site / "nanobot_ai-0.3.5.dist-info/RECORD").read_bytes()
        with pytest.raises(InstallationBusyError):
            with installation_access(environment=plan.installation.environment):
                pytest.fail("Runtime failure released the installation fence")
        with pytest.raises(InstallationBusyError):
            with data_access([plan.profiles[0].receipt.config]):
                pytest.fail("Runtime failure released the data reservation")

        async def offline(*_args, **_kwargs):
            pytest.fail("Already-installed handoff repair must not depend on a release feed")

        monkeypatch.setattr(feed, "revalidate", offline)
        requests.clear()
        with pytest.raises(ValueError, match="explicit repair"):
            await start_job(directory, feed)
        failure.unlink()
        if standalone:
            approval = read_record(directory / "approval.json")
            approval.update(created_at=int(time.time()) - 1800, expires_at=int(time.time()) - 900)
            write_record(directory / "approval.json", approval)
            result = await asyncio.to_thread(subprocess.run, [
                sys._base_executable, "-I", "-S", str(directory.parents[2] / "recover.py"), plan.id, "--repair", "--yes",
            ], capture_output=True, text=True, timeout=40)
            assert result.returncode == 0, result.stdout + result.stderr
        else:
            await wait_worker(await start_job(directory, feed, repair=True))
    assert not requests
    assert JobStatus.read(directory).phase == Phase.SUCCEEDED
    assert JobStatus.read(directory).attempt == 1
    assert read_record(directory / "handoff-probe.json")["phase"] == "restart_failed"
    assert (directory / "backup/data.zip").read_bytes() == backup
    assert (site / "nanobot_ai-0.3.5.dist-info/RECORD").read_bytes() == record
    with installation_access(environment=plan.installation.environment), data_access([plan.profiles[0].receipt.config]):
        pass


def test_update_record_size_is_bounded_before_replacement(tmp_path):
    path = tmp_path / "record.json"
    record = {"message": "配置实例"}
    write_record(path, record)
    original = path.read_bytes()
    assert read_record(path, max_bytes=len(original)) == record
    write_record(path, record, max_bytes=len(original))
    with pytest.raises(ValueError, match="size limit"):
        write_record(path, record, max_bytes=len(original) - 1)
    assert path.read_bytes() == original
    with pytest.raises(ValueError, match="size limit"):
        read_record(path, max_bytes=len(original) - 1)


@pytest.mark.asyncio
async def test_expanded_profile_request_is_readable_by_the_standalone_worker(installation, tmp_path):
    plan, _, _, _, transport = installation
    async with ReleaseFeed(tmp_path / "feed", transport=transport) as feed:
        directory = await prepare_job(plan, feed)
    spec = WorkerSpec.read(directory)
    sources = tuple(BackupSource(str(tmp_path / f"profile-{i}" / ("nested-" * 16) / "sessions")) for i in range(8192))
    expanded = replace(spec, backup_sources=sources)
    expanded.save(directory)
    assert (directory / "request.json").stat().st_size > 1024 * 1024
    assert WorkerSpec.read(directory) == expanded
    result = subprocess.run([spec.baseline.base_python, "-I", str(directory / "worker.pyz"), "--status", str(directory)],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["phase"] == "ready"
    spec.save(directory)
    legacy = read_record(directory / "request.json")
    legacy["schema_version"] = 1
    legacy.pop("backup_sources")
    write_record(directory / "request.json", legacy)
    with pytest.raises(ValueError, match="Unsupported update worker request"):
        WorkerSpec.read(directory)
    assert inspect_environment(plan.installation.python).app_version == "0.3.4"


@pytest.mark.asyncio
async def test_real_job_stages_then_installs_exact_app_and_dependency(installation, monkeypatch, tmp_path):
    plan, _, site, requests, transport = installation
    async with ReleaseFeed(tmp_path / "feed", transport=transport) as feed:
        directory = await prepare_job(plan, feed)
        assert inspect_environment(plan.installation.python).app_version == "0.3.4"
        assert not (directory / "approval.json").exists()
        spec = WorkerSpec.read(directory)
        # The detached archive may load the target runtime only after acquiring
        # its installation lease. Its frozen helpers must remain separate from
        # the real installed nanobot package, not supply an empty __init__.
        probe_command = [
            plan.installation.python, "-I", "-c", """
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from _nanobot_update.installation_lock import installation_access
from _nanobot_update.update_worker import JobStatus
with installation_access():
    import nanobot
    print(json.dumps([nanobot.__version__, nanobot.__file__, JobStatus.read(Path(sys.argv[2])).phase.value]))
""", str(directory / "worker.pyz"), str(directory),
        ]
        probe = subprocess.run(probe_command, check=True, capture_output=True, text=True, timeout=20)
        loaded_version, loaded_path, phase = json.loads(probe.stdout)
        assert loaded_version == "0.3.4" and phase == "ready"
        assert Path(loaded_path).resolve() == (site / "nanobot/__init__.py").resolve()
        assert {(item.name, item.version) for item in spec.wheels} == {
            ("nanobot-ai", "0.3.5"), ("fixture-update-dep", "2.0.0"),
        }
        assert await prepare_job(plan, feed) == directory
        unintended = tmp_path / "not-the-approved-environment"
        monkeypatch.setenv("PIP_TARGET", str(unintended))
        monkeypatch.setenv("PIP_PYTHON", str(unintended / "python"))
        await wait_worker(await start_job(directory, feed))
    status = JobStatus.read(directory)
    assert status.phase == Phase.INSTALLED and status.attempt == 1 and status.mutation_started
    assert "not yet verified" in status.message
    assert inspect_environment(plan.installation.python).app_version == "0.3.5"
    probe = subprocess.run(probe_command, check=True, capture_output=True, text=True, timeout=20)
    loaded_version, loaded_path, phase = json.loads(probe.stdout)
    assert loaded_version == "0.3.5" and phase == "installed"
    assert Path(loaded_path).resolve() == (site / "nanobot/__init__.py").resolve()
    assert (site / "nanobot/web/dist/index.html").read_text() == "verified UI 0.3.5"
    assert not unintended.exists()
    with ZipFile(directory / "backup/data.zip") as archive:
        entries = json.loads(archive.read("manifest.json"))["entries"]
        configs = [item for item in entries if item["path"] == plan.profiles[0].receipt.config]
        assert len(configs) == 1
        assert archive.read(configs[0]["member"]) == b'{"fixture":"private credential"}'
        assert not any(item["path"].endswith("private-project.py") for item in entries)
    assert not pending_update_path(plan.installation.environment).exists()
    write_record(pending_update_path(plan.installation.environment),
                 {"schema_version": 2, "job_id": plan.id, "version": "0.3.5"})
    result = subprocess.run([spec.baseline.base_python, "-I", str(directory / "worker.pyz"), str(directory)],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert JobStatus.read(directory).attempt == 1
    assert not pending_update_path(plan.installation.environment).exists()
    assert requests and all("/0.3.5/" in url or "/packages/" in url for url in requests)


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["site", "atexit"])
async def test_planning_probe_retains_lease_after_caller_loss(installation, tmp_path, stage):
    plan, _, site, _, _ = installation
    ready, release = tmp_path / "planning-ready", tmp_path / "planning-continue"
    caller_pid = tmp_path / "planning-caller-pid"
    hook = site / "hold_planning_probe.py"
    hook.write_text(
        "import atexit,os,time\nfrom pathlib import Path\n"
        "def hold():\n"
        f"    Path({str(ready)!r}).write_text(str(os.getpid()))\n"
        "    deadline=time.monotonic()+20\n"
        f"    while not Path({str(release)!r}).exists():\n"
        "        if time.monotonic()>deadline: raise SystemExit(99)\n"
        "        time.sleep(0.02)\n"
        + ("atexit.register(hold)\n" if stage == "atexit" else "hold()\n")
    )
    pth = site / "hold_planning_probe.pth"
    pth.write_text("import hold_planning_probe\n")
    caller = (
        "import os,sys\nfrom pathlib import Path\nfrom nanobot.update_plan import inspect_installation\n"
        f"sys.prefix={plan.installation.environment!r}\n"
        f"sys.executable={plan.installation.python!r}\n"
        f"Path({str(caller_pid)!r}).write_text(str(os.getpid()))\n"
        "inspect_installation()\n"
    )
    process = subprocess.Popen([sys.executable, "-c", caller], cwd=Path(__file__).resolve().parents[1],
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    try:
        for _ in range(200):
            if ready.exists():
                break
            if process.poll() is not None:
                pytest.fail(process.communicate()[1])
            await asyncio.sleep(0.025)
        assert ready.exists()
        child_pid = int(ready.read_text())
        # Kill the actual caller, not a Windows venv redirector. The planning
        # child must survive; killing the whole process tree would not prove it.
        os.kill(int(caller_pid.read_text()), signal.SIGTERM)
        process.wait(timeout=5)
        assert process_is_running(child_pid)
        with pytest.raises(InstallationBusyError):
            with installation_access(updating=True, environment=plan.installation.environment):
                pytest.fail("A live planning probe lost its lease with its caller")
    finally:
        release.touch()
        if process.poll() is None:
            process.wait(timeout=15)
        if process.stderr is not None:
            process.stderr.close()
        for _ in range(400):
            try:
                with installation_access(updating=True, environment=plan.installation.environment):
                    break
            except InstallationBusyError:
                await asyncio.sleep(0.025)
        else:
            pytest.fail("The planning probe did not release its own lease")
        pth.unlink()
        hook.unlink()
    assert inspect_environment(plan.installation.python).app_version == "0.3.4"
    assert not pending_update_path(plan.installation.environment).exists()
    assert not (installation_state_dir(plan.installation.environment) / "jobs").exists()


@pytest.mark.asyncio
async def test_changed_artifact_or_owner_receipt_never_installs(installation, tmp_path):
    plan, _, _, _, transport = installation
    async with ReleaseFeed(tmp_path / "feed", transport=transport) as feed:
        directory = await prepare_job(plan, feed)
        app = directory / "wheels" / plan.target.artifact.filename
        original = app.read_bytes()
        app.write_bytes(original + b"changed")
        with pytest.raises(ValueError, match="size"):
            await start_job(directory, feed)
        assert not pending_update_path(plan.installation.environment).exists()
        app.write_bytes(original)
        receipt = Path(plan.installation.environment) / "pyvenv.cfg"
        receipt.write_text(receipt.read_text() + "\n# changed by another owner\n")
        with pytest.raises(ValueError, match="ownership"):
            await start_job(directory, feed)
    assert inspect_environment(plan.installation.python).app_version == "0.3.4"


@pytest.mark.asyncio
async def test_stale_plan_is_rejected_before_staging(installation, tmp_path):
    plan, _, _, requests, transport = installation
    receipt = Path(plan.installation.environment) / "pyvenv.cfg"
    receipt.write_text(receipt.read_text() + "\n# changed\n")
    async with ReleaseFeed(tmp_path / "feed", transport=transport) as feed:
        with pytest.raises(ValueError, match="changed since"):
            await prepare_job(plan, feed)
    assert not requests


@pytest.mark.asyncio
async def test_worker_survives_coordinator_loss_without_unlocking_live_pip(installation, tmp_path):
    plan, _, site, _, transport = installation
    async with ReleaseFeed(tmp_path / "feed", transport=transport) as feed:
        directory = await prepare_job(plan, feed)
        ready, release = tmp_path / "pip-ready", tmp_path / "pip-continue"
        pip_entry = site / "pip/__main__.py"
        original = pip_entry.read_text()
        wrapper = (
            f"from pathlib import Path\nimport os,time\nPath({str(ready)!r}).write_text(str(os.getpid()))\n"
            f"deadline=time.monotonic()+20\nwhile not Path({str(release)!r}).exists():\n"
            "    if time.monotonic()>deadline: raise SystemExit(99)\n    time.sleep(0.02)\n"
            f"exec(compile({original!r}, __file__, 'exec'))\n"
        )
        pip_entry.write_text(wrapper)
        process = await start_job(directory, feed)
        try:
            for _ in range(200):
                if ready.exists():
                    break
                assert process.poll() is None, JobStatus.read(directory)
                await asyncio.sleep(0.025)
            assert ready.exists()
            process.kill()
            process.wait(timeout=10)
            assert JobStatus.read(directory).phase == Phase.INSTALLING
            with pytest.raises(InstallationBusyError):
                with installation_access(updating=True, environment=plan.installation.environment):
                    pytest.fail("Live pip lost its installation lease with the coordinator")
            with pytest.raises(InstallationBusyError, match="data is in use"):
                with data_access([Path(plan.profiles[0].receipt.data_dir) / "sessions"]):
                    pytest.fail("Live pip lost its data lease with the coordinator")
            with pytest.raises(InstallationBusyError):
                await start_job(directory, feed, repair=True)
        finally:
            release.touch()
            if process.poll() is None:
                process.wait(timeout=30)
        for _ in range(400):
            try:
                with installation_access(updating=True, environment=plan.installation.environment):
                    break
            except InstallationBusyError:
                await asyncio.sleep(0.025)
        else:
            pytest.fail("Pip did not release its lease")
        assert inspect_environment(plan.installation.python).app_version == "0.3.5"
        with pytest.raises(InstallationBusyError, match="reserved"):
            with data_access([Path(plan.profiles[0].receipt.data_dir) / "sessions"]):
                pytest.fail("Pip exit lifted the interrupted coordinator's data reservation")
        backup = (directory / "backup/data.zip").read_bytes()
        Path(plan.profiles[0].receipt.config).write_text('{"fixture":"changed after install"}')
        pip_entry.write_text(original)
        retained = directory / "retained-original-backup"
        (directory / "backup").rename(retained)
        refused = await start_job(directory, feed, repair=True)
        assert await asyncio.to_thread(refused.wait, 30) != 0
        assert JobStatus.read(directory).mutation_started
        assert JobStatus.read(directory).attempt == 1
        assert "original pre-update backup is missing" in JobStatus.read(directory).message
        assert not (directory / "backup").exists()
        retained.rename(directory / "backup")
        (site / "nanobot/web/dist/index.html").unlink()
        with pytest.raises(ValueError, match="explicit repair"):
            await start_job(directory, feed)
        await wait_worker(await start_job(directory, feed, repair=True))
        assert (directory / "backup/data.zip").read_bytes() == backup
    assert JobStatus.read(directory).attempt == 2
    assert JobStatus.read(directory).phase == Phase.INSTALLED
    assert (site / "nanobot/web/dist/index.html").read_text() == "verified UI 0.3.5"
    with data_access([Path(plan.profiles[0].receipt.data_dir) / "sessions"]):
        pass


@pytest.mark.asyncio
async def test_other_installation_writer_refuses_job_before_approval_or_backup(installation, tmp_path):
    plan, _, _, _, transport = installation
    async with ReleaseFeed(tmp_path / "feed", transport=transport) as feed:
        directory = await prepare_job(plan, feed)
        with data_access([Path(plan.profiles[0].receipt.workspace) / "sessions"]):
            with pytest.raises(InstallationBusyError, match="data is in use"):
                await start_job(directory, feed)
        assert not (directory / "approval.json").exists()
        assert not (directory / "backup").exists()
        assert JobStatus.read(directory).phase == Phase.READY
        assert inspect_environment(plan.installation.python).app_version == "0.3.4"
        await wait_worker(await start_job(directory, feed))
        assert JobStatus.read(directory).phase == Phase.INSTALLED


@pytest.mark.asyncio
async def test_cancel_interrupted_handoff_releases_data_without_installing(installation, tmp_path, monkeypatch):
    from nanobot import update_jobs

    plan, _, _, _, transport = installation
    ready = tmp_path / "coordinator-ready"
    original_popen = subprocess.Popen
    wrapper = """
import sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from _nanobot_update import update_worker
original_run = update_worker.subprocess.run
def run(command, *args, **kwargs):
    if '--install' in command:
        Path(sys.argv[3]).write_text('ready')
        time.sleep(15)
        raise RuntimeError('Handoff test deadline exceeded')
    return original_run(command, *args, **kwargs)
update_worker.subprocess.run = run
update_worker.run_job(Path(sys.argv[2]))
"""

    def launch(command, **kwargs):
        if len(command) == 5 and str(command[3]).endswith("worker.pyz"):
            command = [command[0], "-I", "-S", "-c", wrapper, command[3], command[4], str(ready)]
        return original_popen(command, **kwargs)

    async with ReleaseFeed(tmp_path / "feed", transport=transport) as feed:
        directory = await prepare_job(plan, feed)
        monkeypatch.setattr(update_jobs.subprocess, "Popen", launch)
        process = await start_job(directory, feed)
        try:
            for _ in range(200):
                if ready.exists():
                    break
                assert process.poll() is None, JobStatus.read(directory)
                await asyncio.sleep(0.025)
            assert ready.exists()
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=10)
        status = JobStatus.read(directory)
        assert status.phase == Phase.BACKING_UP and not status.mutation_started
        assert inspect_environment(plan.installation.python).app_version == "0.3.4"
        store = Path(plan.profiles[0].receipt.data_dir) / "sessions"
        with pytest.raises(InstallationBusyError, match="reserved"):
            with data_access([store]):
                pytest.fail("A dead coordinator lost its maintenance reservation")
        cancel_job(directory)
        assert JobStatus.read(directory).phase == Phase.CANCELLED
        assert not pending_update_path(plan.installation.environment).exists()
        with data_access([store]):
            pass
        with pytest.raises(ValueError, match="already finished"):
            await start_job(directory, feed)


@pytest.mark.asyncio
async def test_prepared_worker_has_no_execution_authority(installation, tmp_path):
    plan, _, _, _, transport = installation
    async with ReleaseFeed(tmp_path / "feed", transport=transport) as feed:
        with pytest.raises(ValueError, match="confirmed extras"):
            await prepare_job(plan.model_copy(update={"id": str(uuid4()), "extras": ["not-provided"]}), feed)
        directory = await prepare_job(plan, feed)
    spec = WorkerSpec.read(directory)
    result = subprocess.run([spec.baseline.base_python, "-I", str(directory / "worker.pyz"), str(directory)],
                            capture_output=True, timeout=20)
    assert result.returncode != 0
    assert inspect_environment(plan.installation.python).app_version == "0.3.4"
    assert not pending_update_path(plan.installation.environment).exists()
    assert JobStatus.read(directory).phase == Phase.FAILED
    assert not JobStatus.read(directory).mutation_started
    now = int(time.time())
    write_record(directory / "approval.json", {
        "plan_id": plan.id, "request_sha256": hashlib.sha256((directory / "request.json").read_bytes()).hexdigest(),
        "created_at": now - 1000, "expires_at": now - 100,
    })
    result = subprocess.run([spec.baseline.base_python, "-I", str(directory / "worker.pyz"), str(directory)],
                            capture_output=True, timeout=20)
    assert result.returncode != 0
    assert "expired" in JobStatus.read(directory).message
    cancel_job(directory)
    result = subprocess.run([spec.baseline.base_python, "-I", str(directory / "worker.pyz"), str(directory)],
                            capture_output=True, timeout=20)
    assert result.returncode != 0
    assert JobStatus.read(directory).phase == Phase.CANCELLED


@pytest.mark.asyncio
@pytest.mark.skipif(os.name == "nt", reason="Symlink creation requires separate Windows privileges")
@pytest.mark.parametrize("standalone", [False, True])
async def test_real_worker_refuses_installation_when_scoped_backup_fails(installation, tmp_path, standalone):
    plan, _, _, _, transport = installation
    async with ReleaseFeed(tmp_path / "feed", transport=transport) as feed:
        directory = await prepare_job(plan, feed)
        external = tmp_path / "external-secret"
        external.write_text("outside the approved stores")
        link = Path(plan.profiles[0].receipt.data_dir) / "sessions/external"
        link.symlink_to(external)
        process = await start_job(directory, feed)
        assert await asyncio.to_thread(process.wait, 30) != 0
        status = JobStatus.read(directory)
        assert status.phase == Phase.FAILED and not status.mutation_started
        assert "symlink" in status.message
        assert inspect_environment(plan.installation.python).app_version == "0.3.4"
        assert not pending_update_path(plan.installation.environment).exists()
        assert not (directory / "backup").exists()
        link.unlink()
        if standalone:
            approval = read_record(directory / "approval.json")
            approval.update(created_at=int(time.time()) - 1800, expires_at=int(time.time()) - 900)
            write_record(directory / "approval.json", approval)
            result = await asyncio.to_thread(subprocess.run, [
                sys._base_executable, "-I", "-S", str(directory.parents[2] / "recover.py"), plan.id, "--repair", "--yes",
            ], capture_output=True, text=True, timeout=40)
            assert result.returncode == 0, result.stdout + result.stderr
        else:
            await wait_worker(await start_job(directory, feed))
    assert JobStatus.read(directory).phase == Phase.INSTALLED


@pytest.mark.asyncio
@pytest.mark.parametrize("installation", [True], indirect=True)
async def test_broken_release_keeps_recovery_record_and_never_overwrites_an_external_upgrade(installation, tmp_path):
    plan, candidate, _, _, transport = installation
    async with ReleaseFeed(tmp_path / "feed", transport=transport) as feed:
        directory = await prepare_job(plan, feed)
        process = await start_job(directory, feed)
        assert await asyncio.to_thread(process.wait, 40) != 0
        state = JobStatus.read(directory)
        assert state.phase == Phase.FAILED and state.mutation_started
        assert "does not import" in state.message
        assert pending_update_path(plan.installation.environment).exists()
        spec = WorkerSpec.read(directory)
        result = subprocess.run([spec.baseline.base_python, "-I", str(directory / "worker.pyz"), "--status", str(directory)],
                                capture_output=True, text=True, timeout=20)
        assert result.returncode == 0
        assert json.loads(result.stdout)["phase"] == "failed"
        with pytest.raises(ValueError, match="not cancellation"):
            cancel_job(directory)
        newer = wheel(candidate.parent, "nanobot-ai", "0.3.6", requires=["fixture-update-dep>=2.0.0"])
        subprocess.run([plan.installation.python, "-I", "-m", "pip", "install", "--disable-pip-version-check", str(newer)],
                       capture_output=True, check=True, timeout=30)
        with pytest.raises(ValueError, match="cannot overwrite"):
            await start_job(directory, feed, repair=True)
    assert inspect_environment(plan.installation.python).app_version == "0.3.6"


def test_program_copy_flushes_writable_handle_and_preserves_read_only_mode(tmp_path, monkeypatch):
    from nanobot.update_fallback import _copy_program_file

    source, destination = tmp_path / "license.txt", tmp_path / "copied-license.txt"
    source.write_bytes(b"Installed package license\n")
    source.chmod(0o444)
    fsync = os.fsync
    flushed = []
    def sync_writable(descriptor):
        # POSIX accepts fsync on read-only handles, but Windows rejects it.
        # A zero-byte write verifies the cross-platform handle requirement.
        os.write(descriptor, b"")
        fsync(descriptor)
        flushed.append(descriptor)
    monkeypatch.setattr(os, "fsync", sync_writable)
    assert _copy_program_file(str(source), str(destination)) == str(destination)
    assert len(flushed) == 1
    assert destination.read_bytes() == source.read_bytes()
    assert destination.stat().st_mode == source.stat().st_mode
    assert destination.stat().st_mtime_ns == source.stat().st_mtime_ns


@pytest.mark.parametrize("installation", ["handoff"], indirect=True)
async def test_job_recovery_capability_comes_from_its_saved_worker(managed_installation, tmp_path, monkeypatch):
    from nanobot.update_jobs import read_update_job

    plan, _, _, _, transport = managed_installation
    async with ReleaseFeed(tmp_path / "feed", transport=transport) as feed:
        directory = await prepare_job(plan, feed)
    monkeypatch.setattr(sys, "prefix", plan.installation.environment)
    assert read_update_job(plan.id).automatic_recovery is True
    # Schema 4 jobs prepared by older releases did not opt into supervision.
    # An eligible installation does not change those frozen jobs' capabilities.
    request = read_record(directory / "request.json")
    request.pop("automatic_recovery")
    write_record(directory / "request.json", request)
    assert read_update_job(plan.id).automatic_recovery is False
    (directory / "worker.pyz").unlink()
    assert read_update_job(plan.id).automatic_recovery is False, "Status must remain readable after damage"


@pytest.mark.parametrize("installation", ["handoff"], indirect=True)
async def test_stale_first_supervisor_cannot_take_new_confirmation(managed_installation, tmp_path, monkeypatch):
    from nanobot import update_jobs

    plan, _, _, _, transport = managed_installation
    async with ReleaseFeed(tmp_path / "feed", transport=transport) as feed:
        directory = await prepare_job(plan, feed)
    spec = WorkerSpec.read(directory)
    assert spec.automatic_recovery
    with monkeypatch.context() as patch:
        patch.setattr(update_jobs, "_spawn_worker", lambda *args, **kwargs: None)
        start_handoff(directory, once=True)
        previous = ExecutionConfirmation.read(directory)
        assert previous is not None
        retry_handoff(directory, previous.id)
    current = ExecutionConfirmation.read(directory)
    assert current is not None and current.id != previous.id
    before = JobStatus.read(directory)
    approval = (directory / "handoff-approval.json").read_bytes()
    command = [spec.baseline.base_python, "-I", "-S", str(directory / "worker.pyz"),
               "--supervise", str(directory), "--confirmed-handoff", str(directory)]
    stale = await asyncio.to_thread(subprocess.run, [*command, previous.id], capture_output=True, timeout=40)
    assert not (directory / "supervision.json").exists(), stale.stderr.decode()
    assert stale.returncode != 0
    assert JobStatus.read(directory) == before
    assert ExecutionConfirmation.read(directory) == current
    assert (directory / "handoff-approval.json").read_bytes() == approval
    assert not (directory / "confirmation-claimed.json").exists()
    assert not (directory / "preflight-entered.json").exists()
    assert not (directory / "approval.json").exists()
    assert not (installation_state_dir(spec.baseline.environment) / "stop.json").exists()
    # B retains its first supervision budget and completes the explicit retry.
    # This path performs a real backup, pip install, restart and snapshot cleanup.
    # Parallel Windows runners can exceed the stale-launcher's 40s rejection budget.
    try:
        completed = await asyncio.to_thread(subprocess.run, [*command, current.id], capture_output=True, timeout=120)
    except subprocess.TimeoutExpired:
        # Identify the blocked phase without exposing the confirmation nonce or
        # making a slow snapshot indistinguishable from a handoff deadlock.
        status = JobStatus.read(directory)
        progress = {"phase": status.phase.value, "attempt": status.attempt,
                    "mutation_started": status.mutation_started, "message": status.message,
                    "snapshot_complete": (directory / "program-backup.json").exists(),
                    "activation_complete": (directory / "activation.json").exists()}
        pytest.fail(f"Confirmed supervisor exceeded 120s: {progress}", pytrace=False)
    assert completed.returncode == 0, completed.stderr.decode()
    assert read_record(directory / "supervision.json")["confirmation_id"] == current.id
    assert JobStatus.read(directory).phase == Phase.SUCCEEDED
    assert JobStatus.read(directory).attempt == 1
    assert inspect_environment(plan.installation.python).app_version == plan.target.version
    assert not pending_update_path(spec.baseline.environment).exists()
    with file_access(installation_state_dir(spec.baseline.environment) / "supervisor.lock", exclusive=True):
        pass


@pytest.mark.parametrize("installation", ["handoff"], indirect=True)
@pytest.mark.parametrize("restarting", [False, True])
async def test_service_restore_keeps_confirmation_identity_after_expiry(managed_installation, tmp_path, monkeypatch, restarting):
    from nanobot import update_jobs, update_worker
    from nanobot.update_fallback import restore_service

    plan, _, _, _, transport = managed_installation
    async with ReleaseFeed(tmp_path / "feed", transport=transport) as feed:
        directory = await prepare_job(plan, feed)
    monkeypatch.setattr(update_jobs, "_spawn_worker", lambda *args, **kwargs: None)
    start_handoff(directory, once=True)
    previous = ExecutionConfirmation.read(directory)
    assert previous is not None
    retry_handoff(directory, previous.id)
    current = ExecutionConfirmation.read(directory)
    assert current is not None
    now = int(time.time())
    current = replace(current, created_at=now - 1800, expires_at=now - 900)
    current.save(directory)
    approval = read_record(directory / "handoff-approval.json")
    approval.update(created_at=current.created_at, expires_at=current.expires_at)
    write_record(directory / "handoff-approval.json", approval)
    if restarting:
        write_record(directory / "restoration.json", {"plan_id": plan.id, "state": "restarting"})
        JobStatus(plan.id, Phase.RESTART_FAILED, 0, False, "Interrupted original-service restart", now).save(directory)
    before = JobStatus.read(directory)
    restarts = []
    monkeypatch.setattr(update_worker, "restart_runtime", lambda path, spec: restarts.append(path))
    with pytest.raises(ValueError, match="replaced or revoked"):
        restore_service(directory, confirmation_id=previous.id)
    assert JobStatus.read(directory) == before
    assert restarts == []
    restore_service(directory, confirmation_id=current.id)
    assert restarts == ([directory] if restarting else [])
    assert JobStatus.read(directory).phase == (Phase.RESTART_FAILED if restarting else Phase.HANDOFF_FAILED)
    assert inspect_environment(plan.installation.python).app_version == plan.installation.installed_version


@pytest.mark.parametrize("installation", [True], indirect=True)
@pytest.mark.parametrize("interrupted", [None, "rename", "journal", "metadata"])
async def test_program_restore_after_real_broken_install_preserves_user_data(installation, tmp_path, monkeypatch, interrupted):
    from nanobot.update_fallback import (
        preserve_program,
        require_unchanged_user_data,
        restore_program,
    )

    plan, _, _, _, transport = installation
    async with ReleaseFeed(tmp_path / "feed", transport=transport) as feed:
        directory = await prepare_job(plan, feed)
        spec = replace(WorkerSpec.read(directory), automatic_recovery=True)
        # No service participants in this fixture: exercise actual package and
        # dependency restoration separately from the packaged gateway E2E.
        with installation_access(updating=True, environment=spec.baseline.environment):
            preserve_program(directory, spec)
        process = await start_job(directory, feed)
        assert await asyncio.to_thread(process.wait, 40) != 0
        assert JobStatus.read(directory).mutation_started
        if interrupted == "metadata":
            from nanobot.update_fallback import _inspect_metadata
            from nanobot.update_worker import check_environment

            # A killed installer can leave dist-info after removing METADATA.
            # Same-target import probes fail, but restoring the saved program
            # must not depend on importing or parsing the damaged package.
            next(Path(spec.baseline.environment).rglob(f"nanobot_ai-{spec.version}.dist-info/METADATA")).unlink()
            check_environment(spec, repairing=True, current=_inspect_metadata(spec))
        config = Path(plan.profiles[0].receipt.config)
        chat = Path(plan.profiles[0].receipt.data_dir) / "sessions/chat.jsonl"
        before = config.read_bytes(), chat.read_bytes()
        with (installation_access(updating=True, environment=spec.baseline.environment),
              data_access((s.path for s in spec.backup_sources), updating=True, job_id=spec.plan_id)):
            require_unchanged_user_data(directory, spec)
            if interrupted in {"rename", "journal"}:
                from nanobot import update_worker

                rename = os.rename
                publish = update_worker.write_record
                def interrupt_switch(source, destination):
                    if Path(source).name == f".nanobot-original-{spec.plan_id}":
                        raise OSError("Injected interruption between program renames")
                    return rename(source, destination)
                def interrupt_publish(path, value, **kwargs):
                    if path.name == "restoration.json" and value.get("state") == "restarting":
                        raise OSError("Injected interruption after program switch")
                    return publish(path, value, **kwargs)
                with monkeypatch.context() as patch:
                    if interrupted == "rename":
                        patch.setattr(os, "rename", interrupt_switch)
                    else:
                        patch.setattr(update_worker, "write_record", interrupt_publish)
                    with pytest.raises(OSError, match="Injected interruption"):
                        restore_program(directory, spec)
                assert Path(spec.baseline.environment).exists() is (interrupted == "journal")
                assert read_record(directory / "restoration.json")["state"] == "restoring"
            restore_program(directory, spec)
            assert read_record(directory / "restoration.json")["state"] == "restarting"
        restored = inspect_environment(plan.installation.python)
        assert restored.app_version == spec.baseline.app_version
        assert restored.versions == spec.baseline.versions
        assert (config.read_bytes(), chat.read_bytes()) == before
        chat.write_bytes(before[1] + b'{"content":"new message"}\n')
        with pytest.raises(ValueError, match="User data changed"):
            require_unchanged_user_data(directory, spec)
        assert chat.read_bytes().endswith(b'{"content":"new message"}\n')


@pytest.mark.parametrize(("outcome", "confirmed"), [
    ("repaired", False), ("restored", False), ("unsafe", False), ("restored", True),
])
async def test_supervisor_has_one_repair_budget_and_replays_transient_restore(installation, tmp_path, monkeypatch, outcome, confirmed):
    from nanobot import update_fallback

    plan, _, _, _, transport = installation
    async with ReleaseFeed(tmp_path / "feed", transport=transport) as feed:
        directory = await prepare_job(plan, feed)
    spec = replace(WorkerSpec.read(directory), automatic_recovery=True,
                   restart_profiles=(plan.profiles[0].receipt.id,))
    monkeypatch.setattr(WorkerSpec, "read", classmethod(lambda cls, directory: spec))
    calls = []
    restored = []
    arguments = ["--handoff", str(directory)]
    confirmation_id = uuid4().hex if confirmed else None
    now = int(time.time())
    if confirmation_id is not None:
        digest = hashlib.sha256((directory / "request.json").read_bytes()).hexdigest()
        ExecutionConfirmation(confirmation_id, plan.id, digest, now, now + 900).save(directory)
        write_record(directory / "handoff-approval.json", {
            "plan_id": plan.id, "request_sha256": digest, "confirmation_id": confirmation_id,
            "created_at": now, "expires_at": now + 900,
        })
        arguments = ["--confirmed-handoff", str(directory), confirmation_id]
    def child(command, **kwargs):
        calls.append(command)
        if len(calls) == 1:
            if confirmed:
                monkeypatch.setattr(update_fallback.time, "time", lambda: now + 901)
            write_record(directory / "approval.json", {"admitted": True})
            phase = Phase.INSTALLING
        else:
            assert command[-2:] == ["--recover", str(directory)]
            phase = Phase.SUCCEEDED if outcome == "repaired" else Phase.FAILED
        JobStatus(spec.plan_id, phase, len(calls), True, "Injected execution result", int(time.time())).save(directory)
        return subprocess.CompletedProcess(command, 91 if len(calls) == 1 else 0)
    def restore(path, *, confirmation_id=None):
        assert confirmation_id == (ExecutionConfirmation.read(directory).id if confirmed else None)
        restored.append(path)
        if outcome == "unsafe":
            raise ValueError("User data changed")
        if len(restored) == 1:
            raise OSError("Transient rename failure")
        JobStatus(spec.plan_id, Phase.RESTORED, 2, True, "Restored", int(time.time())).save(directory)
    monkeypatch.setattr(update_fallback.subprocess, "run", child)
    monkeypatch.setattr(update_fallback, "restore_service", restore)
    update_fallback.supervise(directory, arguments)
    assert len(calls) == 2
    assert len(restored) == {"repaired": 0, "restored": 2, "unsafe": 1}[outcome]
    if outcome == "unsafe":
        assert read_record(directory / "supervision.json")["state"] == "needs_attention"
    update_fallback.supervise(directory, arguments)
    assert len(calls) == 2, "A duplicate launch cannot acquire another recovery budget"


async def test_service_restore_refuses_an_activated_candidate(installation, tmp_path):
    from nanobot.update_fallback import restore_service

    plan, _, _, _, transport = installation
    async with ReleaseFeed(tmp_path / "feed", transport=transport) as feed:
        directory = await prepare_job(plan, feed)
    before = inspect_environment(plan.installation.python)
    write_record(directory / "activation.json", {"plan_id": plan.id})
    JobStatus(plan.id, Phase.RESTART_FAILED, 1, True, "Lost readiness after activation", int(time.time())).save(directory)
    with pytest.raises(ValueError, match="activated"):
        restore_service(directory)
    assert inspect_environment(plan.installation.python) == before
    assert not (directory / "restoration.json").exists()


async def test_supervisor_finishes_refused_stop_without_waiting_for_live_gateway(installation, tmp_path, monkeypatch):
    from nanobot import update_fallback

    plan, _, _, _, transport = installation
    async with ReleaseFeed(tmp_path / "feed", transport=transport) as feed:
        directory = await prepare_job(plan, feed)
    spec = replace(WorkerSpec.read(directory), automatic_recovery=True,
                   restart_profiles=(plan.profiles[0].receipt.id,))
    monkeypatch.setattr(WorkerSpec, "read", classmethod(lambda cls, directory: spec))
    def refused(command, **kwargs):
        JobStatus(spec.plan_id, Phase.HANDOFF_FAILED, 0, False, "Gateway is busy", int(time.time())).save(directory)
        write_record(installation_state_dir(spec.baseline.environment) / "stop.json",
                     {"plan_id": spec.plan_id, "phase": "abort"})
        return subprocess.CompletedProcess(command, 1)
    monkeypatch.setattr(update_fallback.subprocess, "run", refused)
    def must_not_recover(*args, **kwargs):
        raise AssertionError("A refused stop must not wait for or restore the still-running gateway")
    monkeypatch.setattr(update_fallback, "restore_service", must_not_recover)
    with installation_access(environment=spec.baseline.environment):
        monkeypatch.setattr(update_fallback.time, "sleep", must_not_recover)
        update_fallback.supervise(directory, ["--handoff", str(directory)])
    assert JobStatus.read(directory).phase == Phase.HANDOFF_FAILED
    assert not (directory / "approval.json").exists()


@pytest.mark.parametrize("installation", ["restart"], indirect=True)
async def test_service_restore_completes_reservation_after_interrupted_journal(installation, tmp_path, monkeypatch):
    from nanobot import update_worker
    from nanobot.update_fallback import restore_service

    plan, _, _, _, transport = installation
    async with ReleaseFeed(tmp_path / "feed", transport=transport) as feed:
        directory = await prepare_job(plan, feed)
    spec = WorkerSpec.read(directory)
    root = installation_state_dir(spec.baseline.environment)
    JobStatus(plan.id, Phase.FAILED, 0, False, "Backup failure", int(time.time())).save(directory)
    write_record(directory / "handoff-approval.json", {
        "plan_id": spec.plan_id, "request_sha256": hashlib.sha256((directory / "request.json").read_bytes()).hexdigest(),
        "created_at": int(time.time()), "expires_at": int(time.time()) + 900,
    })
    write_record(root / "stop.json", {"plan_id": plan.id, "phase": "stopped"})
    write_record(directory / "restoration.json", {"plan_id": plan.id, "state": "restarting"})
    restarts = []
    def restart(path, request):
        assert JobStatus.read(path).phase == Phase.RESTARTING
        assert read_record(pending_update_path(request.baseline.environment))["version"] == request.baseline.app_version
        restarts.append(path)
    monkeypatch.setattr(update_worker, "restart_runtime", restart)
    restore_service(directory)
    assert restarts == [directory]


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["baseline", "dependencies", "final-probe"])
async def test_cancelled_preparation_keeps_lease_until_native_work_exits(installation, monkeypatch, tmp_path, stage):
    from nanobot import update_jobs

    plan, _, _, _, transport = installation
    entered, finish = threading.Event(), threading.Event()
    target = "_prepare_transaction" if stage == "dependencies" else "inspect_environment"
    original = getattr(update_jobs, target)
    calls = 0

    def held_preparation(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == (2 if stage == "final-probe" else 1):
            entered.set()
            assert finish.wait(20)
        return original(*args, **kwargs)

    monkeypatch.setattr(update_jobs, target, held_preparation)
    directory = installation_state_dir(plan.installation.environment) / "jobs" / plan.id
    async with ReleaseFeed(tmp_path / "feed", transport=transport) as feed:
        preparing = asyncio.create_task(prepare_job(plan, feed))
        try:
            assert await asyncio.to_thread(entered.wait, 10)
            assert JobStatus.read(directory).phase == Phase.PREPARING
            assert UpdatePlan.model_validate_json((directory / "plan.json").read_bytes()) == plan
            preparing.cancel()
            await asyncio.sleep(0)
            preparing.cancel()
            await asyncio.sleep(0)
            assert not preparing.done()
            assert JobStatus.read(directory).phase == Phase.PREPARING
            with pytest.raises(InstallationBusyError):
                with installation_access(updating=True, environment=plan.installation.environment):
                    pytest.fail("Native preparation lost its installation lease")
            with pytest.raises(BlockingIOError):
                await prepare_job(plan, feed)
        finally:
            finish.set()
            with pytest.raises(asyncio.CancelledError):
                await preparing
        assert JobStatus.read(directory).phase == Phase.PREPARATION_FAILED
        assert not (directory / "request.json").exists()
        assert not (directory / "approval.json").exists()
        directory = await prepare_job(plan, feed)
    assert JobStatus.read(directory).phase == Phase.READY
    assert inspect_environment(plan.installation.python).app_version == "0.3.4"


async def test_failed_download_retains_private_exact_job_for_retry(installation, monkeypatch, tmp_path):
    plan, _, _, _, transport = installation
    directory = installation_state_dir(plan.installation.environment) / "jobs" / plan.id

    async def unavailable(*args):
        raise httpx.ConnectError("https://user:secret@private.example")

    async with ReleaseFeed(tmp_path / "feed", transport=transport) as feed:
        with monkeypatch.context() as patch:
            patch.setattr(feed, "download", unavailable)
            with pytest.raises(httpx.ConnectError):
                await prepare_job(plan, feed)
        status = JobStatus.read(directory)
        assert status.phase == Phase.PREPARATION_FAILED and not status.mutation_started
        assert "secret" not in (directory / "status.json").read_text()
        saved = (directory / "plan.json").read_bytes()
        changed = plan.model_copy(update={"expires_at": plan.expires_at - 1})
        with pytest.raises(ValueError, match="another reviewed plan"):
            await prepare_job(changed, feed)
        assert (directory / "plan.json").read_bytes() == saved
        assert not (directory / "request.json").exists()
        assert await prepare_job(plan, feed) == directory
    assert JobStatus.read(directory).phase == Phase.READY
    assert inspect_environment(plan.installation.python).app_version == "0.3.4"


async def test_release_approval_refusal_preserves_original_installation(installation, tmp_path, monkeypatch):
    plan, _, _, _, transport = installation
    before = inspect_environment(plan.installation.python)
    monkeypatch.setattr(ReleaseFeed, "_authorize", AsyncMock(side_effect=ValueError("Unapproved release")))
    async with ReleaseFeed(tmp_path / "feed", transport=transport) as feed:
        with pytest.raises(ValueError, match="Unapproved release"):
            await prepare_job(plan, feed)
    directory = installation_state_dir(plan.installation.environment) / "jobs" / plan.id
    assert not (directory / "request.json").exists()
    assert not (directory / "wheels").exists()
    assert inspect_environment(plan.installation.python) == before


def _preparer_script(plan: UpdatePlan, candidate: Path, cache: Path, hook: str) -> str:
    source = Path(__file__).resolve().parents[1]
    return f"""
import asyncio, os, sys
from pathlib import Path
sys.path.insert(0, {str(source)!r})
import httpx
from nanobot import update_jobs, update_worker
from nanobot.release_feed import ReleaseFeed
from nanobot.update_plan import UpdatePlan
from nanobot.releases import release_filenames
async def private_fixture_approval(self, target):
    # Unsigned lifecycle fixture; public publication authority is tested separately.
    pass
ReleaseFeed._authorize = private_fixture_approval
plan = UpdatePlan.model_validate_json({plan.model_dump_json()!r})
{hook}
def response(request):
    if request.url.host == 'files.pythonhosted.org':
        return httpx.Response(200, content=Path({str(candidate)!r}).read_bytes())
    assert request.url.path == '/pypi/nanobot-ai/0.3.5/json'
    files = [dict(filename=name, size=plan.target.artifact.size if name == plan.target.artifact.filename else 1,
                  url='https://files.pythonhosted.org/packages/' + name, yanked=False,
                  digests=dict(sha256=plan.target.artifact.sha256 if name == plan.target.artifact.filename else 'a' * 64))
             for name in release_filenames(plan.target.version) if name.endswith(('.whl', '.tar.gz'))]
    return httpx.Response(200, json=dict(info=dict(name='nanobot-ai', version=plan.target.version,
                                                  requires_python='>=3.11'), urls=files))
async def run():
    async with ReleaseFeed(Path({str(cache)!r}), transport=httpx.MockTransport(response)) as feed:
        await update_jobs.prepare_job(plan, feed)
asyncio.run(run())
"""


async def test_abrupt_preparer_exit_does_not_authorize_staging_reuse(installation, tmp_path):
    plan, candidate, _, _, transport = installation
    directory = installation_state_dir(plan.installation.environment) / "jobs" / plan.id
    script = _preparer_script(plan, candidate, tmp_path / "feed", "update_jobs._prepare_transaction = lambda *args: os._exit(0)")
    process = await asyncio.to_thread(subprocess.run, [sys.executable, "-I", "-c", script],
                                      capture_output=True, timeout=30)
    assert process.returncode == 0, process.stderr.decode()
    saved_status = (directory / "status.json").read_bytes()
    assert JobStatus.read(directory).phase == Phase.PREPARING
    async with ReleaseFeed(tmp_path / "retry-feed") as feed:
        with pytest.raises(ValueError, match="previous preparation did not settle"):
            await prepare_job(plan, feed)
    assert (directory / "status.json").read_bytes() == saved_status
    assert not (directory / "request.json").exists()
    assert not (directory / "approval.json").exists()
    assert inspect_environment(plan.installation.python).app_version == "0.3.4"
    assert settle_interrupted_preparation(directory).phase == Phase.PREPARATION_FAILED
    async with ReleaseFeed(tmp_path / "retry-feed", transport=transport) as feed:
        assert await prepare_job(plan, feed) == directory
    assert JobStatus.read(directory).phase == Phase.READY


@pytest.mark.parametrize("stage", ["probe", "pip"])
async def test_orphan_preparation_owns_lease_until_real_native_exit(installation, tmp_path, stage):
    plan, candidate, _, _, transport = installation
    root = installation_state_dir(plan.installation.environment)
    directory = root / "jobs" / plan.id
    ready, release = tmp_path / "native-ready", tmp_path / "native-release"
    hold = (
        "import os, time\nfrom pathlib import Path\n"
        f"Path({str(ready)!r}).write_text(str(os.getpid()))\n"
        "deadline=time.monotonic()+15\n"
        f"while not Path({str(release)!r}).exists():\n"
        "    if time.monotonic()>deadline: raise RuntimeError('Native test wait expired')\n"
        "    time.sleep(0.01)\n"
    )
    if stage == "pip":
        site = subprocess.check_output([plan.installation.python, "-I", "-c",
                                        "import sysconfig; print(sysconfig.get_path('purelib'))"], text=True).strip()
        launcher = Path(site) / "pip/__main__.py"
        original = launcher.read_text()
        launcher.write_text(hold + f"exec(compile({original!r}, __file__, 'exec'))\n")
        hook = ""
    else:
        hook = f"update_worker._PROBE = {hold!r} + update_worker._PROBE"
    script = _preparer_script(plan, candidate, tmp_path / "feed", hook)
    parent = subprocess.Popen([sys.executable, "-I", "-c", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        async with asyncio.timeout(12):
            while not ready.exists():
                assert parent.poll() is None, "Preparer exited before its native command started"
                await asyncio.sleep(0.01)
        prior = PreparationProcess.load(directory.resolve())
        parent.kill()
        await asyncio.to_thread(parent.wait, 10)
        # The runtime's Windows implementation uses a process handle, not signal 0.
        assert GatewayRuntime().process_is_running(int(ready.read_text()))
        with pytest.raises(InstallationBusyError):
            with installation_access(updating=True, environment=plan.installation.environment):
                pytest.fail("Parent death released a live preparation's runtime lease")
        with pytest.raises(BlockingIOError):
            settle_interrupted_preparation(directory)
        async with ReleaseFeed(tmp_path / "other-feed", transport=transport) as feed:
            with pytest.raises(BlockingIOError):
                await prepare_job(plan.model_copy(update={"id": str(uuid4())}), feed)
        assert not (directory / "request.json").exists()
        assert JobStatus.read(directory).phase == Phase.PREPARING
    finally:
        release.touch()
        if parent.poll() is None:
            parent.kill()
        await asyncio.to_thread(parent.wait, 10)
        async with asyncio.timeout(15):
            while True:
                try:
                    with file_access(root / "prepare-native.lock", exclusive=True):
                        break
                except BlockingIOError:
                    await asyncio.sleep(0.01)
        if stage == "pip":
            launcher.write_text(original)
    if stage == "pip":
        with file_access(root / "prepare.lock", exclusive=True), file_access(root / "prepare-native.lock", exclusive=True):
            prior.close()
    assert settle_interrupted_preparation(directory).phase == Phase.PREPARATION_FAILED
    assert not (directory / "approval.json").exists()
    marker = tmp_path / "late-child-must-not-run"
    with file_access(root / "prepare.lock", exclusive=True), file_access(root / "prepare-native.lock", exclusive=True):
        replacement = PreparationProcess.create(directory, plan.installation.environment)
    result = await asyncio.to_thread(prior.run, plan.installation.python,
                                     ["-c", f"from pathlib import Path; Path({str(marker)!r}).touch()"], timeout=15)
    assert result.returncode != 0 and not marker.exists()
    replacement.close()
    async with ReleaseFeed(tmp_path / "retry-feed", transport=transport) as feed:
        assert await prepare_job(plan, feed) == directory
    assert JobStatus.read(directory).phase == Phase.READY
    assert inspect_environment(plan.installation.python).app_version == "0.3.4"


@pytest.mark.skipif(os.name != "posix", reason="Checks actual POSIX flock ownership during Python site startup")
async def test_preparation_lease_covers_site_startup_and_exit_cleanup(installation, tmp_path):
    plan, _, _, _, transport = installation
    root = installation_state_dir(plan.installation.environment)
    site = subprocess.check_output([plan.installation.python, "-I", "-c",
                                    "import sysconfig; print(sysconfig.get_path('purelib'))"], text=True).strip()
    hook = Path(site) / "preparation_lease_test.pth"
    observed = tmp_path / "site-loaded-under-child-lease"
    exited = tmp_path / "exit-cleanup-under-child-lease"
    script = (
        "import atexit, fcntl, os\nfrom pathlib import Path\n"
        "def verify_lease():\n"
        f"    with open({str(root / 'prepare-native.lock')!r}, 'a+b') as lease:\n"
        "        try: fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
        "        except BlockingIOError: pass\n"
        "        else: os._exit(99)\n"
        "verify_lease()\n"
        f"Path({str(observed)!r}).touch()\n"
        "def verify_exit():\n"
        "    verify_lease()\n"
        f"    Path({str(exited)!r}).touch()\n"
        "atexit.register(verify_exit)\n"
    )
    hook.write_text(f"import builtins; builtins.exec({script!r}, {{}})\n")
    try:
        async with ReleaseFeed(tmp_path / "feed", transport=transport) as feed:
            directory = await prepare_job(plan, feed)
        assert JobStatus.read(directory).phase == Phase.READY
        assert observed.exists(), "Site startup was skipped instead of protected"
        assert exited.exists(), "Exit cleanup was skipped instead of protected"
    finally:
        hook.unlink()


@pytest.mark.skipif(os.name != "posix", reason="Checks actual flock ownership in site and atexit hooks")
@pytest.mark.parametrize("installation", ["handoff"], indirect=True)
@pytest.mark.parametrize("refuse", [False, True])
async def test_execution_leases_cover_site_and_atexit(installation, tmp_path, refuse):
    plan, _, site, _, transport = installation
    async with ReleaseFeed(tmp_path / "feed", transport=transport) as feed:
        directory = await prepare_job(plan, feed)
    root = installation_state_dir(plan.installation.environment)
    leases = {
        "--prepare-handoff": [str(root / "runtime.lock"), str(root / "handoff-child.lock")],
        "--inspect": [str(root / "runtime.lock"), str(root.parent / "data-locks/maintenance.lock")],
        "--install": [str(root / "runtime.lock"), str(root.parent / "data-locks/maintenance.lock")],
        "--verify": [str(root / "runtime.lock"), str(root.parent / "data-locks/maintenance.lock")],
        "--restart": [str(root / "runtime.lock")],
    }
    hook = site / "execution_lease_test.pth"
    observed = tmp_path / "execution-hooks"
    observed.mkdir()
    script = (
        "import atexit, fcntl, os, sys\nfrom pathlib import Path\n"
        f"leases = {leases!r}\n"
        "entry = sys.argv[1] if len(sys.argv) > 1 else ''\n"
        "if entry in leases:\n"
        "    def verify(stage):\n"
        "        for path in leases[entry]:\n"
        "            with open(path, 'a+b') as lease:\n"
        "                try: fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
        "                except BlockingIOError: pass\n"
        "                else: os._exit(99)\n"
        f"        (Path({str(observed)!r}) / (entry + '.' + stage)).touch()\n"
        "    verify('site')\n"
        "    atexit.register(verify, 'atexit')\n"
    )
    hook.write_text(f"import builtins; builtins.exec({script!r}, {{}})\n")
    if refuse:
        (directory / "refuse-preflight").touch()
    try:
        process = start_handoff(directory, once=True)
        assert process is not None
        code = await asyncio.to_thread(process.wait, 40)
        assert (code != 0) is refuse
        assert JobStatus.read(directory).phase == (Phase.HANDOFF_FAILED if refuse else Phase.SUCCEEDED)
        entries = ["--prepare-handoff"] if refuse else list(leases)
        assert {path.name for path in observed.iterdir()} == {
            entry + "." + stage for entry in entries for stage in ("site", "atexit")
        }
        with (installation_access(updating=True, environment=plan.installation.environment),
              data_access((source.path for source in WorkerSpec.read(directory).backup_sources), updating=True),
              file_access(root / "handoff-child.lock", exclusive=True)):
            pass
    finally:
        hook.unlink()


@pytest.mark.parametrize("stage", ["site", "atexit"])
async def test_admission_probe_keeps_its_leases_after_caller_loss(installation, tmp_path, stage):
    plan, _, site, _, transport = installation
    async with ReleaseFeed(tmp_path / "feed", transport=transport) as feed:
        directory = await prepare_job(plan, feed)
        ready, release = tmp_path / "inspection-ready", tmp_path / "inspection-release"
        hook = site / "inspection_lifetime_test.pth"
        action = "hold()" if stage == "site" else "atexit.register(hold)"
        script = (
            "import atexit, os, sys, time\nfrom pathlib import Path\n"
            "def hold():\n"
            f"    Path({str(ready)!r}).write_text(str(os.getpid()))\n"
            "    deadline = time.monotonic() + 20\n"
            f"    while not Path({str(release)!r}).exists():\n"
            "        if time.monotonic() > deadline: raise RuntimeError('Inspection wait expired')\n"
            "        time.sleep(0.01)\n"
            f"if '--inspect' in sys.argv: {action}\n"
        )
        hook.write_text(f"import builtins; builtins.exec({script!r}, {{}})\n")
        caller_pid = tmp_path / "caller-pid"
        caller = (
            "import os\nfrom pathlib import Path\n"
            f"Path({str(caller_pid)!r}).write_text(str(os.getpid()))\n"
            "import asyncio\n"
            "from nanobot.update_jobs import start_job\n"
            "class Feed:\n"
            "    async def revalidate(self, target): pass\n"
            f"asyncio.run(start_job(Path({str(directory)!r}), Feed()))\n"
        )
        process = subprocess.Popen([sys.executable, "-c", caller], cwd=Path(__file__).parents[1],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        def kill_caller():
            if process.poll() is None:
                # Windows venv python.exe is a redirector. Kill the actual
                # caller, not its launcher or the separately leased probe.
                if caller_pid.exists():
                    os.kill(int(caller_pid.read_text()), signal.SIGTERM if os.name == "nt" else signal.SIGKILL)
                else:
                    process.kill()
        try:
            async with asyncio.timeout(15):
                while not ready.exists():
                    assert process.poll() is None
                    await asyncio.sleep(0.01)
            assert int(caller_pid.read_text()) != int(ready.read_text())
            kill_caller()
            await asyncio.to_thread(process.wait, 10)
            assert GatewayRuntime().process_is_running(int(ready.read_text()))
            with pytest.raises(InstallationBusyError):
                with installation_access(updating=True, environment=plan.installation.environment):
                    pytest.fail("The inspection lost its installation lease with its caller")
            with pytest.raises(InstallationBusyError):
                with data_access([Path(plan.profiles[0].receipt.data_dir) / "sessions"]):
                    pytest.fail("The inspection lost its data lease with its caller")
            with pytest.raises(InstallationBusyError):
                await start_job(directory, feed)
            assert JobStatus.read(directory).phase == Phase.READY
            assert not (directory / "approval.json").exists()
            assert not pending_update_path(plan.installation.environment).exists()
        finally:
            release.touch()
            kill_caller()
            await asyncio.to_thread(process.wait, 10)
            async with asyncio.timeout(20):
                while True:
                    try:
                        with installation_access(updating=True, environment=plan.installation.environment):
                            break
                    except InstallationBusyError:
                        await asyncio.sleep(0.01)
            hook.unlink()
        await wait_worker(await start_job(directory, feed))
        assert JobStatus.read(directory).phase == Phase.INSTALLED


@pytest.mark.parametrize("stage", ["site", "dependencies", "atexit"])
async def test_verification_keeps_its_leases_after_coordinator_loss(installation, tmp_path, stage):
    plan, _, site, _, transport = installation
    ready, release = tmp_path / "verification-ready", tmp_path / "verification-release"
    hook = site / "verification_lifetime_test.pth"
    launcher = site / "pip/__main__.py"
    original = launcher.read_text()
    hold = (
        "import os, time\nfrom pathlib import Path\n"
        "def hold():\n"
        f"    Path({str(ready)!r}).write_text(str(os.getpid()))\n"
        "    deadline = time.monotonic() + 20\n"
        f"    while not Path({str(release)!r}).exists():\n"
        "        if time.monotonic() > deadline: raise RuntimeError('Verification wait expired')\n"
        "        time.sleep(0.01)\n"
    )
    async with ReleaseFeed(tmp_path / "feed", transport=transport) as feed:
        directory = await prepare_job(plan, feed)
        if stage == "dependencies":
            launcher.write_text(hold + "import sys\nif sys.argv[1:] == ['check']: hold()\n"
                                + f"exec(compile({original!r}, __file__, 'exec'))\n")
        else:
            action = "hold()" if stage == "site" else "atexit.register(hold)"
            script = hold + "import atexit, sys\n" + f"if '--verify' in sys.argv: {action}\n"
            hook.write_text(f"import builtins; builtins.exec({script!r}, {{}})\n")
        process = await start_job(directory, feed)
        try:
            async with asyncio.timeout(15):
                while not ready.exists():
                    assert process.poll() is None, JobStatus.read(directory)
                    await asyncio.sleep(0.01)
            assert JobStatus.read(directory).phase == Phase.VERIFYING
            process.kill()
            await asyncio.to_thread(process.wait, 10)
            assert GatewayRuntime().process_is_running(int(ready.read_text()))
            with pytest.raises(InstallationBusyError):
                with installation_access(updating=True, environment=plan.installation.environment):
                    pytest.fail("A live verification lost its installation lease")
            with pytest.raises(InstallationBusyError, match="data is in use"):
                with data_access([Path(plan.profiles[0].receipt.data_dir) / "sessions"]):
                    pytest.fail("A live verification lost its data lease")
            with pytest.raises(InstallationBusyError):
                await start_job(directory, feed, repair=True)
            assert JobStatus.read(directory).phase == Phase.VERIFYING
        finally:
            release.touch()
            if process.poll() is None:
                process.kill()
            await asyncio.to_thread(process.wait, 10)
            async with asyncio.timeout(20):
                while True:
                    try:
                        with installation_access(updating=True, environment=plan.installation.environment):
                            break
                    except InstallationBusyError:
                        await asyncio.sleep(0.01)
            hook.unlink(missing_ok=True)
            launcher.write_text(original)
        assert JobStatus.read(directory).phase == Phase.VERIFYING
        assert pending_update_path(plan.installation.environment).exists()
        backup = (directory / "backup/data.zip").read_bytes()
        await wait_worker(await start_job(directory, feed, repair=True))
        assert JobStatus.read(directory).phase == Phase.INSTALLED
        assert (directory / "backup/data.zip").read_bytes() == backup
        assert not pending_update_path(plan.installation.environment).exists()


async def test_verification_requires_its_own_completion_checkpoint(installation, tmp_path):
    plan, _, site, _, transport = installation
    async with ReleaseFeed(tmp_path / "feed", transport=transport) as feed:
        directory = await prepare_job(plan, feed)
        hook = site / "verification_exit_test.pth"
        write_record(directory / "verification.json", {"id": uuid4().hex})
        hook.write_text("import sys; sys.exit(0) if '--verify' in sys.argv else None\n")
        try:
            process = await start_job(directory, feed)
            assert await asyncio.to_thread(process.wait, 40) != 0
            status = JobStatus.read(directory)
            assert status.phase == Phase.FAILED and status.mutation_started
            assert "verification did not finish" in status.message
            assert pending_update_path(plan.installation.environment).exists()
        finally:
            hook.unlink()


async def test_installed_cleanup_recovery_reverifies_without_reinstalling(installation, tmp_path, monkeypatch):
    plan, _, site, _, transport = installation
    original_popen = subprocess.Popen
    wrapper = """
import os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from _nanobot_update import update_worker
original_save = update_worker.JobStatus.save
def save(status, directory):
    original_save(status, directory)
    if status.phase == update_worker.Phase.INSTALLED:
        os._exit(91)
update_worker.JobStatus.save = save
update_worker.run_job(Path(sys.argv[2]))
"""

    def launch(command, **kwargs):
        if len(command) == 5 and str(command[3]).endswith("worker.pyz"):
            command = [command[0], "-I", "-S", "-c", wrapper, command[3], command[4]]
        return original_popen(command, **kwargs)

    async with ReleaseFeed(tmp_path / "feed", transport=transport) as feed:
        directory = await prepare_job(plan, feed)
        with monkeypatch.context() as patch:
            patch.setattr(subprocess, "Popen", launch)
            process = await start_job(directory, feed)
            assert await asyncio.to_thread(process.wait, 40) == 91
    before = JobStatus.read(directory)
    assert before.phase == Phase.INSTALLED and before.attempt == 1
    pending = pending_update_path(plan.installation.environment)
    assert pending.exists()
    checkpoint = (directory / "verification.json").read_bytes()
    record = site / "nanobot_ai-0.3.5.dist-info/RECORD"
    record_time = record.stat().st_mtime_ns
    backup = (directory / "backup/data.zip").read_bytes()
    spec = WorkerSpec.read(directory)
    recovery = subprocess.Popen([spec.baseline.base_python, "-I", str(directory / "worker.pyz"), str(directory)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    await wait_worker(recovery)
    assert JobStatus.read(directory) == before
    assert (directory / "verification.json").read_bytes() != checkpoint
    assert record.stat().st_mtime_ns == record_time
    assert (directory / "backup/data.zip").read_bytes() == backup
    assert not pending.exists()
    with data_access([Path(plan.profiles[0].receipt.data_dir) / "sessions"]):
        pass
