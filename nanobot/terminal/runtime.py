"""Project-scoped pseudo-terminal sessions shared by the WebUI and agent tools."""

from __future__ import annotations

import asyncio
import codecs
import os
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
from typing import Any, Protocol, cast

_IS_WINDOWS = sys.platform == "win32"
_DEFAULT_ROWS = 30
_DEFAULT_COLS = 100
_MIN_ROWS = 2
_MAX_ROWS = 200
_MIN_COLS = 2
_MAX_COLS = 500
_MAX_INPUT_CHARS = 65_536
_DEFAULT_REPLAY_CHARS = 250_000

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


@dataclass(frozen=True, slots=True)
class TerminalRead:
    data: str
    next_seq: int
    running: bool
    exit_code: int | None
    replay_reset: bool = False


class _TerminalBackend(Protocol):
    def read(self, size: int) -> str: ...

    def write(self, data: str) -> None: ...

    def resize(self, rows: int, cols: int) -> None: ...

    def exit_code(self) -> int | None: ...

    def close(self) -> None: ...


class _PosixPtyBackend:
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
    def __init__(self, process: Any) -> None:
        self._process = process
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
    ) -> _WindowsPtyBackend:
        try:
            from winpty import PtyProcess  # pyright: ignore[reportMissingTypeStubs]
        except ImportError as exc:  # pragma: no cover - dependency is platform-specific
            raise TerminalError(
                "Interactive terminals on Windows require the pywinpty package"
            ) from exc
        pty_process = cast(Any, PtyProcess)
        return cls(
            pty_process.spawn(
                argv,
                cwd=str(cwd),
                env=env,
                dimensions=(rows, cols),
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
                return [resolved, "-NoLogo"]
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
        self.shell_argv = list(shell_argv) if shell_argv else None
        self._backend_factory = backend_factory or _spawn_backend
        self._sessions: dict[str, _TerminalSession] = {}
        self._project_sessions: dict[str, str] = {}
        self._lock = asyncio.Lock()
        self._closed = False

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
                argv = list(self.shell_argv or _default_shell_argv())
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

    async def close(
        self,
        terminal_id: str,
        *,
        project_path: str | Path | None = None,
    ) -> None:
        session = await self._session(terminal_id, project_path=project_path)
        async with self._lock:
            self._sessions.pop(terminal_id, None)
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
        if sessions:
            await asyncio.gather(*(session.close() for session in sessions), return_exceptions=True)
