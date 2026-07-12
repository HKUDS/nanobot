"""Cross-platform lifecycle management for nanobot background processes."""

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

from filelock import FileLock


@dataclass(frozen=True)
class ProcessStartOptions:
    """Options shared by managed nanobot processes."""

    port: int
    verbose: bool = False
    workspace: str | None = None
    config_path: str | None = None


@dataclass(frozen=True)
class ProcessStatus:
    """Current state of one managed process."""

    running: bool
    pid: int | None
    state_path: Path
    log_path: Path
    started_at: str | None = None
    port: int | None = None
    command: tuple[str, ...] = ()
    reason: str = "not_started"


@dataclass(frozen=True)
class ProcessResult:
    """Result of a managed process control operation."""

    ok: bool
    message: str
    status: ProcessStatus


@dataclass(frozen=True)
class ProcessRuntimePaths:
    """Filesystem state used to track one managed process."""

    run_dir: Path
    logs_dir: Path
    state_path: Path
    log_path: Path


class ManagedProcessRuntime:
    """Manage a detached child process without service-specific policy."""

    service_name = "process"

    def __init__(
        self,
        *,
        paths: ProcessRuntimePaths,
        platform_name: str | None = None,
        python_executable: str | None = None,
        popen: Callable[..., Any] = subprocess.Popen,
        subprocess_run: Callable[..., Any] = subprocess.run,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.paths = paths
        self.platform_name = platform_name or _platform_name()
        self.python_executable = python_executable or sys.executable
        self._popen = popen
        self._subprocess_run = subprocess_run
        self._sleep = sleep

    @classmethod
    def refresh_state_pid(cls, *, paths: ProcessRuntimePaths) -> None:
        """Update a managed state file after the recorded process restarts."""
        if not paths.state_path.exists():
            return
        try:
            state = json.loads(paths.state_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        state["pid"] = os.getpid()
        runtime = cls(paths=paths)
        state["identity"] = runtime._process_identity(os.getpid())
        state["started_at"] = _utc_now()
        runtime._write_state(state)

    def start_background(self, options: ProcessStartOptions) -> ProcessResult:
        """Start the configured command as a detached process."""
        with self._lifecycle_lock():
            return self._start_background(options)

    def _start_background(self, options: ProcessStartOptions) -> ProcessResult:
        current = self.status()
        if current.running:
            return ProcessResult(False, self._message("already_running"), current)

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
            return ProcessResult(False, self._message("exited_during_startup"), self.status())

        self._write_state(
            {
                "pid": pid,
                "identity": self._process_identity(pid),
                "started_at": _utc_now(),
                "platform": self.platform_name,
                "port": options.port,
                "workspace": options.workspace,
                "config_path": options.config_path,
                "command": command,
                "log_path": str(self.paths.log_path),
            }
        )
        return ProcessResult(True, self._message("started_background"), self.status())

    def stop(self, *, timeout_s: int = 20) -> ProcessResult:
        """Stop the process recorded in this runtime's state file."""
        with self._lifecycle_lock():
            return self._stop(timeout_s=timeout_s)

    def _stop(self, *, timeout_s: int) -> ProcessResult:
        status = self.status()
        if not status.pid:
            return ProcessResult(False, self._message("not_running"), status)

        state = self._read_state()
        if not self._record_matches_process(state, status.pid):
            self._clear_state()
            return ProcessResult(
                False,
                self._message("state_stale"),
                self.status(reason="stale_state"),
            )

        if not self._terminate(status.pid, timeout_s=timeout_s):
            final_status = self.status(reason="stop_timeout")
            if final_status.running:
                return ProcessResult(
                    False,
                    self._message("stop_timeout"),
                    final_status,
                )
            return ProcessResult(True, self._message("stopped"), final_status)
        self._clear_state()
        return ProcessResult(True, self._message("stopped"), self.status(reason="stopped"))

    def restart(self, options: ProcessStartOptions, *, timeout_s: int = 20) -> ProcessResult:
        """Restart the managed process."""
        with self._lifecycle_lock():
            stop_result = self._stop(timeout_s=timeout_s)
            recoverable = {self._message("not_running"), self._message("state_stale")}
            if not stop_result.ok and stop_result.message not in recoverable:
                return stop_result
            return self._start_background(options)

    def status(self, *, reason: str | None = None) -> ProcessStatus:
        """Return live status, clearing stale state when needed."""
        state = self._read_state()
        pid = _as_int(state.get("pid")) if state else None
        if pid is None:
            return ProcessStatus(
                running=False,
                pid=None,
                state_path=self.paths.state_path,
                log_path=self.paths.log_path,
                reason=reason or "not_started",
            )

        if not self._is_pid_running(pid) or not self._record_matches_process(state, pid):
            self._clear_state()
            return ProcessStatus(
                running=False,
                pid=None,
                state_path=self.paths.state_path,
                log_path=self.paths.log_path,
                reason=reason or "stale_state",
            )

        command = state.get("command")
        return ProcessStatus(
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
        """Print existing log lines and follow new output."""
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

    def _message(self, event: str) -> str:
        return f"{self.service_name}_{event}"

    def _lifecycle_lock(self) -> FileLock:
        lock_path = self.paths.state_path.with_name(f"{self.paths.state_path.name}.lock")
        return FileLock(str(lock_path))

    def _build_child_command(self, options: ProcessStartOptions) -> list[str]:
        raise NotImplementedError

    def _popen_platform_kwargs(self) -> dict[str, Any]:
        if self.platform_name == "Windows":
            flags = 0
            flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
            return {"creationflags": flags}
        return {"start_new_session": True}

    def _terminate(self, pid: int, *, timeout_s: int) -> bool:
        if self.platform_name == "Windows":
            return self._terminate_windows(pid, timeout_s=timeout_s)
        return self._terminate_posix(pid, timeout_s=timeout_s)

    def _terminate_posix(self, pid: int, *, timeout_s: int) -> bool:
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
            return True
        if self._wait_for_exit(pid, timeout_s):
            return True
        with suppress(ProcessLookupError, PermissionError):
            if pgid is not None:
                os.killpg(pgid, signal.SIGKILL)
            else:
                os.kill(pid, signal.SIGKILL)
        return self._wait_for_exit(pid, 2)

    def _terminate_windows(self, pid: int, *, timeout_s: int) -> bool:
        ctrl_break = getattr(signal, "CTRL_BREAK_EVENT", None)
        if ctrl_break is not None:
            ctrl_break_sent = False
            try:
                os.kill(pid, ctrl_break)
            except ProcessLookupError:
                return True
            except OSError:
                pass
            else:
                ctrl_break_sent = True
            if ctrl_break_sent and self._wait_for_exit(pid, timeout_s):
                return True
        self._subprocess_run(
            ["taskkill", "/PID", str(pid), "/T"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if self._wait_for_exit(pid, 2):
            return True
        self._subprocess_run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return self._wait_for_exit(pid, 2)

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
