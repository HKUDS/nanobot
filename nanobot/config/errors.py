"""User-safe configuration diagnostics."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

ConfigErrorKind = Literal[
    "invalid_json",
    "invalid_root",
    "invalid_schema",
    "missing_env",
    "io_error",
]
ConfigPathPart = str | int
_SAFE_LOCATION_PART = re.compile(r"[A-Za-z_][A-Za-z0-9_-]{0,63}")


def _display_location_part(part: ConfigPathPart) -> str:
    if isinstance(part, int):
        return str(part)
    return part if _SAFE_LOCATION_PART.fullmatch(part) else "<redacted>"


@dataclass(frozen=True)
class ConfigIssue:
    """One actionable configuration problem."""

    path: tuple[ConfigPathPart, ...]
    message: str

    @property
    def location(self) -> str:
        # Pydantic locations can contain user-controlled mapping keys. Only
        # render conventional config identifiers so credential-bearing URLs
        # and other free-form values cannot leak through a redacted error.
        if not self.path:
            return "<root>"
        return ".".join(_display_location_part(part) for part in self.path)


class ConfigLoadError(ValueError):
    """A structured, user-safe configuration loading failure."""

    def __init__(
        self,
        path: Path,
        *,
        kind: ConfigErrorKind,
        summary: str,
        issues: tuple[ConfigIssue, ...] = (),
    ) -> None:
        self.path = path
        self.kind = kind
        self.summary = summary
        self.issues = issues
        super().__init__(summary)

    def __str__(self) -> str:
        lines = [f"Invalid configuration: {self.path}", "", self.summary]
        for issue in self.issues[:10]:
            lines.extend(("", f"  {issue.location}", f"    {issue.message}"))
        remaining = len(self.issues) - 10
        if remaining > 0:
            lines.extend(("", f"  … and {remaining} more issue(s)"))
        return "\n".join(lines)


def validation_issues(
    error: ValidationError,
) -> tuple[ConfigIssue, ...]:
    """Convert Pydantic details to actionable messages without exposing input values."""
    issues: list[ConfigIssue] = []
    for detail in error.errors(
        include_url=False,
        include_context=False,
        include_input=False,
    ):
        location = tuple(detail.get("loc", ()))
        code = str(detail.get("type") or "")
        message = _friendly_validation_message(
            str(detail.get("msg") or "Invalid value"),
            code,
        )
        issues.append(ConfigIssue(path=location, message=message))
    return tuple(issues)


def _friendly_validation_message(message: str, code: str) -> str:
    if code == "extra_forbidden":
        return "Unknown setting."
    if code == "missing":
        return "This setting is required."
    if code in {"assertion_error", "value_error"}:
        # Custom validators control these messages and may interpolate the
        # rejected value. Keep the field location, but never render that text.
        return "Value does not satisfy this setting's requirements."
    if message.startswith("Value error, "):
        message = message.removeprefix("Value error, ")
    elif message.startswith("Input should be "):
        message = "Must be " + message.removeprefix("Input should be ")
    elif message.startswith("Input should have "):
        message = "Must have " + message.removeprefix("Input should have ")
    if message:
        message = message[:1].upper() + message[1:]
    if message and message[-1] not in ".!?":
        message += "."
    return message or "Invalid value."
