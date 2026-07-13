import asyncio
import hashlib
import os
import tempfile
from pathlib import Path

import pytest
from filelock import AsyncFileLock

from nanobot.agent.tools import filesystem
from nanobot.agent.tools.apply_patch import ApplyPatchTool
from nanobot.agent.tools.base import ToolResult
from nanobot.agent.tools.filesystem import WriteFileTool
from nanobot.config.paths import get_runtime_subdir


@pytest.fixture(autouse=True)
def _runtime_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("nanobot.config.loader._current_config_path", tmp_path / "config.json")


@pytest.mark.asyncio
async def test_workspace_lock_waits_until_released():
    """Test that a second tool call waits when the workspace lock is held."""
    with tempfile.TemporaryDirectory() as td:
        tmp_path = Path(td)
        workspace = tmp_path / "test_workspace"
        workspace.mkdir()

        tool = WriteFileTool(workspace=workspace)

        resolved_ws = workspace.expanduser().resolve(strict=False)
        ws_key = hashlib.sha256(os.path.normcase(str(resolved_ws)).encode("utf-8")).hexdigest()
        lock_dir = get_runtime_subdir("locks")
        lock_path = lock_dir / f"workspace-{ws_key}.lock"

        lock = AsyncFileLock(str(lock_path), timeout=0.1)
        await lock.acquire()

        try:
            task = asyncio.create_task(tool.execute(path="test.txt", content="hello"))

            _, pending = await asyncio.wait([task], timeout=0.5)
            assert task in pending

            await lock.release()

            result = await task
            assert "Successfully wrote" in result

        finally:
            if lock.is_locked:
                await lock.release()


@pytest.mark.asyncio
async def test_workspace_lock_timeout_error(monkeypatch):
    """Test that a second tool call times out when the workspace lock is held."""
    monkeypatch.setattr(filesystem, "_WORKSPACE_LOCK_TIMEOUT", 0.05)

    with tempfile.TemporaryDirectory() as td:
        tmp_path = Path(td)
        workspace = tmp_path / "test_workspace"
        workspace.mkdir()

        tool = WriteFileTool(workspace=workspace)

        resolved_ws = workspace.expanduser().resolve(strict=False)
        ws_key = hashlib.sha256(os.path.normcase(str(resolved_ws)).encode("utf-8")).hexdigest()
        lock_dir = get_runtime_subdir("locks")
        lock_path = lock_dir / f"workspace-{ws_key}.lock"

        lock = AsyncFileLock(str(lock_path), timeout=0.1)
        await lock.acquire()

        try:
            result = await tool.execute(path="test.txt", content="hello")
            assert isinstance(result, ToolResult)
            assert result.is_error
            assert result == "Workspace is busy: another session is modifying files."
            assert not (workspace / "test.txt").exists()
        finally:
            if lock.is_locked:
                await lock.release()


@pytest.mark.asyncio
async def test_same_workspace_writes_are_serialized():
    """Test that concurrent write calls on the same workspace are serialized."""
    with tempfile.TemporaryDirectory() as td:
        tmp_path = Path(td)
        workspace = tmp_path / "test_workspace"
        workspace.mkdir()

        events = []

        class TrackingWriteFileTool(WriteFileTool):
            def __init__(self, name, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.tool_name = name

            async def execute(self, *args, **kwargs):
                async def original(*a, **k):
                    events.append(f"{self.tool_name}_start")
                    await asyncio.sleep(0.1)
                    events.append(f"{self.tool_name}_end")
                    return "Success"

                decorated = filesystem._workspace_lock_decorator(original)
                return await decorated(self, *args, **kwargs)

        t1 = TrackingWriteFileTool("first", workspace=workspace)
        t2 = TrackingWriteFileTool("second", workspace=workspace)

        task1 = asyncio.create_task(t1.execute(path="test.txt", content="1"))
        task2 = asyncio.create_task(t2.execute(path="test.txt", content="2"))

        await asyncio.gather(task1, task2)

        assert events in (
            ["first_start", "first_end", "second_start", "second_end"],
            ["second_start", "second_end", "first_start", "first_end"],
        )


@pytest.mark.asyncio
async def test_different_workspaces_do_not_block_each_other():
    events: list[str] = []

    class TrackingWriteFileTool(WriteFileTool):
        def __init__(self, label: str, **kwargs):
            super().__init__(**kwargs)
            self.label = label

        async def execute(self, *args, **kwargs):
            async def operation(*_args, **_kwargs):
                events.append(f"{self.label}_start")
                await asyncio.sleep(0.1)
                events.append(f"{self.label}_end")
                return "Success"

            decorated = filesystem._workspace_lock_decorator(operation)
            return await decorated(self, *args, **kwargs)

    with tempfile.TemporaryDirectory() as td:
        tmp_path = Path(td)
        ws1 = tmp_path / "ws1"
        ws2 = tmp_path / "ws2"
        ws1.mkdir()
        ws2.mkdir()

        await asyncio.gather(
            TrackingWriteFileTool("first", workspace=ws1).execute(),
            TrackingWriteFileTool("second", workspace=ws2).execute(),
        )

        assert set(events[:2]) == {"first_start", "second_start"}


@pytest.mark.asyncio
async def test_apply_patch_lock_timeout_error(monkeypatch):
    """Test that ApplyPatchTool respects the workspace lock."""

    monkeypatch.setattr(filesystem, "_WORKSPACE_LOCK_TIMEOUT", 0.05)

    with tempfile.TemporaryDirectory() as td:
        tmp_path = Path(td)
        workspace = tmp_path / "test_workspace"
        workspace.mkdir()

        tool = ApplyPatchTool(workspace=workspace)

        resolved_ws = workspace.expanduser().resolve(strict=False)
        ws_key = hashlib.sha256(os.path.normcase(str(resolved_ws)).encode("utf-8")).hexdigest()
        lock_dir = get_runtime_subdir("locks")
        lock_path = lock_dir / f"workspace-{ws_key}.lock"

        lock = AsyncFileLock(str(lock_path), timeout=0.1)
        await lock.acquire()

        try:
            result = await tool.execute(
                edits=[{"path": "test.txt", "old_text": "", "new_text": "hello"}]
            )
            assert isinstance(result, ToolResult)
            assert result.is_error
            assert result == "Workspace is busy: another session is modifying files."
        finally:
            if lock.is_locked:
                await lock.release()
