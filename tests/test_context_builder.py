from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.agent.context import ContextBuilder


def _workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    return ws


def test_build_user_content_ignores_non_images(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    builder = ContextBuilder(ws)

    text_file = ws / "note.txt"
    text_file.write_text("hello", encoding="utf-8")

    out = builder._build_user_content("question", [str(text_file)])
    assert out == "question"


def test_build_user_content_embeds_image(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    builder = ContextBuilder(ws)

    png = ws / "img.png"
    # Minimal PNG signature bytes are enough for base64 path coverage.
    png.write_bytes(b"\x89PNG\r\n\x1a\n")

    out = builder._build_user_content("describe", [str(png)])
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


def test_build_system_prompt_memory_failure_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _workspace(tmp_path)
    builder = ContextBuilder(ws)

    def _boom(*args, **kwargs):
        raise RuntimeError("memory down")

    monkeypatch.setattr(builder.memory, "get_memory_context", _boom)
    prompt = builder.build_system_prompt(current_message="hello")
    assert "# nanobot" in prompt
    assert "**Answer from these facts first.**" not in prompt
