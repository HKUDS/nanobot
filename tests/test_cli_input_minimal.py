import builtins

import nanobot.cli.commands as commands


def test_read_interactive_input_uses_plain_input(monkeypatch) -> None:
    captured: dict[str, str] = {}
    def fake_input(prompt: str = "") -> str:
        captured["prompt"] = prompt
        return "hello"

    monkeypatch.setattr(builtins, "input", fake_input)
    monkeypatch.setattr(commands, "_PROMPT_SESSION", None)
    monkeypatch.setattr(commands, "_READLINE", None)

    value = commands._read_interactive_input()

    assert value == "hello"
    assert captured["prompt"] == "You: "


def test_read_interactive_input_prefers_prompt_session(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakePromptSession:
        async def prompt_async(self, label: object) -> str:
            captured["label"] = label
            return "hello"

    monkeypatch.setattr(commands, "_PROMPT_SESSION", FakePromptSession())
    monkeypatch.setattr(commands, "_PROMPT_SESSION_LABEL", "LBL")

    value = __import__("asyncio").run(commands._read_interactive_input_async())

    assert value == "hello"
    assert captured["label"] == "LBL"


def test_prompt_text_for_readline_modes(monkeypatch) -> None:
    monkeypatch.setattr(commands, "_READLINE", object())
    monkeypatch.setattr(commands, "_USING_LIBEDIT", True)
    assert commands._prompt_text() == "\033[1;34mYou:\033[0m "

    monkeypatch.setattr(commands, "_USING_LIBEDIT", False)
    assert "\001" in commands._prompt_text()


def test_flush_pending_tty_input_skips_non_tty(monkeypatch) -> None:
    class FakeStdin:
        def fileno(self) -> int:
            return 0

    monkeypatch.setattr(commands.sys, "stdin", FakeStdin())
    monkeypatch.setattr(commands.os, "isatty", lambda _fd: False)

    commands._flush_pending_tty_input()
