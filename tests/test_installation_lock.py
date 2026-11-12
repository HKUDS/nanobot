"""Real process leases, not PID files or mocked lock acquisition."""

import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

from nanobot.installation_lock import (
    InstallationBusyError,
    installation_access,
    installation_state_dir,
)

_CHILD = """
import os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[4])
from nanobot.installation_lock import installation_access
Path.home = classmethod(lambda cls: Path(sys.argv[1]))
sys.prefix = sys.argv[2]
with installation_access(updating=sys.argv[3] == 'update'):
    print(os.getpid(), flush=True)
    sys.stdin.read(1)
"""


@contextmanager
def child_lease(home: Path, prefix: str, *, updating: bool = False):
    # Windows venv python.exe is a redirector: killing/waiting for that launcher
    # does not prove the actual lease holder exited. This stdlib-only probe runs
    # the base interpreter directly and verifies that it is the process we own.
    process = subprocess.Popen(
        [sys._base_executable, "-I", "-S", "-c", _CHILD, str(home), prefix,
         "update" if updating else "runtime", str(Path(__file__).resolve().parents[1])],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        assert process.stdout.readline().strip() == str(process.pid), process.stderr.read()
        yield process
    finally:
        if process.poll() is None:
            process.stdin.write("x")
            process.stdin.flush()
        process.communicate(timeout=10)


@pytest.fixture
def isolated_installation(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(sys, "prefix", str(tmp_path / "installation with spaces"))
    return tmp_path


def assert_update_lease_released():
    # LockFileEx documents deferred kernel cleanup after process death/close.
    # Poll the real lock only after the actual owner has exited; never mistake
    # a launcher exiting for an owner exiting or weaken the live-owner checks.
    deadline = time.monotonic() + (5 if sys.platform == "win32" else 0)
    while True:
        try:
            with installation_access(updating=True):
                return
        except InstallationBusyError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.01)


def test_multiple_runtimes_block_update_until_last_process_exits(isolated_installation):
    with child_lease(isolated_installation, sys.prefix) as first:
        with child_lease(isolated_installation, sys.prefix):
            with installation_access():
                pass  # Shared leases do not prevent normal multi-profile use.
            with pytest.raises(InstallationBusyError, match="Stop its nanobot gateways"):
                with installation_access(updating=True):
                    pytest.fail("Update entered a busy installation")
            first.kill()
            first.wait(timeout=10)
            with pytest.raises(InstallationBusyError):
                with installation_access(updating=True):
                    pytest.fail("Another live runtime was ignored")
        assert_update_lease_released()


def test_update_blocks_startup_and_concurrent_update_and_crash_releases_lease(isolated_installation):
    with child_lease(isolated_installation, sys.prefix, updating=True) as worker:
        with pytest.raises(InstallationBusyError, match="being updated"):
            with installation_access():
                pytest.fail("Runtime entered an updating installation")
        with pytest.raises(InstallationBusyError):
            with installation_access(updating=True):
                pytest.fail("Concurrent updater entered")
        worker.kill()
        worker.wait(timeout=10)
        assert_update_lease_released()


def test_other_installation_does_not_block_runtime(isolated_installation):
    with child_lease(isolated_installation, sys.prefix + "-other", updating=True):
        with installation_access():
            pass


def test_interrupted_installation_refuses_startup_but_allows_repair(isolated_installation):
    pending = isolated_installation / ".nanobot/run" / f"update-{installation_state_dir().name[:16]}.pending"
    pending.parent.mkdir(parents=True)
    pending.write_text("An older updater was interrupted")
    with pytest.raises(InstallationBusyError, match="previous update did not finish"):
        with installation_access():
            pytest.fail("Runtime used partially replaced files")
    with installation_access(updating=True):
        pass
    with installation_access(allow_incomplete=True):
        pass
    with child_lease(isolated_installation, sys.prefix, updating=True):
        with pytest.raises(InstallationBusyError, match="being updated"):
            with installation_access(allow_incomplete=True):
                pytest.fail("A diagnostic command raced the active installer")


def test_aliases_share_installation_lock(isolated_installation, tmp_path):
    environment = Path(sys.prefix)
    environment.mkdir()
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(environment, target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlinks are not enabled for this account")
    with child_lease(isolated_installation, str(alias), updating=True):
        with pytest.raises(InstallationBusyError):
            with installation_access():
                pytest.fail("Alias bypassed installation lease")
