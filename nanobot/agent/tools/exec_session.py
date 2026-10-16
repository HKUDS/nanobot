"""Session support for long-running exec workflows."""

from __future__ import annotations

import asyncio
import codecs
import shlex
import time
import uuid
from collections import deque
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Literal

from loguru import logger

from nanobot.agent.tools.base import Tool, ToolResult, tool_parameters
from nanobot.agent.tools.context import (
    ToolContext,
    current_request_session_key,
    tool_log_content_allowed,
)
from nanobot.agent.tools.schema import (
    BooleanSchema,
    IntegerSchema,
    StringSchema,
    tool_parameters_schema,
)
from nanobot.agent.tools.shell_config import ExecToolConfig
from nanobot.agent.tools.shell_output import ShellOutputFilter

DEFAULT_YIELD_MS = 1000
MAX_YIELD_MS = 30_000
DEFAULT_WAIT_FOR_MS = 10_000
DEFAULT_UNTIL_EXIT_MS = 600_000
MAX_WAIT_FOR_MS = 600_000
DEFAULT_MAX_OUTPUT_CHARS = 10_000
MAX_OUTPUT_CHARS = 50_000


FinishReason = Literal[
    "exit", "max_runtime", "idle_timeout", "cancelled", "owner_closed", "shutdown", "execution_error",
]


@dataclass(slots=True)
class _SessionPoll:
    output: str
    done: bool
    exit_code: int | None
    elapsed_s: float = 0.0
    finish_reason: FinishReason | None = None
    stopping: bool = False
    output_idle_s: float = 0.0
    idle_timeout: int = 0
    remaining_s: float | None = None
    stdin_closed: bool = False
    truncated_chars: int = 0
    output_incomplete: bool = False
    execution_error: str | None = None

    @property
    def failed(self) -> bool:
        return self.timed_out or self.finish_reason == "execution_error"

    @property
    def timed_out(self) -> bool:
        return self.finish_reason in ("max_runtime", "idle_timeout")

    @property
    def terminated(self) -> bool:
        return self.finish_reason in ("cancelled", "owner_closed", "shutdown")


@dataclass(slots=True)
class ExecSessionInfo:
    session_id: str
    command: str
    cwd: str
    elapsed_s: float
    idle_s: float
    remaining_s: float | None
    returncode: int | None
    owner_session_key: str | None = None
    idle_timeout: int = 0
    stopping: bool = False
    finish_reason: FinishReason | None = None
    cleanup_error: str | None = None


class _BoundedOutputBuffer:
    """Keep the first and most recent characters within a fixed budget."""

    def __init__(self, max_chars: int) -> None:
        self.max_chars = max_chars
        self._content = ""
        self._tail: deque[str] = deque()
        self._tail_chars = 0
        self._total_chars = 0
        self._truncated = False

    @property
    def has_output(self) -> bool:
        return self._total_chars > 0

    @property
    def retained_chars(self) -> int:
        return len(self._content) + self._tail_chars

    def append(self, text: str) -> None:
        if not text:
            return
        self._total_chars += len(text)
        if not self._truncated:
            combined = self._content + text
            if len(combined) <= self.max_chars:
                self._content = combined
                return
            head_chars = self.max_chars // 2
            tail_chars = self.max_chars - head_chars
            self._content = combined[:head_chars]
            self._tail.append(combined[-tail_chars:])
            self._tail_chars = tail_chars
            self._truncated = True
            return

        tail_chars = self.max_chars - len(self._content)
        self._tail.append(text)
        self._tail_chars += len(text)
        while self._tail_chars > tail_chars:
            excess = self._tail_chars - tail_chars
            first = self._tail[0]
            if len(first) <= excess:
                self._tail.popleft()
                self._tail_chars -= len(first)
            else:
                self._tail[0] = first[excess:]
                self._tail_chars -= excess

    def drain(self) -> tuple[str, int]:
        output = self._content + "".join(self._tail)
        truncated_chars = self._total_chars - len(output)
        self._content = ""
        self._tail.clear()
        self._tail_chars = 0
        self._total_chars = 0
        self._truncated = False
        return output, truncated_chars


