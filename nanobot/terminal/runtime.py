"""Project-scoped pseudo-terminal sessions shared by the WebUI and agent tools."""

from __future__ import annotations

import asyncio
import codecs
import importlib
import os
import re
import shlex
import shutil
import signal
import struct
import subprocess
import sys
import time
import uuid
from collections import deque
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

_IS_WINDOWS = sys.platform == "win32"
_DEFAULT_ROWS = 30
_DEFAULT_COLS = 100
_MIN_ROWS = 2
_MAX_ROWS = 200
_MIN_COLS = 2
_MAX_COLS = 500
_MAX_INPUT_CHARS = 65_536
_DEFAULT_REPLAY_CHARS = 250_000
_MAX_EXEC_CAPTURE_CHARS = 1_000_000
_TERMINAL_EXEC_PREFIX = "termexec-"

_ANSI_ESCAPE_RE = re.compile(
    r"\x1B(?:\][^\x07]*(?:\x07|\x1B\\)|\[[0-?]*[ -/]*[@-~]|[@-_])"
)

_POWERSHELL_EXEC_HELPERS = (
    "function global:__nb0 { param([string]$id); "
    "$global:LASTEXITCODE = $null; "
    '[Console]::Write("`e]633;nanobot;begin;$id`a") }; '
    "function global:__nb1 { "
    "param([string]$id, [bool]$ok, [object]$native); "
    "if ($null -ne $native) { $code = [int]$native } "
    "elseif ($ok) { $code = 0 } else { $code = 1 }; "
    '[Console]::Write("`e]633;nanobot;done;$id;$code`a"); '
    "$global:LASTEXITCODE = $null }"
)

# Set only by the authenticated WebUI channel on a locally trusted request.
# Tool callers must not infer terminal authority from the workspace scope alone.
TRUSTED_TERMINAL_REQUEST_METADATA_KEY = "_nanobot_trusted_terminal_request"


class TerminalError(RuntimeError):
    """A stable, user-presentable terminal runtime error."""


@dataclass(frozen=True, slots=True)
class TerminalInfo:
    terminal_id: str
    project_path: str
    rows: int
    cols: int
    running: bool
    exit_code: int | None
    created_at: float
    pty_backend: str | None = None
    windows_build: int | None = None


@dataclass(frozen=True, slots=True)
class TerminalRead:
    data: str
    next_seq: int
    running: bool
    exit_code: int | None
    replay_reset: bool = False


@dataclass(slots=True)
class TerminalExecPoll:
    """One compatibility poll for a command running in the shared PTY."""

    output: str
    done: bool
    exit_code: int | None
    elapsed_s: float = 0.0
    timed_out: bool = False
    terminated: bool = False
    stdin_closed: bool = False
    truncated_chars: int = 0


@dataclass(frozen=True, slots=True)
class TerminalExecInfo:
    session_id: str
    command: str
    cwd: str
    elapsed_s: float
    idle_s: float
    remaining_s: float
    returncode: int | None
    owner_session_key: str | None = None


class _TerminalBackend(Protocol):
    pty_backend: str | None
    windows_build: int | None

    def read(self, size: int) -> str: ...

    def write(self, data: str) -> None: ...

    def resize(self, rows: int, cols: int) -> None: ...

    def exit_code(self) -> int | None: ...

    def close(self) -> None: ...


