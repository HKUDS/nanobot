"""Session support for long-running exec workflows."""

from __future__ import annotations

import asyncio
import time
import uuid
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from nanobot.agent.tools.base import Tool, ToolResult, tool_parameters
from nanobot.agent.tools.context import current_request_session_key
from nanobot.agent.tools.schema import (
    BooleanSchema,
    IntegerSchema,
    StringSchema,
    tool_parameters_schema,
)

DEFAULT_YIELD_MS = 1000
MAX_YIELD_MS = 30_000
DEFAULT_WAIT_FOR_MS = 10_000
MAX_WAIT_FOR_MS = 120_000
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
        self._chunks: list[str] = []
        self._lock = asyncio.Lock()
        self._timed_out = False
        self._stdout_task = asyncio.create_task(self._read_stream(process.stdout, ""))
        self._stderr_task = asyncio.create_task(self._read_stream(process.stderr, "STDERR:\n"))

    async def _read_stream(
        self,
        stream: asyncio.StreamReader | None,
        prefix: str,
    ) -> None:
        if stream is None:
            return
        first = True
        while True:
            chunk = await stream.read(4096)
            if not chunk:
                break
            text = chunk.decode("utf-8", errors="replace")
            if prefix and first:
                text = prefix + text
                first = False
            async with self._lock:
                self._chunks.append(text)

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
            from nanobot.agent.tools.shell import _reap_pid
            _reap_pid(self.process.pid)
        elif yield_time_ms > 0:
            await self._wait_for_buffered_output()

        async with self._lock:
            output = "".join(self._chunks)
            self._chunks.clear()

        output, truncated = _truncate_output(output, max_output_chars)
        return _SessionPoll(
            output=output,
            done=self.process.returncode is not None,
            exit_code=self.process.returncode,
            elapsed_s=max(0.0, time.monotonic() - self.started_at),
            timed_out=self._timed_out,
            terminated=terminated,
            stdin_closed=stdin_closed,
            truncated_chars=truncated,
        )

    async def kill(self) -> None:
        from nanobot.agent.tools.shell import ExecTool

        try:
            if self._process_tree:
                await ExecTool._kill_process_tree(self.process)
            else:
                await ExecTool._kill_process(self.process)
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
                if self._chunks:
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
            sessions = list(self._sessions.values())
            self._sessions.clear()
        results = await asyncio.gather(
            *(session.kill() for session in sessions),
            return_exceptions=True,
        )
        failures = [
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
            victims = []
            for sid, s in list(self._sessions.items()):
                if s.owner_session_key == owner_session_key:
                    victims.append(self._sessions.pop(sid))
        await asyncio.gather(
            *(s.kill() for s in victims),
            return_exceptions=True,
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
            session = self._sessions.pop(session_id)
            await session.kill()

    async def _spawn(
        self,
        command: str,
        cwd: str,
        env: dict[str, str],
        shell_program: str | None,
        login: bool,
    ) -> asyncio.subprocess.Process:
        from nanobot.agent.tools.shell import ExecTool

        return await ExecTool._spawn(
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
    half = max_output_chars // 2
    omitted = len(output) - max_output_chars
    return (
        output[:half]
        + f"\n\n... ({omitted:,} chars truncated) ...\n\n"
        + output[-half:],
        omitted,
    )


def format_session_poll(session_id: str, poll: _SessionPoll) -> str:
    parts = [poll.output] if poll.output else []
    if poll.truncated_chars:
        parts.append(f"(output truncated by {poll.truncated_chars:,} chars)")
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
        session_id=StringSchema("Session id returned by exec when yield_time_ms is used."),
        chars=StringSchema(
            "Bytes/text to write to stdin. Omit or pass an empty string to only poll recent output.",
            nullable=True,
        ),
        close_stdin=BooleanSchema(
            description="Close stdin after writing chars. Useful for commands waiting for EOF.",
            default=False,
        ),
        terminate=BooleanSchema(
            description="Terminate the running exec session.",
            default=False,
        ),
        yield_time_ms=IntegerSchema(
            DEFAULT_YIELD_MS,
            description="Milliseconds to wait before returning recent output (default 1000, max 30000).",
            minimum=0,
            maximum=MAX_YIELD_MS,
        ),
        wait_for=StringSchema(
            "Optional text to wait for in output before returning. "
            "Useful for interactive commands and dev servers.",
            nullable=True,
        ),
        wait_timeout_ms=IntegerSchema(
            DEFAULT_WAIT_FOR_MS,
            description="Maximum milliseconds to wait for wait_for text (default 10000, max 120000).",
            minimum=0,
            maximum=MAX_WAIT_FOR_MS,
            nullable=True,
        ),
        max_output_chars=IntegerSchema(
            DEFAULT_MAX_OUTPUT_CHARS,
            description="Maximum output characters to return from this poll (default 10000, max 50000).",
            minimum=1000,
            maximum=MAX_OUTPUT_CHARS,
        ),
        max_output_tokens=IntegerSchema(
            DEFAULT_MAX_OUTPUT_CHARS,
            description="Compatibility alias for max_output_chars. The current runtime uses a character budget.",
            minimum=1000,
            maximum=MAX_OUTPUT_CHARS,
            nullable=True,
        ),
        required=["session_id"],
    )
)
class WriteStdinTool(Tool):
    """Write to or poll a running exec session."""

    _scopes = {"core", "subagent"}
    config_key = "exec"

    @classmethod
    def config_cls(cls):
        from nanobot.agent.tools.shell import ExecToolConfig

        return ExecToolConfig

    @classmethod
    def enabled(cls, ctx: Any) -> bool:
        return ctx.config.exec.enable

    def __init__(
        self,
        *,
        manager: ExecSessionManager | None = None,
    ) -> None:
        self._manager = manager or DEFAULT_EXEC_SESSION_MANAGER

    @classmethod
    def create(cls, ctx: Any) -> Tool:
        return cls(manager=getattr(ctx, "exec_session_manager", None))

    @property
    def exclusive(self) -> bool:
        return True

    @property
    def name(self) -> str:
        return "write_stdin"

    @property
    def description(self) -> str:
        return (
            "Interact with a running exec session created by exec with "
            "yield_time_ms. Use chars='' to poll without writing, chars to send "
            "stdin, close_stdin=true to send EOF, or terminate=true to stop the "
            "process. Use wait_for with wait_timeout_ms for dev servers, test "
            "watchers, and prompts where you need to wait for expected output. "
            "Do not use this to start new commands; start them with exec."
        )

    async def execute(
        self,
        session_id: str,
        chars: str | None = None,
        close_stdin: bool = False,
        terminate: bool = False,
        yield_time_ms: int | None = None,
        wait_for: str | None = None,
        wait_timeout_ms: int | None = None,
        max_output_chars: int | None = None,
        max_output_tokens: int | None = None,
        **kwargs: Any,
    ) -> str:
        try:
            if max_output_chars is None:
                max_output_chars = max_output_tokens
            output_limit = clamp_session_int(
                max_output_chars,
                DEFAULT_MAX_OUTPUT_CHARS,
                1000,
                MAX_OUTPUT_CHARS,
            )
            if wait_for:
                return await self._wait_for_output(
                    session_id=session_id,
                    chars=chars,
                    close_stdin=close_stdin,
                    terminate=terminate,
                    wait_for=wait_for,
                    wait_timeout_ms=clamp_session_int(
                        wait_timeout_ms,
                        DEFAULT_WAIT_FOR_MS,
                        0,
                        MAX_WAIT_FOR_MS,
                    ),
                    max_output_chars=output_limit,
                )
            poll = await self._manager.write(
                session_id=session_id,
                chars=chars,
                close_stdin=close_stdin,
                terminate=terminate,
                yield_time_ms=clamp_session_int(yield_time_ms, DEFAULT_YIELD_MS, 0, MAX_YIELD_MS),
                max_output_chars=output_limit,
                owner_session_key=current_request_session_key(),
            )
            result = format_session_poll(session_id, poll)
            return ToolResult.error(result) if poll.timed_out else result
        except KeyError:
            return ToolResult.error(f"Error: exec session not found: {session_id!r}")
        except Exception as exc:
            return ToolResult.error(f"Error writing to exec session: {exc}")

    async def _wait_for_output(
        self,
        *,
        session_id: str,
        chars: str | None,
        close_stdin: bool,
        terminate: bool,
        wait_for: str,
        wait_timeout_ms: int,
        max_output_chars: int,
    ) -> str:
        deadline = time.monotonic() + (wait_timeout_ms / 1000)
        aggregate: list[str] = []
        first = True
        poll: _SessionPoll | None = None

        while True:
            remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
            step_ms = min(500, remaining_ms)
            poll = await self._manager.write(
                session_id=session_id,
                chars=chars if first else None,
                close_stdin=close_stdin if first else False,
                terminate=terminate if first else False,
                yield_time_ms=step_ms,
                max_output_chars=max_output_chars,
                owner_session_key=current_request_session_key(),
            )
            first = False
            if poll.output:
                aggregate.append(poll.output)
                joined = "".join(aggregate)
                if wait_for in joined:
                    poll.output = joined
                    result = format_session_poll(session_id, poll)
                    return ToolResult.error(result) if poll.timed_out else result
            if poll.done or remaining_ms <= 0:
                poll.output = "".join(aggregate)
                result = format_session_poll(session_id, poll)
                if wait_for not in poll.output:
                    result += f"\nWait target not observed: {wait_for!r}"
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
    def enabled(cls, ctx: Any) -> bool:
        return ctx.config.exec.enable

    def __init__(
        self,
        *,
        manager: ExecSessionManager | None = None,
    ) -> None:
        self._manager = manager or DEFAULT_EXEC_SESSION_MANAGER

    @classmethod
    def create(cls, ctx: Any) -> Tool:
        return cls(manager=getattr(ctx, "exec_session_manager", None))

    @property
    def name(self) -> str:
        return "list_exec_sessions"

    @property
    def description(self) -> str:
        return (
            "List active long-running exec sessions, including session_id, cwd, "
            "elapsed time, idle time, remaining timeout, and command preview. "
            "Use this to recover a session_id after context shifts before "
            "polling, writing stdin, or terminating with write_stdin."
        )

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
            lines = []
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
