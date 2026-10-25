"""Real uv/frozen-worker transactions; synthetic packages and a private HTTP index.

These prove manager ownership and prepared-input behavior, not gateway migration,
UI acceptance, public distribution or native Windows support.
"""

import asyncio
import hashlib
import os
import shutil
import subprocess
import sys
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4
from zipfile import ZipFile

import httpx
import pytest
from packaging.tags import sys_tags
from test_update_jobs import _preparer_script, wheel

import nanobot.update_jobs as jobs
from nanobot.installation_lock import (
    InstallationBusyError,
    file_access,
    installation_access,
    installation_state_dir,
)
from nanobot.release_feed import ReleaseFeed, ReleaseTarget
from nanobot.releases import PLATFORMS, ReleaseArtifact, release_filenames
from nanobot.update_manager import read_manager_policy
from nanobot.update_plan import InstallationSnapshot, UpdatePlan
from nanobot.update_stop import stop_reviewed_gateways
from nanobot.update_uv import UV_TRANSACTION_VERSION, cache_digest, uv_environment
from nanobot.update_worker import JobStatus, Phase, WorkerSpec, inspect_environment

pytestmark = pytest.mark.skipif(os.name != "posix" or not shutil.which("uv"), reason="Native POSIX uv required")

_FAIL_VERIFICATION_ONCE = """
from _nanobot_update import update_worker
original_verify = update_worker._verify
def verify(spec, directory):
    marker = directory / 'fail-verification'
    if marker.exists():
        marker.unlink()
        raise ValueError('Controlled post-install verification failure')
    original_verify(spec, directory)
update_worker._verify = verify
"""


class IndexHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