class _PosixPtyBackend:
    pty_backend: str | None = None
    windows_build: int | None = None

    def __init__(self, process: subprocess.Popen[bytes], master_fd: int) -> None:
        self._process = process
        self._master_fd = master_fd
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._closed = False

    @classmethod
    def spawn(
        cls,
        argv: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        rows: int,
        cols: int,
    ) -> _PosixPtyBackend:
        import fcntl
        import pty
        import termios

        master_fd, slave_fd = pty.openpty()
        try:
            fcntl.ioctl(
                slave_fd,
                termios.TIOCSWINSZ,
                struct.pack("HHHH", rows, cols, 0, 0),
            )
            process = subprocess.Popen(
                argv,
                cwd=str(cwd),
                env=env,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                start_new_session=True,
                close_fds=True,
            )
        except BaseException:
            os.close(master_fd)
            raise
        finally:
            os.close(slave_fd)
        return cls(process, master_fd)

    def read(self, size: int) -> str:
        data = os.read(self._master_fd, size)
        if not data:
            raise EOFError("PTY is closed")
        return self._decoder.decode(data)

    def write(self, data: str) -> None:
        encoded = data.encode("utf-8")
        view = memoryview(encoded)
        while view:
            written = os.write(self._master_fd, view)
            view = view[written:]

    def resize(self, rows: int, cols: int) -> None:
        import fcntl
        import termios

        fcntl.ioctl(
            self._master_fd,
            termios.TIOCSWINSZ,
            struct.pack("HHHH", rows, cols, 0, 0),
        )

    def exit_code(self) -> int | None:
        return self._process.poll()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        with suppress(OSError):
            os.close(self._master_fd)
        if self._process.poll() is not None:
            return
        with suppress(ProcessLookupError):
            os.killpg(self._process.pid, signal.SIGTERM)
        try:
            self._process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            with suppress(ProcessLookupError):
                os.killpg(self._process.pid, signal.SIGKILL)
            with suppress(subprocess.TimeoutExpired):
                self._process.wait(timeout=1.0)


class _WindowsPtyBackend:
    pty_backend: str | None
    windows_build: int | None

    def __init__(self, process: Any) -> None:
        self._process = process
        self._closed = False
        self.pty_backend = "conpty"
        self.windows_build = sys.getwindowsversion().build

    @classmethod
    def spawn(
        cls,
        argv: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        rows: int,
        cols: int,
    ) -> _WindowsPtyBackend:
        try:
            winpty = importlib.import_module("winpty")
        except ImportError as exc:  # pragma: no cover - dependency is platform-specific
            raise TerminalError(
                "Interactive terminals on Windows require the pywinpty package"
            ) from exc
        pty_process = getattr(winpty, "PtyProcess")
        backend = getattr(getattr(winpty, "Backend"), "ConPTY")
        return cls(
            pty_process.spawn(
                argv,
                cwd=str(cwd),
                env=env,
                dimensions=(rows, cols),
                backend=backend,
            )
        )

    def read(self, size: int) -> str:
        return str(self._process.read(size))

    def write(self, data: str) -> None:
        self._process.write(data)

    def resize(self, rows: int, cols: int) -> None:
        self._process.setwinsize(rows, cols)

    def exit_code(self) -> int | None:
        if self._process.isalive():
            return None
        return int(self._process.wait())

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._process.close(force=True)


BackendFactory = Callable[[list[str], Path, dict[str, str], int, int], _TerminalBackend]


def _clamp_dimensions(rows: int, cols: int) -> tuple[int, int]:
    return (
        max(_MIN_ROWS, min(_MAX_ROWS, rows)),
        max(_MIN_COLS, min(_MAX_COLS, cols)),
    )


def _default_shell_argv() -> list[str]:
    if _IS_WINDOWS:
        for candidate in ("pwsh.exe", "powershell.exe"):
            resolved = shutil.which(candidate)
            if resolved:
                # -Command runs after the user's normal profile and -NoExit
                # leaves the shell interactive. The helpers keep the marker
                # appended to visible agent commands short and deterministic.
                return [
                    resolved,
                    "-NoLogo",
                    "-NoExit",
                    "-Command",
                    _POWERSHELL_EXEC_HELPERS,
                ]
        return [os.environ.get("COMSPEC", "cmd.exe"), "/Q"]

    configured = os.environ.get("SHELL", "").strip()
    if configured and Path(configured).is_file():
        return [configured]
    return [shutil.which("bash") or shutil.which("sh") or "/bin/sh"]


def _spawn_backend(
    argv: list[str],
    cwd: Path,
    env: dict[str, str],
    rows: int,
    cols: int,
) -> _TerminalBackend:
    backend_cls = _WindowsPtyBackend if _IS_WINDOWS else _PosixPtyBackend
    return backend_cls.spawn(argv, cwd=cwd, env=env, rows=rows, cols=cols)