class _ExecSession:
    def __init__(
        self,
        *,
        session_id: str,
        process: asyncio.subprocess.Process,
        command: str,
        cwd: str,
        timeout: int | None,
        owner_session_key: str | None = None,
        process_tree: bool = False,
        idle_timeout: int = 300,
        idle_action: Literal["report", "terminate"] = "report",
        started_at: float | None = None,
    ) -> None:
        self.session_id = session_id
        self.process = process
        self.command = command
        self.cwd = cwd
        self.owner_session_key = owner_session_key
        self._process_tree = process_tree
        self.started_at = time.monotonic() if started_at is None else started_at
        self.deadline = self.started_at + timeout if timeout else float("inf")
        self.last_output_at: float | None = None
        self.finished_at: float | None = None
        self._execution_exited = False
        self.idle_timeout = idle_timeout
        self.idle_action = idle_action
        self.finish_reason: FinishReason | None = None
        self._stop_reason: FinishReason | None = None
        self.cleanup_error: str | None = None
        self._stop_complete = asyncio.Event()
        self._state_changed = asyncio.Event()
        self._output_incomplete = False
        self._execution_error: str | None = None
        self._stdout = _BoundedOutputBuffer(MAX_OUTPUT_CHARS)
        self._stderr = _BoundedOutputBuffer(MAX_OUTPUT_CHARS)
        self._lock = asyncio.Lock()
        self._kill_task: asyncio.Task[None] | None = None
        self._stdout_task = asyncio.create_task(self._read_stream(process.stdout, self._stdout))
        self._stderr_task = asyncio.create_task(self._read_stream(process.stderr, self._stderr))
        self._completion_task = asyncio.create_task(self._complete())
        self._completion_task.add_done_callback(self._on_supervisor_done)
        self._timeout_task = (
            asyncio.create_task(self._watch_timeout())
            if timeout or (idle_timeout and idle_action == "terminate") else None
        )
        if self._timeout_task is not None:
            self._timeout_task.add_done_callback(self._on_supervisor_done)

    @property
    def stopping(self) -> bool:
        return self._stop_reason is not None and self.finished_at is None

    def output_idle_s(self, now: float) -> float:
        anchor = self.started_at if self.last_output_at is None else self.last_output_at
        return max(0.0, now - anchor)

    def remaining_s(self, now: float) -> float | None:
        return max(0.0, self.deadline - now) if self.deadline != float("inf") else None

    def _on_supervisor_done(self, task: asyncio.Task[None]) -> None:
        if not task.cancelled() and (error := task.exception()) is not None:
            if task is self._completion_task:
                self.cleanup_error = str(error)
                self._state_changed.set()
            logger.opt(exception=error if tool_log_content_allowed() else False).error(
                "Exec session supervision failed for {}", self.session_id,
            )

    async def _complete(self) -> None:
        await self.process.wait()
        # Root exit is not completion while a worker still holds captured pipes.
        readers = asyncio.gather(self._stdout_task, self._stderr_task)
        stopped = asyncio.create_task(self._stop_complete.wait())
        try:
            await asyncio.wait({readers, stopped}, return_when=asyncio.FIRST_COMPLETED)
            if stopped.done():
                try:
                    await asyncio.wait_for(readers, timeout=2.0)
                except asyncio.TimeoutError:
                    self._output_incomplete = True
            else:
                await readers
            self._execution_exited = True
            if self._stop_reason is not None:
                await stopped
        finally:
            stopped.cancel()
            await asyncio.gather(stopped, return_exceptions=True)
        from nanobot.agent.tools.shell import ExecTool, _reap_pid  # pyright: ignore[reportPrivateUsage]

        ExecTool._release_process_tree(self.process)  # pyright: ignore[reportPrivateUsage]
        _reap_pid(self.process.pid)
        self.finish_reason = self._stop_reason or "exit"
        self.finished_at = time.monotonic()
        self._state_changed.set()

    async def wait_exit(self) -> None:
        while self.finished_at is None:
            if self.cleanup_error is not None:
                raise RuntimeError(f"session {self.session_id} cleanup failed: {self.cleanup_error}")
            self._state_changed.clear()
            await self._state_changed.wait()

    async def _watch_timeout(self) -> None:
        """Supervise execution budgets independently of tool waits and log reads."""
        while not self._completion_task.done():
            now = time.monotonic()
            deadline = self.deadline
            if self.idle_timeout and self.idle_action == "terminate":
                anchor = self.started_at if self.last_output_at is None else self.last_output_at
                deadline = min(deadline, anchor + self.idle_timeout)
            done, _ = await asyncio.wait(
                {self._completion_task}, timeout=max(0.0, deadline - now),
            )
            if done:
                return
            if self._execution_exited:
                await asyncio.shield(self._completion_task)
                return
            now = time.monotonic()
            if now >= self.deadline:
                await self.kill("max_runtime")
                return
            if self.idle_timeout and self.idle_action == "terminate":
                if self.output_idle_s(now) >= self.idle_timeout:
                    await self.kill("idle_timeout")
                    return

    async def _read_stream(
        self,
        stream: asyncio.StreamReader | None,
        buffer: _BoundedOutputBuffer,
    ) -> None:
        if stream is None:
            return
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        output_filter = ShellOutputFilter()
        try:
            while True:
                chunk = await stream.read(4096)
                if chunk:
                    self.last_output_at = time.monotonic()
                text = output_filter.feed(decoder.decode(chunk, final=not chunk))
                async with self._lock:
                    buffer.append(text)
                if not chunk:
                    break
        except Exception as exc:
            self._output_incomplete = True
            self._execution_error = str(exc)
            await self._begin_stop("execution_error")

    async def write(self, chars: str) -> str | None:
        if self.process.returncode is not None:
            return "session has already exited"
        if self.process.stdin is None:
            return "session stdin is not available"
        try:
            self.process.stdin.write(chars.encode("utf-8"))
            await self.process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            return "session stdin is closed"
        return None

    async def close_stdin(self) -> str | None:
        if self.process.returncode is not None:
            return "session has already exited"
        if self.process.stdin is None:
            return "session stdin is not available"
        self.process.stdin.close()
        with suppress(BrokenPipeError, ConnectionResetError):
            await self.process.stdin.wait_closed()
        return None

    async def poll(
        self,
        yield_time_ms: int,
        max_output_chars: int,
        *,
        stdin_closed: bool = False,
    ) -> _SessionPoll:
        if yield_time_ms > 0 and not self._completion_task.done():
            await asyncio.wait(
                {self._completion_task}, timeout=min(yield_time_ms, MAX_YIELD_MS) / 1000,
            )
        if self._completion_task.done():
            await asyncio.shield(self._completion_task)
        if self.cleanup_error is not None:
            raise RuntimeError(f"session {self.session_id} cleanup failed: {self.cleanup_error}")

        async with self._lock:
            stdout, stdout_truncated = self._stdout.drain()
            stderr, stderr_truncated = self._stderr.drain()

        output_parts = [stdout] if stdout else []
        if stderr:
            output_parts.append(f"STDERR:\n{stderr}")
        output = "\n".join(output_parts)
        output, response_truncated = _truncate_output(output, max_output_chars)
        now = time.monotonic()
        return _SessionPoll(
            output=output,
            done=self.finished_at is not None,
            exit_code=self.process.returncode,
            elapsed_s=max(0.0, (self.finished_at or now) - self.started_at),
            finish_reason=self.finish_reason,
            stopping=self.stopping,
            output_idle_s=self.output_idle_s(now),
            idle_timeout=self.idle_timeout,
            remaining_s=self.remaining_s(now),
            stdin_closed=stdin_closed,
            truncated_chars=stdout_truncated + stderr_truncated + response_truncated,
            output_incomplete=self._output_incomplete,
            execution_error=self._execution_error,
        )

    async def kill(self, reason: FinishReason = "cancelled") -> None:
        await self._begin_stop(reason)
        await asyncio.shield(self._completion_task)

    async def _begin_stop(self, reason: FinishReason) -> None:
        if self.finished_at is not None:
            return
        if self._execution_exited and self._stop_reason is None:
            return
        if self._stop_reason is None:
            self._stop_reason = reason
        if self._kill_task is None:
            self.cleanup_error = None
            self._kill_task = asyncio.create_task(self._kill())
            self._kill_task.add_done_callback(self._on_kill_done)
        await asyncio.shield(self._kill_task)

    def _on_kill_done(self, task: asyncio.Task[None]) -> None:
        error = None if task.cancelled() else task.exception()
        if error is not None:
            self.cleanup_error = str(error)
            self._state_changed.set()
            logger.opt(exception=error if tool_log_content_allowed() else False).error(
                "Failed to terminate exec session {}", self.session_id,
            )
        if (task.cancelled() or error is not None) and self._kill_task is task:
            self._kill_task = None

    async def _kill(self) -> None:
        from nanobot.agent.tools.shell import ExecTool

        if self._process_tree:
            await ExecTool._kill_process_tree(self.process)  # pyright: ignore[reportPrivateUsage]
        else:
            await ExecTool._kill_process(self.process)  # pyright: ignore[reportPrivateUsage]
        self._stop_complete.set()


