"""Regression tests for atomic workspace file writes (issue #4798).

Workspace files are read by users and other agents while a tool writes them.
A torn write (truncate-then-write) exposes half a file to readers, and a
failed write destroys the previous content. These tests pin the atomic
behavior of WriteFileTool, EditFileTool and ApplyPatchTool.
"""

from __future__ import annotations

import asyncio
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from nanobot.agent.tools import apply_patch
from nanobot.agent.tools.apply_patch import ApplyPatchTool
from nanobot.agent.tools.filesystem import EditFileTool, WriteFileTool
from nanobot.utils import helpers


def _platform_bytes(text: str) -> bytes:
    """Bytes a default write_text produces: newlines translated to os.linesep."""
    return text.replace("\n", os.linesep).encode("utf-8")


def test_write_tool_replaces_file_without_temp_residue(tmp_path):
    target = tmp_path / "notes.md"
    target.write_text("old content\n", encoding="utf-8")
    tool = WriteFileTool(workspace=tmp_path)

    result = asyncio.run(tool.execute(path=str(target), content="new content\n"))

    assert "Successfully wrote" in result
    assert target.read_text(encoding="utf-8") == "new content\n"
    assert not [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]


def test_write_tool_failure_keeps_previous_content(tmp_path, monkeypatch):
    target = tmp_path / "config.json"
    target.write_text('{"version": 1}', encoding="utf-8")

    def failing_fsync(fd: int) -> None:
        raise OSError("fsync failed")

    monkeypatch.setattr(helpers.os, "fsync", failing_fsync)
    tool = WriteFileTool(workspace=tmp_path)

    result = asyncio.run(tool.execute(path=str(target), content='{"version": 2}'))

    assert "Error" in result
    assert target.read_text(encoding="utf-8") == '{"version": 1}'
    assert not [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]


def test_edit_tool_create_path_writes_atomically(tmp_path):
    target = tmp_path / "created.py"
    tool = EditFileTool(workspace=tmp_path)

    result = asyncio.run(tool.execute(path=str(target), old_text="", new_text="print('hi')\n"))

    assert "Patch applied" in result
    assert target.read_bytes() == _platform_bytes("print('hi')\n")


def test_edit_tool_modify_preserves_crlf_bytes(tmp_path):
    target = tmp_path / "win.ini"
    target.write_bytes(b"a\r\nb\r\n")
    tool = EditFileTool(workspace=tmp_path)

    result = asyncio.run(tool.execute(path=str(target), old_text="b", new_text="c"))

    assert "Patch applied" in result
    assert target.read_bytes() == b"a\r\nc\r\n"


def test_apply_patch_add_does_not_translate_newlines(tmp_path):
    tool = ApplyPatchTool(workspace=tmp_path)

    result = asyncio.run(
        tool.execute(edits=[{"path": "p.py", "action": "add", "new_text": "a\nb\n"}])
    )

    assert "add p.py" in result
    assert (tmp_path / "p.py").read_bytes() == b"a\nb\n"


def test_apply_patch_rolls_back_when_a_later_write_fails(tmp_path, monkeypatch):
    first = tmp_path / "first.txt"
    first.write_text("one\n", encoding="utf-8")
    second = tmp_path / "second.txt"
    second.write_text("two\n", encoding="utf-8")
    tool = ApplyPatchTool(workspace=tmp_path)

    real_write = apply_patch._write_text_atomic

    def flaky(path: Path, content: str, *, newline: str | None = None) -> None:
        if path == second:
            raise OSError("simulated disk failure")
        real_write(path, content, newline=newline)

    monkeypatch.setattr(apply_patch, "_write_text_atomic", flaky)

    result = asyncio.run(
        tool.execute(
            edits=[
                {"path": "first.txt", "action": "replace", "old_text": "one", "new_text": "uno"},
                {"path": "second.txt", "action": "replace", "old_text": "two", "new_text": "dos"},
            ]
        )
    )

    assert "Error" in result
    assert first.read_text(encoding="utf-8") == "one\n"
    assert second.read_text(encoding="utf-8") == "two\n"
    assert not [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows rejects os.replace while a reader holds the target; tearing is a POSIX failure mode",
)
def test_concurrent_write_tools_never_tear(tmp_path):
    target = tmp_path / "shared.log"
    payloads = [f"writer-{i}\n" + "x" * 4096 + "\n" for i in range(6)]
    target.write_text(payloads[0], encoding="utf-8")
    barrier = threading.Barrier(len(payloads))
    torn: list[str] = []

    def write(index: int) -> None:
        tool = WriteFileTool(workspace=tmp_path)
        barrier.wait()
        asyncio.run(tool.execute(path=str(target), content=payloads[index]))

    def read() -> None:
        for _ in range(300):
            observed = target.read_text(encoding="utf-8")
            if observed not in payloads:
                torn.append(observed[:50])

    with ThreadPoolExecutor(max_workers=len(payloads) + 1) as pool:
        reader = pool.submit(read)
        writers = [pool.submit(write, i) for i in range(len(payloads))]
        for future in writers:
            future.result()
        reader.result()

    assert not torn