class _TerminalSession:
    def __init__(
        self,
        *,
        terminal_id: str,
        project_path: Path,
        backend: _TerminalBackend,
        rows: int,
        cols: int,
        replay_chars: int,
    ) -> None:
        self.terminal_id = terminal_id
        self.project_path = project_path
        self.rows = rows
        self.cols = cols
        self.created_at = time.time()
        self.last_access = time.monotonic()
        self._backend = backend
        self._replay_chars = replay_chars
        self._chunks: deque[tuple[int, str]] = deque()
        self._chunk_chars = 0
        self._seq = 0
        self._exit_code: int | None = None
        self._closing = False
        self._condition = asyncio.Condition()
        self._close_lock = asyncio.Lock()
        self._reader_task = asyncio.create_task(
            self._reader_loop(),
            name=f"nanobot-terminal-{terminal_id}",
        )

    @property
    def running(self) -> bool:
        return not self._closing and self._exit_code is None

    def info(self) -> TerminalInfo:
        return TerminalInfo(
            terminal_id=self.terminal_id,
            project_path=str(self.project_path),
            rows=self.rows,
            cols=self.cols,
            running=self.running,
            exit_code=self._exit_code,
            created_at=self.created_at,
            pty_backend=getattr(self._backend, "pty_backend", None),
            windows_build=getattr(self._backend, "windows_build", None),
        )

    async def _reader_loop(self) -> None:
        try:
            while True:
                data = await asyncio.to_thread(self._backend.read, 4096)
                if not data:
                    continue
                async with self._condition:
                    self._seq += 1
                    self._chunks.append((self._seq, data))
                    self._chunk_chars += len(data)
                    while self._chunk_chars > self._replay_chars and len(self._chunks) > 1:
                        _seq, removed = self._chunks.popleft()
                        self._chunk_chars -= len(removed)
                    self._condition.notify_all()
        except (EOFError, OSError):
            pass
        except Exception:
            # PTY adapters use backend-specific EOF exceptions. Treat an
            # unexpected reader failure as terminal exit; writes still report
            # a stable TerminalError through the public methods below.
            pass
        except asyncio.CancelledError:
            raise
        finally:
            exit_code = await asyncio.to_thread(self._backend.exit_code)
            async with self._condition:
                self._exit_code = exit_code if exit_code is not None else -1
                self._condition.notify_all()

    async def write(self, data: str) -> None:
        if not data:
            return
        if len(data) > _MAX_INPUT_CHARS:
            raise TerminalError(f"Terminal input exceeds {_MAX_INPUT_CHARS} characters")
        if not self.running:
            raise TerminalError("Terminal has already exited")
        self.last_access = time.monotonic()
        try:
            await asyncio.to_thread(self._backend.write, data)
        except Exception as exc:
            raise TerminalError("Terminal input is closed") from exc

    async def resize(self, rows: int, cols: int) -> None:
        rows, cols = _clamp_dimensions(rows, cols)
        if rows == self.rows and cols == self.cols:
            return
        if not self.running:
            return
        try:
            await asyncio.to_thread(self._backend.resize, rows, cols)
        except Exception as exc:
            raise TerminalError("Terminal has already exited") from exc
        self.rows = rows
        self.cols = cols
        self.last_access = time.monotonic()

    async def read(self, after_seq: int | None, wait_ms: int = 0) -> TerminalRead:
        wait_ms = max(0, min(30_000, wait_ms))
        deadline = time.monotonic() + wait_ms / 1000
        async with self._condition:
            while (
                after_seq is not None
                and after_seq >= self._seq
                and self.running
                and wait_ms > 0
            ):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                with suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self._condition.wait(), timeout=remaining)

            oldest_seq = self._chunks[0][0] if self._chunks else self._seq + 1
            replay_reset = after_seq is not None and after_seq < oldest_seq - 1
            if after_seq is None or replay_reset:
                data = "".join(chunk for _seq, chunk in self._chunks)
            else:
                data = "".join(chunk for seq, chunk in self._chunks if seq > after_seq)
            self.last_access = time.monotonic()
            return TerminalRead(
                data=data,
                next_seq=self._seq,
                running=self.running,
                exit_code=self._exit_code,
                replay_reset=replay_reset,
            )

    async def close(self) -> None:
        async with self._close_lock:
            if self._closing:
                return
            self._closing = True
            await asyncio.to_thread(self._backend.close)
            if not self._reader_task.done():
                try:
                    await asyncio.wait_for(self._reader_task, timeout=2.0)
                except asyncio.TimeoutError:
                    self._reader_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await self._reader_task
            async with self._condition:
                if self._exit_code is None:
                    exit_code = await asyncio.to_thread(self._backend.exit_code)
                    self._exit_code = exit_code if exit_code is not None else -1
                self._condition.notify_all()