class ExecSessionManager:
    def __init__(self, *, max_sessions: int = 8, result_retention: int = 1800) -> None:
        self.max_sessions = max_sessions
        self.result_retention = result_retention
        self._sessions: dict[str, _ExecSession] = {}
        self._starting: dict[str, tuple[str | None, asyncio.Task[_ExecSession]]] = {}
        self._lock = asyncio.Lock()
        self._closed = False

    async def start(
        self,
        *,
        command: str | list[str],
        cwd: str,
        env: dict[str, str],
        timeout: int | None,
        shell_program: str | None,
        login: bool,
        yield_time_ms: int,
        max_output_chars: int,
        owner_session_key: str | None = None,
        idle_timeout: int = 300,
        idle_action: Literal["report", "terminate"] = "report",
        stdin: int = asyncio.subprocess.PIPE,
        until_exit: bool = False,
    ) -> tuple[str, _SessionPoll]:
        async with self._lock:
            if self._closed:
                raise RuntimeError("exec session manager is closed")
            self._cleanup_finished_locked()
            if len(self._sessions) + len(self._starting) >= self.max_sessions:
                finished = [
                    (session.finished_at, session_id)
                    for session_id, session in self._sessions.items()
                    if session.finished_at is not None
                ]
                if not finished:
                    raise RuntimeError(f"maximum exec sessions reached ({self.max_sessions})")
                self._sessions.pop(min(finished)[1])
            session_id = uuid.uuid4().hex[:12]
            launch = asyncio.create_task(self._launch(
                session_id=session_id, command=command, cwd=cwd, env=env,
                timeout=timeout, shell_program=shell_program, login=login,
                owner_session_key=owner_session_key, idle_timeout=idle_timeout,
                idle_action=idle_action, stdin=stdin,
            ))
            self._starting[session_id] = (owner_session_key, launch)
        try:
            session = await launch
            if until_exit:
                await session.wait_exit()
            poll = await session.poll(yield_time_ms, max_output_chars)
        except asyncio.CancelledError:
            if launch.done() and not launch.cancelled() and launch.exception() is None:
                await launch.result().kill("cancelled")
                async with self._lock:
                    self._sessions.pop(session_id, None)
            raise
        finally:
            async with self._lock:
                self._starting.pop(session_id, None)
        if poll.done:
            async with self._lock:
                self._sessions.pop(session_id, None)
        return session_id, poll

    async def _launch(
        self, *, session_id: str, command: str | list[str], cwd: str,
        env: dict[str, str], timeout: int | None, shell_program: str | None,
        login: bool, owner_session_key: str | None, idle_timeout: int,
        idle_action: Literal["report", "terminate"], stdin: int,
    ) -> _ExecSession:
        session: _ExecSession | None = None
        try:
            started_at = time.monotonic()
            process = await self._spawn(command, cwd, env, shell_program, login, stdin=stdin)
            session = _ExecSession(
                session_id=session_id, process=process,
                command=shlex.join(command) if isinstance(command, list) else command,
                cwd=cwd, timeout=timeout, owner_session_key=owner_session_key,
                process_tree=True, idle_timeout=idle_timeout, idle_action=idle_action,
                started_at=started_at,
            )
            async with self._lock:
                if self._closed or session_id not in self._starting:
                    raise RuntimeError("exec session owner closed during startup")
                self._sessions[session_id] = session
            return session
        except BaseException:
            if session is not None:
                try:
                    await session.kill("owner_closed")
                except BaseException:
                    async with self._lock:
                        self._sessions[session_id] = session
                    raise
            raise
        finally:
            async with self._lock:
                self._starting.pop(session_id, None)

    async def write(
        self,
        *,
        session_id: str,
        chars: str | None,
        close_stdin: bool,
        terminate: bool,
        yield_time_ms: int,
        max_output_chars: int,
        owner_session_key: str | None = None,
    ) -> _SessionPoll:
        async with self._lock:
            self._cleanup_finished_locked()
            session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(session_id)
        if session.owner_session_key and session.owner_session_key != owner_session_key:
            raise KeyError(session_id)

        if chars:
            error = await session.write(chars)
            if error:
                raise RuntimeError(error)
        stdin_closed = False
        if close_stdin:
            error = await session.close_stdin()
            if error:
                raise RuntimeError(error)
            stdin_closed = True
        if terminate:
            await session.kill()
        poll = await session.poll(
            yield_time_ms,
            max_output_chars,
            stdin_closed=stdin_closed,
        )
        if poll.done:
            async with self._lock:
                self._sessions.pop(session_id, None)
        return poll

    async def list(self, *, owner_session_key: str | None = None) -> list[ExecSessionInfo]:
        async with self._lock:
            self._cleanup_finished_locked()
            now = time.monotonic()
            return [
                ExecSessionInfo(
                    session_id=session_id,
                    command=session.command,
                    cwd=session.cwd,
                    elapsed_s=max(0.0, now - session.started_at),
                    idle_s=session.output_idle_s(now),
                    remaining_s=session.remaining_s(now),
                    returncode=session.process.returncode,
                    owner_session_key=session.owner_session_key,
                    idle_timeout=session.idle_timeout,
                    stopping=session.stopping,
                    finish_reason=session.finish_reason,
                    cleanup_error=session.cleanup_error,
                )
                for session_id, session in sorted(self._sessions.items())
                if session.owner_session_key == owner_session_key
            ]

    async def close_all(self) -> int:
        """Terminate and remove all active sessions during shutdown."""
        async with self._lock:
            self._closed = True
            sessions: list[_ExecSession] = list(self._sessions.values())
            self._sessions.clear()
            launches = [task for _, task in self._starting.values()]
            self._starting.clear()
        return await self._stop_owned(sessions, launches, "shutdown")

    async def terminate_by_owner(self, owner_session_key: str) -> int:
        """Terminate all sessions owned by owner_session_key. Returns count."""
        async with self._lock:
            victims: list[_ExecSession] = []
            for sid, s in list(self._sessions.items()):
                if s.owner_session_key == owner_session_key:
                    victims.append(self._sessions.pop(sid))
            launches = [
                task for owner, task in self._starting.values() if owner == owner_session_key
            ]
            for sid, (owner, _) in list(self._starting.items()):
                if owner == owner_session_key:
                    self._starting.pop(sid)
        return await self._stop_owned(victims, launches, "owner_closed")

    async def _stop_owned(
        self, sessions: list[_ExecSession], launches: list[asyncio.Task[_ExecSession]],
        reason: FinishReason,
    ) -> int:
        results: list[None | BaseException] = list(await asyncio.gather(
            *(session.kill(reason) for session in sessions),
            self._cancel_launches(launches),
            return_exceptions=True,
        ))
        startup_error = results.pop()
        failures = [
            (session, result)
            for session, result in zip(sessions, results, strict=True)
            if isinstance(result, BaseException)
        ]
        if failures:
            async with self._lock:
                for session, _ in failures:
                    self._sessions[session.session_id] = session
        errors = [result for _, result in failures]
        if isinstance(startup_error, BaseException):
            errors.append(startup_error)
        if len(errors) == 1:
            raise errors[0]
        if errors:
            raise BaseExceptionGroup("failed to stop owned exec sessions", errors)
        return len(sessions) + len(launches)

    @staticmethod
    async def _cancel_launches(launches: list[asyncio.Task[_ExecSession]]) -> None:
        for task in launches:
            task.cancel()
        results = await asyncio.gather(*launches, return_exceptions=True)
        errors = [result for result in results if isinstance(result, Exception)]
        if errors:
            raise ExceptionGroup("failed to cancel exec startup", errors)

    def _cleanup_finished_locked(self) -> None:
        now = time.monotonic()
        stale = [
            session_id
            for session_id, session in self._sessions.items()
            if session.finished_at is not None
            and now - session.finished_at > self.result_retention
        ]
        for session_id in stale:
            self._sessions.pop(session_id)

    async def _spawn(
        self,
        command: str | list[str],
        cwd: str,
        env: dict[str, str],
        shell_program: str | None,
        login: bool,
        *,
        stdin: int = asyncio.subprocess.PIPE,
    ) -> asyncio.subprocess.Process:
        from nanobot.agent.tools.shell import ExecTool

        return await ExecTool._spawn(  # pyright: ignore[reportPrivateUsage]
            command, cwd, env, shell_program, login,
            stdin=stdin,
            process_tree=True,
        )


