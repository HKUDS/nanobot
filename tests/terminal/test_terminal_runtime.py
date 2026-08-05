from __future__ import annotations

import queue
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
