import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from nanobot.api.runtime import ApiRuntime, ApiStartOptions, api_runtime_paths


class FakeProcess:
    pid = 23456


_API_CHILD = r"""
import json
import os
import sys
import time
from pathlib import Path

from nanobot.api.runtime import ApiRuntime, ApiStartOptions, api_runtime_paths

home = Path(sys.argv[1])
paths = api_runtime_paths(home)
host_runtime = ApiRuntime(paths=paths)
runtime = ApiRuntime(paths=paths, platform_name=sys.argv[2])
runtime._process_identity = host_runtime.process_identity
runtime._is_pid_running = host_runtime.process_is_running

def publish_result(payload):
    path = home / "result.tmp"
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.replace(home / "result.json")

options = ApiStartOptions(
    port=9900, home=str(home), config_path=str(home / "config.json"),
    workspace=str(home / "workspace"),
)
deadline = time.monotonic() + 10
while not (home / "claim").exists():
    if time.monotonic() > deadline:
        raise TimeoutError("API claim was not released")
    time.sleep(0.01)
try:
    with runtime.foreground_instance(options):
        publish_result({
            "pid": os.getpid(), "parent": os.getppid(), "result": "claimed",
        })
        while not (home / "exit").exists():
            if time.monotonic() > deadline:
                raise TimeoutError("API exit was not released")
            time.sleep(0.01)
except RuntimeError as exc:
    publish_result({"result": str(exc)})
"""


class _ManagedApiChildRuntime(ApiRuntime):
    def __init__(self, home: Path, *, wrapper: bool) -> None:
        super().__init__(paths=api_runtime_paths(home))
        self._home = home
        self._wrapper = wrapper

    def _build_child_command(self, options: ApiStartOptions) -> list[str]:
        command = [sys.executable, "-c", _API_CHILD, str(self._home), "Windows"]
        if self._wrapper:
            return [
                sys.executable, "-c",
                "import subprocess, sys; raise SystemExit(subprocess.call(sys.argv[1:]))",
                *command,
            ]
        return command


def _wait_for_api_result(process: subprocess.Popen, home: Path) -> dict:
    deadline = time.monotonic() + 5
    result_path = home / "result.json"
    while time.monotonic() < deadline:
        if result_path.exists():
            return json.loads(result_path.read_text(encoding="utf-8"))
        if process.poll() is not None:
            break
        time.sleep(0.01)
    pytest.fail(f"API child did not report a claim: returncode={process.poll()}")


def _exercise_managed_api_child(
    home: Path, monkeypatch, *, wrapper: bool, changed: str | None = None,
) -> None:
    root = str(Path(__file__).resolve().parents[2])
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(filter(None, (
        root, os.environ.get("PYTHONPATH"),
    ))))
    runtime = _ManagedApiChildRuntime(home, wrapper=wrapper)
    options = ApiStartOptions(
        port=9900, home=str(home), config_path=str(home / "config.json"),
        workspace=str(home / "workspace"),
    )
    result = runtime.start_background(options)
    launcher = runtime._owned_process
    assert isinstance(launcher, subprocess.Popen)
    try:
        assert result.ok
        with runtime._lifecycle_lock():
            state = runtime._read_state()
            assert state is not None
            if changed == "pending_pid_handoff":
                state.pop(changed, None)
            elif changed == "launch_mode":
                state[changed] = "foreground"
            elif changed == "pid":
                state[changed] = os.getpid()
                state.update(runtime.process_identity_record(os.getpid()))
            elif changed:
                state[changed] = str(home / "other")
            runtime._write_state(state)
        (home / "claim").touch()
        claimed = _wait_for_api_result(launcher, home)
        if changed:
            expected = (
                "api_instance_mismatch"
                if changed in {"home", "config_path", "workspace"}
                else "api_already_running"
            )
            assert claimed["result"] == expected
            assert runtime._read_state() == state
        else:
            assert claimed["result"] == "claimed"
            assert claimed["parent"] == launcher.pid
            assert claimed["pid"] != launcher.pid
            status = runtime.status()
            assert status.pid == claimed["pid"]
            assert status.home == options.home
            assert status.config_path == options.config_path
            assert status.workspace == options.workspace
            record = runtime._read_state()
            assert record is not None
            assert record["launch_mode"] == "background"
            assert "pending_pid_handoff" not in record
    finally:
        (home / "claim").touch()
        (home / "exit").touch()
        launcher.wait(timeout=5)
    if changed is None:
        assert not runtime.paths.state_path.exists()


