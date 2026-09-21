"""Bounded, file-backed user prompts. Templates never execute code or read other files."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

import yaml
from filelock import FileLock, Timeout

from nanobot.command.builtin import BUILTIN_COMMAND_SPECS, USER_SHELL_COMMAND
from nanobot.command.router import normalize_command_text
from nanobot.config.paths import get_config_path

_NAME = re.compile(r"[a-z][a-z0-9-]{0,47}\Z")
_RESERVED = {spec.command[1:] for spec in BUILTIN_COMMAND_SPECS} | {USER_SHELL_COMMAND[1:]}
_MAX_BYTES = 64 * 1024
_MAX_COMMANDS = 128
# PyYAML does not annotate scan's stream/token iterator; constrain it at this SDK edge.
_scan = cast(Callable[[str], Iterable[object]], yaml.scan)  # pyright: ignore[reportUnknownMemberType]


class PromptCommandError(ValueError):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class PromptCommand:
    name: str
    description: str
    argument_hint: str
    body: str
    enabled: bool
    source: str
    revision: str

    def palette(self) -> dict[str, str | bool]:
        return {
            "command": f"/{self.name}", "title": self.name,
            "description": self.description, "arg_hint": self.argument_hint,
            "icon": "file-text", "lifecycle": "agent_turn", "accepts_args": True,
            "source": self.source,
        }

    def expand(self, arguments: str) -> str:
        body = self.body.replace("$ARGUMENTS", arguments)
        if "$ARGUMENTS" not in self.body and arguments:
            body += f"\n\n{arguments}"
        # This is a normal user message, not a system instruction or slash redispatch.
        return f"Prompt /{self.name} ({self.source}):\n\n{body}"


class PromptCommands:
    def __init__(self, workspace: Path, config_path: Path | None = None) -> None:
        self._bases = {
            "user": (config_path or get_config_path()).expanduser().resolve().parent,
            "workspace": workspace.expanduser().resolve(),
        }

    def _root(self, source: str) -> Path:
        if source not in self._bases:
            raise PromptCommandError("invalid command source")
        base = self._bases[source]
        relative = Path("commands") if source == "user" else Path(".nanobot/commands")
        root = base / relative
        current = base
        for segment in relative.parts:
            current /= segment
            if current.is_symlink():
                raise PromptCommandError("command directories must not be symbolic links", 403)
        return root

    @staticmethod
    def _validate_name(name: str) -> None:
        if not _NAME.fullmatch(name) or name in _RESERVED:
            raise PromptCommandError("use a lowercase name (letters, digits, hyphens); built-ins are reserved")

    def _read(self, source: str, name: str) -> PromptCommand | None:
        self._validate_name(name)
        path = self._root(source) / f"{name}.md"
        if path.is_symlink():
            raise PromptCommandError("command files must not be symbolic links", 403)
        if not path.exists():
            return None
        with path.open("rb") as stream:
            raw = stream.read(_MAX_BYTES + 1)
        if len(raw) > _MAX_BYTES:
            raise PromptCommandError("command exceeds 64 KiB")
        text = raw.decode("utf-8")
        if not text.startswith("---\n") or "\n---\n" not in text[4:]:
            raise PromptCommandError("command requires YAML frontmatter and a prompt body")
        header, body = text[4:].split("\n---\n", 1)
        if len(header) > 4096:
            raise PromptCommandError("command metadata is too large")
        # Flat scalars only: disallow alias graphs, tags and YAML object construction.
        mappings = 0
        for index, token in enumerate(_scan(header)):
            if isinstance(token, yaml.BlockMappingStartToken):
                mappings += 1
            if (index > 64 or mappings > 1 or isinstance(token, (
                    yaml.AliasToken, yaml.AnchorToken, yaml.TagToken,
                    yaml.FlowMappingStartToken, yaml.FlowSequenceStartToken,
                    yaml.BlockSequenceStartToken))):
                raise PromptCommandError("command metadata must contain plain scalars")
        parsed: object = yaml.load(header, Loader=yaml.BaseLoader)
        if not isinstance(parsed, dict):
            raise PromptCommandError("invalid command metadata")
        meta = cast(dict[str, object], parsed)
        if set(meta) - {"description", "argument_hint", "enabled"}:
            raise PromptCommandError("unknown command metadata field")
        description, hint = meta.get("description", ""), meta.get("argument_hint", "")
        enabled = meta.get("enabled", "true")
        if (not isinstance(description, str) or len(description) > 240
                or not isinstance(hint, str) or len(hint) > 120
                or enabled not in ("true", "false") or not body.strip()):
            raise PromptCommandError("invalid description, argument hint, enabled flag or empty prompt")
        return PromptCommand(name, description, hint, body.strip(), enabled == "true", source,
                             hashlib.sha256(raw).hexdigest())

    def entries(self) -> tuple[list[PromptCommand], int]:
        entries: list[PromptCommand] = []
        invalid = 0
        for source in self._bases:
            try:
                paths = sorted(self._root(source).glob("*.md"))
            except (OSError, ValueError):
                invalid += 1
                continue
            invalid += max(0, len(paths) - _MAX_COMMANDS)
            for path in paths[:_MAX_COMMANDS]:
                try:
                    entry = self._read(source, path.stem)
                    if entry is not None:
                        entries.append(entry)
                except (OSError, ValueError, yaml.YAMLError):
                    invalid += 1
        return entries, invalid

    def effective(self) -> list[PromptCommand]:
        # Workspace entries, including disabled ones, shadow instance entries.
        entries, _ = self.entries()
        names = dict.fromkeys(entry.name for entry in entries)
        return [match[0] for name in names if (match := self.lookup(f"/{name}"))]

    def lookup(self, text: str) -> tuple[PromptCommand, str] | None:
        parts = normalize_command_text(text).split(maxsplit=1)
        if not parts or not parts[0].startswith("/"):
            return None
        name = parts[0][1:].lower()
        if not _NAME.fullmatch(name) or name in _RESERVED:
            return None
        # Read only the requested name on the hot ingress path.
        selected = None
        for source in self._bases:
            try:
                entry = self._read(source, name)
            except (OSError, ValueError, yaml.YAMLError):
                # A broken workspace override must not silently run a different user prompt.
                return None
            if entry is not None:
                selected = entry
        return (selected, parts[1] if len(parts) > 1 else "") if selected and selected.enabled else None

    def payload(self) -> dict[str, Any]:
        entries, invalid = self.entries()
        overrides = {entry.name for entry in entries if entry.source == "workspace"}
        return {"commands": [{**asdict(entry), "shadowed": entry.source == "user"
                              and entry.name in overrides} for entry in entries], "invalid": invalid}

    def save(self, data: dict[str, Any], *, delete: bool = False) -> None:
        name, source, revision = data.get("name"), data.get("source"), data.get("revision")
        if not all(isinstance(value, str) for value in (name, source, revision)):
            raise PromptCommandError("name, source and revision are required")
        name, source, revision = str(name), str(source), str(revision)
        self._validate_name(name)
        root = self._root(source)
        root.mkdir(parents=True, exist_ok=True)
        lock_path = root / ".commands.lock"
        if lock_path.is_symlink():
            raise PromptCommandError("invalid command lock", 403)
        lock = FileLock(str(lock_path), timeout=5)
        try:
            lock.acquire()
        except Timeout as exc:
            raise PromptCommandError("command is busy; retry saving", 409) from exc
        try:
            current = self._read(source, name)
            if (current.revision if current else "") != revision:
                raise PromptCommandError("command changed; reload before saving", 409)
            target = root / f"{name}.md"
            if delete:
                if current:
                    target.unlink()
                return
            description, hint, body = (data.get(key, "") for key in
                                       ("description", "argument_hint", "body"))
            enabled = data.get("enabled", True)
            if (not isinstance(description, str) or len(description) > 240
                    or not isinstance(hint, str) or len(hint) > 120
                    or not isinstance(body, str) or not body.strip() or not isinstance(enabled, bool)):
                raise PromptCommandError("invalid command fields")
            if current is None and sum(1 for _ in root.glob("*.md")) >= _MAX_COMMANDS:
                raise PromptCommandError("command limit reached (128 per source)")
            encoded = ("---\n" + yaml.safe_dump({"description": description,
                       "argument_hint": hint, "enabled": enabled}, allow_unicode=True)
                       + "---\n" + body.strip() + "\n").encode("utf-8")
            if len(encoded) > _MAX_BYTES:
                raise PromptCommandError("command exceeds 64 KiB")
            with tempfile.NamedTemporaryFile(dir=root, prefix=".prompt-", delete=False) as temporary:
                pending = Path(temporary.name)
                try:
                    temporary.write(encoded)
                    temporary.flush()
                    os.fsync(temporary.fileno())
                except BaseException:
                    pending.unlink(missing_ok=True)
                    raise
            try:
                os.replace(pending, target)
            finally:
                pending.unlink(missing_ok=True)
        finally:
            lock.release()
