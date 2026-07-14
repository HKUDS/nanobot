"""Instance-scoped configuration persistence and resolution."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import threading
import uuid
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger
from pydantic import BaseModel

from nanobot.config.schema import Config

ConfigMutator = Callable[[Config], None]

_ENV_REF_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

# Several WebUI config actions run in worker threads via asyncio.to_thread().
# Repository instances for the same path therefore share a process-local lock.
_path_locks_guard = threading.Lock()
_path_locks: dict[Path, threading.RLock] = {}


class ConfigConflictError(RuntimeError):
    """Raised when a caller tries to update a stale configuration snapshot."""


@dataclass(frozen=True)
class PersistedConfigSnapshot:
    """Validated configuration as represented by the persisted source."""

    config: Config
    path: Path
    revision: str


@dataclass(frozen=True)
class EffectiveConfigSnapshot:
    """Runtime configuration with environment references resolved."""

    config: Config
    path: Path
    revision: str


@dataclass(frozen=True)
class ConfigCommit:
    """One atomic configuration update and its semantic field changes."""

    before: PersistedConfigSnapshot
    after: PersistedConfigSnapshot
    changed_paths: frozenset[str]


def _lock_for_path(path: Path) -> threading.RLock:
    key = path.expanduser().resolve(strict=False)
    with _path_locks_guard:
        return _path_locks.setdefault(key, threading.RLock())


def _revision_for_bytes(raw: bytes | None) -> str:
    if raw is None:
        return "missing"
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def _config_data(config: Config) -> dict[str, Any]:
    data = config.model_dump(mode="json", by_alias=True)
    if config.providers.openai_codex.proxy is not None:
        data.setdefault("providers", {})["openaiCodex"] = {
            "proxy": config.providers.openai_codex.proxy,
        }
    return data


def _validate_config_data(data: dict[str, Any], path: Path) -> Config:
    try:
        return Config.model_validate(data)
    except ValueError as exc:
        raise ValueError(f"Failed to load config from {path}: {exc}") from exc


def _read_snapshot(path: Path) -> PersistedConfigSnapshot:
    if not path.exists():
        return PersistedConfigSnapshot(Config(), path, "missing")

    try:
        raw = path.read_bytes()
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("config root must be a JSON object")
        data = _migrate_config(data)
        config = Config.model_validate(data)
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"Failed to load config from {path}: {exc}") from exc
    return PersistedConfigSnapshot(config, path, _revision_for_bytes(raw))


def _write_config_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(data, indent=2, ensure_ascii=False)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    existing_mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else None
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            if existing_mode is not None:
                try:
                    os.chmod(tmp, existing_mode)
                except OSError:
                    if os.name != "nt":
                        raise
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        with suppress(OSError, NotImplementedError):
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        tmp.unlink(missing_ok=True)


def _changed_paths(before: Any, after: Any, prefix: str = "") -> set[str]:
    if isinstance(before, dict) and isinstance(after, dict):
        changed: set[str] = set()
        for key in before.keys() | after.keys():
            path = f"{prefix}.{key}" if prefix else str(key)
            if key not in before or key not in after:
                changed.add(path)
            else:
                changed.update(_changed_paths(before[key], after[key], path))
        return changed
    if before != after:
        return {prefix} if prefix else {"<root>"}
    return set()


class FileConfigRepository:
    """Read and atomically update one configuration file.

    The repository does not cache. Every read returns a new validated snapshot.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve(strict=False)
        self._lock = _lock_for_path(self.path)

    def load_raw(self) -> PersistedConfigSnapshot:
        """Load the persisted form without resolving secret references."""
        with self._lock:
            return _read_snapshot(self.path)

    def load_effective(self) -> EffectiveConfigSnapshot:
        """Load an isolated runtime snapshot with ``${VAR}`` references resolved."""
        raw = self.load_raw()
        effective = resolve_config_env_vars(raw.config.model_copy(deep=True))
        return EffectiveConfigSnapshot(effective, raw.path, raw.revision)

    def save(
        self,
        config: Config,
        *,
        expected_revision: str | None = None,
    ) -> PersistedConfigSnapshot:
        """Atomically save a complete config, optionally rejecting stale writes."""
        with self._lock:
            current = _read_snapshot(self.path)
            if expected_revision is not None and current.revision != expected_revision:
                raise ConfigConflictError(
                    f"Config changed since revision {expected_revision}; "
                    f"current revision is {current.revision}"
                )
            data = _config_data(config)
            _validate_config_data(data, self.path)
            _write_config_atomic(self.path, data)
            return _read_snapshot(self.path)

    def update(
        self,
        mutator: ConfigMutator,
        *,
        expected_revision: str | None = None,
    ) -> ConfigCommit:
        """Atomically apply a mutation to the latest persisted config."""
        with self._lock:
            before = _read_snapshot(self.path)
            if expected_revision is not None and before.revision != expected_revision:
                raise ConfigConflictError(
                    f"Config changed since revision {expected_revision}; "
                    f"current revision is {before.revision}"
                )

            before_data = _config_data(before.config)
            draft = before.config.model_copy(deep=True)
            mutator(draft)
            after_data = _config_data(draft)
            changed = frozenset(_changed_paths(before_data, after_data))
            if not changed:
                return ConfigCommit(before, before, changed)

            _validate_config_data(after_data, self.path)
            _write_config_atomic(self.path, after_data)
            after = _read_snapshot(self.path)
            return ConfigCommit(before, after, changed)