DEFAULT_EXEC_SESSION_MANAGER = ExecSessionManager()


def clamp_session_int(value: int | None, default: int, minimum: int, maximum: int) -> int:
    if value is None:
        return default
    return min(max(value, minimum), maximum)


def _truncate_output(output: str, max_output_chars: int) -> tuple[str, int]:
    if len(output) <= max_output_chars:
        return output, 0
    head_chars = max_output_chars // 2
    tail_chars = max_output_chars - head_chars
    omitted = len(output) - max_output_chars
    return output[:head_chars] + output[-tail_chars:], omitted


def format_session_poll(session_id: str, poll: _SessionPoll) -> str:
    parts = [poll.output] if poll.output else []
    if poll.truncated_chars:
        parts.append(f"({poll.truncated_chars:,} chars truncated from output)")
    if poll.finish_reason == "max_runtime":
        parts.append("Error: Command timed out; session was terminated. Reason: max_runtime.")
    elif poll.finish_reason == "idle_timeout":
        parts.append("Error: Output silence limit reached; session was terminated. Reason: idle_timeout.")
    elif poll.terminated:
        parts.append(f"Session terminated. Reason: {poll.finish_reason}.")
    elif poll.finish_reason == "execution_error":
        parts.append(f"Error: Command output failed: {poll.execution_error}. Reason: execution_error.")
    if poll.output_incomplete:
        parts.append("Output collection ended before EOF; output may be incomplete.")
    if poll.stdin_closed:
        parts.append("Stdin closed.")
    if poll.done:
        parts.append(f"Exit code: {poll.exit_code}")
    else:
        state = "stopping" if poll.stopping else "running"
        parts.append(f"Process {state}. session_id: {session_id}")
        if poll.idle_timeout and poll.output_idle_s >= poll.idle_timeout:
            parts.append(
                f"Output silent for {poll.output_idle_s:.1f}s; "
                "no stdout/stderr bytes observed. This does not establish a stall."
            )
        remaining = "unlimited" if poll.remaining_s is None else f"{poll.remaining_s:.1f}s"
        parts.append(f"Runtime remaining: {remaining}")
    parts.append(f"Elapsed: {poll.elapsed_s:.1f}s")
    return "\n".join(parts) if parts else "(no output yet)"


