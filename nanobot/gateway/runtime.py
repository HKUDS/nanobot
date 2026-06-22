"""Background process control for ``nanobot gateway``.

This module intentionally stays small: the CLI owns command wording, while this
runtime owns process state, log files, and platform-specific detach/stop details.
"""

from __future__ import annotations

import ctypes
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nanobot.config.paths import get_data_dir


@dataclass(frozen=True)
class GatewayStartOptions:
    """Options needed to start a background gateway instance."""

    port: int
    verbose: bool = False
    workspace: str | None = None
    config_path: str | None = None


@dataclass(frozen=True)
class GatewayStatus:
    """Current background gateway status."""

    running: bool
    pid: int | None
    state_path: Path
    log_path: Path
    started_at: str | None = None
    port: int | None = None
    command: tuple[str, ...] = ()
    reason: str = "not_started"


@dataclass(frozen=True)
class RuntimeResult:
    """Result from a gateway runtime control operation."""

    ok: bool
    message: str
    status: GatewayStatus


def build_gateway_command(python_executable: str, options: GatewayStartOptions) -> list[str]:
    """Build a foreground gateway command for process supervisors."""
    command = [
        python_executable,
        "-m",
        "nanobot",
        "gateway",
        "--foreground",
        "--port",
        str(options.port),
    ]
    if options.verbose:
        command.append("--verbose")
    if options.workspace:
        command.extend(["--workspace", options.workspace])
    if options.config_path:
        command.extend(["--config", options.config_path])
    return command


@dataclass(frozen=True)
class GatewayRuntimePaths:
    """Filesystem layout for one gateway runtime instance."""

    run_dir: Path
    logs_dir: Path
    state_path: Path
    log_path: Path

    @classmethod
    def for_instance(
        cls,
        *,
        data_dir: Path | None = None,
        workspace: str | None = None,
        config_path: str | None = None,
    ) -> "GatewayRuntimePaths":
        base = data_dir or get_data_dir()
        suffix = _instance_suffix(workspace=workspace, config_path=config_path)
        run_dir = base / "run"
        logs_dir = base / "logs"
        stem = "gateway" if suffix is None else f"gateway.{suffix}"
        return cls(
            run_dir=run_dir,
            logs_dir=logs_dir,
            state_path=run_dir / f"{stem}.json",
            log_path=logs_dir / f"{stem}.log",
        )