def resolve_config_env_vars(config: Config) -> Config:
    """Return *config* with ``${VAR}`` environment references resolved."""
    return _resolve_in_place(config)


def _resolve_in_place(obj: Any) -> Any:
    if isinstance(obj, str):
        new = _ENV_REF_PATTERN.sub(_env_replace, obj)
        return new if new != obj else obj
    if isinstance(obj, BaseModel):
        updates: dict[str, Any] = {}
        for name in type(obj).model_fields:
            old = getattr(obj, name)
            new = _resolve_in_place(old)
            if new is not old:
                updates[name] = new
        extras = obj.__pydantic_extra__
        new_extras: dict[str, Any] | None = None
        if extras:
            resolved = {key: _resolve_in_place(value) for key, value in extras.items()}
            if any(resolved[key] is not extras[key] for key in extras):
                new_extras = resolved
        if not updates and new_extras is None:
            return obj
        copy = obj.model_copy(update=updates) if updates else obj.model_copy()
        if new_extras is not None:
            copy.__pydantic_extra__ = new_extras
        return copy
    if isinstance(obj, dict):
        resolved = {key: _resolve_in_place(value) for key, value in obj.items()}
        return resolved if any(resolved[key] is not obj[key] for key in obj) else obj
    if isinstance(obj, list):
        resolved = [_resolve_in_place(value) for value in obj]
        return resolved if any(new is not old for new, old in zip(resolved, obj)) else obj
    return obj


def _env_replace(match: re.Match[str]) -> str:
    name = match.group(1)
    value = os.environ.get(name)
    if value is None:
        raise ValueError(f"Environment variable '{name}' referenced in config is not set")
    return value


def _migrate_config(data: dict[str, Any]) -> dict[str, Any]:
    """Migrate old config formats to the current schema."""
    agents = data.get("agents", {})
    defaults = agents.get("defaults", {}) if isinstance(agents, dict) else {}
    if isinstance(defaults, dict):
        had_legacy_max_messages = "maxMessages" in defaults or "max_messages" in defaults
        defaults.pop("maxMessages", None)
        defaults.pop("max_messages", None)
        if had_legacy_max_messages:
            logger.warning(
                "agents.defaults.maxMessages/max_messages is legacy and ignored; "
                "replay max messages is now an internal safety cap. Remove it from "
                "config. This compatibility warning will be removed in the next version."
            )

    tools = data.get("tools", {})
    if not isinstance(tools, dict):
        return data
    exec_cfg = tools.get("exec", {})
    if isinstance(exec_cfg, dict) and "restrictToWorkspace" in exec_cfg and "restrictToWorkspace" not in tools:
        tools["restrictToWorkspace"] = exec_cfg.pop("restrictToWorkspace")

    if "myEnabled" in tools or "mySet" in tools:
        my_cfg = tools.setdefault("my", {})
        if not isinstance(my_cfg, dict):
            return data
        if "myEnabled" in tools and "enable" not in my_cfg:
            my_cfg["enable"] = tools.pop("myEnabled")
        else:
            tools.pop("myEnabled", None)
        if "mySet" in tools and "allowSet" not in my_cfg:
            my_cfg["allowSet"] = tools.pop("mySet")
        else:
            tools.pop("mySet", None)

    return data