@tool_parameters(
    tool_parameters_schema(
        session_id=StringSchema("Session ID returned by exec."),
        input=StringSchema(
            "Text to send to stdin; omit to poll output.",
            nullable=True,
        ),
        close_stdin=BooleanSchema(
            description="Close stdin after sending input.",
            default=False,
        ),
        terminate=BooleanSchema(
            description="Terminate the session; use alone.",
            default=False,
        ),
        wait_for=StringSchema(
            "Return when this text appears in output.",
            min_length=1,
            nullable=True,
        ),
        until_exit=BooleanSchema(
            description="Wait for the process to exit.",
            default=False,
        ),
        timeout_ms=IntegerSchema(
            description="Maximum wait: 1s normally, 10s for wait_for, 10m for until_exit.",
            minimum=0,
            maximum=MAX_WAIT_FOR_MS,
            nullable=True,
        ),
        required=["session_id"],
    )
)
class ExecSessionTool(Tool):
    """Interact with or wait for a running exec session."""

    _scopes = {"core", "subagent"}
    config_key = "exec"

    @classmethod
    def config_cls(cls):
        return ExecToolConfig

    @classmethod
    def enabled(cls, ctx: ToolContext) -> bool:
        return ctx.config.exec.enable

    def __init__(
        self,
        *,
        manager: ExecSessionManager | None = None,
    ) -> None:
        self._manager = manager or DEFAULT_EXEC_SESSION_MANAGER

    @classmethod
    def create(cls, ctx: ToolContext) -> Tool:
        return cls(manager=ctx.exec_session_manager)

    @property
    def exclusive(self) -> bool:
        return True

    @property
    def name(self) -> str:
        return "exec_session"

    @property
    def description(self) -> str:
        return "Manage a session returned by exec."

    async def execute(  # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        session_id: str,
        input: str | None = None,
        close_stdin: bool = False,
        terminate: bool = False,
        wait_for: str | None = None,
        until_exit: bool = False,
        timeout_ms: int | None = None,
        **kwargs: Any,
    ) -> str:
        try:
            if wait_for == "":
                return ToolResult.error("Error: wait_for must not be empty.")
            if wait_for is not None and until_exit:
                return ToolResult.error(
                    "Error: wait_for and until_exit are mutually exclusive."
                )
            if terminate:
                if any(
                    (
                        input is not None,
                        close_stdin,
                        wait_for is not None,
                        until_exit,
                        timeout_ms is not None,
                    )
                ):
                    return ToolResult.error("Error: terminate must be used alone.")
                poll = await self._manager.write(
                    session_id=session_id,
                    chars=None,
                    close_stdin=False,
                    terminate=True,
                    yield_time_ms=0,
                    max_output_chars=DEFAULT_MAX_OUTPUT_CHARS,
                    owner_session_key=current_request_session_key(),
                )
                result = format_session_poll(session_id, poll)
                return ToolResult.error(result) if poll.failed else result

            default_timeout_ms = (
                DEFAULT_UNTIL_EXIT_MS
                if until_exit
                else DEFAULT_WAIT_FOR_MS
                if wait_for is not None
                else DEFAULT_YIELD_MS
            )
            return await self._wait(
                session_id=session_id,
                input=input,
                close_stdin=close_stdin,
                wait_for=wait_for,
                until_exit=until_exit,
                timeout_ms=clamp_session_int(
                    timeout_ms,
                    default_timeout_ms,
                    0,
                    MAX_WAIT_FOR_MS,
                ),
            )
        except KeyError:
            return ToolResult.error(f"Error: exec session not found: {session_id!r}")
        except Exception as exc:
            return ToolResult.error(f"Error managing exec session: {exc}")

    async def _wait(
        self,
        *,
        session_id: str,
        input: str | None,
        close_stdin: bool,
        wait_for: str | None,
        until_exit: bool,
        timeout_ms: int,
    ) -> str:
        deadline = time.monotonic() + (timeout_ms / 1000)
        aggregate = _BoundedOutputBuffer(DEFAULT_MAX_OUTPUT_CHARS)
        upstream_truncated = 0
        search_overlap = ""
        first = True
        matched = False

        while True:
            remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
            step_ms = min(MAX_YIELD_MS if until_exit else 500, remaining_ms)
            poll = await self._manager.write(
                session_id=session_id,
                chars=input if first else None,
                close_stdin=close_stdin if first else False,
                terminate=False,
                yield_time_ms=step_ms,
                max_output_chars=MAX_OUTPUT_CHARS,
                owner_session_key=current_request_session_key(),
            )
            first = False
            upstream_truncated += poll.truncated_chars
            if poll.output:
                aggregate.append(poll.output)
                if wait_for is not None:
                    searchable = search_overlap + poll.output
                    matched = wait_for in searchable
                    overlap_chars = len(wait_for) - 1
                    search_overlap = searchable[-overlap_chars:] if overlap_chars else ""

            expired = time.monotonic() >= deadline
            has_activity = wait_for is None and not until_exit and bool(poll.output)
            if poll.done or matched or has_activity or expired:
                poll.output, aggregate_truncated = aggregate.drain()
                poll.truncated_chars = upstream_truncated + aggregate_truncated
                result = format_session_poll(session_id, poll)
                if wait_for is not None and not matched:
                    result += f"\nWait target not observed: {wait_for!r}"
                if expired and not poll.done and not matched:
                    result += (
                        f"\nWait timed out after {timeout_ms / 1000:g}s; "
                        "session remains active."
                    )
                return ToolResult.error(result) if poll.failed else result


