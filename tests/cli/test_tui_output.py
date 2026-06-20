import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from nanobot.cli.tui.output import (
    MarkdownStreamBuffer,
    ReasoningBuffer,
    TuiOutput,
    _message_styles,
)
from nanobot.cli.tui.state import CliTuiState

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _plain(chunks) -> str:
    return _ANSI.sub("", "".join(chunks))


def _msg(content: str = "", *, media=None, **metadata):
    return SimpleNamespace(content=content, media=media or [], metadata=metadata)


def _state() -> CliTuiState:
    return CliTuiState(
        model="m",
        preset="p",
        workspace=Path("/tmp"),
        access_mode="restricted",
        session_id="cli:direct",
    )


def _output(state: CliTuiState):
    sink: list[str] = []

    async def _emit(text: str) -> None:
        sink.append(text)

    return TuiOutput(state, render_markdown=True, bot_name="nanobot", emit=_emit), sink


def test_message_styles_default_to_light_safe_palette(monkeypatch):
    monkeypatch.delenv("NANOBOT_TUI_THEME", raising=False)
    monkeypatch.delenv("COLORFGBG", raising=False)

    user_style, _marker_style, assistant_style, _queued_style = _message_styles()

    assert user_style.endswith("on #e8f3ff")
    assert assistant_style == "#111827 on #f3f4f6"


def test_message_styles_respect_dark_terminal_hint(monkeypatch):
    monkeypatch.delenv("NANOBOT_TUI_THEME", raising=False)
    monkeypatch.setenv("COLORFGBG", "15;0")

    user_style, _marker_style, assistant_style, _queued_style = _message_styles()

    assert user_style.endswith("on #102033")
    assert assistant_style == "#e5e7eb on #15171a"


def test_message_styles_allow_theme_override(monkeypatch):
    monkeypatch.setenv("NANOBOT_TUI_THEME", "dark")
    monkeypatch.setenv("COLORFGBG", "0;15")

    user_style, _marker_style, assistant_style, _queued_style = _message_styles()

    assert user_style.endswith("on #102033")
    assert assistant_style == "#e5e7eb on #15171a"


def test_markdown_stream_buffer_commits_blocks_on_blank_lines():
    buf = MarkdownStreamBuffer()
    assert buf.feed("first paragraph") == []
    # A blank line closes the first block; the unterminated tail stays buffered.
    blocks = buf.feed("\n\nsecond paragraph")
    assert blocks == ["first paragraph"]
    assert buf.feed(" continues") == []
    assert buf.flush() == "second paragraph continues"


def test_markdown_stream_buffer_keeps_fenced_code_together():
    buf = MarkdownStreamBuffer()
    blocks = buf.feed("```python\ncode line 1\n\ncode line 2\n```\n\nafter")
    assert blocks == ["```python\ncode line 1\n\ncode line 2\n```"]
    assert buf.flush() == "after"


def test_reasoning_buffer_keeps_split_dangling_word():
    buf = ReasoningBuffer()

    first = buf.add("* **Fetching current star count**\n\nI")
    second = buf.add(" need to check the current star count.")

    assert first == "* **Fetching current star count**"
    assert second == "I need to check the current star count."


@pytest.mark.asyncio
async def test_print_user_input_renders_submitted_message():
    state = _state()
    output, sink = _output(state)

    await output.print_user_input("cool")

    text = _plain(sink)
    assert "› cool" in text


@pytest.mark.asyncio
async def test_print_reasoning_prefixes_each_line():
    state = _state()
    output, sink = _output(state)

    await output.print_reasoning("first thought\nsecond thought")

    text = _plain(sink)
    assert "✻ first thought" in text
    assert "✻ second thought" in text


@pytest.mark.asyncio
async def test_handle_outbound_streams_then_ends_turn():
    state = _state()
    output, sink = _output(state)

    await output.handle_outbound(_msg("hello world\n\n", _stream_delta=True))
    assert state.turn_active is True
    assert state.status == "responding"
    assert any("hello world" in chunk for chunk in sink)

    await output.handle_outbound(_msg("hello world", _streamed=True))
    assert state.turn_active is False
    assert state.status == "idle"


@pytest.mark.asyncio
async def test_empty_sentinel_ends_turn_without_printing():
    state = _state()
    state.begin_turn()
    output, sink = _output(state)

    await output.handle_outbound(_msg("", _wants_stream=True))
    assert state.turn_active is False
    assert sink == []


@pytest.mark.asyncio
async def test_command_output_prints_and_ends_turn():
    state = _state()
    state.begin_turn()
    output, sink = _output(state)

    await output.handle_outbound(_msg("## Status\nok", render_as="text"))
    assert state.turn_active is False
    assert any("Status" in chunk for chunk in sink)


@pytest.mark.asyncio
async def test_outbound_media_is_surfaced():
    state = _state()
    state.begin_turn()
    output, sink = _output(state)

    await output.handle_outbound(
        _msg("Here is your image", media=["/tmp/media/cat.png"])
    )
    text = _plain(sink)
    assert "cat.png" in text
    assert "/tmp/media/cat.png" in text
    assert "Here is your image" in text
    assert state.turn_active is False


@pytest.mark.asyncio
async def test_media_only_message_ends_turn():
    state = _state()
    state.begin_turn()
    output, sink = _output(state)

    await output.handle_outbound(_msg("", media=["/tmp/media/cat.png"]))
    assert "cat.png" in _plain(sink)
    assert state.turn_active is False


@pytest.mark.asyncio
async def test_resume_metadata_switches_active_chat_id():
    state = _state()
    state.active_chat_id = "direct"
    state.begin_turn()
    output, sink = _output(state)

    await output.handle_outbound(
        _msg("Resumed `cli:other`.", render_as="text", cli_resume_session="other")
    )
    assert state.active_chat_id == "other"
    assert state.turn_active is False
    # The screen is cleared (ANSI clear sequence emitted) before the notice.
    assert any("\x1b[2J" in chunk for chunk in sink)
    state = _state()
    output, sink = _output(state)

    await output.toggle_reasoning()  # turn reasoning off
    assert state.show_reasoning is False

    # Reasoning deltas while hidden are buffered, not printed.
    await output.handle_outbound(_msg("thinking step one. ", _progress=True, _reasoning=True))
    assert not any("thinking step one" in chunk for chunk in sink)

    await output.toggle_reasoning()  # turn reasoning back on, reveal buffered text
    assert state.show_reasoning is True
    assert any("thinking step one" in chunk for chunk in sink)


@pytest.mark.asyncio
async def test_start_event_sets_tool_status_without_printing():
    state = _state()
    output, sink = _output(state)

    await output.handle_outbound(
        _msg(_tool_events=[{"phase": "start", "name": "exec", "arguments": {"command": "ls"}}])
    )
    # Start events drive the live status line only; nothing is printed yet.
    assert state.status == "tool"
    assert state.current_tool == "exec"
    assert sink == []


@pytest.mark.asyncio
async def test_end_event_prints_collapsed_result():
    state = _state()
    output, sink = _output(state)

    await output.handle_outbound(
        _msg(
            _tool_events=[
                {
                    "phase": "end",
                    "name": "read_file",
                    "arguments": {"path": "README.md"},
                    "result": {"summary": "read 12 lines"},
                }
            ]
        )
    )
    text = _plain(sink)
    assert "Read" in text and "README.md" in text
    assert "read 12 lines" in text
    # The redundant tool-name line is gone.
    assert "read_file" not in text
