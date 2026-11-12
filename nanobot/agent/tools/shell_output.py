"""Terminal control filtering for shell tool output."""

from __future__ import annotations


class ShellOutputFilter:
    """Strip terminal escapes, preserving visible text and whitespace.

    Use one instance per decoded stdout/stderr stream so escape sequences can
    span reads. Only parser state is retained, never control-string payloads.
    """

    def __init__(self) -> None:
        self._state = "text"
        self._string_escape = False

    def feed(self, text: str) -> str:
        if self._state == "text" and "\x1b" not in text:
            return text

        output: list[str] = []
        for char in text:
            if self._state in ("osc", "string"):
                if (self._string_escape and char == "\\") or (
                    self._state == "osc" and char == "\x07"
                ):
                    self._state = "text"
                self._string_escape = char == "\x1b"
            elif char == "\x1b":
                self._state = "escape"
            elif self._state in ("escape", "intermediate"):
                if self._state == "escape" and char == "[":
                    self._state = "csi"
                elif self._state == "escape" and char in "]PX^_":
                    self._state = "osc" if char == "]" else "string"
                    self._string_escape = False
                elif " " <= char <= "/":
                    self._state = "intermediate"
                else:
                    self._state = "text"
                    if not "0" <= char <= "~":
                        output.append(char)
            elif self._state == "csi":
                if "@" <= char <= "~":
                    self._state = "text"
                elif not " " <= char <= "?":
                    self._state = "text"
                    output.append(char)
            else:
                output.append(char)
        return "".join(output)
