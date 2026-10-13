#!/usr/bin/env python3
"""Exercise the TUI through the native Windows ConPTY boundary."""

from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ENTER_ALT_SCREEN = "\x1b[?1049h"
LEAVE_ALT_SCREEN = "\x1b[?1049l"
RESUME_COMMAND = "Resume with: nanobot agent --session websocket:resume-chat"


def _read(process: Any, timeout: float) -> str:
    output: list[str] = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            chunk = process.read(65_536)
        except EOFError:
            break
        if chunk:
            output.append(chunk)
        else:
            time.sleep(0.01)
    return "".join(output)


def _wait_for(process: Any, needle: str, timeout: float) -> str:
    output: list[str] = []
    deadline = time.monotonic() + timeout
    while needle not in "".join(output) and time.monotonic() < deadline:
        output.append(_read(process, min(0.1, deadline - time.monotonic())))
    text = "".join(output)
    if needle not in text:
        raise AssertionError(
            f"terminal output did not contain {needle!r}; recent output: {text[-2000:]!r}"
        )
    return text


def _wait_for_exit(process: Any, timeout: float) -> int:
    deadline = time.monotonic() + timeout
    while process.isalive() and time.monotonic() < deadline:
        time.sleep(0.05)
    if process.isalive():
        process.close(force=True)
        raise AssertionError("TUI did not exit after the exit command")
    return int(process.exitstatus or 0)


def main() -> int:
    if os.name != "nt":
        raise SystemExit("ConPTY smoke test requires Windows")

    # PyWinPTY's high-level reader otherwise blocks when ConPTY has no new
    # bytes, preventing bounded CI assertions.
    os.environ["PYWINPTY_BLOCK"] = "0"
    from winpty import PtyProcess  # type: ignore[import-not-found]
    from winpty.enums import Backend  # type: ignore[import-not-found]

    bun = shutil.which("bun")
    if not bun:
        raise SystemExit("bun is required")
    env = {
        **os.environ,
        "NANOBOT_TUI_WS_URL": "ws://127.0.0.1:9/ws",
        "NANOBOT_TUI_API_URL": "",
        "NANOBOT_TUI_API_TOKEN": "",
        "NANOBOT_TUI_CHAT_ID": "resume-chat",
        "NANOBOT_TUI_MODEL": "test/model",
        "NANOBOT_TUI_WORKSPACE": r"C:\nanobot-tui-conpty",
        "NANOBOT_TUI_VERSION": "test",
        "NANOBOT_TUI_ACCESS": "workspace access",
        "NANOBOT_TUI_THEME": "dark",
        # Headless ConPTY has no terminal emulator to answer optional OSC 66
        # width probes. Keep this smoke test focused on application behavior.
        "OPENTUI_FORCE_EXPLICIT_WIDTH": "false",
    }
    env.pop("HERDR_ENV", None)
    env.pop("HERDR_PANE_ID", None)
    process = PtyProcess.spawn(
        [bun, "src/index.ts"],
        cwd=str(ROOT),
        env=env,
        dimensions=(24, 80),
        backend=Backend.ConPTY,
    )

    output: list[str] = []
    try:
        output.append(_wait_for(process, ENTER_ALT_SCREEN, 15))
        for grapheme in "abc中文🙂":
            process.write(grapheme)
            time.sleep(0.03)
        output.append(_read(process, 0.5))

        process.setwinsize(18, 42)
        resized = _read(process, 0.75)
        output.append(resized)
        if "\x1b[18;" not in resized or ";42H" not in resized:
            raise AssertionError("TUI did not repaint to the resized ConPTY dimensions")

        # Ctrl+C clears the draft. The local exit command must still work while
        # the intentionally unavailable gateway has not attached a chat.
        process.sendcontrol("c")
        output.append(_read(process, 0.2))
        process.write("exit\r")
        output.append(_wait_for(process, LEAVE_ALT_SCREEN, 8))
        exit_code = _wait_for_exit(process, 8)
        output.append(_read(process, 0.5))
    finally:
        if process.isalive():
            process.close(force=True)

    text = "".join(output)
    if exit_code != 0:
        raise AssertionError(f"TUI exited with status {exit_code}")
    for glyph in "abc中文🙂":
        if glyph not in text:
            raise AssertionError(f"TUI did not render committed input {glyph!r}")
    if "Traceback" in text or "Task exception was never retrieved" in text:
        raise AssertionError("TUI emitted an exception during shutdown")
    if text.count(RESUME_COMMAND) != 1:
        raise AssertionError("TUI did not print exactly one reusable session command")
    if text.index(RESUME_COMMAND) < text.index(LEAVE_ALT_SCREEN):
        raise AssertionError("TUI printed the session command before restoring the terminal")
    print("ConPTY smoke test passed: Unicode input, resize, restoration, and session resume")
    return 0


if __name__ == "__main__":
    sys.exit(main())
