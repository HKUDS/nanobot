from __future__ import annotations

import asyncio
import queue
import re
import sys
from pathlib import Path

import pytest

from nanobot.terminal.runtime import TerminalError, TerminalSessionManager


class _FakeBackend:
    def __init__(self) -> None:
        self.output: queue.Queue[str | None] = queue.Queue()
        self.writes: list[str] = []
        self.dimensions: list[tuple[int, int]] = []
        self.return_code: int | None = None

    def read(self, _size: int) -> str:
        value = self.output.get(timeout=2)
        if value is None:
            raise EOFError("closed")
        return value

    def write(self, data: str) -> None:
        self.writes.append(data)

    def resize(self, rows: int, cols: int) -> None:
        self.dimensions.append((rows, cols))

    def exit_code(self) -> int | None:
        return self.return_code

    def close(self) -> None:
        self.return_code = 0
        self.output.put(None)


class _FakeBackendFactory:
    def __init__(self) -> None:
        self.instances: list[_FakeBackend] = []
        self.calls: list[tuple[list[str], Path, dict[str, str], int, int]] = []

    def __call__(
        self,
        argv: list[str],
        cwd: Path,
        env: dict[str, str],
        rows: int,
        cols: int,
    ) -> _FakeBackend:
        backend = _FakeBackend()
        self.instances.append(backend)
        self.calls.append((argv, cwd, env, rows, cols))
        return backend


async def _wait_for_write(backend: _FakeBackend) -> str:
    for _ in range(100):
        if backend.writes:
            return backend.writes[0]
        await asyncio.sleep(0.001)
    raise AssertionError("terminal command was not written")


@pytest.mark.asyncio
async def test_project_terminal_is_reused_and_replays_output(tmp_path: Path) -> None:
    factory = _FakeBackendFactory()
    manager = TerminalSessionManager(
        shell_argv=["fake-shell"],
        backend_factory=factory,
    )
    try:
        opened = await manager.open(tmp_path, rows=24, cols=80)
        reopened = await manager.open(tmp_path, rows=40, cols=120)

        assert reopened.terminal_id == opened.terminal_id
        assert len(factory.instances) == 1
        assert factory.calls[0][1] == tmp_path.resolve()
        assert factory.calls[0][2]["TERM"] == "xterm-256color"

        backend = factory.instances[0]
        backend.output.put("hello from PTY\r\n")
        first = await manager.read(opened.terminal_id, after_seq=0, wait_ms=1_000)
        assert first.data == "hello from PTY\r\n"
        assert first.next_seq == 1

        replay = await manager.read(opened.terminal_id)
        assert replay.data == "hello from PTY\r\n"

        await manager.write(opened.terminal_id, "git status\r", project_path=tmp_path)
        assert backend.writes == ["git status\r"]
        assert backend.dimensions[-1] == (40, 120)
    finally:
        await manager.close_all()


@pytest.mark.asyncio
async def test_project_terminal_rejects_cross_project_access(tmp_path: Path) -> None:
    first_project = tmp_path / "first"
    second_project = tmp_path / "second"
    first_project.mkdir()
    second_project.mkdir()
    factory = _FakeBackendFactory()
    manager = TerminalSessionManager(
        shell_argv=["fake-shell"],
        backend_factory=factory,
    )
    try:
        opened = await manager.open(first_project)

        with pytest.raises(TerminalError, match="does not belong"):
            await manager.write(
                opened.terminal_id,
                "pwd\r",
                project_path=second_project,
            )

        await manager.close(opened.terminal_id, project_path=first_project)
        assert await manager.list(first_project) == []
        with pytest.raises(TerminalError, match="Unknown terminal"):
            await manager.read(opened.terminal_id)
    finally:
        await manager.close_all()


@pytest.mark.asyncio
async def test_exec_compatibility_command_is_visible_and_returns_clean_output(
    tmp_path: Path,
) -> None:
    factory = _FakeBackendFactory()
    manager = TerminalSessionManager(
        shell_argv=["bash"],
        backend_factory=factory,
    )
    try:
        task = asyncio.create_task(manager.run_exec(
            tmp_path,
            command="printf 'shared-output\\n'",
            cwd=str(tmp_path),
            timeout=5,
            max_output_chars=10_000,
            owner_session_key="websocket:chat-1",
        ))
        while not factory.instances:
            await asyncio.sleep(0.001)
        backend = factory.instances[0]
        payload = await _wait_for_write(backend)
        token = re.search(r"nanobot;begin;([a-f0-9]+)", payload)
        assert token is not None
        marker = token.group(1)
        backend.output.put(
            payload
            + "\r\n"
            + f"\x1b]633;nanobot;begin;{marker}\x07"
            + "\x1b[32mshared-output\x1b[0m\r\n"
            + f"\x1b]633;nanobot;done;{marker};0\x07"
        )

        poll = await task
        replay = await manager.read((await manager.list(tmp_path))[0].terminal_id)

        assert poll.done is True
        assert poll.exit_code == 0
        assert poll.output == "shared-output\r\n"
        assert "printf 'shared-output" in replay.data
    finally:
        await manager.close_all()


@pytest.mark.asyncio
async def test_exec_compatibility_session_accepts_write_stdin(tmp_path: Path) -> None:
    factory = _FakeBackendFactory()
    manager = TerminalSessionManager(
        shell_argv=["bash"],
        backend_factory=factory,
    )
    try:
        session_id, initial = await manager.start_exec(
            tmp_path,
            command="read answer; printf '%s\\n' \"$answer\"",
            cwd=str(tmp_path),
            timeout=5,
            yield_time_ms=0,
            max_output_chars=10_000,
            owner_session_key="websocket:chat-1",
        )
        backend = factory.instances[0]
        payload = await _wait_for_write(backend)
        token = re.search(r"nanobot;begin;([a-f0-9]+)", payload)
        assert token is not None
        marker = token.group(1)
        backend.output.put(f"\x1b]633;nanobot;begin;{marker}\x07ready\r\n")

        ready = await manager.write_exec(
            session_id,
            chars=None,
            close_stdin=False,
            terminate=False,
            yield_time_ms=10,
            max_output_chars=10_000,
            owner_session_key="websocket:chat-1",
        )
        backend.output.put(
            "answer\r\n"
            + f"\x1b]633;nanobot;done;{marker};0\x07"
        )
        final = await manager.write_exec(
            session_id,
            chars="answer\n",
            close_stdin=False,
            terminate=False,
            yield_time_ms=100,
            max_output_chars=10_000,
            owner_session_key="websocket:chat-1",
        )

        assert initial.done is False
        assert ready.output == "ready\r\n"
        assert backend.writes[-1] == ("answer\r" if sys.platform == "win32" else "answer\n")
        assert final.done is True
        assert final.output == "answer\r\n"
    finally:
        await manager.close_all()
