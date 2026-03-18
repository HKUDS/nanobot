"""Resolve secret references used in runtime config values.

Supported forms:
- {file:/abs/or/relative/path}
- {exec:command to run}

References can be used as a whole value or interpolated inline, for example:
"Bearer {file:~/.secrets/token}".
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

_REF_PATTERN = re.compile(r"\{(?P<kind>file|exec):(?P<body>[^{}]+)\}")


class SecretRefError(ValueError):
    """Raised when a secret reference cannot be resolved."""


def get_active_config_dir() -> Path:
    """Return the parent directory of the active config file."""
    from nanobot.config.loader import get_config_path

    return get_config_path().expanduser().resolve().parent


def resolve_config_value(
    value: Any,
    *,
    field_path: str = "config",
    base_dir: Path | None = None,
) -> Any:
    """Resolve secret refs recursively in values used at runtime.

    Only string values are transformed. Non-string values are returned as-is.
    """
    if isinstance(value, str):
        if "{file:" not in value and "{exec:" not in value:
            return value
        base = base_dir or get_active_config_dir()
        return _resolve_string(value, field_path=field_path, base_dir=base)
    if isinstance(value, list):
        base = base_dir or get_active_config_dir()
        return [
            resolve_config_value(item, field_path=f"{field_path}[{idx}]", base_dir=base)
            for idx, item in enumerate(value)
        ]
    if isinstance(value, dict):
        base = base_dir or get_active_config_dir()
        resolved: dict[Any, Any] = {}
        for key, item in value.items():
            key_str = str(key)
            child_path = f"{field_path}.{key_str}" if field_path else key_str
            resolved[key] = resolve_config_value(item, field_path=child_path, base_dir=base)
        return resolved
    return value


def _resolve_string(text: str, *, field_path: str, base_dir: Path) -> str:
    """Resolve all refs in a string, preserving other text verbatim."""
    if "{file:" not in text and "{exec:" not in text:
        return text

    chunks: list[str] = []
    last = 0
    refs = 0
    for match in _REF_PATTERN.finditer(text):
        refs += 1
        chunks.append(text[last : match.start()])
        kind = match.group("kind")
        body = match.group("body")
        if kind == "file":
            chunks.append(_resolve_file_ref(body, field_path=field_path, base_dir=base_dir))
        else:
            chunks.append(_resolve_exec_ref(body, field_path=field_path, base_dir=base_dir))
        last = match.end()

    if refs == 0:
        raise SecretRefError(f"{field_path}: malformed secret ref syntax")

    chunks.append(text[last:])
    return "".join(chunks)


def _resolve_file_ref(path_spec: str, *, field_path: str, base_dir: Path) -> str:
    raw_path = path_spec.strip()
    if not raw_path:
        raise SecretRefError(f"{field_path}: empty file ref")

    file_path = Path(raw_path).expanduser()
    if not file_path.is_absolute():
        file_path = base_dir / file_path

    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception as exc:
        raise SecretRefError(
            f"{field_path}: failed to read secret file '{file_path}': {exc}"
        ) from exc

    return content.rstrip("\r\n")


def _resolve_exec_ref(command_spec: str, *, field_path: str, base_dir: Path) -> str:
    command = command_spec.strip()
    if not command:
        raise SecretRefError(f"{field_path}: empty exec ref")

    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=str(base_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )
    except Exception as exc:
        raise SecretRefError(
            f"{field_path}: failed to execute secret command '{command}': {exc}"
        ) from exc

    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip() or "(no stderr output)"
        raise SecretRefError(
            f"{field_path}: secret command failed (exit {proc.returncode}): {stderr}"
        )

    output = (proc.stdout or "").rstrip("\r\n")
    if not output:
        raise SecretRefError(f"{field_path}: secret command returned empty output")

    return output
