"""Session support for long-running exec workflows."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections import deque
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from nanobot.agent.tools.base import Tool, ToolResult, tool_parameters
from nanobot.agent.tools.context import ToolContext, current_request_session_key
from nanobot.agent.tools.schema import (
    BooleanSchema,
    IntegerSchema,
    StringSchema,
    tool_parameters_schema,
)

DEFAULT_YIELD_MS = 1000
MAX_YIELD_MS = 30_000
DEFAULT_WAIT_FOR_MS = 10_000
DEFAULT_UNTIL_EXIT_MS = 600_000
MAX_WAIT_FOR_MS = 600_000
DEFAULT_MAX_OUTPUT_CHARS = 10_000
MAX_OUTPUT_CHARS = 50_000
OUTPUT_DRAIN_GRACE_S = 0.1


@dataclass(slots=True)
class _SessionPoll:
    output: str
    done: bool
    exit_code: int | None
    elapsed_s: float = 0.0
    timed_out: bool = False
    terminated: bool = False
    stdin_closed: bool = False
    truncated_chars: int = 0


@dataclass(slots=True)
class ExecSessionInfo:
    session_id: str
    command: str
    cwd: str
    elapsed_s: float
    idle_s: float
    remaining_s: float
    returncode: int | None
    owner_session_key: str | None = None


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
    ) -> None:
        self.session_id = session_id
        self.process = process
        self.command = command
        self.cwd = cwd
        self.owner_session_key = owner_session_key
        self._process_tree = process_tree
        self.started_at = time.monotonic()
        # timeout None/0 means no limit; an infinite deadline is never reached.
        self.deadline = time.monotonic() + timeout if timeout else float("inf")
        self.last_access = time.monotonic()
        self._stdout = _BoundedOutputBuffer(MAX_OUTPUT_CHARS)
        self._stderr = _BoundedOutputBuffer(MAX_OUTPUT_CHARS)
        self._lock = asyncio.Lock()
        self._timed_out = False
        self._stdout_task = asyncio.create_task(self._read_stream(process.stdout, self._stdout))
        self._stderr_task = asyncio.create_task(self._read_stream(process.stderr, self._stderr))

    async def _read_stream(
        self,
        stream: asyncio.StreamReader | None,
        buffer: _BoundedOutputBuffer,
    ) -> None:
        if stream is None:
            return
        while True:
            chunk = await stream.read(4096)
            if not chunk:
                break
            text = chunk.decode("utf-8", errors="replace")
            async with self._lock:
                buffer.append(text)

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
        terminated: bool = False,
        stdin_closed: bool = False,
    ) -> _SessionPoll:
        self.last_access = time.monotonic()
        if yield_time_ms > 0 and self.process.returncode is None:
            wait_s = min(yield_time_ms, MAX_YIELD_MS) / 1000
            remaining_s = self.deadline - time.monotonic()
            if remaining_s <= 0:
                wait_s = 0
            else:
                wait_s = min(wait_s, remaining_s)
            if wait_s > 0:
                with suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self.process.wait(), timeout=wait_s)

        if self.process.returncode is None and time.monotonic() >= self.deadline:
            self._timed_out = True
            await self.kill()

        if self.process.returncode is not None:
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(
                    asyncio.gather(self._stdout_task, self._stderr_task),
                    timeout=2.0,
                )
            # Safety-net reap after normal exit.
            from nanobot.agent.tools.shell import (  # pyright: ignore[reportPrivateUsage]
                ExecTool,
                _reap_pid,  # pyright: ignore[reportPrivateUsage]
            )
            ExecTool._release_process_tree(self.process)  # pyright: ignore[reportPrivateUsage]
            _reap_pid(self.process.pid)  # pyright: ignore[reportPrivateUsage]
        elif yield_time_ms > 0:
            await self._wait_for_buffered_output()

        async with self._lock:
            stdout, stdout_truncated = self._stdout.drain()
            stderr, stderr_truncated = self._stderr.drain()

        output_parts = [stdout] if stdout else []
        if stderr:
            output_parts.append(f"STDERR:\n{stderr}")
        output = "\n".join(output_parts)
        output, response_truncated = _truncate_output(output, max_output_chars)
        return _SessionPoll(
            output=output,
            done=self.process.returncode is not None,
            exit_code=self.process.returncode,
            elapsed_s=max(0.0, time.monotonic() - self.started_at),
            timed_out=self._timed_out,
            terminated=terminated,
            stdin_closed=stdin_closed,
            truncated_chars=stdout_truncated + stderr_truncated + response_truncated,
        )

    async def kill(self) -> None:
        from nanobot.agent.tools.shell import ExecTool

        try:
            if self._process_tree:
                await ExecTool._kill_process_tree(self.process)  # pyright: ignore[reportPrivateUsage]
            else:
                await ExecTool._kill_process(self.process)  # pyright: ignore[reportPrivateUsage]
        finally:
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(
                    asyncio.gather(
                        self._stdout_task,
                        self._stderr_task,
                        return_exceptions=True,
                    ),
                    timeout=2.0,
                )

    async def _wait_for_buffered_output(self) -> None:
        deadline = time.monotonic() + OUTPUT_DRAIN_GRACE_S
        while time.monotonic() < deadline:
            async with self._lock:
                if self._stdout.has_output or self._stderr.has_output:
                    return
            await asyncio.sleep(0.01)


class ExecSessionManager:
    def __init__(self, *, max_sessions: int = 8, idle_timeout: int = 1800) -> None:
        self.max_sessions = max_sessions
        self.idle_timeout = idle_timeout
        self._sessions: dict[str, _ExecSession] = {}
        self._lock = asyncio.Lock()
        self._closed = False

    async def start(
        self,
        *,
        command: str,
        cwd: str,
        env: dict[str, str],
        timeout: int | None,
        shell_program: str | None,
        login: bool,
        yield_time_ms: int,
        max_output_chars: int,
        owner_session_key: str | None = None,
    ) -> tuple[str, _SessionPoll]:
        async with self._lock:
            if self._closed:
                raise RuntimeError("exec session manager is closed")
            await self._cleanup_locked()
            if len(self._sessions) >= self.max_sessions:
                raise RuntimeError(f"maximum exec sessions reached ({self.max_sessions})")
            process = await self._spawn(command, cwd, env, shell_program, login)
            session_id = uuid.uuid4().hex[:12]
            session = _ExecSession(
                session_id=session_id,
                process=process,
                command=command,
                cwd=cwd,
                timeout=timeout,
                owner_session_key=owner_session_key,
                process_tree=True,
            )
            self._sessions[session_id] = session

        poll = await session.poll(yield_time_ms, max_output_chars)
        if poll.done:
            async with self._lock:
                self._sessions.pop(session_id, None)
        return session_id, poll

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
            await self._cleanup_locked()
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
            terminated=terminate,
            stdin_closed=stdin_closed,
        )
        if poll.done:
            async with self._lock:
                self._sessions.pop(session_id, None)
        return poll

    async def list(self, *, owner_session_key: str | None = None) -> list[ExecSessionInfo]:
        async with self._lock:
            await self._cleanup_locked()
            now = time.monotonic()
            return [
                ExecSessionInfo(
                    session_id=session_id,
                    command=session.command,
                    cwd=session.cwd,
                    elapsed_s=max(0.0, now - session.started_at),
                    idle_s=max(0.0, now - session.last_access),
                    remaining_s=max(0.0, session.deadline - now),
                    returncode=session.process.returncode,
                    owner_session_key=session.owner_session_key,
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
        results: list[None | BaseException] = list(await asyncio.gather(
            *(session.kill() for session in sessions),
            return_exceptions=True,
        ))
        failures: list[tuple[_ExecSession, BaseException]] = [
            (session, result)
            for session, result in zip(sessions, results, strict=True)
            if isinstance(result, BaseException)
        ]
        if failures:
            async with self._lock:
                for session, _ in failures:
                    self._sessions[session.session_id] = session
            if len(failures) == 1:
                raise failures[0][1]
            raise BaseExceptionGroup(
                "failed to close exec sessions",
                [result for _, result in failures],
            )
        return len(sessions)

    async def terminate_by_owner(self, owner_session_key: str) -> int:
        """Terminate all sessions owned by owner_session_key. Returns count."""
        async with self._lock:
            victims: list[_ExecSession] = []
            for sid, s in list(self._sessions.items()):
                if s.owner_session_key == owner_session_key:
                    victims.append(self._sessions.pop(sid))
        results: list[None | BaseException] = list(await asyncio.gather(
            *(s.kill() for s in victims),
            return_exceptions=True,
        ))
        failures: list[tuple[_ExecSession, BaseException]] = [
            (session, result)
            for session, result in zip(victims, results, strict=True)
            if isinstance(result, BaseException)
        ]
        if failures:
            async with self._lock:
                for session, _ in failures:
                    self._sessions[session.session_id] = session
            if len(failures) == 1:
                raise failures[0][1]
            raise BaseExceptionGroup(
                "failed to terminate exec sessions by owner",
                [result for _, result in failures],
            )
        return len(victims)

    async def _cleanup_locked(self) -> None:
        now = time.monotonic()
        stale = [
            session_id
            for session_id, session in self._sessions.items()
            if now - session.last_access > self.idle_timeout
        ]
        for session_id in stale:
            session = self._sessions[session_id]
            await session.kill()
            self._sessions.pop(session_id, None)

    async def _spawn(
        self,
        command: str,
        cwd: str,
        env: dict[str, str],
        shell_program: str | None,
        login: bool,
    ) -> asyncio.subprocess.Process:
        from nanobot.agent.tools.shell import ExecTool

        return await ExecTool._spawn(  # pyright: ignore[reportPrivateUsage]
            command, cwd, env, shell_program, login,
            stdin=asyncio.subprocess.PIPE,
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
    if poll.timed_out:
        parts.append("Error: Command timed out; session was terminated.")
    if poll.terminated and not poll.timed_out:
        parts.append("Session terminated.")
    if poll.stdin_closed:
        parts.append("Stdin closed.")
    if poll.done:
        parts.append(f"Exit code: {poll.exit_code}")
    else:
        parts.append(f"Process running. session_id: {session_id}")
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
        from nanobot.agent.tools.shell import ExecToolConfig

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
                return ToolResult.error(result) if poll.timed_out else result

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
                elif until_exit and not poll.done:
                    result += (
                        f"\nWait timed out after {timeout_ms / 1000:g}s; "
                        "session remains active."
                    )
                return ToolResult.error(result) if poll.timed_out else result


@tool_parameters(tool_parameters_schema())
class ListExecSessionsTool(Tool):
    """List active exec sessions."""

    _scopes = {"core", "subagent"}
    config_key = "exec"

    @classmethod
    def config_cls(cls):
        from nanobot.agent.tools.shell import ExecToolConfig

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
                status = "exited" if info.returncode is not None else "running"
                lines.append(
                    f"{info.session_id} | {status} | elapsed={info.elapsed_s:.1f}s "
                    f"| idle={info.idle_s:.1f}s | remaining={info.remaining_s:.1f}s "
                    f"| cwd={info.cwd} | {command}"
                )
            return "\n".join(lines)
        except Exception as exc:
            return ToolResult.error(f"Error listing exec sessions: {exc}")
