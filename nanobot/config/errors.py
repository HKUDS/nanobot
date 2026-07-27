"""User-safe configuration diagnostics."""

from __future__ import annotations

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


@dataclass(frozen=True)
class ConfigIssue:
    """One actionable configuration problem."""

    path: tuple[ConfigPathPart, ...]
    message: str
    code: str | None = None

    @property
    def location(self) -> str:
        return ".".join(str(part) for part in self.path) if self.path else "<root>"


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
    *,
    prefix: tuple[ConfigPathPart, ...] = (),
) -> tuple[ConfigIssue, ...]:
    """Convert Pydantic details to actionable messages without exposing input values."""
    issues: list[ConfigIssue] = []
    for detail in error.errors(
        include_url=False,
        include_context=False,
        include_input=False,
    ):
        location = prefix + tuple(detail.get("loc", ()))
        code = str(detail.get("type") or "")
        message = _friendly_validation_message(
            str(detail.get("msg") or "Invalid value"),
            code,
        )
        issues.append(ConfigIssue(path=location, message=message, code=code or None))
    return tuple(issues)


def concise_validation_error(
    error: ValidationError,
    *,
    prefix: tuple[ConfigPathPart, ...] = (),
) -> str:
    """Return a compact validation message suitable for status surfaces."""
    issues = validation_issues(error, prefix=prefix)
    visible = issues[:3]
    message = "; ".join(f"{issue.location}: {issue.message}" for issue in visible)
    remaining = len(issues) - len(visible)
    if remaining > 0:
        message += f"; and {remaining} more issue(s)"
    return message or "Invalid configuration."


def _friendly_validation_message(message: str, code: str) -> str:
    if code == "extra_forbidden":
        return "Unknown setting."
    if code == "missing":
        return "This setting is required."
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
