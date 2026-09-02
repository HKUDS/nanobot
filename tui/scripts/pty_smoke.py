#!/usr/bin/env python3
"""Exercise the TUI through a real POSIX pseudo-terminal.

OpenTUI's test renderer proves retained-layout semantics. This smoke test covers
the OS boundary it cannot: raw Unicode input, SIGWINCH-driven resize, and
alternate-screen restoration after Ctrl+C.
"""

from __future__ import annotations

import errno
import fcntl
import os
import pty
import select
import shutil
import signal
import struct
import sys
import termios
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTER_ALT_SCREEN = b"\x1b[?1049h"
LEAVE_ALT_SCREEN = b"\x1b[?1049l"
RESUME_COMMAND = b"Resume with: nanobot agent --session websocket:resume-chat"


def _resize(fd: int, rows: int, columns: int) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, columns, 0, 0))


def _read(fd: int, timeout: float) -> bytes:
    output = bytearray()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        readable, _, _ = select.select([fd], [], [], min(0.05, deadline - time.monotonic()))
        if not readable:
            continue
        try:
            chunk = os.read(fd, 65_536)
        except OSError as exc:
            if exc.errno == errno.EIO:  # PTY slave closed.
                break
            raise
        if not chunk:
            break
        output.extend(chunk)
    return bytes(output)


def _wait_for(fd: int, needle: bytes, timeout: float) -> bytes:
    output = bytearray()
    deadline = time.monotonic() + timeout
    while needle not in output and time.monotonic() < deadline:
        output.extend(_read(fd, min(0.1, deadline - time.monotonic())))
    if needle not in output:
        raise AssertionError(f"terminal output did not contain {needle!r}")
    return bytes(output)


def _wait_for_exit(pid: int, timeout: float) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        child, status = os.waitpid(pid, os.WNOHANG)
        if child:
            return os.waitstatus_to_exitcode(status)
        time.sleep(0.05)
    os.kill(pid, signal.SIGKILL)
    os.waitpid(pid, 0)
    raise AssertionError("TUI did not exit after the exit command")


def main() -> int:
    if os.name != "posix":
        raise SystemExit("PTY smoke test requires POSIX")
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
        "NANOBOT_TUI_WORKSPACE": "/tmp/nanobot-tui-pty",
        "NANOBOT_TUI_VERSION": "test",
        "NANOBOT_TUI_ACCESS": "workspace access",
        # A fixed theme keeps this test about PTY behavior rather than the
        # terminal emulator's optional OSC 10/11 response.
        "NANOBOT_TUI_THEME": "dark",
    }
    env.pop("HERDR_ENV", None)
    env.pop("HERDR_PANE_ID", None)

    pid, master = pty.fork()
    if pid == 0:
        os.chdir(ROOT)
        os.execvpe(bun, [bun, "src/index.ts"], env)

    output = bytearray()
    reaped = False
    try:
        _resize(master, 24, 80)
        output.extend(_wait_for(master, ENTER_ALT_SCREEN, 10))

        # Feed committed UTF-8 one grapheme at a time. The raw terminal stream
        # should contain every glyph, even though differential rendering may
        # place escape sequences between adjacent characters.
        for grapheme in "abc中文🙂":
            os.write(master, grapheme.encode())
            time.sleep(0.03)
        output.extend(_read(master, 0.5))

        _resize(master, 18, 42)
        os.kill(pid, signal.SIGWINCH)
        resized = _read(master, 0.5)
        output.extend(resized)
        if b"\x1b[18;" not in resized or b";42H" not in resized:
            raise AssertionError("TUI did not repaint to the resized PTY dimensions")

        # Ctrl+C clears the draft. The local exit command must still work while
        # the intentionally unavailable gateway has not attached a chat.
        os.write(master, b"\x03")
        output.extend(_read(master, 0.2))
        os.write(master, b"exit\r")
        output.extend(_wait_for(master, LEAVE_ALT_SCREEN, 5))
        exit_code = _wait_for_exit(pid, 5)
        output.extend(_read(master, 0.5))
        reaped = True
    finally:
        if not reaped:
            try:
                child, _ = os.waitpid(pid, os.WNOHANG)
                if not child:
                    os.kill(pid, signal.SIGKILL)
                    os.waitpid(pid, 0)
            except ChildProcessError:
                pass
        os.close(master)

    text = output.decode("utf-8", errors="replace")
    if exit_code != 0:
        raise AssertionError(f"TUI exited with status {exit_code}")
    for glyph in "abc中文🙂":
        if glyph not in text:
            raise AssertionError(f"TUI did not render committed input {glyph!r}")
    if "Traceback" in text or "Task exception was never retrieved" in text:
        raise AssertionError("TUI emitted an exception during shutdown")
    if output.count(RESUME_COMMAND) != 1:
        raise AssertionError("TUI did not print exactly one reusable session command")
    if output.index(RESUME_COMMAND) < output.index(LEAVE_ALT_SCREEN):
        raise AssertionError("TUI printed the session command before restoring the terminal")
    # The UI must inherit the host terminal background. Fixed RGB/indexed
    # surfaces become black strips in embedded terminals after long output.
    for escape in (
        b"\x1b[48;2;14;15;17m",
        b"\x1b[48;2;23;24;27m",
        b"\x1b[48;5;233m",
        b"\x1b[48;5;234m",
    ):
        if escape in output:
            raise AssertionError(f"TUI painted a fixed background: {escape!r}")
    print("PTY smoke test passed: Unicode input, resize, restoration, and session resume")
    return 0


if __name__ == "__main__":
    sys.exit(main())