@tool_parameters(tool_parameters_schema())
class ListExecSessionsTool(Tool):
    """List active exec sessions."""

    _scopes = {"core", "subagent"}
    config_key = "exec"

    @classmethod
    def config_cls(cls):
        return ExecToolConfig

    @classmethod
    def enabled(cls, ctx: ToolContext) -> bool:
        return ctx.config.exec.enable

    def __init__(
        self,
        *,
        manager: ExecSessionManager | None = None,
    ) -> None:
        self._manager = manager or DEFAULT_EXEC_SESSION_MANAGER

    @classmethod
    def create(cls, ctx: ToolContext) -> Tool:
        return cls(manager=ctx.exec_session_manager)

    @property
    def name(self) -> str:
        return "list_exec_sessions"

    @property
    def description(self) -> str:
        return "List active exec sessions."

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, **kwargs: Any) -> str:
        try:
            sessions = await self._manager.list(
                owner_session_key=current_request_session_key(),
            )
            if not sessions:
                return "No active exec sessions."
            lines: list[str] = []
            for info in sessions:
                command = " ".join(info.command.split())
                if len(command) > 120:
                    command = command[:119] + "..."
                status = "finished" if info.finish_reason is not None else (
                    "stopping" if info.stopping else "running"
                )
                remaining = "unlimited" if info.remaining_s is None else f"{info.remaining_s:.1f}s"
                silent = bool(info.idle_timeout and info.idle_s >= info.idle_timeout)
                lines.append(
                    f"{info.session_id} | {status} | elapsed={info.elapsed_s:.1f}s "
                    f"| output_idle={info.idle_s:.1f}s | silent={str(silent).lower()} "
                    f"| remaining={remaining} | reason={info.finish_reason or '-'} "
                    f"| cwd={info.cwd} | {command}"
                )
                if info.cleanup_error is not None:
                    lines.append(f"Cleanup failed: {info.cleanup_error}")
            return "\n".join(lines)
        except Exception as exc:
            return ToolResult.error(f"Error listing exec sessions: {exc}")
