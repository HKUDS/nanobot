from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.context.context import ContextBuilder
from nanobot.memory.store import MemoryStore


def _workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    return ws


async def test_build_user_content_ignores_non_images(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    builder = ContextBuilder(ws)

    text_file = ws / "note.txt"
    text_file.write_text("hello", encoding="utf-8")

    out = await builder._build_user_content("question", [str(text_file)])
    assert out == "question"


async def test_build_user_content_embeds_image(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    builder = ContextBuilder(ws)

    png = ws / "img.png"
    # Minimal PNG signature bytes are enough for base64 path coverage.
    png.write_bytes(b"\x89PNG\r\n\x1a\n")

    out = await builder._build_user_content("describe", [str(png)])
    assert isinstance(out, list)
    assert out[-1]["type"] == "text"
    assert out[-1]["text"] == "describe"
    assert out[0]["type"] == "image_url"


def test_inject_runtime_context_with_list_payload(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    builder = ContextBuilder(ws)

    content = [{"type": "text", "text": "hi"}]
    out = builder._inject_runtime_context(content, "cli", "direct")
    assert isinstance(out, list)
    assert out[-1]["type"] == "text"
    assert "[Runtime Context]" in out[-1]["text"]


def test_add_assistant_and_tool_messages(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    builder = ContextBuilder(ws)
    messages: list[dict] = []

    builder.add_assistant_message(
        messages,
        content=None,
        tool_calls=[{"id": "1", "function": {"name": "read_file", "arguments": "{}"}}],
        reasoning_content="chain",
    )
    assert messages[-1]["role"] == "assistant"
    assert "tool_calls" in messages[-1]
    assert messages[-1]["reasoning_content"] == "chain"

    builder.add_tool_result(messages, tool_call_id="1", tool_name="read_file", result="ok")
    assert messages[-1]["role"] == "tool"
    assert messages[-1]["name"] == "read_file"


async def test_build_system_prompt_memory_failure_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = _workspace(tmp_path)
    mock_memory = MagicMock()
    mock_memory.get_memory_context = AsyncMock(side_effect=RuntimeError("memory down"))
    builder = ContextBuilder(ws, memory=mock_memory)

    prompt = await builder.build_system_prompt(current_message="hello")
    assert "# nanobot" in prompt
    assert "**Answer from these facts first.**" not in prompt


async def test_bootstrap_files_cached_across_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T-L1 (LAN-93): bootstrap files must be read at most once when mtime hasn't changed."""
    ws = _workspace(tmp_path)
    (ws / "SOUL.md").write_text("soul content", encoding="utf-8")
    builder = ContextBuilder(ws)

    read_count = 0
    original_read_text = Path.read_text

    def counting_read_text(self: Path, *args, **kwargs) -> str:
        nonlocal read_count
        if self.name == "SOUL.md":
            read_count += 1
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting_read_text)

    # Call build_system_prompt three times — SOUL.md should only be read once
    await builder.build_system_prompt(current_message="first")
    await builder.build_system_prompt(current_message="second")
    await builder.build_system_prompt(current_message="third")

    assert read_count == 1, f"SOUL.md read {read_count} times; expected 1 (cache miss only)"


def test_injected_memory_store_is_used(tmp_path: Path) -> None:
    """LAN-105: when memory= is passed, ContextBuilder uses that instance, not a new one."""
    ws = _workspace(tmp_path)
    mock_store = MagicMock(spec=MemoryStore)
    builder = ContextBuilder(ws, memory=mock_store)
    assert builder.memory is mock_store
