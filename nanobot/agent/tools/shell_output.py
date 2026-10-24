"""Terminal control filtering for shell tool output."""

from __future__ import annotations

import re


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


_BENIGN_XCRUN_CACHE_NOISE = re.compile(
    r"^\S+: error: couldn't (?:create|open|replace) cache file '[^']*xcrun_db[^']*'"
    r" \(errno=Operation not permitted\)$"
)


def filter_stderr_noise(stderr: str) -> str:
    """Drop xcrun shim cache-denial noise that the sandbox cannot allow.

    On stock macOS the ``/usr/bin`` toolchain shims (``git``, ``swift``, ...)
    must open/replace their shared ``xcrun_db`` cache under the host
    DARWIN_USER temp dir, which the seatbelt profile intentionally does not
    share (host scratch directories must stay private). The denial does not
    affect the command's outcome, but every invocation injects two
    ``couldn't <verb> cache file ... (errno=Operation not permitted)`` lines
    into stderr — surfacing to the agent as a spurious STDERR section that
    reads like a failure. Only lines matching that exact xcrun cache shape
    are dropped; any other stderr content is preserved.
    """
    if "xcrun_db" not in stderr:
        return stderr
    kept = [line for line in stderr.splitlines() if not _BENIGN_XCRUN_CACHE_NOISE.match(line)]
    if not kept:
        return ""
    return "\n".join(kept) + ("\n" if stderr.endswith("\n") else "")