@pytest.mark.skipif(
    os.name != "nt" or sys.prefix == sys.base_prefix,
    reason="requires a Windows virtualenv launcher",
)
def test_managed_api_hands_off_virtualenv_launcher_pid(tmp_path: Path, monkeypatch) -> None:
    _exercise_managed_api_child(tmp_path, monkeypatch, wrapper=False)


@pytest.mark.skipif(os.name == "nt", reason="uses a POSIX wrapper to model a Windows launcher")
@pytest.mark.parametrize("changed", [
    None, "pending_pid_handoff", "launch_mode", "pid", "home", "config_path", "workspace",
])
def test_managed_api_handoff_requires_owned_parent_and_selectors(
    tmp_path: Path, monkeypatch, changed: str | None,
) -> None:
    _exercise_managed_api_child(tmp_path, monkeypatch, wrapper=True, changed=changed)


def test_api_runtime_uses_home_paths(tmp_path: Path) -> None:
    paths = api_runtime_paths(tmp_path)

    assert paths.state_path.parent == tmp_path / "run"
    assert paths.state_path.name == "api.json"
    assert paths.log_path.parent == tmp_path / "logs"
    assert paths.log_path.name == "api.log"


def test_api_runtime_builds_detached_serve_command(tmp_path: Path, monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_popen(command, **_kwargs):
        calls.append(command)
        return FakeProcess()

    runtime = ApiRuntime(
        paths=api_runtime_paths(tmp_path),
        platform_name="Linux",
        python_executable="/python",
        popen=fake_popen,
        sleep=lambda _seconds: None,
    )
    monkeypatch.setattr(runtime, "_is_pid_running", lambda _pid: True)
    monkeypatch.setattr(runtime, "_process_identity", lambda _pid: 23456)

    result = runtime.start_background(ApiStartOptions(
        host="0.0.0.0",
        port=9900,
        workspace="/tmp/workspace",
        config_path="/tmp/config.json",
        home=str(tmp_path),
    ))

    assert result.ok is True
    assert result.message == "api_started_background"
    assert calls == [[
        "/python",
        "-m",
        "nanobot",
        "--home",
        str(tmp_path),
        "serve",
        "--host",
        "0.0.0.0",
        "--port",
        "9900",
        "--workspace",
        "/tmp/workspace",
        "--config",
        "/tmp/config.json",
    ]]


def test_api_home_rejects_changed_config_without_restarting(tmp_path: Path, monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_popen(command, **_kwargs):
        calls.append(command)
        return FakeProcess()

    runtime = ApiRuntime(
        paths=api_runtime_paths(tmp_path), popen=fake_popen,
        sleep=lambda _seconds: None,
    )
    monkeypatch.setattr(runtime, "_is_pid_running", lambda _pid: True)
    monkeypatch.setattr(runtime, "_process_identity", lambda _pid: 23456)
    first = ApiStartOptions(
        port=9900, home=str(tmp_path), config_path=str(tmp_path / "first.json"),
        workspace=str(tmp_path / "workspace"),
    )
    changed = ApiStartOptions(
        port=9900, home=str(tmp_path), config_path=str(tmp_path / "second.json"),
        workspace=str(tmp_path / "workspace"),
    )
    assert runtime.start_background(first).ok

    result = runtime.restart(changed)

    assert result.message == "api_instance_mismatch"
    assert result.status.config_path == first.config_path
    assert result.status.running
    assert len(calls) == 1


def test_foreground_api_claim_is_home_scoped(tmp_path: Path, monkeypatch) -> None:
    runtime = ApiRuntime(paths=api_runtime_paths(tmp_path))
    monkeypatch.setattr(runtime, "_is_pid_running", lambda _pid: True)
    monkeypatch.setattr(runtime, "_process_identity", lambda _pid: 23456)
    first = ApiStartOptions(
        port=9900, home=str(tmp_path), config_path=str(tmp_path / "first.json"),
        workspace=str(tmp_path / "workspace"),
    )
    changed = ApiStartOptions(
        port=9900, home=str(tmp_path), config_path=str(tmp_path / "second.json"),
        workspace=str(tmp_path / "workspace"),
    )

    with runtime.foreground_instance(first):
        status = runtime.status()
        assert status.running and status.home == str(tmp_path)
        assert runtime.restart(first).message == "api_foreground_restart_required"
        with pytest.raises(RuntimeError, match="api_instance_mismatch"):
            with runtime.foreground_instance(changed):
                pass

    assert not runtime.paths.state_path.exists()