class GatewayRuntime:
    """Manage a background ``nanobot gateway`` process."""

    def __init__(
        self,
        *,
        paths: GatewayRuntimePaths | None = None,
        platform_name: str | None = None,
        python_executable: str | None = None,
        popen: Callable[..., Any] = subprocess.Popen,
        subprocess_run: Callable[..., Any] = subprocess.run,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.paths = paths or GatewayRuntimePaths.for_instance()
        self.platform_name = platform_name or _platform_name()
        self.python_executable = python_executable or sys.executable
        self._popen = popen
        self._subprocess_run = subprocess_run
        self._sleep = sleep

    def start_background(self, options: GatewayStartOptions) -> RuntimeResult:
        """Start gateway as a detached background process."""
        current = self.status()
        if current.running:
            return RuntimeResult(False, "gateway_already_running", current)

        command = self._build_child_command(options)
        self.paths.run_dir.mkdir(parents=True, exist_ok=True)
        self.paths.logs_dir.mkdir(parents=True, exist_ok=True)

        with self.paths.log_path.open("a", encoding="utf-8") as log_handle:
            process = self._popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                **self._popen_platform_kwargs(),
            )

        pid = int(process.pid)
        self._sleep(0.2)
        if not self._is_pid_running(pid):
            return RuntimeResult(False, "gateway_exited_during_startup", self.status())

        identity = self._process_identity(pid)
        self._write_state(
            {
                "pid": pid,
                "identity": identity,
                "started_at": _utc_now(),
                "platform": self.platform_name,
                "port": options.port,
                "workspace": options.workspace,
                "config_path": options.config_path,
                "command": command,
                "log_path": str(self.paths.log_path),
            }
        )
        return RuntimeResult(True, "gateway_started_background", self.status())

    def stop(self, *, timeout_s: int = 20) -> RuntimeResult:
        """Stop the recorded background gateway process."""
        status = self.status()
        if not status.pid:
            return RuntimeResult(False, "gateway_not_running", status)

        state = self._read_state()
        if not self._record_matches_process(state, status.pid):
            self._clear_state()
            return RuntimeResult(False, "gateway_state_stale", self.status(reason="stale_state"))

        self._terminate(status.pid, timeout_s=timeout_s)
        self._clear_state()
        return RuntimeResult(True, "gateway_stopped", self.status(reason="stopped"))

    def restart(self, options: GatewayStartOptions, *, timeout_s: int = 20) -> RuntimeResult:
        """Restart the background gateway."""
        stop_result = self.stop(timeout_s=timeout_s)
        if not stop_result.ok and stop_result.message not in {"gateway_not_running", "gateway_state_stale"}:
            return stop_result
        return self.start_background(options)

    def status(self, *, reason: str | None = None) -> GatewayStatus:
        """Return live status, clearing stale state when needed."""
        state = self._read_state()
        pid = _as_int(state.get("pid")) if state else None
        if pid is None:
            return GatewayStatus(
                running=False,
                pid=None,
                state_path=self.paths.state_path,
                log_path=self.paths.log_path,
                reason=reason or "not_started",
            )

        if not self._is_pid_running(pid) or not self._record_matches_process(state, pid):
            self._clear_state()
            return GatewayStatus(
                running=False,
                pid=None,
                state_path=self.paths.state_path,
                log_path=self.paths.log_path,
                reason=reason or "stale_state",
            )

        command = state.get("command")
        return GatewayStatus(
            running=True,
            pid=pid,
            state_path=self.paths.state_path,
            log_path=self.paths.log_path,
            started_at=_as_str(state.get("started_at")),
            port=_as_int(state.get("port")),
            command=tuple(command) if isinstance(command, list) else (),
            reason=reason or "running",
        )

    def read_log_tail(self, *, tail: int = 200) -> list[str]:
        """Return the last ``tail`` log lines."""
        if tail <= 0 or not self.paths.log_path.exists():
            return []
        try:
            lines = self.paths.log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []
        return lines[-tail:]

    def follow_logs(self, *, tail: int = 200) -> int:
        """Print existing log tail and follow new log lines."""
        for line in self.read_log_tail(tail=tail):
            print(line)
        self.paths.logs_dir.mkdir(parents=True, exist_ok=True)
        self.paths.log_path.touch(exist_ok=True)
        try:
            with self.paths.log_path.open("r", encoding="utf-8", errors="replace") as handle:
                handle.seek(0, os.SEEK_END)
                while True:
                    line = handle.readline()
                    if line:
                        print(line.rstrip("\n"))
                    else:
                        self._sleep(0.5)
        except KeyboardInterrupt:
            return 130

    def _build_child_command(self, options: GatewayStartOptions) -> list[str]:
        return build_gateway_command(self.python_executable, options)

    def _popen_platform_kwargs(self) -> dict[str, Any]:
        if self.platform_name == "Windows":
            flags = 0
            flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
            return {"creationflags": flags}
        return {"start_new_session": True}

    def _terminate(self, pid: int, *, timeout_s: int) -> None:
        if self.platform_name == "Windows":
            self._terminate_windows(pid, timeout_s=timeout_s)
        else:
            self._terminate_posix(pid, timeout_s=timeout_s)

    def _terminate_posix(self, pid: int, *, timeout_s: int) -> None:
        try:
            pgid = os.getpgid(pid)
        except OSError:
            pgid = None
        try:
            if pgid is not None:
                os.killpg(pgid, signal.SIGTERM)
            else:
                os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        if self._wait_for_exit(pid, timeout_s):
            return
        with suppress(ProcessLookupError):
            if pgid is not None:
                os.killpg(pgid, signal.SIGKILL)
            else:
                os.kill(pid, signal.SIGKILL)
        self._wait_for_exit(pid, 2)

    def _terminate_windows(self, pid: int, *, timeout_s: int) -> None:
        ctrl_break = getattr(signal, "CTRL_BREAK_EVENT", None)
        if ctrl_break is not None:
            with suppress(ProcessLookupError):
                os.kill(pid, ctrl_break)
            if self._wait_for_exit(pid, timeout_s):
                return
        self._subprocess_run(["taskkill", "/PID", str(pid), "/T"], check=False)
        if self._wait_for_exit(pid, 2):
            return
        self._subprocess_run(["taskkill", "/PID", str(pid), "/T", "/F"], check=False)
        self._wait_for_exit(pid, 2)

    def _wait_for_exit(self, pid: int, timeout_s: int | float) -> bool:
        deadline = time.monotonic() + max(float(timeout_s), 0.0)
        while time.monotonic() < deadline:
            if not self._is_pid_running(pid):
                return True
            self._sleep(0.1)
        return not self._is_pid_running(pid)

    def _is_pid_running(self, pid: int) -> bool:
        if pid <= 0:
            return False
        if self.platform_name == "Windows":
            return _windows_process_identity(pid) is not None
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        return True

    def _process_identity(self, pid: int) -> str | int | None:
        if self.platform_name == "Windows":
            return _windows_process_identity(pid)
        try:
            return os.getpgid(pid)
        except OSError:
            return None

    def _record_matches_process(self, state: dict[str, Any] | None, pid: int) -> bool:
        if not state:
            return False
        recorded = state.get("identity")
        if recorded is None:
            return True
        return recorded == self._process_identity(pid)

    def _read_state(self) -> dict[str, Any] | None:
        try:
            with self.paths.state_path.open(encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None

    def _write_state(self, payload: dict[str, Any]) -> None:
        self.paths.run_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=f"{self.paths.state_path.name}.",
            suffix=".tmp",
            dir=self.paths.run_dir,
        )
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            tmp_path.replace(self.paths.state_path)
        finally:
            tmp_path.unlink(missing_ok=True)

    def _clear_state(self) -> None:
        self.paths.state_path.unlink(missing_ok=True)


def _instance_suffix(*, workspace: str | None, config_path: str | None) -> str | None:
    raw = "|".join(value for value in (workspace, config_path) if value)
    if not raw:
        return None
    import hashlib

    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _platform_name() -> str:
    if sys.platform.startswith("win"):
        return "Windows"
    if sys.platform == "darwin":
        return "Darwin"
    return "Linux"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _as_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _as_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _windows_process_identity(pid: int) -> str | None:
    if os.name != "nt":
        return None

    class FileTime(ctypes.Structure):
        _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_uint32)]

        @property
        def value(self) -> int:
            return (int(self.high) << 32) | int(self.low)

    process_query_limited_information = 0x1000
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return None
    try:
        creation_time = FileTime()
        exit_time = FileTime()
        kernel_time = FileTime()
        user_time = FileTime()
        ok = kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation_time),
            ctypes.byref(exit_time),
            ctypes.byref(kernel_time),
            ctypes.byref(user_time),
        )
        if not ok:
            return None
        exit_code = ctypes.c_uint32()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return None
        if exit_code.value != 259:
            return None
        return str(creation_time.value)
    finally:
        kernel32.CloseHandle(handle)
