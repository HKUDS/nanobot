import builtins

import pytest

import nanobot.cli.commands as commands


def test_read_interactive_input_prefers_prompt_session(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakePromptSession:
        def prompt(self, label: object) -> str:
            captured["label"] = label
            return "hello"

    monkeypatch.setattr(commands, "_PROMPT_SESSION", FakePromptSession())
    monkeypatch.setattr(commands, "_PROMPT_SESSION_LABEL", "LABEL")

    value = commands._read_interactive_input()

    assert value == "hello"
    assert captured["label"] == "LABEL"


def test_read_interactive_input_converts_prompt_session_eof(monkeypatch) -> None:
    class FakePromptSession:
        def prompt(self, _label: object) -> str:
            raise EOFError

    monkeypatch.setattr(commands, "_PROMPT_SESSION", FakePromptSession())
    monkeypatch.setattr(commands, "_PROMPT_SESSION_LABEL", "LABEL")

    try:
        commands._read_interactive_input()
    except KeyboardInterrupt:
        assert True
    else:
        assert False, "EOF should be converted to KeyboardInterrupt"


@pytest.mark.asyncio
async def test_read_interactive_input_async_prefers_prompt_session(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakePromptSession:
        async def prompt_async(self, label: object) -> str:
            captured["label"] = label
            return "hello"

    monkeypatch.setattr(commands, "_PROMPT_SESSION", FakePromptSession())
    monkeypatch.setattr(commands, "_PROMPT_SESSION_LABEL", "LABEL")

    value = await commands._read_interactive_input_async()

    assert value == "hello"
    assert captured["label"] == "LABEL"


@pytest.mark.asyncio
async def test_read_interactive_input_async_converts_prompt_session_eof(monkeypatch) -> None:
    class FakePromptSession:
        async def prompt_async(self, _label: object) -> str:
            raise EOFError

    monkeypatch.setattr(commands, "_PROMPT_SESSION", FakePromptSession())
    monkeypatch.setattr(commands, "_PROMPT_SESSION_LABEL", "LABEL")

    with pytest.raises(KeyboardInterrupt):
        await commands._read_interactive_input_async()


def test_read_interactive_input_plain_prompt_when_no_readline(monkeypatch) -> None:
    captured: dict[str, str] = {}

    def fake_input(prompt: str = "") -> str:
        captured["prompt"] = prompt
        return "hello"

    monkeypatch.setattr(commands, "_PROMPT_SESSION", None)
    monkeypatch.setattr(commands, "_READLINE", None)
    monkeypatch.setattr(builtins, "input", fake_input)

    value = commands._read_interactive_input()

    assert value == "hello"
    assert captured["prompt"] == "You: "


def test_read_interactive_input_colored_prompt_with_readline(monkeypatch) -> None:
    captured: dict[str, str] = {}

    def fake_input(prompt: str = "") -> str:
        captured["prompt"] = prompt
        return "hello"

    monkeypatch.setattr(commands, "_PROMPT_SESSION", None)
    monkeypatch.setattr(commands, "_READLINE", object())
    monkeypatch.setattr(commands, "_USING_LIBEDIT", False)
    monkeypatch.setattr(builtins, "input", fake_input)

    value = commands._read_interactive_input()

    assert value == "hello"
    assert "You:" in captured["prompt"]
    assert "\x1b[" in captured["prompt"]


def test_read_interactive_input_colored_prompt_with_libedit(monkeypatch) -> None:
    captured: dict[str, str] = {}

    def fake_input(prompt: str = "") -> str:
        captured["prompt"] = prompt
        return "hello"

    monkeypatch.setattr(commands, "_PROMPT_SESSION", None)
    monkeypatch.setattr(commands, "_READLINE", object())
    monkeypatch.setattr(commands, "_USING_LIBEDIT", True)
    monkeypatch.setattr(builtins, "input", fake_input)

    value = commands._read_interactive_input()

    assert value == "hello"
    assert captured["prompt"] == "\x1b[1;34mYou:\x1b[0m "


def test_remember_input_history_dedupes_adjacent(monkeypatch) -> None:
    class FakeReadline:
        def __init__(self) -> None:
            self.items: list[str] = []

        def get_current_history_length(self) -> int:
            return len(self.items)

        def get_history_item(self, index: int) -> str | None:
            if index <= 0 or index > len(self.items):
                return None
            return self.items[index - 1]

        def add_history(self, text: str) -> None:
            self.items.append(text)

    fake = FakeReadline()
    monkeypatch.setattr(commands, "_READLINE", fake)

    commands._remember_input_history("abc")
    commands._remember_input_history("abc")
    commands._remember_input_history("xyz")

    assert fake.items == ["abc", "xyz"]


def test_compute_visual_positions_wraps_wide_chars() -> None:
    positions = commands._compute_visual_positions(
        text="哈哈哈哈",
        columns=8,
        prompt_columns=4,
    )

    assert positions[0] == (0, 4)
    assert positions[1] == (0, 6)
    assert positions[2] == (0, 8)
    assert positions[3] == (1, 2)
    assert positions[4] == (1, 4)


def test_move_cursor_visual_moves_across_soft_wrapped_lines() -> None:
    text = "哈哈哈哈哈哈"
    end = len(text)

    new_pos, moved, preferred = commands._move_cursor_visual(
        text=text,
        cursor_position=end,
        delta=-1,
        columns=10,
        prompt_columns=4,
        preferred_column=None,
    )

    assert moved is True
    assert new_pos < end
    assert preferred is not None


def test_move_cursor_visual_returns_false_at_boundary() -> None:
    new_pos, moved, preferred = commands._move_cursor_visual(
        text="hello",
        cursor_position=0,
        delta=-1,
        columns=80,
        prompt_columns=4,
        preferred_column=None,
    )

    assert moved is False
    assert new_pos == 0
    assert preferred is None


def test_find_cursor_for_row_and_column_uses_nearest_column() -> None:
    positions = [
        (0, 4),
        (0, 6),
        (1, 0),
        (1, 2),
        (1, 4),
        (1, 6),
    ]

    idx = commands._find_cursor_for_row_and_column(
        positions=positions,
        target_row=1,
        preferred_column=5,
    )
    assert idx == 5


def test_choose_visual_rowcol_moves_to_same_screen_column() -> None:
    rowcol_to_yx = {
        (0, 0): (0, 5),
        (0, 1): (0, 7),
        (0, 2): (0, 9),
        (0, 3): (1, 1),
        (0, 4): (1, 3),
        (0, 5): (1, 5),
    }

    next_rowcol, pref_x = commands._choose_visual_rowcol(
        rowcol_to_yx=rowcol_to_yx,
        current_rowcol=(0, 4),
        delta=-1,
        preferred_x=None,
    )

    assert next_rowcol == (0, 0)
    assert pref_x == 3


def test_choose_visual_rowcol_returns_none_at_boundary() -> None:
    rowcol_to_yx = {
        (0, 0): (0, 5),
        (0, 1): (0, 7),
    }

    next_rowcol, pref_x = commands._choose_visual_rowcol(
        rowcol_to_yx=rowcol_to_yx,
        current_rowcol=(0, 1),
        delta=-1,
        preferred_x=None,
    )

    assert next_rowcol is None
    assert pref_x is None


def test_can_reuse_visual_anchor_requires_continuity() -> None:
    class FakeBuffer:
        def __init__(self) -> None:
            self.cursor_position = 5
            self.text = "hello"

    buf = FakeBuffer()
    setattr(buf, "_nanobot_visual_last_dir", -1)
    setattr(buf, "_nanobot_visual_last_cursor", 5)
    setattr(buf, "_nanobot_visual_last_text", "hello")

    assert commands._can_reuse_visual_anchor(buf, -1) is True

    buf.cursor_position = 4
    assert commands._can_reuse_visual_anchor(buf, -1) is False


def test_clear_visual_nav_state_resets_cache() -> None:
    class FakeBuffer:
        pass

    buf = FakeBuffer()
    setattr(buf, "_nanobot_visual_pref_col", 3)
    setattr(buf, "_nanobot_visual_pref_x", 10)
    setattr(buf, "_nanobot_visual_last_dir", -1)
    setattr(buf, "_nanobot_visual_last_cursor", 99)
    setattr(buf, "_nanobot_visual_last_text", "abc")

    commands._clear_visual_nav_state(buf)

    assert getattr(buf, "_nanobot_visual_pref_col") is None
    assert getattr(buf, "_nanobot_visual_pref_x") is None
    assert getattr(buf, "_nanobot_visual_last_dir") is None
    assert getattr(buf, "_nanobot_visual_last_cursor") is None
    assert getattr(buf, "_nanobot_visual_last_text") is None
