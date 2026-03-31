from unittest.mock import AsyncMock

import pytest

from nanobot.agent.tools.todo_write import TodoWriteTool


@pytest.mark.asyncio
async def test_todo_write_merge_and_emit_progress():
    send = AsyncMock()
    tool = TodoWriteTool(send_callback=send)
    tool.set_context("telegram", "c1")

    out = await tool.execute(
        merge=False,
        todos=[
            {"id": "a", "content": "Read files", "status": "in_progress"},
            {"id": "b", "content": "Write patch", "status": "pending"},
        ],
    )
    assert "Plan status:" in out
    assert "Read files" in out
    assert send.await_count == 1

    out2 = await tool.execute(
        merge=True,
        todos=[
            {"id": "a", "content": "Read files", "status": "completed"},
        ],
    )
    assert "completed" not in out2.lower()  # rendered with emoji
    assert "Read files" in out2


@pytest.mark.asyncio
async def test_todo_write_rejects_multiple_in_progress():
    tool = TodoWriteTool()
    out = await tool.execute(
        merge=False,
        todos=[
            {"id": "a", "content": "one", "status": "in_progress"},
            {"id": "b", "content": "two", "status": "in_progress"},
        ],
    )
    assert out.startswith("Error:")
    assert "only one todo can be in_progress" in out

