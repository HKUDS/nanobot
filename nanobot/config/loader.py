"""Configuration loading utilities."""

import json
import os
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError
from pydantic_settings import SettingsError

from nanobot.config.errors import ConfigIssue, ConfigLoadError, validation_issues
from nanobot.config.schema import Config, _resolve_tool_config_refs
from nanobot.utils.helpers import _write_text_atomic

# Global variable to store current config path (for multi-instance support)
_current_config_path: Path | None = None
_schema_refs_ready = False


def set_config_path(path: Path) -> None:
    """Set the current config path (used to derive data directory)."""
    global _current_config_path
    _current_config_path = path


def get_config_path() -> Path:
    """Get the configuration file path."""
    if _current_config_path:
        return _current_config_path
    return Path.home() / ".nanobot" / "config.json"


def load_config(config_path: Path | None = None) -> Config:
    """
    Load configuration from file or create default.

    Args:
        config_path: Optional path to config file. Uses default if not provided.

    Returns:
        Loaded configuration object.
    """
    global _schema_refs_ready
    if not _schema_refs_ready:
        _resolve_tool_config_refs()
        _schema_refs_ready = True

    path = config_path or get_config_path()

    if not path.exists():
        try:
            config = Config()
        except SettingsError as exc:
            raise ConfigLoadError(
                path,
                kind="invalid_schema",
                summary=(
                    "Environment-based configuration could not be parsed. "
                    "Check that complex NANOBOT_* values use valid JSON."
                ),
            ) from exc
        except ValidationError as exc:
            raise ConfigLoadError(
                path,
                kind="invalid_schema",
                summary="Environment-based configuration is invalid.",
                issues=validation_issues(exc),
            ) from exc
        _apply_ssrf_whitelist(config)
        return config

    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError as exc:
        raise ConfigLoadError(
            path,
            kind="invalid_json",
            summary=(
                f"JSON syntax error at line {exc.lineno}, column {exc.colno}: "
                f"{_sentence(exc.msg)}"
            ),
        ) from exc
    except UnicodeDecodeError as exc:
        raise ConfigLoadError(
            path,
            kind="io_error",
            summary="The file is not valid UTF-8.",
        ) from exc
    except OSError as exc:
        detail = exc.strerror or type(exc).__name__
        raise ConfigLoadError(
            path,
            kind="io_error",
            summary=f"Unable to read the file: {_sentence(detail)}",
        ) from exc

    if not isinstance(data, dict):
        root_type = type(data).__name__
        raise ConfigLoadError(
            path,
            kind="invalid_root",
            summary="The top level of config.json must be a JSON object.",
            issues=(
                ConfigIssue(
                    path=(),
                    message=f"Expected an object, but found {root_type}.",
                ),
            ),
        )

    data = _migrate_config(data)
    try:
        config = Config.model_validate(data)
    except ValidationError as exc:
        issues = validation_issues(exc)
        raise ConfigLoadError(
            path,
            kind="invalid_schema",
            summary=f"Found {len(issues)} invalid setting(s).",
            issues=issues,
        ) from exc

    _apply_ssrf_whitelist(config)
    return config


def _apply_ssrf_whitelist(config: Config) -> None:
    """Apply SSRF whitelist from config to the network security module."""
    from nanobot.security.network import configure_ssrf_whitelist

    configure_ssrf_whitelist(config.tools.ssrf_whitelist)


def save_config(config: Config, config_path: Path | None = None) -> None:
    """
    Save configuration to file.

    Args:
        config: Configuration to save.
        config_path: Optional path to save to. Uses default if not provided.
    """
    path = config_path or get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    data = config.model_dump(mode="json", by_alias=True)
    # OAuth credentials live in dedicated token stores. Persist only the
    # non-credential request settings consumed by these provider backends.
    for alias, provider in (
        ("openaiCodex", config.providers.openai_codex),
        ("xaiGrok", config.providers.xai_grok),
    ):
        settings = provider.model_dump(
            mode="json",
            by_alias=True,
            include={"proxy", "extra_body"},
            exclude_none=True,
        )
        if settings:
            data.setdefault("providers", {})[alias] = settings

    # Temp + replace so a crash mid-write cannot leave a truncated config.json.
    _write_text_atomic(path, json.dumps(data, indent=2, ensure_ascii=False))


def merge_missing_defaults(existing: Any, defaults: Any) -> Any:
    """Recursively add missing defaults without replacing configured values."""
    if not isinstance(existing, dict) or not isinstance(defaults, dict):
        return existing

    merged = dict(existing)
    for key, value in defaults.items():
        if key not in merged:
            merged[key] = value
        else:
            merged[key] = merge_missing_defaults(merged[key], value)
    return merged


