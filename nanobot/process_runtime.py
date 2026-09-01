"""Cross-platform lifecycle management for nanobot background processes."""

from __future__ import annotations

import ctypes
import json
import os
import re
import signal
import struct
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from contextlib import suppress
from ctypes import wintypes
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Generic, Literal, TypeVar, cast

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


_StartOptionsT = TypeVar("_StartOptionsT", bound=ProcessStartOptions)


class ManagedProcessRuntime(Generic[_StartOptionsT]):
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
        # Keep the handle for children spawned by this runtime. On POSIX an
        # exited child remains visible to kill(pid, 0) until its parent reaps
        # it; poll() both reaps it and reports the real lifecycle state.
        self._owned_process: Any | None = None

    def start_background(self, options: _StartOptionsT) -> ProcessResult:
        """Start the configured command as a detached process."""
        with self._lifecycle_lock():
            return self._start_background(options)

    def _start_background(self, options: _StartOptionsT) -> ProcessResult:
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
        self._owned_process = process

        pid = int(process.pid)
        self._sleep(0.2)
        if not self._is_pid_running(pid):
            return ProcessResult(False, self._message("exited_during_startup"), self.status())

        state: dict[str, object] = {
            "pid": pid,
            "started_at": _utc_now(),
            "platform": self.platform_name,
            "port": options.port,
            "workspace": options.workspace,
            "config_path": options.config_path,
            "command": command,
            "log_path": str(self.paths.log_path),
        }
        state.update(self.process_identity_record(pid))
        self._write_state(state)
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
        identity_match = self._process_identity_match(state, status.pid)
        if identity_match == "unknown":
            return ProcessResult(
                False,
                self._message("identity_unavailable"),
                status,
            )
        if identity_match == "mismatch":
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

    def restart(self, options: _StartOptionsT, *, timeout_s: int = 20) -> ProcessResult:
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
        assert state is not None

        identity_match = self._process_identity_match(state, pid)
        if not self._is_pid_running(pid) or identity_match == "mismatch":
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
            command=tuple(cast(list[str], command)) if isinstance(command, list) else (),
            reason=reason or (
                "identity_unavailable" if identity_match == "unknown" else "running"
            ),
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

    def process_identity(self, pid: int) -> str | int | None:
        """Return an identity that changes when an operating-system PID is reused."""
        return self._process_identity(pid)

    def process_identity_record(
        self,
        pid: int,
        *,
        lease: bool = False,
    ) -> dict[str, str | int | None]:
        """Serialize an identity without breaking pre-upgrade macOS readers."""
        return process_identity_record(self._process_identity(pid), lease=lease)

    def process_identity_match(
        self,
        recorded: object,
        pid: int,
    ) -> Literal["match", "mismatch", "unknown"]:
        """Compare a recorded identity with the current process safely."""
        if recorded is None:
            return "match"
        current = self._process_identity(pid)
        if current is None:
            return "unknown"
        if recorded == current:
            return "match"
        # Older POSIX state files stored only the process group id.
        if (
            isinstance(recorded, int)
            and isinstance(current, str)
            and (
                current.startswith(f"{recorded}:")
                or current.startswith(f"darwin:{recorded}:")
            )
        ):
            return "match"
        if self.platform_name == "Darwin":
            return _darwin_identity_match(recorded, current)
        return "mismatch"

    def process_is_running(self, pid: int) -> bool:
        """Return whether the recorded operating-system process is still live."""
        return self._is_pid_running(pid)

    def _message(self, event: str) -> str:
        return f"{self.service_name}_{event}"

    def _lifecycle_lock(self) -> FileLock:
        lock_path = self.paths.state_path.with_name(f"{self.paths.state_path.name}.lock")
        return FileLock(str(lock_path))

    def _build_child_command(self, options: _StartOptionsT) -> list[str]:
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
        # ``os.kill(pid, CTRL_BREAK_EVENT)`` delegates to
        # GenerateConsoleCtrlEvent.  That API targets a console process group,
        # not an individual process, and can interrupt the caller when a
        # detached/no-window child has no addressable console group.  Keep
        # termination scoped to the recorded PID tree instead.
        self._subprocess_run(
            ["taskkill", "/PID", str(pid), "/T"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if self._wait_for_exit(pid, timeout_s):
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
        owned_process = self._owned_process
        if owned_process is not None and getattr(owned_process, "pid", None) == pid:
            poll = getattr(owned_process, "poll", None)
            if callable(poll):
                try:
                    return poll() is None
                except OSError:
                    pass
        return process_is_running(pid, platform_name=self.platform_name)

    def _process_identity(self, pid: int) -> str | int | None:
        # Process inspection must follow the host API even when tests inject a
        # target platform.  On Windows, falling through to POSIX calls is not
        # merely unsupported: ``os.kill(pid, 0)`` broadcasts CTRL_C_EVENT.
        host_platform = _platform_name()
        if host_platform == "Windows" or self.platform_name == "Windows":
            return _windows_process_identity(pid)
        if self.platform_name == "Darwin":
            birth = _darwin_process_birth(pid)
            if birth is None:
                return None
            process_group, started_at_seconds, started_at_microseconds = birth
            return (
                f"darwin:{process_group}:{started_at_seconds}:"
                f"{started_at_microseconds}"
            )
        try:
            process_group = os.getpgid(pid)
        except OSError:
            return None
        started_at = self._posix_process_started_at(pid)
        return f"{process_group}:{started_at}" if started_at else process_group

    def _posix_process_started_at(self, pid: int) -> str | None:
        if self.platform_name == "Linux":
            try:
                stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
            except OSError:
                return None
            closing_paren = stat.rfind(")")
            fields = stat[closing_paren + 2 :].split() if closing_paren >= 0 else []
            # /proc/<pid>/stat fields after comm begin at field 3; starttime is field 22.
            return fields[19] if len(fields) > 19 else None
        return None

    def _record_matches_process(self, state: dict[str, Any] | None, pid: int) -> bool:
        return self._process_identity_match(state, pid) == "match"

    def _process_identity_match(
        self,
        state: dict[str, Any] | None,
        pid: int,
    ) -> Literal["match", "mismatch", "unknown"]:
        if not state:
            return "mismatch"
        recorded = state.get("stable_identity")
        if recorded is None:
            recorded = state.get("identity")
        return self.process_identity_match(recorded, pid)

    def _read_state(self) -> dict[str, Any] | None:
        try:
            with self.paths.state_path.open(encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError, ValueError):
            return None
        return cast(dict[str, Any], payload) if isinstance(payload, dict) else None

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


def process_is_running(pid: int, *, platform_name: str | None = None) -> bool:
    """Probe a PID without delivering a control event on Windows."""
    if pid <= 0:
        return False
    host_platform = _platform_name()
    if host_platform == "Windows" or platform_name == "Windows":
        # On Windows ``os.kill(pid, 0)`` sends CTRL_C_EVENT (whose value is 0)
        # instead of performing the harmless POSIX existence probe.
        return _windows_process_identity(pid) is not None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return _posix_process_state(pid, platform_name=host_platform) != "Z"


def _posix_process_state(pid: int, *, platform_name: str) -> str | None:
    """Return the host process state when available; zombies are not live clients."""
    if platform_name == "Linux":
        try:
            stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        except OSError:
            return None
        closing_paren = stat.rfind(")")
        fields = stat[closing_paren + 2 :].split() if closing_paren >= 0 else []
        return fields[0] if fields else None
    if platform_name == "Darwin":
        try:
            result = subprocess.run(
                ["ps", "-o", "stat=", "-p", str(pid)],
                check=False,
                capture_output=True,
                text=True,
                timeout=1,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        value = getattr(result, "stdout", "").strip()
        return value[:1].upper() or None
    return None


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


def _darwin_identity_match(
    recorded: object,
    current: object,
) -> Literal["match", "mismatch", "unknown"]:
    """Compare the new numeric identity with a pre-upgrade ``ps`` identity."""
    if not isinstance(recorded, str) or not isinstance(current, str):
        return "mismatch"
    current_identity = _parse_darwin_identity(current)
    if current_identity is None:
        return "mismatch"
    current_group, current_seconds, _ = current_identity
    recorded_group, separator, recorded_started_at = recorded.partition(":")
    if not separator or not recorded_group.isdigit():
        return "mismatch"
    if int(recorded_group) != current_group:
        return "mismatch"
    legacy_epoch = _legacy_darwin_started_at(recorded_started_at)
    if legacy_epoch is None:
        # The PID is alive and its process group still matches, but an older
        # locale produced a date we cannot safely parse. Keep the record until
        # the owning client exits instead of killing a live gateway.
        return "unknown"
    return "match" if legacy_epoch == current_seconds else "mismatch"


def _parse_darwin_identity(value: object) -> tuple[int, int, int] | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"darwin:(\d+):(\d+):(\d+)", value)
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def process_identity_record(
    identity: str | int | None,
    *,
    lease: bool = False,
) -> dict[str, str | int | None]:
    """Serialize an identity without breaking pre-upgrade macOS readers."""
    darwin = _parse_darwin_identity(identity)
    if darwin is None:
        return {"identity": identity}
    process_group, _, _ = darwin
    # Old process-state readers understand a PGID-only integer. Old lease
    # readers raw-compare identities, so ``None`` asks them to rely on the
    # still-live PID while upgraded readers use the stable native value.
    return {
        "identity": None if lease else process_group,
        "stable_identity": identity,
    }


def _legacy_darwin_started_at(value: str) -> int | None:
    """Parse the English and numeric macOS ``ps lstart`` formats we released."""
    english = re.fullmatch(
        r"[A-Za-z]{3}\s+([A-Za-z]{3})\s+(\d{1,2})\s+"
        r"(\d{2}):(\d{2}):(\d{2})\s+(\d{4})",
        value.strip(),
    )
    months = {
        "Jan": 1,
        "Feb": 2,
        "Mar": 3,
        "Apr": 4,
        "May": 5,
        "Jun": 6,
        "Jul": 7,
        "Aug": 8,
        "Sep": 9,
        "Oct": 10,
        "Nov": 11,
        "Dec": 12,
    }
    if english is not None:
        month = months.get(english.group(1))
        if month is None:
            return None
        day, hour, minute, second, year = map(int, english.groups()[1:])
    else:
        numeric = re.fullmatch(
            r"\S+\s+(\d{1,2})/(\d{1,2})\s+"
            r"(\d{2}):(\d{2}):(\d{2})\s+(\d{4})",
            value.strip(),
        )
        if numeric is None:
            return None
        month, day, hour, minute, second, year = map(int, numeric.groups())
    try:
        return int(time.mktime((year, month, day, hour, minute, second, -1, -1, -1)))
    except (OSError, OverflowError, ValueError):
        return None


@lru_cache(maxsize=1)
def _darwin_proc_pidinfo() -> Any | None:
    if sys.platform != "darwin":
        return None
    try:
        proc_pidinfo = ctypes.CDLL(
            "/usr/lib/libproc.dylib",
            use_errno=True,
        ).proc_pidinfo
    except (AttributeError, OSError):
        return None
    proc_pidinfo.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint64,
        ctypes.c_void_p,
        ctypes.c_int,
    ]
    proc_pidinfo.restype = ctypes.c_int
    return proc_pidinfo


def _darwin_process_birth(pid: int) -> tuple[int, int, int] | None:
    """Read PGID and microsecond process birth time from ``proc_bsdinfo``."""
    proc_pidinfo = _darwin_proc_pidinfo()
    if proc_pidinfo is None:
        return None
    # ``proc_bsdinfo`` is 136 bytes on supported macOS versions. These stable
    # field offsets come from ``sys/proc_info.h``: pid=12, pgid=100,
    # start_tvsec=120, and start_tvusec=128.
    buffer = ctypes.create_string_buffer(136)
    try:
        written = proc_pidinfo(pid, 3, 0, buffer, len(buffer))
    except (OSError, ValueError):
        return None
    if written != len(buffer) or struct.unpack_from("=I", buffer, 12)[0] != pid:
        return None
    process_group = struct.unpack_from("=I", buffer, 100)[0]
    started_at_seconds = struct.unpack_from("=Q", buffer, 120)[0]
    started_at_microseconds = struct.unpack_from("=Q", buffer, 128)[0]
    if started_at_seconds <= 0:
        return None
    return process_group, started_at_seconds, started_at_microseconds


def _windows_process_identity(pid: int) -> str | None:
    if os.name != "nt":
        return None

    class FileTime(ctypes.Structure):
        _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_uint32)]

        @property
        def value(self) -> int:
            return (int(self.high) << 32) | int(self.low)

    process_query_limited_information = 0x1000
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetProcessTimes.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(FileTime),
        ctypes.POINTER(FileTime),
        ctypes.POINTER(FileTime),
        ctypes.POINTER(FileTime),
    ]
    kernel32.GetProcessTimes.restype = wintypes.BOOL
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
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
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return None
        if exit_code.value != 259:
            return None
        return str(creation_time.value)
    finally:
        kernel32.CloseHandle(handle)