def _strip_terminal_controls(value: str) -> str:
    """Remove terminal control sequences from output returned to the model."""
    return _ANSI_ESCAPE_RE.sub("", value).replace("\x00", "")


def _truncate_terminal_output(value: str, limit: int) -> tuple[str, int]:
    if len(value) <= limit:
        return value, 0
    head = limit // 2
    tail = limit - head
    return value[:head] + value[-tail:], len(value) - limit


class _TerminalExecSession:
    """Track one legacy exec call multiplexed through a project terminal."""

    def __init__(
        self,
        *,
        session_id: str,
        token: str,
        terminal: _TerminalSession,
        command: str,
        cwd: str,
        timeout: int | None,
        owner_session_key: str | None,
        cursor: int,
    ) -> None:
        self.session_id = session_id
        self.terminal = terminal
        self.command = command
        self.cwd = cwd
        self.owner_session_key = owner_session_key
        self.started_at = time.monotonic()
        self.last_access = self.started_at
        self.deadline = self.started_at + timeout if timeout else float("inf")
        self.cursor = cursor
        self.returncode: int | None = None
        self.timed_out = False
        self._terminated = False
        self._stdin_closed = False
        self._pending_raw = ""
        self._body_raw = ""
        self._output = ""
        self._delivered_chars = 0
        self._begun = False
        self._begin_marker = f"\x1b]633;nanobot;begin;{token}\x07"
        self._done_pattern = re.compile(
            re.escape(f"\x1b]633;nanobot;done;{token};") + r"(-?\d+)\x07"
        )
        self._lock = asyncio.Lock()

    @property
    def done(self) -> bool:
        return self.returncode is not None

    def _ingest(self, data: str) -> None:
        if not data:
            return
        if not self._begun:
            self._pending_raw += data
            marker_at = self._pending_raw.find(self._begin_marker)
            if marker_at < 0:
                # Profiles and rich prompts may be noisy. The marker is short,
                # so retaining this tail is enough to match a split sequence.
                self._pending_raw = self._pending_raw[-65_536:]
                return
            self._begun = True
            self._body_raw = self._pending_raw[marker_at + len(self._begin_marker):]
            self._pending_raw = ""
        else:
            self._body_raw += data

        match = self._done_pattern.search(self._body_raw)
        visible_raw = self._body_raw[: match.start()] if match else self._body_raw
        self._output = _strip_terminal_controls(visible_raw)
        if match:
            self.returncode = int(match.group(1))

    def _compact_delivered_output(self) -> None:
        """Bound marker-scanning state without redelivering retained text."""
        if self.done or len(self._body_raw) <= 65_536:
            return
        self._body_raw = self._body_raw[-65_536:]
        self._output = _strip_terminal_controls(self._body_raw)
        self._delivered_chars = len(self._output)

    async def write(self, chars: str) -> None:
        if self.done:
            raise TerminalError("exec session has already exited")
        if _IS_WINDOWS:
            # write_stdin historically accepts "\n" for Enter, while a
            # ConPTY-backed line editor expects the carriage-return key.
            chars = chars.replace("\r\n", "\r").replace("\n", "\r")
        await self.terminal.write(chars)
        self.last_access = time.monotonic()

    async def close_stdin(self) -> None:
        if self.done:
            raise TerminalError("exec session has already exited")
        await self.terminal.write("\x1a\r" if _IS_WINDOWS else "\x04")
        self._stdin_closed = True
        self.last_access = time.monotonic()

    async def interrupt(self, *, timed_out: bool = False) -> None:
        if self.done:
            return
        await self.terminal.write("\x03")
        self.timed_out = self.timed_out or timed_out
        self._terminated = not timed_out
        # Ctrl+C aborts the submitted shell line, including its completion
        # marker. Treat the compatibility session as complete while keeping
        # the underlying project shell alive for the next collaborator.
        self.returncode = -1
        self.last_access = time.monotonic()

    async def poll(
        self,
        yield_time_ms: int,
        max_output_chars: int,
    ) -> TerminalExecPoll:
        async with self._lock:
            self.last_access = time.monotonic()
            poll_deadline = self.last_access + max(0, min(30_000, yield_time_ms)) / 1000
            while not self.done:
                now = time.monotonic()
                if now >= self.deadline:
                    await self.interrupt(timed_out=True)
                    break
                if now >= poll_deadline:
                    break
                deadline_wait_ms = (
                    30_000
                    if self.deadline == float("inf")
                    else int((self.deadline - now) * 1000)
                )
                wait_ms = max(
                    0,
                    min(
                        30_000,
                        int((poll_deadline - now) * 1000),
                        deadline_wait_ms,
                    ),
                )
                result = await self.terminal.read(self.cursor, wait_ms)
                self.cursor = result.next_seq
                self._ingest(result.data)
                if not result.running and not self.done:
                    self.returncode = result.exit_code if result.exit_code is not None else -1
                if len(self._body_raw) >= _MAX_EXEC_CAPTURE_CHARS and not self.done:
                    break
                if wait_ms == 0:
                    break

            # An immediate poll still needs to consume output already buffered.
            if not self.done and yield_time_ms == 0:
                result = await self.terminal.read(self.cursor)
                self.cursor = result.next_seq
                self._ingest(result.data)
                if not result.running and not self.done:
                    self.returncode = result.exit_code if result.exit_code is not None else -1

            fresh = self._output[self._delivered_chars:]
            self._delivered_chars = len(self._output)
            fresh, response_truncated = _truncate_terminal_output(
                fresh,
                max_output_chars,
            )
            self._compact_delivered_output()
            return TerminalExecPoll(
                output=fresh,
                done=self.done,
                exit_code=self.returncode,
                elapsed_s=max(0.0, time.monotonic() - self.started_at),
                timed_out=self.timed_out,
                terminated=self._terminated,
                stdin_closed=self._stdin_closed,
                truncated_chars=response_truncated,
            )

    def info(self) -> TerminalExecInfo:
        now = time.monotonic()
        return TerminalExecInfo(
            session_id=self.session_id,
            command=self.command,
            cwd=self.cwd,
            elapsed_s=max(0.0, now - self.started_at),
            idle_s=max(0.0, now - self.last_access),
            remaining_s=max(0.0, self.deadline - now),
            returncode=self.returncode,
            owner_session_key=self.owner_session_key,
        )


