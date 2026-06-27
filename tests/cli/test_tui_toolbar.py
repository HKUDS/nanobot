from pathlib import Path
from unittest.mock import patch

from nanobot.cli.tui import build_prompt_message, build_rprompt
from nanobot.cli.tui.state import CliTuiState


def _state() -> CliTuiState:
    return CliTuiState(
        model="gemini-3-flash",
        preset="primary",
        workspace=Path("/tmp"),
        access_mode="restricted",
        session_id="cli:direct",
    )


def test_rprompt_shows_idle_hints_and_clears_during_turn_or_palette():
    state = _state()
    rprompt = build_rprompt(state)

    with patch("nanobot.cli.tui.app._buffer_text", return_value=""):
        idle = "".join(f for _s, f in rprompt())
        assert "ctrl+o" in idle

        # During a turn the rprompt clears — status lives on the thinking line.
        state.begin_turn()
        assert rprompt() == []

    state.end_turn()
    # While the palette is open, the rprompt clears to keep the input line clean.
    with patch("nanobot.cli.tui.app._buffer_text", return_value="/dia"):
        assert rprompt() == []


def test_prompt_message_shows_thinking_line_during_turn():
    state = _state()
    message = build_prompt_message(state, "nanobot", width=lambda: 40)

    idle = "".join(f for _s, f in message())
    assert "nanobot" not in idle  # no thinking line when idle
    assert "›" in idle

    state.begin_turn()
    state.note_tool("exec")
    running = "".join(f for _s, f in message())
    assert "nanobot" in running
    assert "Running exec" in running
    assert "esc to interrupt" in running
    # Thinking line carries the dedicated style.
    assert any(style == "class:thinking" for style, _ in message())
