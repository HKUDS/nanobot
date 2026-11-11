import os
import selectors
import subprocess
import sys
from pathlib import Path

import pytest

from nanobot.data_access import data_access
from nanobot.installation_lock import InstallationBusyError, installation_access

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX exec handoff only")

_PROGRAM = "import os,sys; print(os.getpid(), flush=True); sys.stdin.read(1)"
_EXEC = """
import os,sys
from pathlib import Path
from nanobot.data_access import data_access
from nanobot.installation_lock import installation_access
Path.home = classmethod(lambda cls: Path(sys.argv[1]))
with installation_access(updating=True, environment=sys.argv[2]) as installation:
    with data_access([sys.argv[3]], updating=True) as data:
        with installation.inherit_for_exec(), data.inherit_for_exec():
            os.execve(sys.executable, [sys.executable, '-I', '-c', sys.argv[4]], os.environ)
"""


def ready(process):
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        assert selector.select(timeout=10), "Installer did not become ready"
    assert process.stdout.readline().strip() == str(process.pid)


def finish(process):
    if process.poll() is None:
        process.kill()
    process.communicate(timeout=10)


@pytest.mark.parametrize("crash", [False, True])
def test_exec_retains_both_leases_until_installer_exits(tmp_path, monkeypatch, crash):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    environment, store = tmp_path / "installation", tmp_path / "sessions"
    process = subprocess.Popen(
        [sys.executable, "-c", _EXEC, str(tmp_path), str(environment), str(store), _PROGRAM],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        ready(process)
        for updating in (False, True):
            with pytest.raises(InstallationBusyError):
                with installation_access(updating=updating, environment=environment):
                    pytest.fail("Exec lost the installation lease")
        with pytest.raises(InstallationBusyError, match="data is in use"):
            with data_access([store / "conversation.jsonl"]):
                pytest.fail("Exec lost the overlapping store lease")
        with data_access([tmp_path / "other sessions"]):
            pass
        if crash:
            process.kill()
        else:
            process.stdin.write("x")
            process.stdin.flush()
        process.wait(timeout=10)
    finally:
        finish(process)
    with installation_access(updating=True, environment=environment), data_access([store], updating=True):
        pass


@pytest.mark.parametrize("high_stdout_fd", [False, True])
def test_failed_exec_does_not_leak_leases_to_later_children(tmp_path, monkeypatch, high_stdout_fd):
    if high_stdout_fd:
        import fcntl
        import resource

        if resource.getrlimit(resource.RLIMIT_NOFILE)[0] <= 1024:
            pytest.skip("Process limit cannot reproduce a stdout FD outside select()'s range")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    environment, store = tmp_path / "installation", tmp_path / "sessions"
    process = None
    try:
        with (installation_access(updating=True, environment=environment) as installation,
              data_access([store], updating=True) as data):
            with pytest.raises(FileNotFoundError):
                with installation.inherit_for_exec(), data.inherit_for_exec():
                    os.execve(str(tmp_path / "missing-installer"), ["missing-installer"], os.environ)
            # Deliberately allow inheritable FDs here. Restoration, not Popen's
            # normal close_fds=True, must prevent this unrelated child retaining them.
            process = subprocess.Popen(
                [sys.executable, "-I", "-c", _PROGRAM], close_fds=False,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            if high_stdout_fd:
                # Full-suite CI can allocate pipes above select()'s FD_SETSIZE.
                descriptor = fcntl.fcntl(process.stdout.fileno(), fcntl.F_DUPFD_CLOEXEC, 1024)
                process.stdout.close()
                process.stdout = os.fdopen(descriptor)
            ready(process)
        assert process.poll() is None
        with installation_access(updating=True, environment=environment), data_access([store], updating=True):
            pass
    finally:
        if process is not None:
            finish(process)