@pytest.fixture
def uv_installation(tmp_path, monkeypatch):
    # Private synthetic package-manager fixtures, not release-signature proof.
    monkeypatch.setattr(ReleaseFeed, "_authorize", AsyncMock())
    from nanobot import update_process

    manager_version = subprocess.check_output([shutil.which("uv"), "--version"], text=True, timeout=10)
    if manager_version.split()[:2] != ["uv", UV_TRANSACTION_VERSION]:
        pytest.skip(f"Native transaction integration requires uv {UV_TRANSACTION_VERSION}")
    tmp_path = tmp_path.resolve()
    account = tmp_path / "private account"
    account.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: account))
    # The read-only bootstrap has the same isolated account as frozen workers.
    monkeypatch.setattr(update_process, "_INSPECTION_BOOTSTRAP", (
        "from pathlib import Path\n"
        f"Path.home = classmethod(lambda cls: Path({str(account)!r}))\n"
    ) + update_process._INSPECTION_BOOTSTRAP)
    archive_worker = jobs._worker_archive

    def private_worker(path):
        # All worker entrypoints, including installer children, use a private
        # account. Do not change HOME or patch production transaction behavior.
        archive_worker(path)
        with ZipFile(path) as source:
            files = {item.filename: source.read(item) for item in source.infolist()}
        files["__main__.py"] = (
            "from pathlib import Path\n"
            f"Path.home = classmethod(lambda cls: Path({str(account)!r}))\n"
        ).encode() + _FAIL_VERIFICATION_ONCE.encode() + files["__main__.py"]
        with ZipFile(path, "w") as target:
            for name, content in files.items():
                target.writestr(name, content)
        return hashlib.sha256(path.read_bytes()).hexdigest()

    monkeypatch.setattr(jobs, "_worker_archive", private_worker)
    artifacts = tmp_path / "index"
    artifacts.mkdir()

    def index():
        for file in artifacts.glob("*.whl"):
            name = file.name.split("-")[0].replace("_", "-")
            page = artifacts / "simple" / name / "index.html"
            page.parent.mkdir(parents=True, exist_ok=True)
            links = artifacts.glob(file.name.split("-")[0] + "-*.whl")
            page.write_text("\n".join(f'<a href="../../{item.name}">{item.name}</a>' for item in links))

    wheel(artifacts, "fixture-feature", "1.0.0")
    wheel(artifacts, "fixture-injected", "1.0.0")
    wheel(artifacts, "fixture-obsolete", "1.0.0")
    wheel(artifacts, "nanobot-ai", "0.3.4", extras=["feature"], entrypoint=True,
          requires=['fixture-feature>=1; extra == "feature"', "fixture-obsolete==1.0.0"])
    index()
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(IndexHandler, directory=str(artifacts)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        tools, binaries = tmp_path / "tools", tmp_path / "bin"
        env = uv_environment(tools=tools, binaries=binaries, cache=tmp_path / "original cache")
        subprocess.run([
            shutil.which("uv"), "tool", "install", "--no-config", "--python", sys._base_executable,
            "--index-url", f"http://127.0.0.1:{server.server_port}/simple/",
            "--with", "fixture-injected==1.0.0", "nanobot-ai[feature]>=0.3.4,<0.4",
        ], env=env, check=True, capture_output=True, timeout=60)
        environment = tools / "nanobot-ai"
        python = str(environment / "bin/python")
        baseline = inspect_environment(python, uv=True)
        receipt = environment / "uv-receipt.toml"
        assert "no-build" not in receipt.read_text(), "Baseline must not already have staging's no-build option"
        package = subprocess.check_output([
            python, "-I", "-c", "import nanobot; print(nanobot.__file__)",
        ], text=True).strip()
        snapshot = InstallationSnapshot(
            environment=str(environment), python=python, installed_version="0.3.4", running_version="0.3.4",
            package_path=package, running_package=package, owner="uv",
            records={"pyvenv.cfg": baseline.receipt_sha, "uv-receipt.toml": baseline.manager_receipt_sha,
                     **baseline.app_records},
            manager=read_manager_policy(environment, "uv", baseline.manager_receipt_sha),
        )
        wheel(artifacts, "fixture-feature", "2.0.0")
        wheel(artifacts, "fixture-runtime", "2.0.0")
        platform = next(tag.platform for tag in sys_tags() if tag.platform in PLATFORMS.values())
        candidate = wheel(artifacts, "nanobot-ai", "0.3.5", platform=platform, extras=["feature"], entrypoint=True,
                          requires=['fixture-feature>=2; extra == "feature"', "fixture-runtime>=2"])
        wheel(artifacts, "nanobot-ai", "0.3.6", entrypoint=True)
        index()
        target = ReleaseTarget(version="0.3.5", source="pypi",
                               url=f"https://files.pythonhosted.org/packages/{candidate.name}",
                               artifact=ReleaseArtifact(filename=candidate.name, size=candidate.stat().st_size,
                                                        sha256=hashlib.sha256(candidate.read_bytes()).hexdigest()))
        now = int(time.time())
        plan = UpdatePlan(id=str(uuid4()), installation=snapshot, target=target, extras=["feature"],
                          channel="stable", created_at=now, expires_at=now + 900)

        def response(request):
            if request.url.host == "files.pythonhosted.org":
                assert request.url.path.endswith(candidate.name)
                return httpx.Response(200, content=candidate.read_bytes())
            assert request.url.path == "/pypi/nanobot-ai/0.3.5/json"
            files = []
            for filename in release_filenames("0.3.5"):
                if filename.endswith((".whl", ".tar.gz")):
                    selected = filename == candidate.name
                    files.append({"filename": filename, "size": target.artifact.size if selected else 1,
                                  "url": f"https://files.pythonhosted.org/packages/{filename}", "yanked": False,
                                  "digests": {"sha256": target.artifact.sha256 if selected else "a" * 64}})
            return httpx.Response(200, json={"info": {"name": "nanobot-ai", "version": "0.3.5", "requires_python": ">=3.11"}, "urls": files})

        yield plan, baseline, receipt, httpx.MockTransport(response), server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


@pytest.mark.parametrize("mode", ["install", "tamper", "repair", "external-policy"])
async def test_uv_prepared_job_preserves_owner_and_sealed_inputs(uv_installation, tmp_path, monkeypatch, mode):
    plan, before, receipt, transport, server = uv_installation
    original_receipt = receipt.read_bytes()
    async with ReleaseFeed(tmp_path / "feed", transport=transport) as feed:
        if mode == "external-policy":
            # A later user-level index/security policy cannot silently disappear
            # merely because this first implementation only froze the receipt.
            config_root = tmp_path / "user config"
            config = config_root / "uv/uv.toml"
            config.parent.mkdir(parents=True)
            config.write_text('exclude-newer = "2026-01-01T00:00:00Z"\n')
            monkeypatch.setenv("XDG_CONFIG_HOME", str(config_root))
            with pytest.raises(ValueError, match="External uv configuration"):
                await jobs.prepare_job(plan, feed)
            assert inspect_environment(plan.installation.python, uv=True) == before
            assert receipt.read_bytes() == original_receipt
            return
        directory = await jobs.prepare_job(plan, feed)
        spec = WorkerSpec.read(directory)
        assert spec.uv is not None
        assert inspect_environment(plan.installation.python, uv=True) == before
        assert receipt.read_bytes() == original_receipt
        # The selected app is not the newer index version, injected packages and
        # extras survive, and an obsolete dependency is removed by the owner.
        assert spec.uv.versions == {
            "nanobot-ai": "0.3.5", "fixture-feature": "2.0.0",
            "fixture-runtime": "2.0.0", "fixture-injected": "1.0.0",
        }
        cache = directory / spec.uv.cache
        server.shutdown()
        server.server_close()  # Dependencies must come entirely from prepared inputs.
        if mode == "tamper":
            (cache / "changed-after-preparation").write_text("not part of approved preparation")
            # Preflight can encounter cache changes after the initial worker
            # check (for example during release revalidation). Refuse before
            # posting even a shutdown preparation request to the gateways.
            with pytest.raises(ValueError, match="cache changed"):
                await stop_reviewed_gateways(directory)
            assert not (directory.parent.parent / "stop.json").exists()
            with pytest.raises(ValueError, match="cache changed"):
                await jobs.start_job(directory, feed)
            assert not (directory / "approval.json").exists()
            assert not (directory / "backup").exists()
            assert inspect_environment(plan.installation.python, uv=True) == before
            return
        if mode == "repair":
            (directory / "fail-verification").touch()
        process = await jobs.start_job(directory, feed)
        code = await asyncio.to_thread(process.wait, 60)
        status = JobStatus.read(directory)
        if mode == "repair":
            assert code != 0 and status.phase == Phase.FAILED and status.mutation_started
            backup = (directory / "backup/data.zip").read_bytes()
            with pytest.raises(ValueError, match="explicit repair"):
                await jobs.start_job(directory, feed)
            process = await jobs.start_job(directory, feed, repair=True)
            code = await asyncio.to_thread(process.wait, 60)
            status = JobStatus.read(directory)
            assert (directory / "backup/data.zip").read_bytes() == backup
        assert code == 0, status
        assert status.phase == Phase.INSTALLED, status
        assert inspect_environment(plan.installation.python, uv=True).versions == spec.uv.versions
        assert receipt.read_bytes() == original_receipt
        assert cache_digest(cache) == spec.uv.cache_sha256
        assert (directory / "backup/data.zip").is_file()
        assert len(list(directory.glob(".uv-apply-*"))) == (2 if mode == "repair" else 1)


async def test_orphan_native_uv_preparation_keeps_lease_and_can_be_settled(uv_installation, tmp_path):
    plan, before, receipt, transport, server = uv_installation
    async with ReleaseFeed(tmp_path / "ready-feed", transport=transport) as feed:
        prepared = await jobs.prepare_job(plan, feed)
    plan = plan.model_copy(update={"id": str(uuid4())})
    root = installation_state_dir(plan.installation.environment)
    directory = root / "jobs" / plan.id
    entered, release = threading.Event(), threading.Event()
    original_receipt = receipt.read_bytes()
    native_pid = tmp_path / "native-pid"

    class HeldIndex(IndexHandler):
        def do_GET(self):
            if self.path.startswith("/simple/fixture-runtime/"):
                entered.set()
                assert release.wait(20), "The native uv test was not released"
            super().do_GET()

    server.RequestHandlerClass = partial(HeldIndex, directory=str(tmp_path / "index"))
    template = tmp_path / "private-worker.pyz"
    jobs._worker_archive(template)  # Existing fixture makes every child use the private account.
    hook = f"""
import shutil, subprocess
Path.home = classmethod(lambda cls: Path({str(Path.home())!r}))
def private_worker(path):
    shutil.copyfile({str(template)!r}, path)
    return 'unused-before-final-checksum'
update_jobs._worker_archive = private_worker
original_popen = subprocess.Popen
def observed_popen(*args, **kwargs):
    child = original_popen(*args, **kwargs)
    Path({str(native_pid)!r}).write_text(str(child.pid))
    return child
subprocess.Popen = observed_popen
"""
    script = _preparer_script(plan, tmp_path / "index" / plan.target.artifact.filename, tmp_path / "feed", hook)
    parent = subprocess.Popen([sys.executable, "-I", "-c", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        async with asyncio.timeout(15):
            while not entered.is_set():
                assert parent.poll() is None, "Preparation exited before native uv reached the index"
                await asyncio.sleep(0.01)
        parent.kill()
        await asyncio.to_thread(parent.wait, 10)
        os.kill(int(native_pid.read_text()), 0)
        with pytest.raises(InstallationBusyError):
            with installation_access(updating=True, environment=plan.installation.environment):
                pytest.fail("Native uv lost its own runtime lease after parent death")
        with pytest.raises(BlockingIOError):
            jobs.settle_interrupted_preparation(directory)
        with pytest.raises(BlockingIOError):
            await stop_reviewed_gateways(prepared)
        assert not (root / "stop.json").exists(), "A live native preparation must be refused before shutdown"
        assert JobStatus.read(directory).phase == Phase.PREPARING
        assert not (directory / "request.json").exists()
    finally:
        release.set()
        if parent.poll() is None:
            parent.kill()
        await asyncio.to_thread(parent.wait, 10)
        async with asyncio.timeout(20):
            while True:
                try:
                    with file_access(root / "prepare-native.lock", exclusive=True):
                        break
                except BlockingIOError:
                    await asyncio.sleep(0.01)
    assert jobs.settle_interrupted_preparation(directory).phase == Phase.PREPARATION_FAILED
    assert inspect_environment(plan.installation.python, uv=True) == before
    assert receipt.read_bytes() == original_receipt
    async with ReleaseFeed(tmp_path / "retry-feed", transport=transport) as feed:
        assert await jobs.prepare_job(plan, feed) == directory
    assert JobStatus.read(directory).phase == Phase.READY
    assert not (directory / "approval.json").exists()