_ENV_REF_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def resolve_config_env_vars(
    config: Config,
    *,
    config_path: Path | None = None,
) -> Config:
    """Return *config* with ``${VAR}`` env-var references resolved.

    Walks in place so fields declared with ``exclude=True`` survive;
    returns the same instance when no references are present.
    Raises ``ConfigLoadError`` if a referenced variable is not set.
    """
    missing = tuple(_missing_env_issues(config))
    if missing:
        raise ConfigLoadError(
            config_path or get_config_path(),
            kind="missing_env",
            summary=f"Found {len(missing)} missing environment variable reference(s).",
            issues=missing,
        )
    return _resolve_in_place(config)


def resolve_env_refs(value: str) -> str:
    """Resolve ``${VAR}`` references in a single string, leniently.

    Unlike :func:`resolve_config_env_vars` (which walks a whole ``Config`` and
    raises on a missing variable), this resolves one value and returns an empty
    string if any reference is unset. It is meant for individual, lazily consumed
    fields — e.g. a transcription provider's ``api_key`` or ``api_base`` — so a
    missing variable degrades to "not configured" instead of producing a partial
    value. Non-string input is returned unchanged.
    """
    if not isinstance(value, str):
        return value
    names = _ENV_REF_PATTERN.findall(value)
    if any(name not in os.environ for name in names):
        return ""
    return _ENV_REF_PATTERN.sub(lambda m: os.environ[m.group(1)], value)


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
            resolved = {k: _resolve_in_place(v) for k, v in extras.items()}
            if any(resolved[k] is not extras[k] for k in extras):
                new_extras = resolved
        if not updates and new_extras is None:
            return obj
        copy = obj.model_copy(update=updates) if updates else obj.model_copy()
        if new_extras is not None:
            copy.__pydantic_extra__ = new_extras
        return copy
    if isinstance(obj, dict):
        resolved = {k: _resolve_in_place(v) for k, v in obj.items()}
        return resolved if any(resolved[k] is not obj[k] for k in obj) else obj
    if isinstance(obj, list):
        resolved = [_resolve_in_place(v) for v in obj]
        return resolved if any(nv is not ov for nv, ov in zip(resolved, obj)) else obj
    return obj


def _missing_env_issues(
    obj: Any,
    path: tuple[str | int, ...] = (),
) -> list[ConfigIssue]:
    if isinstance(obj, str):
        return [
            ConfigIssue(
                path=path,
                message=f"Environment variable '{name}' is not set.",
            )
            for name in dict.fromkeys(_ENV_REF_PATTERN.findall(obj))
            if name not in os.environ
        ]
    if isinstance(obj, BaseModel):
        issues: list[ConfigIssue] = []
        for name, field in type(obj).model_fields.items():
            alias = field.serialization_alias or field.alias or name
            part = alias if isinstance(alias, str) else name
            issues.extend(_missing_env_issues(getattr(obj, name), (*path, part)))
        for name, value in (obj.__pydantic_extra__ or {}).items():
            issues.extend(_missing_env_issues(value, (*path, name)))
        return issues
    if isinstance(obj, dict):
        issues = []
        for name, value in obj.items():
            part = name if isinstance(name, (str, int)) else str(name)
            issues.extend(_missing_env_issues(value, (*path, part)))
        return issues
    if isinstance(obj, list):
        issues = []
        for index, value in enumerate(obj):
            issues.extend(_missing_env_issues(value, (*path, index)))
        return issues
    return []


def _resolve_env_vars(obj: object) -> object:
    """Recursively resolve ``${VAR}`` patterns in plain strings/dicts/lists."""
    if isinstance(obj, str):
        return _ENV_REF_PATTERN.sub(_env_replace, obj)
    if isinstance(obj, dict):
        return {k: _resolve_env_vars(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_env_vars(v) for v in obj]
    return obj


def _env_replace(match: re.Match[str]) -> str:
    name = match.group(1)
    value = os.environ.get(name)
    if value is None:
        raise ValueError(
            f"Environment variable '{name}' referenced in config is not set"
        )
    return value


def _migrate_config(data: dict) -> dict:
    """Migrate old config formats to current."""
    # Move tools.exec.restrictToWorkspace → tools.restrictToWorkspace
    tools = data.get("tools", {})
    if not isinstance(tools, dict):
        return data
    exec_cfg = tools.get("exec", {})
    if (
        isinstance(exec_cfg, dict)
        and "restrictToWorkspace" in exec_cfg
        and "restrictToWorkspace" not in tools
    ):
        tools["restrictToWorkspace"] = exec_cfg.pop("restrictToWorkspace")

    # Move tools.myEnabled / tools.mySet → tools.my.{enable, allowSet}.
    # The old flat keys shipped in the initial MyTool landing; wrapping them in a
    # sub-config keeps `web` / `exec` / `my` symmetric and gives room to grow.
    if "myEnabled" in tools or "mySet" in tools:
        my_cfg = tools.get("my")
        if my_cfg is None:
            my_cfg = {}
            tools["my"] = my_cfg
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


def _sentence(message: str) -> str:
    message = message.strip()
    if message and message[-1] not in ".!?":
        message += "."
    return message