class TerminalSessionManager:
    """Own one persistent PTY per canonical project path."""

    def __init__(
        self,
        *,
        max_sessions: int = 8,
        replay_chars: int = _DEFAULT_REPLAY_CHARS,
        allowed_env_keys: list[str] | None = None,
        path_prepend: str = "",
        path_append: str = "",
        shell_argv: list[str] | None = None,
        backend_factory: BackendFactory | None = None,
    ) -> None:
        self.max_sessions = max(1, max_sessions)
        self.replay_chars = max(10_000, replay_chars)
        self.allowed_env_keys = tuple(allowed_env_keys or ())
        self.path_prepend = path_prepend
        self.path_append = path_append
        self.shell_argv = list(shell_argv) if shell_argv else _default_shell_argv()
        shell_name = Path(self.shell_argv[0]).name.lower()
        if shell_name in {"pwsh", "pwsh.exe", "powershell", "powershell.exe"}:
            self.shell_family = "powershell"
        elif shell_name in {"bash", "bash.exe", "sh", "sh.exe", "zsh", "zsh.exe"}:
            self.shell_family = "posix"
        else:
            self.shell_family = "other"
        self._backend_factory = backend_factory or _spawn_backend
        self._sessions: dict[str, _TerminalSession] = {}
        self._project_sessions: dict[str, str] = {}
        self._exec_sessions: dict[str, _TerminalExecSession] = {}
        self._lock = asyncio.Lock()
        self._closed = False

    @property
    def supports_exec_bridge(self) -> bool:
        return self.shell_family in {"powershell", "posix"}

    def supports_exec_shell(self, shell: str | None, *, login: bool) -> bool:
        """Return whether an exec shell override preserves this PTY's semantics."""
        if not self.supports_exec_bridge or login:
            return False
        if not shell:
            return True

        requested = Path(shell).expanduser()
        active = Path(self.shell_argv[0]).expanduser()
        if requested.is_absolute():
            try:
                return os.path.normcase(str(requested.resolve())) == os.path.normcase(
                    str(active.resolve())
                )
            except OSError:
                return False

        requested_name = requested.name.lower()
        active_name = active.name.lower()
        if self.shell_family == "powershell":
            # Providers often serialize the default Windows shell explicitly
            # as "powershell" even when the host selected pwsh (or vice versa).
            # Both names are compatible with the PowerShell bridge helpers.
            return requested_name in {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}
        return requested_name.removesuffix(".exe") == active_name.removesuffix(".exe")

    @staticmethod
    def _canonical_project(project_path: str | Path) -> tuple[Path, str]:
        try:
            path = Path(project_path).expanduser().resolve(strict=True)
        except OSError as exc:
            raise TerminalError(f"Terminal project is unavailable: {project_path}") from exc
        if not path.is_dir():
            raise TerminalError(f"Terminal project is not a directory: {path}")
        return path, os.path.normcase(str(path))

    def _environment(self) -> dict[str, str]:
        safe_keys = (
            "HOME",
            "USER",
            "LOGNAME",
            "SHELL",
            "LANG",
            "LC_ALL",
            "PATH",
            "TMPDIR",
            "SYSTEMROOT",
            "COMSPEC",
            "USERPROFILE",
            "HOMEDRIVE",
            "HOMEPATH",
            "TEMP",
            "TMP",
            "PATHEXT",
            "APPDATA",
            "LOCALAPPDATA",
            "ProgramData",
            "ProgramFiles",
            "ProgramFiles(x86)",
            "ProgramW6432",
        )
        env = {key: os.environ[key] for key in safe_keys if key in os.environ}
        for key in self.allowed_env_keys:
            value = os.environ.get(key)
            if value is not None:
                env[key] = value
        path_parts = [part for part in (self.path_prepend, env.get("PATH", ""), self.path_append) if part]
        if path_parts:
            env["PATH"] = os.pathsep.join(path_parts)
        env.update({"TERM": "xterm-256color", "COLORTERM": "truecolor", "PYTHONUNBUFFERED": "1"})
        return env

    async def open(
        self,
        project_path: str | Path,
        *,
        rows: int = _DEFAULT_ROWS,
        cols: int = _DEFAULT_COLS,
    ) -> TerminalInfo:
        project, project_key = self._canonical_project(project_path)
        rows, cols = _clamp_dimensions(rows, cols)
        stale: _TerminalSession | None = None
        async with self._lock:
            if self._closed:
                raise TerminalError("Terminal manager is closed")
            existing_id = self._project_sessions.get(project_key)
            existing = self._sessions.get(existing_id or "")
            if existing is not None and existing.running:
                session = existing
            else:
                if existing is not None:
                    stale = existing
                    self._sessions.pop(existing.terminal_id, None)
                self._project_sessions.pop(project_key, None)
                if len(self._sessions) >= self.max_sessions:
                    raise TerminalError(
                        f"Terminal session limit reached ({self.max_sessions}); close one first"
                    )
                argv = list(self.shell_argv)
                try:
                    backend = await asyncio.to_thread(
                        self._backend_factory,
                        argv,
                        project,
                        self._environment(),
                        rows,
                        cols,
                    )
                except TerminalError:
                    raise
                except Exception as exc:
                    raise TerminalError(f"Unable to start terminal: {exc}") from exc
                terminal_id = f"term-{uuid.uuid4().hex[:12]}"
                session = _TerminalSession(
                    terminal_id=terminal_id,
                    project_path=project,
                    backend=backend,
                    rows=rows,
                    cols=cols,
                    replay_chars=self.replay_chars,
                )
                self._sessions[terminal_id] = session
                self._project_sessions[project_key] = terminal_id
        if stale is not None:
            await stale.close()
        await session.resize(rows, cols)
        return session.info()

    async def _session(
        self,
        terminal_id: str,
        *,
        project_path: str | Path | None = None,
    ) -> _TerminalSession:
        async with self._lock:
            session = self._sessions.get(terminal_id)
        if session is None:
            raise TerminalError("Unknown terminal session")
        if project_path is not None:
            project, _key = self._canonical_project(project_path)
            if os.path.normcase(str(project)) != os.path.normcase(str(session.project_path)):
                raise TerminalError("Terminal does not belong to this project")
        return session

    async def read(
        self,
        terminal_id: str,
        *,
        after_seq: int | None = None,
        wait_ms: int = 0,
        project_path: str | Path | None = None,
    ) -> TerminalRead:
        session = await self._session(terminal_id, project_path=project_path)
        return await session.read(after_seq, wait_ms)

    async def write(
        self,
        terminal_id: str,
        data: str,
        *,
        project_path: str | Path | None = None,
    ) -> None:
        session = await self._session(terminal_id, project_path=project_path)
        await session.write(data)

    async def resize(
        self,
        terminal_id: str,
        *,
        rows: int,
        cols: int,
        project_path: str | Path | None = None,
    ) -> TerminalInfo:
        session = await self._session(terminal_id, project_path=project_path)
        await session.resize(rows, cols)
        return session.info()

    async def list(self, project_path: str | Path | None = None) -> list[TerminalInfo]:
        project: Path | None = None
        if project_path is not None:
            project, _key = self._canonical_project(project_path)
        async with self._lock:
            sessions = tuple(self._sessions.values())
        return [
            session.info()
            for session in sessions
            if project is None
            or os.path.normcase(str(session.project_path)) == os.path.normcase(str(project))
        ]

    def _exec_payload(
        self,
        command: str,
        cwd: str,
        token: str,
        project_path: Path,
    ) -> str:
        if self.shell_family == "powershell":
            escaped_cwd = cwd.replace("'", "''")
            if "\n" in command or "\r" in command:
                raise TerminalError(
                    "Multiline PowerShell commands are not yet supported by the shared exec bridge"
                )
            location = ""
            if os.path.normcase(str(Path(cwd).resolve())) != os.path.normcase(str(project_path)):
                location = f"Set-Location -LiteralPath '{escaped_cwd}'; "
            return f"__nb0 {token}; {location}& {{ {command} }}; __nb1 {token} $? $LASTEXITCODE\r"
        if self.shell_family == "posix":
            location = ""
            if os.path.normcase(str(Path(cwd).resolve())) != os.path.normcase(str(project_path)):
                location = f"cd -- {shlex.quote(cwd)}\n"
            body = f"{location}{command}"
            return (
                f"printf '\\033]633;nanobot;begin;{token}\\007'; {{\n"
                f"{body}\n"
                "}; __nb_status=$?; "
                f"printf '\\033]633;nanobot;done;{token};%s\\007' \"$__nb_status\"\r"
            )
        raise TerminalError("The configured project shell cannot host shared exec commands")

    async def start_exec(
        self,
        project_path: str | Path,
        *,
        command: str,
        cwd: str,
        timeout: int | None,
        yield_time_ms: int,
        max_output_chars: int,
        owner_session_key: str | None,
    ) -> tuple[str, TerminalExecPoll]:
        """Start an exec-compatible command inside the shared project PTY."""
        if not self.supports_exec_bridge:
            raise TerminalError("The configured project shell does not support shared exec")
        info = await self.open(project_path)
        terminal = await self._session(info.terminal_id, project_path=project_path)
        cursor = await terminal.read(2**63 - 1)
        session_id = f"{_TERMINAL_EXEC_PREFIX}{uuid.uuid4().hex[:12]}"
        token = uuid.uuid4().hex[:10]
        session = _TerminalExecSession(
            session_id=session_id,
            token=token,
            terminal=terminal,
            command=command,
            cwd=cwd,
            timeout=timeout,
            owner_session_key=owner_session_key,
            cursor=cursor.next_seq,
        )
        async with self._lock:
            active = [
                item
                for item in self._exec_sessions.values()
                if item.terminal.terminal_id == terminal.terminal_id and not item.done
            ]
            if active:
                raise TerminalError(
                    "The shared project terminal is already running an agent command; "
                    "poll it with write_stdin first"
                )
            self._exec_sessions[session_id] = session
        try:
            await terminal.write(
                self._exec_payload(command, cwd, token, terminal.project_path)
            )
            poll = await session.poll(yield_time_ms, max_output_chars)
        except BaseException:
            async with self._lock:
                self._exec_sessions.pop(session_id, None)
            raise
        if poll.done:
            async with self._lock:
                self._exec_sessions.pop(session_id, None)
        return session_id, poll

    async def run_exec(
        self,
        project_path: str | Path,
        *,
        command: str,
        cwd: str,
        timeout: int | None,
        max_output_chars: int,
        owner_session_key: str | None,
    ) -> TerminalExecPoll:
        """Run a one-shot exec command visibly, preserving the legacy result shape."""
        first_wait = 30_000 if timeout is None else min(30_000, max(0, timeout * 1000))
        session_id, poll = await self.start_exec(
            project_path,
            command=command,
            cwd=cwd,
            timeout=timeout,
            yield_time_ms=first_wait,
            max_output_chars=_MAX_EXEC_CAPTURE_CHARS,
            owner_session_key=owner_session_key,
        )
        output_parts = [poll.output] if poll.output else []
        truncated = poll.truncated_chars
        while not poll.done:
            poll = await self.write_exec(
                session_id,
                chars=None,
                close_stdin=False,
                terminate=False,
                yield_time_ms=30_000,
                max_output_chars=_MAX_EXEC_CAPTURE_CHARS,
                owner_session_key=owner_session_key,
            )
            if poll.output:
                output_parts.append(poll.output)
            truncated += poll.truncated_chars
        output, response_truncated = _truncate_terminal_output(
            "".join(output_parts),
            max_output_chars,
        )
        poll.output = output
        poll.truncated_chars = truncated + response_truncated
        return poll

    async def write_exec(
        self,
        session_id: str,
        *,
        chars: str | None,
        close_stdin: bool,
        terminate: bool,
        yield_time_ms: int,
        max_output_chars: int,
        owner_session_key: str | None,
    ) -> TerminalExecPoll:
        async with self._lock:
            session = self._exec_sessions.get(session_id)
        if session is None or (
            session.owner_session_key
            and session.owner_session_key != owner_session_key
        ):
            raise KeyError(session_id)
        if chars:
            await session.write(chars)
        if close_stdin:
            await session.close_stdin()
        if terminate:
            await session.interrupt()
        poll = await session.poll(yield_time_ms, max_output_chars)
        if poll.done:
            async with self._lock:
                self._exec_sessions.pop(session_id, None)
        return poll

    async def list_exec(
        self,
        project_path: str | Path,
        *,
        owner_session_key: str | None,
    ) -> list[TerminalExecInfo]:
        project, _project_key = self._canonical_project(project_path)
        async with self._lock:
            sessions = tuple(self._exec_sessions.values())
        return [
            session.info()
            for session in sessions
            if session.owner_session_key == owner_session_key
            and os.path.normcase(str(session.terminal.project_path))
            == os.path.normcase(str(project))
            and not session.done
        ]

    @staticmethod
    def is_exec_session_id(session_id: str) -> bool:
        return session_id.startswith(_TERMINAL_EXEC_PREFIX)

    async def close(
        self,
        terminal_id: str,
        *,
        project_path: str | Path | None = None,
    ) -> None:
        session = await self._session(terminal_id, project_path=project_path)
        async with self._lock:
            self._sessions.pop(terminal_id, None)
            for exec_id, exec_session in tuple(self._exec_sessions.items()):
                if exec_session.terminal.terminal_id == terminal_id:
                    self._exec_sessions.pop(exec_id, None)
            project_key = os.path.normcase(str(session.project_path))
            if self._project_sessions.get(project_key) == terminal_id:
                self._project_sessions.pop(project_key, None)
        await session.close()

    async def close_all(self) -> None:
        async with self._lock:
            if self._closed and not self._sessions:
                return
            self._closed = True
            sessions = tuple(self._sessions.values())
            self._sessions.clear()
            self._project_sessions.clear()
            self._exec_sessions.clear()
        if sessions:
            await asyncio.gather(*(session.close() for session in sessions), return_exceptions=True)
