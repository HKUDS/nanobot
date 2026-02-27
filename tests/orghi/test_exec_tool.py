"""Tests for ExecTool env inheritance (subprocess inherits os.environ)."""

from unittest.mock import AsyncMock, patch

import pytest

from nanobot.agent.tools.shell import ExecTool


@pytest.fixture
def mock_subprocess():
    """Mock asyncio.create_subprocess_shell to capture env."""
    proc = AsyncMock()
    proc.communicate = AsyncMock(return_value=(b"", b""))
    proc.returncode = 0
    proc.wait = AsyncMock(return_value=0)
    with patch(
        "nanobot.agent.tools.shell.asyncio.create_subprocess_shell",
        new_callable=AsyncMock,
        return_value=proc,
    ) as m:
        yield m


async def test_exec_tool_inherits_parent_env(mock_subprocess) -> None:
    """ExecTool passes env=None so subprocess inherits os.environ from parent."""
    tool = ExecTool()
    await tool.execute("true")
    mock_subprocess.assert_called_once()
    env = mock_subprocess.call_args.kwargs.get("env")
    assert env is None
