"""IT-05: ToolExecutor with real built-in tools.

Verifies the executor's parallel/sequential logic with actual filesystem
and shell tools, not stubs. Does not require LLM API key.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nanobot.providers.base import ToolCallRequest
from nanobot.tools.builtin.filesystem import (
    EditFileTool,
    ListDirTool,
    ReadFileTool,
    WriteFileTool,
)
from nanobot.tools.builtin.shell import ExecTool
from nanobot.tools.executor import ToolExecutor
from nanobot.tools.registry import ToolRegistry

pytestmark = pytest.mark.integration


def _tc(name: str, **kwargs: Any) -> ToolCallRequest:
    return ToolCallRequest(id=f"tc-{name}", name=name, arguments=kwargs)


def _make_executor(tmp_path: Path) -> ToolExecutor:
    reg = ToolRegistry()
    reg.register(ReadFileTool(workspace=tmp_path))
    reg.register(WriteFileTool(workspace=tmp_path, allowed_dir=tmp_path))
    reg.register(EditFileTool(workspace=tmp_path, allowed_dir=tmp_path))
    reg.register(ListDirTool(workspace=tmp_path))
    reg.register(ExecTool(working_dir=str(tmp_path), shell_mode="denylist"))
    return ToolExecutor(reg)


class TestReadWriteIntegration:
    async def test_write_then_read(self, tmp_path: Path) -> None:
        exe = _make_executor(tmp_path)
        write_results = await exe.execute_batch(
            [_tc("write_file", path=str(tmp_path / "hello.txt"), content="Hello, world!")]
        )
        assert write_results[0].success

        read_results = await exe.execute_batch([_tc("read_file", path=str(tmp_path / "hello.txt"))])
        assert read_results[0].success
        assert "Hello, world!" in read_results[0].output

    async def test_list_dir_shows_written_file(self, tmp_path: Path) -> None:
        exe = _make_executor(tmp_path)
        (tmp_path / "alpha.py").write_text("x = 1")
        (tmp_path / "beta.py").write_text("y = 2")

        results = await exe.execute_batch([_tc("list_dir", path=str(tmp_path))])
        assert results[0].success
        assert "alpha.py" in results[0].output
        assert "beta.py" in results[0].output

    async def test_edit_modifies_file(self, tmp_path: Path) -> None:
        target = tmp_path / "data.txt"
        target.write_text("old content here")
        exe = _make_executor(tmp_path)

        results = await exe.execute_batch(
            [
                _tc(
                    "edit_file",
                    path=str(target),
                    old_text="old content",
                    new_text="new content",
                )
            ]
        )
        assert results[0].success
        assert "new content here" == target.read_text()


class TestParallelReadSequentialWrite:
    async def test_readonly_tools_batch_parallel(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("aaa")
        (tmp_path / "b.txt").write_text("bbb")
        (tmp_path / "c.txt").write_text("ccc")
        exe = _make_executor(tmp_path)

        results = await exe.execute_batch(
            [
                _tc("read_file", path=str(tmp_path / "a.txt")),
                _tc("read_file", path=str(tmp_path / "b.txt")),
                _tc("read_file", path=str(tmp_path / "c.txt")),
            ]
        )
        assert all(r.success for r in results)
        assert "aaa" in results[0].output
        assert "bbb" in results[1].output
        assert "ccc" in results[2].output

    async def test_write_between_reads_preserves_order(self, tmp_path: Path) -> None:
        (tmp_path / "existing.txt").write_text("before")
        exe = _make_executor(tmp_path)

        results = await exe.execute_batch(
            [
                _tc("read_file", path=str(tmp_path / "existing.txt")),
                _tc("write_file", path=str(tmp_path / "new.txt"), content="written"),
                _tc("read_file", path=str(tmp_path / "new.txt")),
            ]
        )
        assert results[0].success
        assert results[1].success
        assert results[2].success
        assert "written" in results[2].output


class TestShellExecution:
    async def test_echo_command(self, tmp_path: Path) -> None:
        exe = _make_executor(tmp_path)
        results = await exe.execute_batch([_tc("exec", command="echo integration-test-output")])
        assert results[0].success
        assert "integration-test-output" in results[0].output

    async def test_denied_command_rejected(self, tmp_path: Path) -> None:
        exe = _make_executor(tmp_path)
        results = await exe.execute_batch([_tc("exec", command="rm -rf /")])
        assert not results[0].success


class TestErrorHandling:
    async def test_read_nonexistent_file(self, tmp_path: Path) -> None:
        exe = _make_executor(tmp_path)
        results = await exe.execute_batch(
            [_tc("read_file", path=str(tmp_path / "nonexistent.txt"))]
        )
        assert not results[0].success

    async def test_write_outside_workspace(self, tmp_path: Path) -> None:
        exe = _make_executor(tmp_path)
        # allowed_dir is set to tmp_path, so writing outside should be rejected
        escape_path = str(tmp_path.parent / "escape-attempt.txt")
        results = await exe.execute_batch([_tc("write_file", path=escape_path, content="bad")])
        assert not results[0].success
