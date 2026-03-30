from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from nanobot.agent.context import ContextBuilder


def _make_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


async def test_build_messages_returns_list(tmp_path):
    ws = _make_workspace(tmp_path)
    ctx = ContextBuilder(ws)
    result = await ctx.build_messages(history=[], current_message="hi")
    assert isinstance(result, list)
    assert result[-1]["role"] == "user"


async def test_build_messages_no_backend_no_injection(tmp_path):
    ws = _make_workspace(tmp_path)
    ctx = ContextBuilder(ws)
    result = await ctx.build_messages(
        history=[], current_message="hi", session_key="telegram:123"
    )
    # Without a backend there is no memory block
    roles = [m["role"] for m in result]
    assert roles.count("system") == 1  # only the main system prompt


async def test_build_messages_with_backend_injects_memory_block(tmp_path):
    ws = _make_workspace(tmp_path)
    mock_backend = MagicMock()
    mock_backend.retrieve = AsyncMock(return_value="[Memory — 1 relevant facts]\n• you like tea (2026-01-01)")
    ctx = ContextBuilder(ws, memory_backend=mock_backend)

    result = await ctx.build_messages(
        history=[], current_message="hi", session_key="telegram:123"
    )

    memory_blocks = [m for m in result if m.get("role") == "system" and "[Memory" in (m.get("content") or "")]
    assert len(memory_blocks) == 1
    mock_backend.retrieve.assert_awaited_once_with("hi", "telegram:123", 5)


async def test_build_messages_empty_retrieve_skips_injection(tmp_path):
    ws = _make_workspace(tmp_path)
    mock_backend = MagicMock()
    mock_backend.retrieve = AsyncMock(return_value="")
    ctx = ContextBuilder(ws, memory_backend=mock_backend)

    result = await ctx.build_messages(
        history=[], current_message="hi", session_key="telegram:123"
    )

    roles = [m["role"] for m in result]
    assert roles.count("system") == 1


async def test_build_messages_no_session_key_skips_retrieval(tmp_path):
    ws = _make_workspace(tmp_path)
    mock_backend = MagicMock()
    mock_backend.retrieve = AsyncMock(return_value="some memory")
    ctx = ContextBuilder(ws, memory_backend=mock_backend)

    await ctx.build_messages(history=[], current_message="probe", session_key=None)

    mock_backend.retrieve.assert_not_awaited()


async def test_memory_block_inserted_before_history(tmp_path):
    ws = _make_workspace(tmp_path)
    mock_backend = MagicMock()
    mock_backend.retrieve = AsyncMock(return_value="[Memory — 1 relevant facts]\n• you like tea")
    ctx = ContextBuilder(ws, memory_backend=mock_backend)
    history = [{"role": "user", "content": "old message"}, {"role": "assistant", "content": "old reply"}]

    result = await ctx.build_messages(
        history=history, current_message="new message", session_key="telegram:123"
    )

    # Order: system_prompt, memory_block, history..., current_user_message
    system_indices = [i for i, m in enumerate(result) if m["role"] == "system"]
    first_history_idx = next(i for i, m in enumerate(result) if m.get("content") == "old message")
    assert system_indices[-1] < first_history_idx
